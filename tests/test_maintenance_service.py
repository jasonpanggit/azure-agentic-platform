"""Unit tests for maintenance_service.py (Phase 94).

Covers:
- _stable_id: determinism and uniqueness
- _map_level_to_severity: all branches
- _classify_event_type: planned, advisory, degraded
- scan_maintenance_events: happy path, ARG failure, empty subscriptions, partial failure
- persist_events: happy path, empty list, exception
- get_events: no filter, subscription filter, event_type filter, exception
- get_maintenance_summary: counts correct, empty
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
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


# ---------------------------------------------------------------------------
# _stable_id
# ---------------------------------------------------------------------------

def test_stable_id_deterministic():
    assert _stable_id("abc") == _stable_id("abc")


def test_stable_id_unique():
    assert _stable_id("abc") != _stable_id("xyz")


# ---------------------------------------------------------------------------
# _map_level_to_severity
# ---------------------------------------------------------------------------

def test_map_level_critical():
    assert _map_level_to_severity("critical") == "critical"


def test_map_level_unavailable_state():
    assert _map_level_to_severity("information", availability_state="Unavailable") == "critical"


def test_map_level_warning():
    assert _map_level_to_severity("warning") == "high"


def test_map_level_degraded_state():
    assert _map_level_to_severity("information", availability_state="Degraded") == "high"


def test_map_level_information():
    assert _map_level_to_severity("information") == "medium"


# ---------------------------------------------------------------------------
# _classify_event_type
# ---------------------------------------------------------------------------

def test_classify_planned_from_type():
    assert _classify_event_type("PlannedMaintenance") == "planned_maintenance"


def test_classify_planned_from_reason():
    assert _classify_event_type("", reason_type="Planned") == "planned_maintenance"


def test_classify_advisory():
    assert _classify_event_type("HealthAdvisory") == "health_advisory"


def test_classify_degraded_fallback():
    assert _classify_event_type("SomeOtherType") == "resource_degraded"


# ---------------------------------------------------------------------------
# scan_maintenance_events
# ---------------------------------------------------------------------------

def _make_credential() -> MagicMock:
    return MagicMock()


def _make_resource_health_row() -> Dict[str, Any]:
    return {
        "health_id": "/sub/s1/rg/rg1/vm/vm1/providers/microsoft.resourcehealth/abc",
        "resource_id": "/sub/s1/rg/rg1/vm/vm1",
        "resource_type": "virtualmachines",
        "subscription_id": "sub1",
        "resource_group": "rg1",
        "availability_state": "Degraded",
        "reason_type": "Hardware",
        "summary": "VM is degraded",
        "reason_chronicity": "Persistent",
        "occurred_time": "2026-04-16T10:00:00Z",
        "reported_time": "2026-04-16T10:05:00Z",
    }


def _make_service_health_row() -> Dict[str, Any]:
    return {
        "event_id": "/subscriptions/sub1/providers/microsoft.resourcehealth/events/ev1",
        "subscription_id": "sub1",
        "title": "Planned maintenance: East US VMs",
        "event_type": "PlannedMaintenance",
        "status": "Active",
        "level": "Warning",
        "impact_start_time": "2026-04-20T02:00:00Z",
        "impact_mitigation_time": "2026-04-20T06:00:00Z",
        "affected_regions": "East US",
        "description": "Scheduled host updates",
    }


def test_scan_empty_subscriptions():
    cred = _make_credential()
    result = scan_maintenance_events(cred, [])
    assert result == []


def test_scan_happy_path():
    cred = _make_credential()
    with patch("services.api_gateway.maintenance_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = [
            [_make_resource_health_row()],
            [_make_service_health_row()],
        ]
        result = scan_maintenance_events(cred, ["sub1"])
    assert len(result) == 2
    types = {e.event_type for e in result}
    assert "resource_degraded" in types
    assert "planned_maintenance" in types


def test_scan_resource_health_arg_failure_continues():
    cred = _make_credential()
    with patch("services.api_gateway.maintenance_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = [
            Exception("ARG timeout"),
            [_make_service_health_row()],
        ]
        result = scan_maintenance_events(cred, ["sub1"])
    # Should still return service health events
    assert len(result) == 1
    assert result[0].event_type == "planned_maintenance"


def test_scan_both_arg_failures_returns_empty():
    cred = _make_credential()
    with patch("services.api_gateway.maintenance_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = Exception("ARG down")
        result = scan_maintenance_events(cred, ["sub1"])
    assert result == []


def test_scan_arg_helper_import_error():
    cred = _make_credential()
    import sys
    with patch.dict(sys.modules, {"services.api_gateway.arg_helper": None}):
        # Simulate ImportError path
        result = scan_maintenance_events(cred, ["sub1"])
    # May return [] or process depending on cached import; no exception is the key assertion
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# persist_events
# ---------------------------------------------------------------------------

def _make_cosmos() -> tuple:
    cosmos = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    return cosmos, container


def _make_event() -> MaintenanceEvent:
    return MaintenanceEvent(
        event_id="ev1",
        subscription_id="sub1",
        resource_id="/sub/s1/vm1",
        resource_group="rg1",
        event_type="planned_maintenance",
        title="Scheduled maintenance",
        status="Active",
        level="Warning",
        impact_start="2026-04-20T02:00:00Z",
        impact_end="2026-04-20T06:00:00Z",
        description="Host updates",
        severity="high",
        detected_at="2026-04-17T00:00:00Z",
    )


def test_persist_events_calls_upsert():
    cosmos, container = _make_cosmos()
    persist_events(cosmos, "aap", [_make_event()])
    container.upsert_item.assert_called_once()
    item = container.upsert_item.call_args[0][0]
    assert item["id"] == "ev1"


def test_persist_events_empty_no_call():
    cosmos, container = _make_cosmos()
    persist_events(cosmos, "aap", [])
    container.upsert_item.assert_not_called()


def test_persist_events_exception_does_not_raise():
    cosmos, container = _make_cosmos()
    container.upsert_item.side_effect = Exception("cosmos down")
    persist_events(cosmos, "aap", [_make_event()])  # must not raise


# ---------------------------------------------------------------------------
# get_events
# ---------------------------------------------------------------------------

def _cosmos_row() -> Dict[str, Any]:
    return {
        "id": "ev1", "event_id": "ev1", "subscription_id": "sub1",
        "resource_id": "/r/vm1", "resource_group": "rg1",
        "event_type": "planned_maintenance", "title": "Maint",
        "status": "Active", "level": "Warning",
        "impact_start": "2026-04-20T02:00:00Z", "impact_end": "2026-04-20T06:00:00Z",
        "description": "Host updates", "severity": "high", "detected_at": "now",
    }


def test_get_events_no_filter():
    cosmos, container = _make_cosmos()
    container.query_items.return_value = [_cosmos_row()]
    result = get_events(cosmos, "aap")
    assert len(result) == 1
    assert result[0].event_type == "planned_maintenance"


def test_get_events_subscription_filter():
    cosmos, container = _make_cosmos()
    container.query_items.return_value = []
    result = get_events(cosmos, "aap", subscription_ids=["sub1"])
    container.query_items.assert_called_once()
    assert result == []


def test_get_events_event_type_filter():
    cosmos, container = _make_cosmos()
    container.query_items.return_value = [_cosmos_row()]
    result = get_events(cosmos, "aap", event_type="planned_maintenance")
    assert result[0].event_type == "planned_maintenance"


def test_get_events_status_filter():
    cosmos, container = _make_cosmos()
    container.query_items.return_value = [_cosmos_row()]
    result = get_events(cosmos, "aap", status="Active")
    assert result[0].status == "Active"


def test_get_events_exception_returns_empty():
    cosmos, container = _make_cosmos()
    container.query_items.side_effect = Exception("cosmos error")
    result = get_events(cosmos, "aap")
    assert result == []


# ---------------------------------------------------------------------------
# get_maintenance_summary
# ---------------------------------------------------------------------------

def test_get_maintenance_summary_counts():
    cosmos, container = _make_cosmos()
    rows = [
        {**_cosmos_row(), "id": "e1", "event_id": "e1", "status": "Active",
         "event_type": "planned_maintenance", "severity": "critical", "subscription_id": "sub1"},
        {**_cosmos_row(), "id": "e2", "event_id": "e2", "status": "Active",
         "event_type": "health_advisory", "severity": "medium", "subscription_id": "sub2"},
        {**_cosmos_row(), "id": "e3", "event_id": "e3", "status": "Resolved",
         "event_type": "resource_degraded", "severity": "high", "subscription_id": "sub1"},
    ]
    container.query_items.return_value = rows
    summary = get_maintenance_summary(cosmos, "aap")
    assert summary["active_events"] == 2
    assert summary["planned_upcoming"] == 1
    assert summary["health_advisories"] == 1
    assert summary["affected_subscriptions"] == 2
    assert summary["critical_count"] == 1


def test_get_maintenance_summary_empty():
    cosmos, container = _make_cosmos()
    container.query_items.return_value = []
    summary = get_maintenance_summary(cosmos, "aap")
    assert summary["active_events"] == 0
    assert summary["planned_upcoming"] == 0
    assert summary["critical_count"] == 0
