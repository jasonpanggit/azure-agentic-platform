"""Unit tests for vm_extension_service.py (Phase 89).

Covers:
- _assess_coverage: all severity branches, Windows/Linux
- scan_vm_extensions: happy path, ARG failure, empty results, failed extensions
- persist_findings: happy path, empty list, exception
- get_findings: happy path, subscription filter, severity filter, exception
- get_extension_summary: happy path, empty, mixed severities, exception
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.vm_extension_service import (
    VMExtensionFinding,
    _assess_coverage,
    get_extension_summary,
    get_findings,
    persist_findings,
    scan_vm_extensions,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_vm(vm_id: str = "/sub/sub1/rg/rg1/vm1", os_type: str = "Windows") -> Dict[str, Any]:
    return {
        "vm_id": vm_id.lower(),
        "vm_name": "vm1",
        "subscription_id": "sub1",
        "resource_group": "rg1",
        "location": "eastus",
        "os_type": os_type,
    }


def _make_ext(vm_id: str, ext_type: str, state: str = "Succeeded") -> Dict[str, Any]:
    return {
        "vm_id": vm_id.lower(),
        "ext_type": ext_type,
        "publisher": "Microsoft.Azure.Monitor",
        "provisioning_state": state,
        "ext_name": ext_type,
    }


# ---------------------------------------------------------------------------
# _assess_coverage tests (7)
# ---------------------------------------------------------------------------

def test_assess_coverage_windows_missing_both():
    sev, score, missing = _assess_coverage("Windows", set())
    assert sev == "critical"
    assert score == 0.0
    assert len(missing) >= 1


def test_assess_coverage_windows_has_monitoring_only():
    sev, score, missing = _assess_coverage("Windows", {"AzureMonitorWindowsAgent"})
    assert sev == "medium"
    assert 0.5 < score <= 0.8


def test_assess_coverage_windows_has_security_only():
    sev, score, missing = _assess_coverage("Windows", {"MDE.Windows"})
    assert sev == "high"
    assert score == 0.5


def test_assess_coverage_windows_fully_compliant():
    sev, score, missing = _assess_coverage(
        "Windows", {"AzureMonitorWindowsAgent", "MDE.Windows"}
    )
    assert sev == "compliant"
    assert score == 1.0
    assert missing == []


def test_assess_coverage_linux_missing_both():
    sev, score, missing = _assess_coverage("Linux", set())
    assert sev == "critical"
    assert score == 0.0


def test_assess_coverage_linux_fully_compliant():
    sev, score, missing = _assess_coverage(
        "Linux", {"AzureMonitorLinuxAgent", "MDE.Linux"}
    )
    assert sev == "compliant"
    assert score == 1.0


def test_assess_coverage_unknown_os_treated_as_linux():
    # Unknown OS falls back to Linux required set
    sev, score, missing = _assess_coverage("Unknown", {"AzureMonitorLinuxAgent", "MDE.Linux"})
    assert sev == "compliant"


# ---------------------------------------------------------------------------
# scan_vm_extensions tests (7)
# ---------------------------------------------------------------------------

def test_scan_vm_extensions_happy_path():
    credential = MagicMock()
    vm_id = "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"
    vms = [_make_vm(vm_id, "Windows")]
    exts = [
        _make_ext(vm_id, "AzureMonitorWindowsAgent"),
        _make_ext(vm_id, "MDE.Windows"),
    ]
    with patch("services.api_gateway.vm_extension_service.run_arg_query", side_effect=[vms, exts]):
        results = scan_vm_extensions(credential, ["sub1"])
    assert len(results) == 1
    assert results[0].severity == "compliant"
    assert results[0].compliance_score == 1.0


def test_scan_vm_extensions_critical_vm():
    credential = MagicMock()
    vm_id = "/sub/sub1/rg/rg1/vm/vm2"
    vms = [_make_vm(vm_id, "Windows")]
    exts: list = []
    with patch("services.api_gateway.vm_extension_service.run_arg_query", side_effect=[vms, exts]):
        results = scan_vm_extensions(credential, ["sub1"])
    assert results[0].severity == "critical"
    assert len(results[0].missing_extensions) >= 1


def test_scan_vm_extensions_failed_extension_info():
    credential = MagicMock()
    vm_id = "/sub/sub1/rg/rg1/vm/vm3"
    vms = [_make_vm(vm_id, "Linux")]
    exts = [
        _make_ext(vm_id, "AzureMonitorLinuxAgent", "Succeeded"),
        _make_ext(vm_id, "MDE.Linux", "Succeeded"),
        _make_ext(vm_id, "SomeOtherExt", "Failed"),
    ]
    with patch("services.api_gateway.vm_extension_service.run_arg_query", side_effect=[vms, exts]):
        results = scan_vm_extensions(credential, ["sub1"])
    assert results[0].severity == "info"
    assert len(results[0].failed_extensions) == 1


def test_scan_vm_extensions_arg_failure_returns_empty():
    credential = MagicMock()
    with patch(
        "services.api_gateway.vm_extension_service.run_arg_query",
        side_effect=Exception("ARG error"),
    ):
        results = scan_vm_extensions(credential, ["sub1"])
    assert results == []


def test_scan_vm_extensions_no_vms_returns_empty():
    credential = MagicMock()
    with patch("services.api_gateway.vm_extension_service.run_arg_query", side_effect=[[], []]):
        results = scan_vm_extensions(credential, ["sub1"])
    assert results == []


def test_scan_vm_extensions_multiple_vms():
    credential = MagicMock()
    vm_id1 = "/sub/sub1/rg/rg1/vm/vm1"
    vm_id2 = "/sub/sub1/rg/rg1/vm/vm2"
    vms = [_make_vm(vm_id1, "Windows"), _make_vm(vm_id2, "Linux")]
    exts = [_make_ext(vm_id1, "AzureMonitorWindowsAgent")]
    with patch("services.api_gateway.vm_extension_service.run_arg_query", side_effect=[vms, exts]):
        results = scan_vm_extensions(credential, ["sub1"])
    assert len(results) == 2


def test_scan_vm_extensions_stable_finding_id():
    credential = MagicMock()
    vm_id = "/sub/sub1/rg/rg1/vm/vm1"
    vms = [_make_vm(vm_id, "Windows")]
    with patch("services.api_gateway.vm_extension_service.run_arg_query", side_effect=[vms, []]):
        r1 = scan_vm_extensions(credential, ["sub1"])
    with patch("services.api_gateway.vm_extension_service.run_arg_query", side_effect=[vms, []]):
        r2 = scan_vm_extensions(credential, ["sub1"])
    assert r1[0].finding_id == r2[0].finding_id


# ---------------------------------------------------------------------------
# persist_findings tests (3)
# ---------------------------------------------------------------------------

def test_persist_findings_upserts_all():
    cosmos = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    findings = [
        VMExtensionFinding(
            finding_id="fid1", vm_id="vmid1", vm_name="vm1", resource_group="rg1",
            subscription_id="sub1", location="eastus", os_type="Windows",
            installed_extensions=[], missing_extensions=[], failed_extensions=[],
            severity="compliant", compliance_score=1.0, scanned_at="2026-01-01T00:00:00Z",
        )
    ]
    persist_findings(cosmos, "aap", findings)
    container.upsert_item.assert_called_once()


def test_persist_findings_empty_list_no_call():
    cosmos = MagicMock()
    persist_findings(cosmos, "aap", [])
    cosmos.get_database_client.assert_not_called()


def test_persist_findings_exception_does_not_raise():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("cosmos error")
    findings = [
        VMExtensionFinding(
            finding_id="fid2", vm_id="vmid2", vm_name="vm2", resource_group="rg1",
            subscription_id="sub1", location="eastus", os_type="Linux",
            installed_extensions=[], missing_extensions=[], failed_extensions=[],
            severity="critical", compliance_score=0.0, scanned_at="2026-01-01T00:00:00Z",
        )
    ]
    # Must not raise
    persist_findings(cosmos, "aap", findings)


# ---------------------------------------------------------------------------
# get_findings tests (3)
# ---------------------------------------------------------------------------

def test_get_findings_returns_items():
    cosmos = MagicMock()
    expected = [{"finding_id": "f1", "severity": "critical"}]
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter(expected)
    result = get_findings(cosmos, "aap")
    assert result == expected


def test_get_findings_with_filters():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter([])
    result = get_findings(cosmos, "aap", subscription_ids=["sub1"], severity="critical")
    assert result == []


def test_get_findings_exception_returns_empty():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("db error")
    result = get_findings(cosmos, "aap")
    assert result == []


# ---------------------------------------------------------------------------
# get_extension_summary tests (5)
# ---------------------------------------------------------------------------

def test_get_extension_summary_empty():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter([])
    result = get_extension_summary(cosmos, "aap")
    assert result["total_vms"] == 0
    assert result["coverage_pct"] == 0.0


def test_get_extension_summary_all_compliant():
    cosmos = MagicMock()
    findings = [{"severity": "compliant", "missing_extensions": []} for _ in range(5)]
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter(findings)
    result = get_extension_summary(cosmos, "aap")
    assert result["compliant"] == 5
    assert result["coverage_pct"] == 100.0


def test_get_extension_summary_mixed_severities():
    cosmos = MagicMock()
    findings = [
        {"severity": "critical", "missing_extensions": [{"name": "AzureMonitorWindowsAgent"}]},
        {"severity": "high", "missing_extensions": [{"name": "MDE.Windows"}]},
        {"severity": "compliant", "missing_extensions": []},
    ]
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter(findings)
    result = get_extension_summary(cosmos, "aap")
    assert result["critical"] == 1
    assert result["high"] == 1
    assert result["total_vms"] == 3


def test_get_extension_summary_top_missing():
    cosmos = MagicMock()
    findings = [
        {"severity": "high", "missing_extensions": [{"name": "MDE.Windows"}]},
        {"severity": "high", "missing_extensions": [{"name": "MDE.Windows"}]},
        {"severity": "medium", "missing_extensions": [{"name": "IaaSAntimalware"}]},
    ]
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter(findings)
    result = get_extension_summary(cosmos, "aap")
    assert result["top_missing"][0]["name"] == "MDE.Windows"
    assert result["top_missing"][0]["count"] == 2


def test_get_extension_summary_exception_returns_defaults():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("db error")
    result = get_extension_summary(cosmos, "aap")
    assert result["total_vms"] == 0
    assert "coverage_pct" in result
