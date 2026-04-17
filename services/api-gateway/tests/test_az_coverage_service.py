"""Tests for az_coverage_service.py — Phase 102.

Covers:
- _parse_zones: various input formats
- _build_finding: vm and vmss, AZ-supported regions, severity
- scan_az_coverage: success, empty, error paths
- persist_az_findings: upsert, no-op, error
- get_az_findings: with / without filters, cosmos error
- get_az_summary: aggregation, zero state, coverage_pct
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vm_row(
    name: str = "my-vm",
    location: str = "eastus",
    zone_list: str = '["1","2","3"]',
    has_zones: bool = True,
    subscription_id: str = "sub-1",
    resource_group: str = "rg-compute",
    vm_size: str = "Standard_D2s_v3",
) -> dict:
    return {
        "id": f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{name}",
        "name": name,
        "subscriptionId": subscription_id,
        "resourceGroup": resource_group,
        "location": location,
        "zone_list": zone_list,
        "has_zones": has_zones,
        "vm_size": vm_size,
    }


def _make_vmss_row(
    name: str = "my-vmss",
    location: str = "eastus",
    zone_list: str = '["1","2","3"]',
    has_zones: bool = True,
    subscription_id: str = "sub-1",
    resource_group: str = "rg-compute",
    sku_name: str = "Standard_D2s_v3",
    capacity: int = 3,
) -> dict:
    return {
        "id": f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachineScaleSets/{name}",
        "name": name,
        "subscriptionId": subscription_id,
        "resourceGroup": resource_group,
        "location": location,
        "zone_list": zone_list,
        "has_zones": has_zones,
        "sku_name": sku_name,
        "capacity": capacity,
    }


# ---------------------------------------------------------------------------
# _parse_zones tests
# ---------------------------------------------------------------------------

from services.api_gateway.az_coverage_service import _parse_zones


class TestParseZones:
    def test_three_zones(self):
        assert _parse_zones('["1","2","3"]') == ["1", "2", "3"]

    def test_empty_array(self):
        assert _parse_zones("[]") == []

    def test_none(self):
        assert _parse_zones(None) == []

    def test_empty_string(self):
        assert _parse_zones("") == []

    def test_single_zone(self):
        assert _parse_zones('["1"]') == ["1"]

    def test_malformed_returns_empty(self):
        assert _parse_zones("not-json") == []


# ---------------------------------------------------------------------------
# _build_finding tests
# ---------------------------------------------------------------------------

from services.api_gateway.az_coverage_service import _build_finding


class TestBuildFinding:
    def test_zone_redundant_vm(self):
        row = _make_vm_row(zone_list='["1","2","3"]', location="eastus")
        f = _build_finding(row, "vm", "2026-01-01T00:00:00+00:00")
        assert f["has_zone_redundancy"] is True
        assert f["zone_count"] == 3
        assert f["severity"] == "info"
        assert f["resource_type"] == "vm"

    def test_no_zones_in_supported_region_is_high(self):
        row = _make_vm_row(zone_list="[]", location="eastus")
        f = _build_finding(row, "vm", "2026-01-01T00:00:00+00:00")
        assert f["has_zone_redundancy"] is False
        assert f["severity"] == "high"

    def test_no_zones_in_unsupported_region_is_info(self):
        row = _make_vm_row(zone_list="[]", location="brazilsouth")
        f = _build_finding(row, "vm", "2026-01-01T00:00:00+00:00")
        assert f["severity"] == "info"

    def test_vmss_resource_type(self):
        row = _make_vmss_row(zone_list='["1","2"]', location="westeurope")
        f = _build_finding(row, "vmss", "2026-01-01T00:00:00+00:00")
        assert f["resource_type"] == "vmss"
        assert f["has_zone_redundancy"] is True

    def test_single_zone_is_not_redundant(self):
        """One zone is pinned but not redundant."""
        row = _make_vm_row(zone_list='["1"]', location="eastus")
        f = _build_finding(row, "vm", "2026-01-01T00:00:00+00:00")
        assert f["has_zone_redundancy"] is False
        assert f["severity"] == "high"

    def test_stable_id_deterministic(self):
        row = _make_vm_row(name="stable")
        f1 = _build_finding(row, "vm", "2026-01-01T00:00:00+00:00")
        f2 = _build_finding(row, "vm", "2026-01-02T00:00:00+00:00")
        assert f1["id"] == f2["id"]

    def test_required_fields_present(self):
        row = _make_vm_row()
        f = _build_finding(row, "vm", "2026-01-01T00:00:00+00:00")
        required = {
            "id", "subscription_id", "resource_group", "resource_name",
            "resource_type", "location", "zones", "has_zone_redundancy",
            "zone_count", "severity", "recommendation", "scanned_at",
        }
        assert required.issubset(set(f.keys()))


# ---------------------------------------------------------------------------
# scan_az_coverage tests
# ---------------------------------------------------------------------------

from services.api_gateway.az_coverage_service import scan_az_coverage


class TestScanAzCoverage:
    def test_empty_subscription_ids(self):
        assert scan_az_coverage([]) == []

    def test_scans_both_vm_and_vmss(self):
        vm_rows = [_make_vm_row("vm-1"), _make_vm_row("vm-2")]
        vmss_rows = [_make_vmss_row("vmss-1")]

        def _fake_run(credential, subscription_ids, kql):
            if "virtualmachinescalesets" not in kql.lower() and "virtualmachines" in kql.lower():
                return vm_rows
            return vmss_rows

        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=_fake_run), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_az_coverage(["sub-1"])

        assert len(findings) == 3
        types = {f["resource_type"] for f in findings}
        assert types == {"vm", "vmss"}

    def test_arg_error_returns_empty(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("timeout")), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_az_coverage(["sub-1"])
        assert findings == []

    def test_vm_query_error_continues_with_vmss(self):
        call_count = {"n": 0}

        def _flaky(credential, subscription_ids, kql):
            call_count["n"] += 1
            if "virtualmachines" in kql.lower() and "scaleset" not in kql.lower():
                raise Exception("vm query failed")
            return [_make_vmss_row()]

        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=_flaky), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_az_coverage(["sub-1"])

        # VMSS results still returned despite VM query failure
        assert len(findings) == 1
        assert findings[0]["resource_type"] == "vmss"

    def test_no_zones_high_severity_in_az_region(self):
        rows = [_make_vm_row(zone_list="[]", location="eastus")]

        def _fake_run(credential, subscription_ids, kql):
            if "virtualmachines" in kql.lower() and "scaleset" not in kql.lower():
                return rows
            return []

        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=_fake_run), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_az_coverage(["sub-1"])

        assert findings[0]["severity"] == "high"


# ---------------------------------------------------------------------------
# persist_az_findings tests
# ---------------------------------------------------------------------------

from services.api_gateway.az_coverage_service import persist_az_findings


class TestPersistAzFindings:
    def test_no_op_on_empty(self):
        persist_az_findings([])

    def test_no_op_when_endpoint_missing(self, monkeypatch):
        monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
        persist_az_findings([{"id": "x"}])

    def test_calls_upsert_for_each(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        mock_container = MagicMock()
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_client = MagicMock()
        mock_client.get_database_client.return_value = mock_db

        with patch("azure.cosmos.CosmosClient", return_value=mock_client), \
             patch("azure.identity.DefaultAzureCredential"):
            persist_az_findings([{"id": "a"}, {"id": "b"}, {"id": "c"}])

        assert mock_container.upsert_item.call_count == 3

    def test_cosmos_error_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        with patch("azure.cosmos.CosmosClient", side_effect=Exception("oops")), \
             patch("azure.identity.DefaultAzureCredential"):
            persist_az_findings([{"id": "x"}])


# ---------------------------------------------------------------------------
# get_az_findings tests
# ---------------------------------------------------------------------------

from services.api_gateway.az_coverage_service import get_az_findings


class TestGetAzFindings:
    def test_returns_empty_when_no_endpoint(self, monkeypatch):
        monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
        assert get_az_findings() == []

    def test_returns_items(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        items = [{"id": "1", "has_zone_redundancy": True}, {"id": "2", "has_zone_redundancy": False}]
        mock_container = MagicMock()
        mock_container.query_items.return_value = items
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_client = MagicMock()
        mock_client.get_database_client.return_value = mock_db

        with patch("azure.cosmos.CosmosClient", return_value=mock_client), \
             patch("azure.identity.DefaultAzureCredential"):
            result = get_az_findings()
        assert len(result) == 2

    def test_cosmos_error_returns_empty(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        with patch("azure.cosmos.CosmosClient", side_effect=Exception("boom")), \
             patch("azure.identity.DefaultAzureCredential"):
            assert get_az_findings() == []


# ---------------------------------------------------------------------------
# get_az_summary tests
# ---------------------------------------------------------------------------

from services.api_gateway.az_coverage_service import get_az_summary


class TestGetAzSummary:
    def test_empty_findings(self):
        with patch("services.api_gateway.az_coverage_service.get_az_findings", return_value=[]):
            summary = get_az_summary()
        assert summary["total"] == 0
        assert summary["coverage_pct"] == 0.0

    def test_mixed_findings(self):
        findings = [
            {"has_zone_redundancy": True},
            {"has_zone_redundancy": True},
            {"has_zone_redundancy": False},
            {"has_zone_redundancy": False},
        ]
        with patch("services.api_gateway.az_coverage_service.get_az_findings", return_value=findings):
            summary = get_az_summary()
        assert summary["total"] == 4
        assert summary["zone_redundant"] == 2
        assert summary["non_redundant"] == 2
        assert summary["coverage_pct"] == 50.0

    def test_all_redundant_gives_100_pct(self):
        findings = [{"has_zone_redundancy": True}] * 5
        with patch("services.api_gateway.az_coverage_service.get_az_findings", return_value=findings):
            summary = get_az_summary()
        assert summary["coverage_pct"] == 100.0

    def test_error_returns_safe_default(self):
        with patch("services.api_gateway.az_coverage_service.get_az_findings", side_effect=Exception("boom")):
            summary = get_az_summary()
        assert summary["total"] == 0
        assert summary["coverage_pct"] == 0.0
        assert "zone_redundant" in summary
