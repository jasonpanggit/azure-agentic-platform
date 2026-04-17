"""Tests for tagging_service.py and tagging_endpoints.py (Phase 75).

Covers:
- scan_tagging_compliance: ARG available → list of results
- scan_tagging_compliance: ImportError → empty list (no raise)
- scan_tagging_compliance: ARG error → empty list
- TagComplianceResult: compliant resource (all tags present)
- TagComplianceResult: non-compliant resource (missing tags)
- compliance_pct calculation
- compute_compliance_summary: total/compliant/non_compliant counts
- compute_compliance_summary: by_resource_type breakdown
- compute_compliance_summary: missing_tag_frequency
- generate_remediation_script: contains az tag update commands
- generate_remediation_script: groups by subscription
- generate_remediation_script: uses placeholder values for missing tags
- compliance endpoint returns results + pagination
- remediation-script endpoint returns text/plain
- required_tags override via query param
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("PGVECTOR_CONNECTION_STRING", "postgresql://test:test@localhost/test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.tagging_endpoints import router
from services.api_gateway.tagging_service import (
    DEFAULT_REQUIRED_TAGS,
    TagComplianceResult,
    _build_result,
    compute_compliance_summary,
    generate_remediation_script,
    scan_tagging_compliance,
)

# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------

_test_app = FastAPI()
_test_app.include_router(router)
_test_app.state.credential = MagicMock()

client = TestClient(_test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_row(
    name: str = "my-vm",
    resource_type: str = "microsoft.compute/virtualmachines",
    tags: dict | None = None,
    subscription_id: str = "sub-001",
    resource_group: str = "rg-prod",
) -> dict[str, Any]:
    return {
        "id": f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/{resource_type}/{name}",
        "name": name,
        "type": resource_type,
        "resourceGroup": resource_group,
        "location": "eastus",
        "subscriptionId": subscription_id,
        "tags": tags or {},
    }


COMPLIANT_TAGS = {
    "Environment": "prod",
    "Owner": "team-ops",
    "CostCenter": "CC-100",
    "Application": "platform",
}

PARTIAL_TAGS = {
    "Environment": "prod",
}


# ---------------------------------------------------------------------------
# Unit tests — TagComplianceResult / _build_result
# ---------------------------------------------------------------------------

class TestBuildResult:
    def test_compliant_resource_all_tags_present(self):
        row = _make_row(tags=COMPLIANT_TAGS)
        result = _build_result(row, DEFAULT_REQUIRED_TAGS)

        assert result.is_compliant is True
        assert result.missing_tags == []
        assert result.compliance_pct == 100.0

    def test_non_compliant_resource_missing_tags(self):
        row = _make_row(tags=PARTIAL_TAGS)
        result = _build_result(row, DEFAULT_REQUIRED_TAGS)

        assert result.is_compliant is False
        assert "Owner" in result.missing_tags
        assert "CostCenter" in result.missing_tags
        assert "Application" in result.missing_tags
        assert len(result.missing_tags) == 3

    def test_compliance_pct_one_of_four(self):
        row = _make_row(tags=PARTIAL_TAGS)
        result = _build_result(row, DEFAULT_REQUIRED_TAGS)
        assert result.compliance_pct == 25.0

    def test_compliance_pct_three_of_four(self):
        tags = {**COMPLIANT_TAGS}
        del tags["CostCenter"]
        row = _make_row(tags=tags)
        result = _build_result(row, DEFAULT_REQUIRED_TAGS)
        assert result.compliance_pct == 75.0

    def test_no_tags_all_missing(self):
        row = _make_row(tags={})
        result = _build_result(row, DEFAULT_REQUIRED_TAGS)
        assert result.is_compliant is False
        assert len(result.missing_tags) == 4
        assert result.compliance_pct == 0.0

    def test_tag_comparison_is_case_insensitive(self):
        """Tags with different casing should still satisfy requirements."""
        row = _make_row(tags={"environment": "prod", "owner": "x", "costcenter": "cc", "application": "app"})
        result = _build_result(row, DEFAULT_REQUIRED_TAGS)
        assert result.is_compliant is True

    def test_none_tags_treated_as_empty(self):
        row = _make_row(tags=None)
        result = _build_result(row, DEFAULT_REQUIRED_TAGS)
        assert result.is_compliant is False


# ---------------------------------------------------------------------------
# Unit tests — scan_tagging_compliance
# ---------------------------------------------------------------------------

class TestScanTaggingCompliance:
    def test_arg_available_returns_list_of_results(self):
        rows = [
            _make_row("vm-1", tags=COMPLIANT_TAGS),
            _make_row("vm-2", tags=PARTIAL_TAGS),
        ]
        credential = MagicMock()

        with patch("services.api_gateway.tagging_service.run_arg_query", return_value=rows) as mock_arg:
            results = scan_tagging_compliance(credential, ["sub-001"])

        assert len(results) == 2
        mock_arg.assert_called_once()

    def test_import_error_returns_empty_list(self):
        credential = MagicMock()

        with patch.dict("sys.modules", {"services.api_gateway.arg_helper": None}):
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                results = scan_tagging_compliance(credential, ["sub-001"])

        # Should never raise; returns empty list
        assert results == []

    def test_arg_query_error_returns_empty_list(self):
        credential = MagicMock()

        with patch("services.api_gateway.tagging_service.run_arg_query", side_effect=Exception("ARG unavailable")):
            results = scan_tagging_compliance(credential, ["sub-001"])

        assert results == []

    def test_required_tags_override(self):
        rows = [_make_row("vm-1", tags={"Env": "prod"})]
        credential = MagicMock()

        with patch("services.api_gateway.tagging_service.run_arg_query", return_value=rows):
            results = scan_tagging_compliance(credential, ["sub-001"], required_tags=["Env"])

        assert results[0].is_compliant is True


# ---------------------------------------------------------------------------
# Unit tests — compute_compliance_summary
# ---------------------------------------------------------------------------

class TestComputeComplianceSummary:
    def _make_result(self, compliant: bool, resource_type: str = "microsoft.compute/virtualmachines", missing: list[str] | None = None, sub: str = "sub-001") -> TagComplianceResult:
        return TagComplianceResult(
            subscription_id=sub,
            resource_id="/sub/r",
            resource_name="r",
            resource_type=resource_type,
            resource_group="rg",
            location="eastus",
            existing_tags={},
            missing_tags=missing or [],
            is_compliant=compliant,
            compliance_pct=100.0 if compliant else 0.0,
        )

    def test_total_compliant_non_compliant_counts(self):
        results = [
            self._make_result(True),
            self._make_result(True),
            self._make_result(False, missing=["Owner"]),
        ]
        summary = compute_compliance_summary(results)

        assert summary["total"] == 3
        assert summary["compliant"] == 2
        assert summary["non_compliant"] == 1

    def test_compliance_pct_calculation(self):
        results = [self._make_result(True), self._make_result(False)]
        summary = compute_compliance_summary(results)
        assert summary["compliance_pct"] == 50.0

    def test_by_resource_type_breakdown(self):
        results = [
            self._make_result(True, resource_type="microsoft.compute/virtualmachines"),
            self._make_result(False, resource_type="microsoft.compute/virtualmachines", missing=["Owner"]),
            self._make_result(True, resource_type="microsoft.storage/storageaccounts"),
        ]
        summary = compute_compliance_summary(results)

        vm_stats = summary["by_resource_type"]["microsoft.compute/virtualmachines"]
        assert vm_stats["total"] == 2
        assert vm_stats["compliant"] == 1

        st_stats = summary["by_resource_type"]["microsoft.storage/storageaccounts"]
        assert st_stats["compliant"] == 1

    def test_missing_tag_frequency(self):
        results = [
            self._make_result(False, missing=["Owner", "CostCenter"]),
            self._make_result(False, missing=["Owner"]),
            self._make_result(True),
        ]
        summary = compute_compliance_summary(results)
        freq = summary["missing_tag_frequency"]

        assert freq["Owner"] == 2
        assert freq["CostCenter"] == 1

    def test_empty_results(self):
        summary = compute_compliance_summary([])
        assert summary["total"] == 0
        assert summary["compliance_pct"] == 0.0


# ---------------------------------------------------------------------------
# Unit tests — generate_remediation_script
# ---------------------------------------------------------------------------

class TestGenerateRemediationScript:
    def _make_non_compliant(self, name: str = "vm-1", sub: str = "sub-001", missing: list[str] | None = None) -> TagComplianceResult:
        return TagComplianceResult(
            subscription_id=sub,
            resource_id=f"/subscriptions/{sub}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/{name}",
            resource_name=name,
            resource_type="microsoft.compute/virtualmachines",
            resource_group="rg",
            location="eastus",
            existing_tags={},
            missing_tags=missing or ["Owner", "CostCenter"],
            is_compliant=False,
            compliance_pct=50.0,
        )

    def test_contains_az_tag_update_commands(self):
        resources = [self._make_non_compliant()]
        script = generate_remediation_script(resources)

        assert "az tag update" in script
        assert "--resource-id" in script
        assert "--operation merge" in script

    def test_groups_by_subscription(self):
        resources = [
            self._make_non_compliant("vm-1", sub="sub-A"),
            self._make_non_compliant("vm-2", sub="sub-B"),
        ]
        script = generate_remediation_script(resources)

        assert "az account set --subscription sub-A" in script
        assert "az account set --subscription sub-B" in script

    def test_uses_placeholder_values_for_missing_tags(self):
        resources = [self._make_non_compliant(missing=["Owner"])]
        script = generate_remediation_script(resources, default_values={"Owner": "team-platform"})

        assert "team-platform" in script

    def test_default_placeholder_when_no_value_provided(self):
        resources = [self._make_non_compliant(missing=["CostCenter"])]
        script = generate_remediation_script(resources)

        assert "PLACEHOLDER" in script

    def test_script_has_shebang(self):
        script = generate_remediation_script([])
        assert script.startswith("#!/usr/bin/env bash")

    def test_empty_non_compliant_returns_script(self):
        script = generate_remediation_script([])
        assert "echo 'Tagging remediation complete.'" in script


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

class TestTaggingEndpoints:
    def test_compliance_endpoint_returns_results_and_pagination(self):
        rows = [
            _make_row("vm-1", tags=COMPLIANT_TAGS),
            _make_row("vm-2", tags=PARTIAL_TAGS),
        ]
        with patch("services.api_gateway.tagging_endpoints.scan_tagging_compliance", return_value=[
            _build_result(r, DEFAULT_REQUIRED_TAGS) for r in rows
        ]):
            resp = client.get("/api/v1/tagging/compliance?subscription_id=sub-001")

        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "summary" in data
        assert "pagination" in data
        assert data["pagination"]["total"] == 2

    def test_remediation_script_endpoint_returns_text_plain(self):
        non_compliant = [
            TagComplianceResult(
                subscription_id="sub-001",
                resource_id="/sub/rg/vm-1",
                resource_name="vm-1",
                resource_type="microsoft.compute/virtualmachines",
                resource_group="rg",
                location="eastus",
                existing_tags={},
                missing_tags=["Owner"],
                is_compliant=False,
                compliance_pct=75.0,
            )
        ]
        with patch("services.api_gateway.tagging_endpoints.scan_tagging_compliance", return_value=non_compliant):
            resp = client.get("/api/v1/tagging/remediation-script?subscription_id=sub-001")

        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "az tag update" in resp.text

    def test_required_tags_override_via_query_param(self):
        with patch("services.api_gateway.tagging_endpoints.scan_tagging_compliance", return_value=[]) as mock_scan:
            resp = client.get("/api/v1/tagging/compliance?subscription_id=sub-001&required_tags=Env,Team")

        assert resp.status_code == 200
        data = resp.json()
        assert data["required_tags"] == ["Env", "Team"]
        # Verify the service was called with the override
        call_kwargs = mock_scan.call_args
        assert call_kwargs[1]["required_tags"] == ["Env", "Team"]

    def test_compliant_filter_non_compliant(self):
        results = [
            _build_result(_make_row("vm-1", tags=COMPLIANT_TAGS), DEFAULT_REQUIRED_TAGS),
            _build_result(_make_row("vm-2", tags=PARTIAL_TAGS), DEFAULT_REQUIRED_TAGS),
        ]
        with patch("services.api_gateway.tagging_endpoints.scan_tagging_compliance", return_value=results):
            resp = client.get("/api/v1/tagging/compliance?subscription_id=sub-001&compliant_filter=non_compliant")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total"] == 1
        assert data["results"][0]["is_compliant"] is False

    def test_summary_endpoint(self):
        results = [
            _build_result(_make_row("vm-1", tags=COMPLIANT_TAGS), DEFAULT_REQUIRED_TAGS),
        ]
        with patch("services.api_gateway.tagging_endpoints.scan_tagging_compliance", return_value=results):
            resp = client.get("/api/v1/tagging/summary?subscription_id=sub-001")

        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "compliance_pct" in data
        assert "required_tags" in data
