from __future__ import annotations
"""Tests for GET /api/v1/cve/fleet endpoint."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────

MOCK_VMS = [
    {
        "vm_name": "vm-prod-01",
        "resource_group": "rg-prod",
        "subscription_id": "sub-abc",
        "os_type": "Windows",
        "os_version": "Windows Server 2019",
        "vm_type": "Azure VM",
        "resource_id": "/subscriptions/sub-abc/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
    },
    {
        "vm_name": "arc-srv-01",
        "resource_group": "rg-arc",
        "subscription_id": "sub-abc",
        "os_type": "Windows",
        "os_version": "Windows Server 2016 Standard",
        "vm_type": "Arc VM",
        "resource_id": "/subscriptions/sub-abc/resourceGroups/rg-arc/providers/Microsoft.HybridCompute/machines/arc-srv-01",
    },
]

MOCK_CVE_LIST = [
    {
        "cve_id": "CVE-2024-1111",
        "severity": "CRITICAL",
        "status": "UNPATCHED",
        "cvss_score": 9.8,
        "affected_product": "Windows",
        "affected_versions": "",
        "description": "Critical RCE",
        "published_date": "2024-01-01",
        "patched_kb_ids": ["KB5034441"],
        "patched_by_installed": False,
        "patched_by_pending": False,
    },
    {
        "cve_id": "CVE-2024-2222",
        "severity": "HIGH",
        "status": "PENDING_PATCH",
        "cvss_score": 7.5,
        "affected_product": "Windows",
        "affected_versions": "",
        "description": "High severity",
        "published_date": "2024-02-01",
        "patched_kb_ids": ["KB5035853"],
        "patched_by_installed": False,
        "patched_by_pending": True,
    },
]


def _make_summary():
    """Helper: produce a valid summary from MOCK_CVE_LIST."""
    from services.api_gateway.cve_fleet_endpoints import _summarise_cve_list
    return _summarise_cve_list(MOCK_CVE_LIST)


# ── Unit tests for _summarise_cve_list ───────────────────────────────────────

class TestSummariseCveList:
    def test_counts_unpatched_by_severity(self):
        from services.api_gateway.cve_fleet_endpoints import _summarise_cve_list
        summary = _summarise_cve_list(MOCK_CVE_LIST)
        assert summary["critical"] == 1
        assert summary["high"] == 1

    def test_top_cves_capped_at_3(self):
        from services.api_gateway.cve_fleet_endpoints import _summarise_cve_list
        many_cves = [
            {
                "cve_id": f"CVE-2024-{i}",
                "severity": "CRITICAL",
                "status": "UNPATCHED",
                "cvss_score": 9.8,
                "affected_product": "Windows",
                "affected_versions": "",
                "description": "",
                "published_date": None,
                "patched_kb_ids": [],
                "patched_by_installed": False,
                "patched_by_pending": False,
            }
            for i in range(5)
        ]
        summary = _summarise_cve_list(many_cves)
        assert len(summary["top_cves"]) <= 3

    def test_patch_status_critical_when_critical_unpatched(self):
        from services.api_gateway.cve_fleet_endpoints import _summarise_cve_list
        summary = _summarise_cve_list(MOCK_CVE_LIST)
        assert summary["patch_status"] == "CRITICAL"

    def test_patch_status_clean_when_all_patched(self):
        from services.api_gateway.cve_fleet_endpoints import _summarise_cve_list
        patched_cves = [
            {
                "cve_id": "CVE-2024-9999",
                "severity": "HIGH",
                "status": "PATCHED",
                "cvss_score": 7.5,
                "affected_product": "Windows",
                "affected_versions": "",
                "description": "",
                "published_date": None,
                "patched_kb_ids": ["KB1"],
                "patched_by_installed": True,
                "patched_by_pending": False,
            }
        ]
        summary = _summarise_cve_list(patched_cves)
        assert summary["patch_status"] == "CLEAN"
        assert summary["critical"] == 0

    def test_empty_list_returns_zero_counts(self):
        from services.api_gateway.cve_fleet_endpoints import _summarise_cve_list
        summary = _summarise_cve_list([])
        assert summary["critical"] == 0
        assert summary["total_unpatched"] == 0

    def test_patch_status_high_when_only_high_unpatched(self):
        from services.api_gateway.cve_fleet_endpoints import _summarise_cve_list
        high_only = [
            {
                "cve_id": "CVE-2024-3333",
                "severity": "HIGH",
                "status": "UNPATCHED",
                "cvss_score": 7.5,
                "affected_product": "Windows",
                "affected_versions": "",
                "description": "",
                "published_date": None,
                "patched_kb_ids": [],
                "patched_by_installed": False,
                "patched_by_pending": False,
            }
        ]
        summary = _summarise_cve_list(high_only)
        assert summary["patch_status"] == "HIGH"
        assert summary["critical"] == 0
        assert summary["high"] == 1

    def test_top_cves_ordered_critical_before_high(self):
        from services.api_gateway.cve_fleet_endpoints import _summarise_cve_list
        mixed = [
            {"cve_id": "CVE-HIGH-1", "severity": "HIGH", "status": "UNPATCHED",
             "cvss_score": 7.5, "affected_product": "W", "affected_versions": "",
             "description": "", "published_date": None, "patched_kb_ids": [],
             "patched_by_installed": False, "patched_by_pending": False},
            {"cve_id": "CVE-CRIT-1", "severity": "CRITICAL", "status": "UNPATCHED",
             "cvss_score": 9.8, "affected_product": "W", "affected_versions": "",
             "description": "", "published_date": None, "patched_kb_ids": [],
             "patched_by_installed": False, "patched_by_pending": False},
        ]
        summary = _summarise_cve_list(mixed)
        # CRITICAL should appear before HIGH in top_cves
        assert summary["top_cves"][0] == "CVE-CRIT-1"


# ── Unit tests for _enumerate_vms_arg ────────────────────────────────────────

class TestEnumerateVmsArg:
    def test_returns_empty_when_resourcegraphclient_is_none(self):
        from services.api_gateway.cve_fleet_endpoints import _enumerate_vms_arg
        with patch("services.api_gateway.cve_fleet_endpoints.ResourceGraphClient", None):
            result = _enumerate_vms_arg(MagicMock(), ["sub-abc"])
        assert result == []

    def test_returns_empty_on_arg_exception(self):
        from services.api_gateway.cve_fleet_endpoints import _enumerate_vms_arg
        mock_client = MagicMock()
        mock_client.resources.side_effect = RuntimeError("ARG unavailable")
        with patch("services.api_gateway.cve_fleet_endpoints.ResourceGraphClient", return_value=mock_client):
            result = _enumerate_vms_arg(MagicMock(), ["sub-abc"])
        assert result == []

    def test_maps_arg_rows_to_vm_dicts(self):
        from services.api_gateway.cve_fleet_endpoints import _enumerate_vms_arg
        mock_row = {
            "name": "vm-01",
            "resourceGroup": "rg-prod",
            "subscriptionId": "sub-abc",
            "osType": "Windows",
            "osVersion": "WS2019",
            "vmType": "Azure VM",
            "id": "/subscriptions/sub-abc/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-01",
        }
        mock_response = MagicMock()
        mock_response.data = [mock_row]
        mock_client = MagicMock()
        mock_client.resources.return_value = mock_response
        with patch("services.api_gateway.cve_fleet_endpoints.ResourceGraphClient", return_value=mock_client):
            with patch("services.api_gateway.cve_fleet_endpoints.QueryRequest", return_value=MagicMock()):
                result = _enumerate_vms_arg(MagicMock(), ["sub-abc"])
        assert len(result) == 1
        assert result[0]["vm_name"] == "vm-01"
        assert result[0]["resource_group"] == "rg-prod"


# ── Integration-style endpoint tests ─────────────────────────────────────────

class TestGetCveFleetEndpoint:
    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from services.api_gateway.cve_fleet_endpoints import router
        from services.api_gateway.dependencies import get_credential_for_subscriptions
        app = FastAPI()
        app.include_router(router)
        # Override the credential dependency so tests never hit Azure
        app.dependency_overrides[get_credential_for_subscriptions] = lambda: MagicMock()
        return TestClient(app, raise_server_exceptions=False)

    def test_returns_400_when_no_subscriptions(self, client):
        with patch("services.api_gateway.cve_fleet_endpoints.resolve_subscription_ids", return_value=[]):
            resp = client.get("/api/v1/cve/fleet")
        assert resp.status_code == 400

    def test_returns_fleet_rows_with_data(self, client):
        with (
            patch("services.api_gateway.cve_fleet_endpoints.resolve_subscription_ids", return_value=["sub-abc"]),
            patch("services.api_gateway.cve_fleet_endpoints.get_cached", return_value=MOCK_VMS),
            patch(
                "services.api_gateway.cve_fleet_endpoints._load_fleet_cve_cache",
                new_callable=AsyncMock,
                return_value={
                    "/subscriptions/sub-abc/resourcegroups/rg-prod/vm/vm-prod-01": _make_summary(),
                },
            ),
            patch("services.api_gateway.cve_fleet_endpoints.get_credential_for_subscriptions", return_value=MagicMock()),
        ):
            resp = client.get("/api/v1/cve/fleet?subscriptions=sub-abc")
        assert resp.status_code == 200
        body = resp.json()
        assert "vms" in body
        assert "total_vms" in body
        assert body["total_vms"] == 2
        assert body["vms_with_data"] == 1

    def test_vms_without_cache_have_no_data_status(self, client):
        with (
            patch("services.api_gateway.cve_fleet_endpoints.resolve_subscription_ids", return_value=["sub-abc"]),
            patch("services.api_gateway.cve_fleet_endpoints.get_cached", return_value=MOCK_VMS),
            patch(
                "services.api_gateway.cve_fleet_endpoints._load_fleet_cve_cache",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("services.api_gateway.cve_fleet_endpoints.get_credential_for_subscriptions", return_value=MagicMock()),
        ):
            resp = client.get("/api/v1/cve/fleet?subscriptions=sub-abc")
        assert resp.status_code == 200
        body = resp.json()
        for vm in body["vms"]:
            assert vm["patch_status"] == "NO_DATA"
            assert vm["has_data"] is False

    def test_response_sorted_critical_first(self, client):
        cache = {
            "/subscriptions/sub-abc/resourcegroups/rg-prod/vm/vm-prod-01": {
                "critical": 3, "high": 1, "medium": 0, "low": 0,
                "total_unpatched": 4, "top_cves": ["CVE-2024-1111"],
                "patch_status": "CRITICAL",
            },
            "/subscriptions/sub-abc/resourcegroups/rg-arc/vm/arc-srv-01": {
                "critical": 0, "high": 1, "medium": 0, "low": 0,
                "total_unpatched": 1, "top_cves": [],
                "patch_status": "HIGH",
            },
        }
        with (
            patch("services.api_gateway.cve_fleet_endpoints.resolve_subscription_ids", return_value=["sub-abc"]),
            patch("services.api_gateway.cve_fleet_endpoints.get_cached", return_value=MOCK_VMS),
            patch(
                "services.api_gateway.cve_fleet_endpoints._load_fleet_cve_cache",
                new_callable=AsyncMock,
                return_value=cache,
            ),
            patch("services.api_gateway.cve_fleet_endpoints.get_credential_for_subscriptions", return_value=MagicMock()),
        ):
            resp = client.get("/api/v1/cve/fleet?subscriptions=sub-abc")
        body = resp.json()
        statuses = [v["patch_status"] for v in body["vms"]]
        assert statuses[0] == "CRITICAL"

    def test_response_contains_expected_fields(self, client):
        with (
            patch("services.api_gateway.cve_fleet_endpoints.resolve_subscription_ids", return_value=["sub-abc"]),
            patch("services.api_gateway.cve_fleet_endpoints.get_cached", return_value=MOCK_VMS[:1]),
            patch(
                "services.api_gateway.cve_fleet_endpoints._load_fleet_cve_cache",
                new_callable=AsyncMock,
                return_value={
                    "/subscriptions/sub-abc/resourcegroups/rg-prod/vm/vm-prod-01": _make_summary(),
                },
            ),
            patch("services.api_gateway.cve_fleet_endpoints.get_credential_for_subscriptions", return_value=MagicMock()),
        ):
            resp = client.get("/api/v1/cve/fleet")
        assert resp.status_code == 200
        vm = resp.json()["vms"][0]
        required_keys = {
            "vm_name", "subscription_id", "resource_group", "os_type", "os_version",
            "vm_type", "critical_count", "high_count", "medium_count", "low_count",
            "total_unpatched", "top_cves", "patch_status", "has_data",
        }
        assert required_keys.issubset(vm.keys())

    def test_empty_vm_list_returns_zero_counts(self, client):
        with (
            patch("services.api_gateway.cve_fleet_endpoints.resolve_subscription_ids", return_value=["sub-abc"]),
            patch("services.api_gateway.cve_fleet_endpoints.get_cached", return_value=[]),
            patch(
                "services.api_gateway.cve_fleet_endpoints._load_fleet_cve_cache",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("services.api_gateway.cve_fleet_endpoints.get_credential_for_subscriptions", return_value=MagicMock()),
        ):
            resp = client.get("/api/v1/cve/fleet?subscriptions=sub-abc")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_vms"] == 0
        assert body["vms_with_data"] == 0
        assert body["vms"] == []
