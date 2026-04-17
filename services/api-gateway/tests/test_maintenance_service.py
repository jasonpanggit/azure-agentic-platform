from __future__ import annotations
"""Tests for maintenance_service — mocks ARG queries and Cosmos DB."""

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.maintenance_service import (
    MaintenanceEvent,
    _classify_event_type,
    _map_level_to_severity,
    _stable_id,
    get_events,
    get_maintenance_summary,
    persist_events,
    scan_maintenance_events,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

MOCK_CREDENTIAL = MagicMock()
_NOW = datetime.now(tz=timezone.utc).isoformat()

_RESOURCE_HEALTH_ROW: Dict[str, Any] = {
    "health_id": "/sub/sub-1/rg/rg-1/vm/vm1/providers/microsoft.resourcehealth/availability",
    "resource_id": "/sub/sub-1/rg/rg-1/vm/vm1",
    "resource_type": "microsoft.compute/virtualmachines",
    "subscription_id": "sub-1",
    "resource_group": "rg-1",
    "availability_state": "Degraded",
    "reason_type": "UserInitiated",
    "summary": "VM is degraded",
    "reason_chronicity": "Persistent",
    "occurred_time": _NOW,
    "reported_time": _NOW,
}

_SERVICE_HEALTH_ROW: Dict[str, Any] = {
    "event_id": "/sub/sub-1/providers/microsoft.resourcehealth/events/maint-1",
    "subscription_id": "sub-1",
    "title": "Planned VM maintenance in East US",
    "event_type": "PlannedMaintenance",
    "status": "Active",
    "level": "Warning",
    "impact_start_time": _NOW,
    "impact_mitigation_time": "",
    "affected_regions": "East US",
    "description": "Scheduled host maintenance",
}


def _make_cosmos(items: List[Dict[str, Any]]) -> MagicMock:
    container = MagicMock()
    container.query_items.return_value = items
    db = MagicMock()
    db.get_container_client.return_value = container
    cosmos = MagicMock()
    cosmos.get_database_client.return_value = db
    return cosmos


def _make_event(**kwargs) -> MaintenanceEvent:
    defaults: Dict[str, Any] = dict(
        event_id="evt-1",
        subscription_id="sub-1",
        resource_id="/subscriptions/sub-1/rg/rg-1/vm/vm1",
        resource_group="rg-1",
        event_type="planned_maintenance",
        title="Host Maintenance",
        status="Active",
        level="Warning",
        impact_start=_NOW,
        impact_end="",
        description="Scheduled maintenance",
        severity="high",
        detected_at=_NOW,
    )
    defaults.update(kwargs)
    return MaintenanceEvent(**defaults)


# ── Helper unit tests ─────────────────────────────────────────────────────────

class TestStableId:
    def test_deterministic(self):
        assert _stable_id("source-id-1") == _stable_id("source-id-1")

    def test_different_inputs_differ(self):
        assert _stable_id("id-a") != _stable_id("id-b")


class TestMapLevelToSeverity:
    def test_critical_level(self):
        assert _map_level_to_severity("critical") == "critical"

    def test_unavailable_state(self):
        assert _map_level_to_severity("", availability_state="Unavailable") == "critical"

    def test_warning_level(self):
        assert _map_level_to_severity("warning") == "high"

    def test_degraded_state(self):
        assert _map_level_to_severity("", availability_state="Degraded") == "high"

    def test_information_is_medium(self):
        assert _map_level_to_severity("Information") == "medium"

    def test_empty_strings_default_medium(self):
        assert _map_level_to_severity("") == "medium"


class TestClassifyEventType:
    def test_planned_in_raw_type(self):
        assert _classify_event_type("PlannedMaintenance") == "planned_maintenance"

    def test_planned_in_reason_type(self):
        assert _classify_event_type("", reason_type="Planned") == "planned_maintenance"

    def test_advisory_in_raw_type(self):
        assert _classify_event_type("HealthAdvisory") == "health_advisory"

    def test_non_planned_non_advisory_falls_back_to_resource_degraded(self):
        # "UserInitiated" contains neither "planned" nor "advisory" substring
        assert _classify_event_type("UserInitiated") == "resource_degraded"

    def test_empty_falls_back_to_resource_degraded(self):
        assert _classify_event_type("") == "resource_degraded"


# ── scan_maintenance_events ───────────────────────────────────────────────────

class TestScanMaintenanceEvents:
    def test_happy_path_resource_and_service_health(self):
        with patch(
            "services.api_gateway.maintenance_service.run_arg_query",
            side_effect=[
                [_RESOURCE_HEALTH_ROW],   # resource health call
                [_SERVICE_HEALTH_ROW],    # service health call
            ],
        ):
            events = scan_maintenance_events(MOCK_CREDENTIAL, ["sub-1"])

        assert len(events) == 2
        types = {e.event_type for e in events}
        assert "resource_degraded" in types
        assert "planned_maintenance" in types

    def test_empty_subscription_list_returns_empty(self):
        events = scan_maintenance_events(MOCK_CREDENTIAL, [])
        assert events == []

    def test_resource_health_arg_exception_still_returns_service_health(self):
        with patch(
            "services.api_gateway.maintenance_service.run_arg_query",
            side_effect=[
                Exception("ARG timeout"),  # resource health fails
                [_SERVICE_HEALTH_ROW],     # service health succeeds
            ],
        ):
            events = scan_maintenance_events(MOCK_CREDENTIAL, ["sub-1"])

        assert len(events) == 1
        assert events[0].event_type == "planned_maintenance"

    def test_service_health_arg_exception_still_returns_resource_health(self):
        with patch(
            "services.api_gateway.maintenance_service.run_arg_query",
            side_effect=[
                [_RESOURCE_HEALTH_ROW],   # resource health succeeds
                Exception("ARG timeout"), # service health fails
            ],
        ):
            events = scan_maintenance_events(MOCK_CREDENTIAL, ["sub-1"])

        assert len(events) == 1
        assert events[0].event_type == "resource_degraded"

    def test_both_arg_exceptions_returns_empty(self):
        with patch(
            "services.api_gateway.maintenance_service.run_arg_query",
            side_effect=[Exception("fail"), Exception("fail")],
        ):
            events = scan_maintenance_events(MOCK_CREDENTIAL, ["sub-1"])

        assert events == []

    def test_arg_helper_none_returns_empty(self):
        with patch("services.api_gateway.maintenance_service.run_arg_query", None):
            events = scan_maintenance_events(MOCK_CREDENTIAL, ["sub-1"])
        assert events == []

    def test_empty_arg_rows_returns_empty(self):
        with patch(
            "services.api_gateway.maintenance_service.run_arg_query",
            side_effect=[[], []],
        ):
            events = scan_maintenance_events(MOCK_CREDENTIAL, ["sub-1"])
        assert events == []

    def test_resource_health_event_fields_mapped_correctly(self):
        with patch(
            "services.api_gateway.maintenance_service.run_arg_query",
            side_effect=[[_RESOURCE_HEALTH_ROW], []],
        ):
            events = scan_maintenance_events(MOCK_CREDENTIAL, ["sub-1"])

        e = events[0]
        assert e.subscription_id == "sub-1"
        assert e.resource_group == "rg-1"
        assert e.status == "Active"
        assert e.description == "VM is degraded"

    def test_service_health_event_fields_mapped_correctly(self):
        with patch(
            "services.api_gateway.maintenance_service.run_arg_query",
            side_effect=[[], [_SERVICE_HEALTH_ROW]],
        ):
            events = scan_maintenance_events(MOCK_CREDENTIAL, ["sub-1"])

        e = events[0]
        assert e.title == "Planned VM maintenance in East US"
        assert e.status == "Active"
        assert e.resource_id == ""      # service health has no resource_id


# ── persist_events ────────────────────────────────────────────────────────────

class TestPersistEvents:
    def test_upserts_each_event(self):
        events = [_make_event(event_id="e1"), _make_event(event_id="e2")]
        container = MagicMock()
        db = MagicMock()
        db.get_container_client.return_value = container
        cosmos = MagicMock()
        cosmos.get_database_client.return_value = db

        persist_events(cosmos, "aap-db", events)

        assert container.upsert_item.call_count == 2
        call_args = [c.args[0] for c in container.upsert_item.call_args_list]
        ids = {c["id"] for c in call_args}
        assert "e1" in ids
        assert "e2" in ids

    def test_empty_list_skips_upsert(self):
        cosmos = MagicMock()
        persist_events(cosmos, "aap-db", [])
        cosmos.get_database_client.assert_not_called()

    def test_cosmos_exception_does_not_raise(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = Exception("cosmos down")
        persist_events(cosmos, "aap-db", [_make_event()])


# ── get_events ────────────────────────────────────────────────────────────────

class TestGetEvents:
    def _cosmos_item(self, **kwargs) -> Dict[str, Any]:
        e = asdict(_make_event(**kwargs))
        e["id"] = e["event_id"]
        return e

    def test_returns_all_events_no_filter(self):
        items = [self._cosmos_item(event_id="e1"), self._cosmos_item(event_id="e2")]
        cosmos = _make_cosmos(items)
        result = get_events(cosmos, "aap-db")
        assert len(result) == 2

    def test_subscription_filter_includes_placeholders(self):
        items = [self._cosmos_item(event_id="e3")]
        cosmos = _make_cosmos(items)
        get_events(cosmos, "aap-db", subscription_ids=["sub-1", "sub-2"])
        container = cosmos.get_database_client().get_container_client()
        query_call = container.query_items.call_args
        query_str = query_call.kwargs.get("query") or query_call.args[0]
        assert "@sub0" in query_str
        assert "@sub1" in query_str

    def test_event_type_filter_in_query(self):
        items = [self._cosmos_item(event_id="e4", event_type="planned_maintenance")]
        cosmos = _make_cosmos(items)
        get_events(cosmos, "aap-db", event_type="planned_maintenance")
        container = cosmos.get_database_client().get_container_client()
        query_call = container.query_items.call_args
        query_str = query_call.kwargs.get("query") or query_call.args[0]
        assert "@event_type" in query_str

    def test_status_filter_in_query(self):
        items = [self._cosmos_item(event_id="e5", status="Active")]
        cosmos = _make_cosmos(items)
        get_events(cosmos, "aap-db", status="Active")
        container = cosmos.get_database_client().get_container_client()
        query_call = container.query_items.call_args
        query_str = query_call.kwargs.get("query") or query_call.args[0]
        assert "@status" in query_str

    def test_empty_cosmos_returns_empty(self):
        cosmos = _make_cosmos([])
        result = get_events(cosmos, "aap-db")
        assert result == []

    def test_cosmos_exception_returns_empty(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = Exception("cosmos error")
        result = get_events(cosmos, "aap-db")
        assert result == []


# ── get_maintenance_summary ───────────────────────────────────────────────────

class TestGetMaintenanceSummary:
    def _cosmos_item(self, **kwargs) -> Dict[str, Any]:
        e = asdict(_make_event(**kwargs))
        e["id"] = e["event_id"]
        return e

    def test_summary_counts_correctly(self):
        items = [
            self._cosmos_item(event_id="e1", event_type="planned_maintenance", status="Active", severity="critical", subscription_id="sub-1"),
            self._cosmos_item(event_id="e2", event_type="health_advisory", status="InProgress", severity="high", subscription_id="sub-2"),
            self._cosmos_item(event_id="e3", event_type="resource_degraded", status="Resolved", severity="medium", subscription_id="sub-1"),
        ]
        cosmos = _make_cosmos(items)
        summary = get_maintenance_summary(cosmos, "aap-db")

        assert summary["active_events"] == 2           # Active + InProgress
        assert summary["planned_upcoming"] == 1
        assert summary["health_advisories"] == 1
        assert summary["affected_subscriptions"] == 2  # sub-1 and sub-2 (only active)
        assert summary["critical_count"] == 1

    def test_summary_empty_events(self):
        cosmos = _make_cosmos([])
        summary = get_maintenance_summary(cosmos, "aap-db")
        assert summary["active_events"] == 0
        assert summary["planned_upcoming"] == 0
        assert summary["affected_subscriptions"] == 0

    def test_summary_cosmos_error_returns_zeros(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = Exception("cosmos down")
        summary = get_maintenance_summary(cosmos, "aap-db")
        assert summary["active_events"] == 0
        assert summary["critical_count"] == 0
