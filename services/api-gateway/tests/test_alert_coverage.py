from __future__ import annotations
"""Tests for Alert Rule Coverage Audit service and endpoints (Phase 90)."""
import os

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("PGVECTOR_CONNECTION_STRING", "postgresql://test:test@localhost/test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.alert_rule_audit_service import (
    AlertCoverageGap,
    CRITICAL_RESOURCE_TYPES,
    get_alert_coverage_summary,
    get_gaps,
    persist_gaps,
    scan_alert_coverage,
)
from services.api_gateway.alert_rule_audit_endpoints import router

_test_app = FastAPI()
_test_app.include_router(router)
_test_app.state.credential = MagicMock()

http_client = TestClient(_test_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# CRITICAL_RESOURCE_TYPES severity classification tests
# ---------------------------------------------------------------------------

class TestResourceTypeSeverity:
    def test_vms_are_critical(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.compute/virtualmachines"]["severity"] == "critical"

    def test_aks_are_critical(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.containerservice/managedclusters"]["severity"] == "critical"

    def test_key_vault_is_critical(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.keyvault/vaults"]["severity"] == "critical"

    def test_storage_accounts_are_critical(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.storage/storageaccounts"]["severity"] == "critical"

    def test_nsg_is_high(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.network/networksecuritygroups"]["severity"] == "high"

    def test_vnet_is_high(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.network/virtualnetworks"]["severity"] == "high"

    def test_cosmos_db_is_high(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.documentdb/databaseaccounts"]["severity"] == "high"

    def test_postgres_is_high(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.dbforpostgresql/flexibleservers"]["severity"] == "high"

    def test_app_services_are_medium(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.web/sites"]["severity"] == "medium"

    def test_service_bus_is_medium(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.servicebus/namespaces"]["severity"] == "medium"

    def test_event_hubs_is_medium(self):
        assert CRITICAL_RESOURCE_TYPES["microsoft.eventhub/namespaces"]["severity"] == "medium"


# ---------------------------------------------------------------------------
# scan_alert_coverage tests
# ---------------------------------------------------------------------------

_METRIC_ALERT_ROWS = [
    {
        "rule_id": "/sub/alert1",
        "rule_name": "vm-cpu-alert",
        "subscription_id": "sub-1",
        "resource_group": "rg1",
        "severity": 2,
        "enabled": True,
        "target_resource_type": "microsoft.compute/virtualmachines",
    }
]

_RESOURCE_ROWS = [
    {
        "type": "microsoft.compute/virtualmachines",
        "subscription_id": "sub-1",
        "resource_count": 3,
    },
    {
        "type": "microsoft.keyvault/vaults",
        "subscription_id": "sub-1",
        "resource_count": 2,
    },
]


class TestScanAlertCoverage:
    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_covered_type_not_in_gaps(self, mock_arg):
        # VMs have an alert rule; Key Vaults do not
        mock_arg.side_effect = [_METRIC_ALERT_ROWS, [], _RESOURCE_ROWS]
        gaps = scan_alert_coverage(MagicMock(), ["sub-1"])
        gap_types = [g.resource_type for g in gaps]
        assert "Virtual Machines" not in gap_types
        assert "Key Vaults" in gap_types

    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_no_alert_rules_creates_gaps_for_all_present_types(self, mock_arg):
        mock_arg.side_effect = [[], [], _RESOURCE_ROWS]
        gaps = scan_alert_coverage(MagicMock(), ["sub-1"])
        gap_types = [g.resource_type for g in gaps]
        assert "Virtual Machines" in gap_types
        assert "Key Vaults" in gap_types

    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_gap_has_correct_severity(self, mock_arg):
        mock_arg.side_effect = [[], [], _RESOURCE_ROWS]
        gaps = scan_alert_coverage(MagicMock(), ["sub-1"])
        vm_gap = next(g for g in gaps if g.resource_type == "Virtual Machines")
        assert vm_gap.severity == "critical"

    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_gap_alert_rule_count_is_zero(self, mock_arg):
        mock_arg.side_effect = [[], [], _RESOURCE_ROWS]
        gaps = scan_alert_coverage(MagicMock(), ["sub-1"])
        for g in gaps:
            assert g.alert_rule_count == 0

    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_arg_exception_returns_empty_list(self, mock_arg):
        mock_arg.side_effect = RuntimeError("ARG down")
        gaps = scan_alert_coverage(MagicMock(), ["sub-1"])
        assert gaps == []

    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_unknown_resource_type_in_arg_skipped(self, mock_arg):
        unknown_rows = [{"type": "microsoft.unknown/things", "subscription_id": "sub-1", "resource_count": 5}]
        mock_arg.side_effect = [[], [], unknown_rows]
        gaps = scan_alert_coverage(MagicMock(), ["sub-1"])
        assert gaps == []

    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_gap_id_is_deterministic(self, mock_arg):
        mock_arg.side_effect = [[], [], _RESOURCE_ROWS]
        g1 = scan_alert_coverage(MagicMock(), ["sub-1"])
        mock_arg.side_effect = [[], [], _RESOURCE_ROWS]
        g2 = scan_alert_coverage(MagicMock(), ["sub-1"])
        assert g1[0].gap_id == g2[0].gap_id


# ---------------------------------------------------------------------------
# get_gaps tests
# ---------------------------------------------------------------------------

def _make_cosmos(items=None):
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = items or []
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    return cosmos, container


class TestGetGaps:
    def test_returns_items_from_cosmos(self):
        cosmos, _ = _make_cosmos([{"gap_id": "g1", "severity": "critical"}])
        result = get_gaps(cosmos, "aap")
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_returns_empty_on_exception(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("cosmos down")
        result = get_gaps(cosmos, "aap")
        assert result == []

    def test_subscription_filter_adds_param(self):
        cosmos, container = _make_cosmos([])
        get_gaps(cosmos, "aap", subscription_ids=["sub1"])
        call_kwargs = container.query_items.call_args[1]
        assert call_kwargs["parameters"] is not None

    def test_severity_filter_adds_severity_param(self):
        cosmos, container = _make_cosmos([])
        get_gaps(cosmos, "aap", severity="critical")
        call_kwargs = container.query_items.call_args[1]
        assert any(p["name"] == "@severity" for p in call_kwargs["parameters"])

    def test_no_filters_passes_no_params(self):
        cosmos, container = _make_cosmos([])
        get_gaps(cosmos, "aap")
        call_kwargs = container.query_items.call_args[1]
        assert call_kwargs["parameters"] is None


# ---------------------------------------------------------------------------
# get_alert_coverage_summary tests
# ---------------------------------------------------------------------------

class TestGetAlertCoverageSummary:
    def test_empty_gaps_returns_zero_totals(self):
        cosmos, _ = _make_cosmos([])
        result = get_alert_coverage_summary(cosmos, "aap")
        assert result["total_gaps"] == 0
        assert result["subscriptions_with_gaps"] == 0

    def test_aggregates_severity_counts(self):
        gaps = [
            {"severity": "critical", "subscription_id": "sub1"},
            {"severity": "critical", "subscription_id": "sub1"},
            {"severity": "high", "subscription_id": "sub2"},
            {"severity": "medium", "subscription_id": "sub2"},
        ]
        cosmos, _ = _make_cosmos(gaps)
        result = get_alert_coverage_summary(cosmos, "aap")
        assert result["total_gaps"] == 4
        assert result["critical_gaps"] == 2
        assert result["high_gaps"] == 1
        assert result["medium_gaps"] == 1

    def test_unique_subscriptions_counted(self):
        gaps = [
            {"severity": "critical", "subscription_id": "sub1"},
            {"severity": "high", "subscription_id": "sub1"},
            {"severity": "medium", "subscription_id": "sub2"},
        ]
        cosmos, _ = _make_cosmos(gaps)
        result = get_alert_coverage_summary(cosmos, "aap")
        assert result["subscriptions_with_gaps"] == 2

    def test_returns_safe_default_on_exception(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("boom")
        result = get_alert_coverage_summary(cosmos, "aap")
        # get_gaps swallows the error and returns [], so total_gaps is 0 and no crash
        assert result["total_gaps"] == 0
        assert "overall_coverage_pct" in result


# ---------------------------------------------------------------------------
# AlertCoverageGap.to_dict tests
# ---------------------------------------------------------------------------

class TestAlertCoverageGapToDict:
    def test_to_dict_includes_id_field(self):
        g = AlertCoverageGap(
            gap_id="gid1",
            subscription_id="sub1",
            resource_type="Virtual Machines",
            resource_count=5,
            alert_rule_count=0,
            severity="critical",
            recommendation="Add metric alerts.",
            scanned_at="2026-01-01T00:00:00+00:00",
        )
        d = g.to_dict()
        assert d["id"] == "gid1"
        assert d["gap_id"] == "gid1"
        assert d["severity"] == "critical"
        assert d["resource_count"] == 5


# ---------------------------------------------------------------------------
# FastAPI endpoint tests
# ---------------------------------------------------------------------------

def _make_cosmos_mock(items=None):
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = items or []
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    return cosmos


def _make_alert_client(items=None, credential=None):
    """Return a TestClient with dependency overrides for alert-coverage endpoints."""
    from fastapi import FastAPI
    from services.api_gateway.alert_rule_audit_endpoints import router as alert_router
    from services.api_gateway.dependencies import get_cosmos_client, get_credential

    app = FastAPI()
    app.include_router(alert_router)
    app.dependency_overrides[get_cosmos_client] = lambda: _make_cosmos_mock(items)
    app.dependency_overrides[get_credential] = lambda: credential or MagicMock()
    return TestClient(app, raise_server_exceptions=False)


class TestAlertCoverageEndpoints:
    def test_list_gaps_returns_200(self):
        client = _make_alert_client([{"gap_id": "g1", "severity": "critical"}])
        resp = client.get("/api/v1/alert-coverage/gaps")
        assert resp.status_code == 200
        data = resp.json()
        assert "gaps" in data
        assert data["total"] == 1

    def test_list_gaps_empty(self):
        client = _make_alert_client([])
        resp = client.get("/api/v1/alert-coverage/gaps")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_gaps_with_severity_filter(self):
        client = _make_alert_client([])
        resp = client.get("/api/v1/alert-coverage/gaps?severity=critical")
        assert resp.status_code == 200

    def test_summary_endpoint_returns_200(self):
        client = _make_alert_client([{"severity": "critical", "subscription_id": "sub1"}])
        resp = client.get("/api/v1/alert-coverage/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_gaps" in data
        assert "overall_coverage_pct" in data

    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_scan_endpoint_returns_ok(self, mock_arg):
        mock_arg.side_effect = [[], [], _RESOURCE_ROWS]
        client = _make_alert_client()
        resp = client.post("/api/v1/alert-coverage/scan?subscription_id=sub-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "gaps_found" in data

    @patch("services.api_gateway.alert_rule_audit_service.run_arg_query")
    def test_scan_endpoint_no_subscription_still_works(self, mock_arg):
        mock_arg.side_effect = [[], [], []]
        client = _make_alert_client()
        resp = client.post("/api/v1/alert-coverage/scan")
        assert resp.status_code == 200
