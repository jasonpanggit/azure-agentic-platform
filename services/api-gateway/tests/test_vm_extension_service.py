from __future__ import annotations
"""Tests for VM Extension Health Audit service and endpoints (Phase 89)."""
import os

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("PGVECTOR_CONNECTION_STRING", "postgresql://test:test@localhost/test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.vm_extension_service import (
    _assess_coverage,
    get_extension_summary,
    get_findings,
    persist_findings,
    scan_vm_extensions,
    VMExtensionFinding,
)
from services.api_gateway.vm_extension_endpoints import router

_test_app = FastAPI()
_test_app.include_router(router)
_test_app.state.credential = MagicMock()

http_client = TestClient(_test_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# _assess_coverage tests
# ---------------------------------------------------------------------------

class TestAssessCoverage:
    def test_windows_no_monitoring_no_security_is_critical(self):
        severity, score, missing = _assess_coverage("Windows", set())
        assert severity == "critical"
        assert score == 0.0
        assert len(missing) == 2  # one monitoring + one security suggestion

    def test_windows_has_security_only_is_high(self):
        severity, score, missing = _assess_coverage("Windows", {"IaaSAntimalware"})
        assert severity == "high"
        assert score == 0.5

    def test_windows_has_monitoring_only_is_medium(self):
        severity, score, missing = _assess_coverage("Windows", {"MicrosoftMonitoringAgent"})
        assert severity == "medium"
        assert score == 0.7

    def test_windows_has_both_is_compliant(self):
        severity, score, missing = _assess_coverage(
            "Windows", {"MicrosoftMonitoringAgent", "IaaSAntimalware"}
        )
        assert severity == "compliant"
        assert score == 1.0
        assert missing == []

    def test_windows_ama_counts_as_monitoring(self):
        severity, score, _ = _assess_coverage("Windows", {"AzureMonitorWindowsAgent", "MDE.Windows"})
        assert severity == "compliant"

    def test_linux_no_monitoring_no_security_is_critical(self):
        severity, score, missing = _assess_coverage("Linux", set())
        assert severity == "critical"
        assert score == 0.0

    def test_linux_oma_counts_as_monitoring(self):
        severity, score, _ = _assess_coverage("Linux", {"OmsAgentForLinux", "MDE.Linux"})
        assert severity == "compliant"
        assert score == 1.0

    def test_linux_has_security_only_is_high(self):
        severity, score, _ = _assess_coverage("Linux", {"MDE.Linux"})
        assert severity == "high"

    def test_linux_has_monitoring_only_is_medium(self):
        severity, score, _ = _assess_coverage("Linux", {"AzureMonitorLinuxAgent"})
        assert severity == "medium"

    def test_case_insensitive_os_type(self):
        sev_lower, _, _ = _assess_coverage("windows", {"MicrosoftMonitoringAgent", "IaaSAntimalware"})
        sev_upper, _, _ = _assess_coverage("WINDOWS", {"MicrosoftMonitoringAgent", "IaaSAntimalware"})
        assert sev_lower == "compliant"
        assert sev_upper == "compliant"

    def test_unknown_os_falls_back_to_linux_table(self):
        # Unknown OS should not raise
        severity, score, _ = _assess_coverage("Unknown", set())
        assert severity == "critical"

    def test_missing_list_empty_when_compliant(self):
        _, _, missing = _assess_coverage("Windows", {"MicrosoftMonitoringAgent", "MDE.Windows"})
        assert missing == []

    def test_missing_contains_one_monitoring_suggestion_when_no_monitoring(self):
        _, _, missing = _assess_coverage("Windows", {"IaaSAntimalware"})
        monitoring_suggestions = [m for m in missing if m.get("severity_contribution") in ("high",)]
        assert len(monitoring_suggestions) >= 1

    def test_critical_security_contribution_when_nothing_installed(self):
        _, _, missing = _assess_coverage("Windows", set())
        security_suggestions = [m for m in missing if m.get("severity_contribution") == "critical"]
        assert len(security_suggestions) >= 1


# ---------------------------------------------------------------------------
# scan_vm_extensions tests
# ---------------------------------------------------------------------------

_VM_ROWS = [
    {
        "vm_id": "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
        "vm_name": "vm1",
        "subscription_id": "sub1",
        "resource_group": "rg1",
        "location": "eastus",
        "os_type": "Windows",
    }
]

_EXT_ROWS_COMPLIANT = [
    {
        "vm_id": "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
        "ext_name": "MicrosoftMonitoringAgent",
        "ext_type": "MicrosoftMonitoringAgent",
        "publisher": "Microsoft.EnterpriseCloud.Monitoring",
        "provisioning_state": "Succeeded",
    },
    {
        "vm_id": "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
        "ext_name": "IaaSAntimalware",
        "ext_type": "IaaSAntimalware",
        "publisher": "Microsoft.Azure.Security",
        "provisioning_state": "Succeeded",
    },
]

_EXT_ROWS_EMPTY: list = []


class TestScanVmExtensions:
    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_returns_finding_per_vm(self, mock_arg):
        mock_arg.side_effect = [_VM_ROWS, _EXT_ROWS_COMPLIANT]
        findings = scan_vm_extensions(MagicMock(), ["sub1"])
        assert len(findings) == 1
        assert findings[0].vm_name == "vm1"

    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_compliant_vm_has_compliant_severity(self, mock_arg):
        mock_arg.side_effect = [_VM_ROWS, _EXT_ROWS_COMPLIANT]
        findings = scan_vm_extensions(MagicMock(), ["sub1"])
        assert findings[0].severity == "compliant"
        assert findings[0].compliance_score == 1.0

    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_vm_with_no_extensions_is_critical(self, mock_arg):
        mock_arg.side_effect = [_VM_ROWS, _EXT_ROWS_EMPTY]
        findings = scan_vm_extensions(MagicMock(), ["sub1"])
        assert findings[0].severity == "critical"

    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_failed_extension_state_bumps_to_info(self, mock_arg):
        failed_ext_rows = [
            {
                "vm_id": "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
                "ext_type": "MicrosoftMonitoringAgent",
                "ext_name": "MicrosoftMonitoringAgent",
                "publisher": "Microsoft.EnterpriseCloud.Monitoring",
                "provisioning_state": "Succeeded",
            },
            {
                "vm_id": "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
                "ext_type": "IaaSAntimalware",
                "ext_name": "IaaSAntimalware",
                "publisher": "Microsoft.Azure.Security",
                "provisioning_state": "Succeeded",
            },
            {
                "vm_id": "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
                "ext_type": "SomeOtherExt",
                "ext_name": "SomeOtherExt",
                "publisher": "Some.Publisher",
                "provisioning_state": "Failed",
            },
        ]
        mock_arg.side_effect = [_VM_ROWS, failed_ext_rows]
        findings = scan_vm_extensions(MagicMock(), ["sub1"])
        assert findings[0].severity == "info"
        assert findings[0].compliance_score == 0.9

    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_arg_exception_returns_empty_list(self, mock_arg):
        mock_arg.side_effect = RuntimeError("ARG down")
        findings = scan_vm_extensions(MagicMock(), ["sub1"])
        assert findings == []

    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_vm_without_vm_id_skipped(self, mock_arg):
        bad_vm_rows = [{"vm_name": "ghost", "os_type": "Windows"}]  # no vm_id
        mock_arg.side_effect = [bad_vm_rows, _EXT_ROWS_EMPTY]
        findings = scan_vm_extensions(MagicMock(), ["sub1"])
        assert findings == []

    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_finding_id_is_deterministic(self, mock_arg):
        mock_arg.side_effect = [_VM_ROWS, _EXT_ROWS_COMPLIANT]
        f1 = scan_vm_extensions(MagicMock(), ["sub1"])[0]
        mock_arg.side_effect = [_VM_ROWS, _EXT_ROWS_COMPLIANT]
        f2 = scan_vm_extensions(MagicMock(), ["sub1"])[0]
        assert f1.finding_id == f2.finding_id


# ---------------------------------------------------------------------------
# get_findings tests
# ---------------------------------------------------------------------------

def _make_cosmos(items=None):
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = items or []
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    return cosmos, container


class TestGetFindings:
    def test_returns_items_from_cosmos(self):
        cosmos, _ = _make_cosmos([{"finding_id": "abc", "severity": "critical"}])
        result = get_findings(cosmos, "aap")
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_returns_empty_on_exception(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("cosmos down")
        result = get_findings(cosmos, "aap")
        assert result == []

    def test_subscription_filter_adds_param(self):
        cosmos, container = _make_cosmos([])
        get_findings(cosmos, "aap", subscription_ids=["sub1"])
        call_kwargs = container.query_items.call_args[1]
        assert call_kwargs["parameters"] is not None

    def test_severity_filter_adds_param(self):
        cosmos, container = _make_cosmos([])
        get_findings(cosmos, "aap", severity="critical")
        call_kwargs = container.query_items.call_args[1]
        assert any(p["name"] == "@severity" for p in call_kwargs["parameters"])

    def test_no_filters_passes_no_params(self):
        cosmos, container = _make_cosmos([])
        get_findings(cosmos, "aap")
        call_kwargs = container.query_items.call_args[1]
        assert call_kwargs["parameters"] is None


# ---------------------------------------------------------------------------
# get_extension_summary tests
# ---------------------------------------------------------------------------

class TestGetExtensionSummary:
    def test_summary_zero_when_no_findings(self):
        cosmos, _ = _make_cosmos([])
        result = get_extension_summary(cosmos, "aap")
        assert result["total_vms"] == 0
        assert result["coverage_pct"] == 0.0

    def test_summary_aggregates_severities(self):
        findings = [
            {"severity": "critical", "missing_extensions": [{"name": "MicrosoftMonitoringAgent"}]},
            {"severity": "high", "missing_extensions": []},
            {"severity": "compliant", "missing_extensions": []},
            {"severity": "info", "missing_extensions": []},
        ]
        cosmos, _ = _make_cosmos(findings)
        result = get_extension_summary(cosmos, "aap")
        assert result["total_vms"] == 4
        assert result["critical"] == 1
        assert result["high"] == 1
        assert result["compliant"] == 2  # compliant + info

    def test_top_missing_sorted_by_count(self):
        findings = [
            {"severity": "critical", "missing_extensions": [{"name": "MMA"}, {"name": "AMA"}]},
            {"severity": "critical", "missing_extensions": [{"name": "MMA"}]},
            {"severity": "high", "missing_extensions": [{"name": "AMA"}]},
        ]
        cosmos, _ = _make_cosmos(findings)
        result = get_extension_summary(cosmos, "aap")
        top = result["top_missing"]
        assert top[0]["name"] in ("MMA", "AMA")
        assert top[0]["count"] >= top[-1]["count"]

    def test_summary_returns_safe_default_on_exception(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("boom")
        result = get_extension_summary(cosmos, "aap")
        assert result["total_vms"] == 0


# ---------------------------------------------------------------------------
# VMExtensionFinding.to_dict tests
# ---------------------------------------------------------------------------

class TestVMExtensionFindingToDict:
    def test_to_dict_includes_id_field(self):
        f = VMExtensionFinding(
            finding_id="fid1",
            vm_id="/sub/vm1",
            vm_name="vm1",
            resource_group="rg1",
            subscription_id="sub1",
            location="eastus",
            os_type="Windows",
            installed_extensions=[],
            missing_extensions=[],
            failed_extensions=[],
            severity="compliant",
            compliance_score=1.0,
            scanned_at="2026-01-01T00:00:00+00:00",
        )
        d = f.to_dict()
        assert d["id"] == "fid1"
        assert d["finding_id"] == "fid1"
        assert d["severity"] == "compliant"


# ---------------------------------------------------------------------------
# FastAPI endpoint tests
# ---------------------------------------------------------------------------

def _make_cosmos_mock(items=None):
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = items or []
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    return cosmos


def _make_ext_client(items=None, credential=None):
    """Return a TestClient with dependency overrides for vm-extensions endpoints."""
    from fastapi import FastAPI
    from services.api_gateway.vm_extension_endpoints import router as ext_router
    from services.api_gateway.dependencies import get_cosmos_client, get_credential

    app = FastAPI()
    app.include_router(ext_router)
    app.dependency_overrides[get_cosmos_client] = lambda: _make_cosmos_mock(items)
    app.dependency_overrides[get_credential] = lambda: credential or MagicMock()
    return TestClient(app, raise_server_exceptions=False)


class TestVmExtensionEndpoints:
    def test_list_findings_returns_200(self):
        client = _make_ext_client([{"finding_id": "x", "severity": "critical"}])
        resp = client.get("/api/v1/vm-extensions")
        assert resp.status_code == 200
        data = resp.json()
        assert "findings" in data
        assert data["total"] == 1

    def test_list_findings_empty(self):
        client = _make_ext_client([])
        resp = client.get("/api/v1/vm-extensions")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_summary_endpoint_returns_200(self):
        client = _make_ext_client([{"severity": "compliant", "missing_extensions": []}])
        resp = client.get("/api/v1/vm-extensions/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_vms" in data
        assert "coverage_pct" in data

    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_scan_endpoint_returns_ok(self, mock_arg):
        mock_arg.side_effect = [_VM_ROWS, _EXT_ROWS_COMPLIANT]
        client = _make_ext_client()
        resp = client.post("/api/v1/vm-extensions/scan?subscription_id=sub1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "findings_count" in data

    @patch("services.api_gateway.vm_extension_service.run_arg_query")
    def test_scan_endpoint_no_subscription_still_works(self, mock_arg):
        mock_arg.side_effect = [[], []]
        client = _make_ext_client()
        resp = client.post("/api/v1/vm-extensions/scan")
        assert resp.status_code == 200
