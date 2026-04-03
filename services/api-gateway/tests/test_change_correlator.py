"""Unit tests for change_correlator.py.

Tests cover:
- Scoring math (_score_event, _change_type_score)
- Activity Log query helper (_query_activity_log_for_resource)
- Full correlate_incident_changes: happy path with topology expansion
- Full correlate_incident_changes: topology unavailable (graceful degradation)
- Full correlate_incident_changes: cosmos_client=None (no persistence)
- Full correlate_incident_changes: activity log returns no write events
- Full correlate_incident_changes: all events outside window
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from datetime import datetime, timezone, timedelta

RESOURCE_ID = "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-001"
NIC_RESOURCE_ID = "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-01"
INCIDENT_CREATED_AT = datetime(2026, 4, 3, 12, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helper imports — loaded here after sys.modules may have been patched
# ---------------------------------------------------------------------------

def _import_module():
    from services.api_gateway import change_correlator
    return change_correlator


# ---------------------------------------------------------------------------
# 1. _extract_subscription_id
# ---------------------------------------------------------------------------

def test_extract_subscription_id():
    from services.api_gateway.change_correlator import _extract_subscription_id
    assert _extract_subscription_id(RESOURCE_ID) == "sub-123"


# ---------------------------------------------------------------------------
# 2. _resource_name
# ---------------------------------------------------------------------------

def test_resource_name():
    from services.api_gateway.change_correlator import _resource_name
    assert _resource_name(RESOURCE_ID) == "vm-prod-001"


# ---------------------------------------------------------------------------
# 3. _change_type_score — parametrized
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("operation,expected_score", [
    ("Microsoft.Compute/virtualMachines/write", 0.9),
    ("Microsoft.Sql/servers/databases/write", 0.8),
    ("Microsoft.Network/networkSecurityGroups/write", 0.8),
    ("Microsoft.Resources/deployments/write", 0.7),
    ("Microsoft.Authorization/roleAssignments/write", 0.6),
    ("Microsoft.Storage/storageAccounts/write", 0.4),   # default
    ("Microsoft.Compute/virtualMachines/read", 0.4),    # read op → default
])
def test_change_type_score_known_operations(operation, expected_score):
    from services.api_gateway.change_correlator import _change_type_score
    assert _change_type_score(operation) == expected_score


# ---------------------------------------------------------------------------
# 4. _score_event — same resource, immediate change
# ---------------------------------------------------------------------------

def test_score_event_same_resource_immediate():
    from services.api_gateway.change_correlator import _score_event, W_TEMPORAL, W_TOPOLOGY, W_CHANGE_TYPE
    delta = 1.0       # 1 minute before incident
    distance = 0      # same resource
    op = "Microsoft.Compute/virtualMachines/write"
    window = 30

    ct_score, corr_score = _score_event(delta, distance, op, window)

    assert ct_score == 0.9
    expected_temporal = 1.0 - (delta / window)          # 0.9667
    expected_topology = 1.0 / (distance + 1)            # 1.0
    expected = W_TEMPORAL * expected_temporal + W_TOPOLOGY * expected_topology + W_CHANGE_TYPE * 0.9
    assert abs(corr_score - round(expected, 4)) < 0.001


# ---------------------------------------------------------------------------
# 5. _score_event — distant, old change
# ---------------------------------------------------------------------------

def test_score_event_distant_old_change():
    from services.api_gateway.change_correlator import _score_event
    delta = 29.0      # near end of window
    distance = 3      # 3 hops away
    op = "Microsoft.Storage/storageAccounts/write"
    window = 30

    ct_score, corr_score = _score_event(delta, distance, op, window)

    # temporal_score ≈ 1/30 ≈ 0.033
    temporal_score = 1.0 - (29.0 / 30.0)
    assert abs(temporal_score - (1.0 / 30.0)) < 0.001
    # Overall score should be low
    assert corr_score < 0.4


# ---------------------------------------------------------------------------
# 6. _score_event — temporal clamped to zero when delta > window
# ---------------------------------------------------------------------------

def test_score_event_temporal_clamped_to_zero():
    from services.api_gateway.change_correlator import (
        _score_event, _change_type_score, W_TOPOLOGY, W_CHANGE_TYPE,
    )
    delta = 31.0      # outside 30-min window → clamped temporal = 0.0
    distance = 0
    op = "Microsoft.Compute/virtualMachines/write"
    window = 30

    ct_score, corr_score = _score_event(delta, distance, op, window)

    # temporal component is clamped to 0 — only topology + change_type contribute
    topology_score = 1.0 / (distance + 1)
    expected = W_TOPOLOGY * topology_score + W_CHANGE_TYPE * _change_type_score(op)
    assert abs(corr_score - round(expected, 4)) < 0.001


# ---------------------------------------------------------------------------
# 7. _query_activity_log — filters out non-write/action events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_activity_log_filters_non_write_events():
    def _make_event(op):
        e = MagicMock()
        e.operation_name.value = op
        e.caller = "user@example.com"
        e.status.value = "Succeeded"
        e.event_timestamp = INCIDENT_CREATED_AT - timedelta(minutes=5)
        e.event_data_id = f"evt-{op}"
        e.correlation_id = None
        return e

    mock_events = [
        _make_event("Microsoft.Compute/virtualMachines/write"),
        _make_event("Microsoft.Compute/virtualMachines/read"),   # should be filtered
        _make_event("Microsoft.Compute/virtualMachines/restart/action"),
    ]

    mock_client = MagicMock()
    mock_client.activity_logs.list.return_value = mock_events
    mock_monitor_module = MagicMock()
    mock_monitor_module.MonitorManagementClient = MagicMock(return_value=mock_client)

    with patch.dict("sys.modules", {"azure.mgmt.monitor": mock_monitor_module}):
        from services.api_gateway.change_correlator import _query_activity_log_for_resource
        result = await _query_activity_log_for_resource(
            MagicMock(), RESOURCE_ID,
            INCIDENT_CREATED_AT - timedelta(minutes=30),
            INCIDENT_CREATED_AT,
        )

    # Only /write and /action should be included
    assert len(result) == 2
    ops = [r["operation_name"] for r in result]
    assert "Microsoft.Compute/virtualMachines/read" not in ops


# ---------------------------------------------------------------------------
# 8. _query_activity_log — returns [] on error (no raise)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_activity_log_returns_empty_on_error():
    mock_monitor_module = MagicMock()
    mock_monitor_module.MonitorManagementClient = MagicMock(side_effect=Exception("Auth failed"))

    with patch.dict("sys.modules", {"azure.mgmt.monitor": mock_monitor_module}):
        from services.api_gateway.change_correlator import _query_activity_log_for_resource
        result = await _query_activity_log_for_resource(
            MagicMock(), RESOURCE_ID,
            INCIDENT_CREATED_AT - timedelta(minutes=30),
            INCIDENT_CREATED_AT,
        )

    assert result == []


# ---------------------------------------------------------------------------
# Shared helper to build a mock cosmos_client
# ---------------------------------------------------------------------------

def _build_cosmos_client(incident_doc: dict) -> MagicMock:
    container = MagicMock()
    container.read_item.return_value = incident_doc
    container.replace_item.return_value = incident_doc

    db = MagicMock()
    db.get_container_client.return_value = container

    client = MagicMock()
    client.get_database_client.return_value = db
    return client


def _make_write_event(resource_id: str, delta_minutes: float, op: str = "Microsoft.Compute/virtualMachines/write") -> dict:
    ts = INCIDENT_CREATED_AT - timedelta(minutes=delta_minutes)
    return {
        "event_id": f"evt-{resource_id[-10:]}",
        "operation_name": op,
        "caller": "admin@example.com",
        "status": "Succeeded",
        "event_timestamp": ts,
    }


# ---------------------------------------------------------------------------
# 9. Happy path — topology expansion + top_changes written to Cosmos
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlate_incident_changes_happy_path():
    from services.api_gateway.change_correlator import correlate_incident_changes

    topology_client = MagicMock()
    topology_client.get_blast_radius.return_value = {
        "affected_resources": [
            {"resource_id": NIC_RESOURCE_ID, "hop_count": 1},
        ]
    }

    incident_doc = {"id": "inc-001", "incident_id": "inc-001"}
    cosmos_client = _build_cosmos_client(incident_doc)

    # Map resource_id → events for the patch
    vm_events = [_make_write_event(RESOURCE_ID, 5.0)]
    nic_events = [_make_write_event(NIC_RESOURCE_ID, 10.0, "Microsoft.Network/networkInterfaces/write")]

    call_count = {"n": 0}
    original_results = [vm_events, nic_events]

    async def _mock_query(credential, rid, window_start, window_end):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(original_results):
            return original_results[idx]
        return []

    with patch(
        "services.api_gateway.change_correlator._query_activity_log_for_resource",
        side_effect=_mock_query,
    ):
        await correlate_incident_changes(
            incident_id="inc-001",
            resource_id=RESOURCE_ID,
            incident_created_at=INCIDENT_CREATED_AT,
            credential=MagicMock(),
            cosmos_client=cosmos_client,
            topology_client=topology_client,
        )

    # replace_item should have been called once
    db = cosmos_client.get_database_client.return_value
    container = db.get_container_client.return_value
    assert container.replace_item.call_count == 1

    # Check the written document contains top_changes
    call_args = container.replace_item.call_args
    written_doc = call_args[0][1] if call_args[0] else call_args[1].get("body", call_args[0][1])
    assert "top_changes" in written_doc
    assert len(written_doc["top_changes"]) <= 3
    # Primary resource (distance=0) should score higher than NIC (distance=1)
    assert written_doc["top_changes"][0]["topology_distance"] == 0


# ---------------------------------------------------------------------------
# 10. No topology client — only primary resource queried
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlate_incident_changes_no_topology():
    from services.api_gateway.change_correlator import correlate_incident_changes

    incident_doc = {"id": "inc-002", "incident_id": "inc-002"}
    cosmos_client = _build_cosmos_client(incident_doc)

    query_calls = []

    async def _mock_query(credential, rid, window_start, window_end):
        query_calls.append(rid)
        return [_make_write_event(rid, 5.0)]

    with patch(
        "services.api_gateway.change_correlator._query_activity_log_for_resource",
        side_effect=_mock_query,
    ):
        await correlate_incident_changes(
            incident_id="inc-002",
            resource_id=RESOURCE_ID,
            incident_created_at=INCIDENT_CREATED_AT,
            credential=MagicMock(),
            cosmos_client=cosmos_client,
            topology_client=None,  # no topology
        )

    # Only the primary resource should have been queried
    assert len(query_calls) == 1
    assert query_calls[0] == RESOURCE_ID


# ---------------------------------------------------------------------------
# 11. cosmos_client=None — no persistence, no crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlate_incident_changes_cosmos_none():
    from services.api_gateway.change_correlator import correlate_incident_changes

    async def _mock_query(credential, rid, window_start, window_end):
        return [_make_write_event(rid, 5.0)]

    # Should not raise
    with patch(
        "services.api_gateway.change_correlator._query_activity_log_for_resource",
        side_effect=_mock_query,
    ):
        await correlate_incident_changes(
            incident_id="inc-003",
            resource_id=RESOURCE_ID,
            incident_created_at=INCIDENT_CREATED_AT,
            credential=MagicMock(),
            cosmos_client=None,
        )
    # If we reached here, no exception was raised — test passes


# ---------------------------------------------------------------------------
# 12. No write events returned — top_changes written as empty list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlate_incident_changes_no_write_events():
    from services.api_gateway.change_correlator import correlate_incident_changes

    incident_doc = {"id": "inc-004", "incident_id": "inc-004"}
    cosmos_client = _build_cosmos_client(incident_doc)

    # Return only /read events — they should be pre-filtered in _query_activity_log_for_resource
    # Here we mock to return an empty list (as _query would after filtering)
    async def _mock_query(credential, rid, window_start, window_end):
        return []  # all filtered out

    with patch(
        "services.api_gateway.change_correlator._query_activity_log_for_resource",
        side_effect=_mock_query,
    ):
        await correlate_incident_changes(
            incident_id="inc-004",
            resource_id=RESOURCE_ID,
            incident_created_at=INCIDENT_CREATED_AT,
            credential=MagicMock(),
            cosmos_client=cosmos_client,
        )

    db = cosmos_client.get_database_client.return_value
    container = db.get_container_client.return_value
    call_args = container.replace_item.call_args
    written_doc = call_args[0][1] if call_args[0] else call_args[1].get("body", call_args[0][1])
    assert written_doc["top_changes"] == []


# ---------------------------------------------------------------------------
# 13. All events outside window — top_changes == []
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlate_incident_changes_all_events_outside_window():
    from services.api_gateway.change_correlator import correlate_incident_changes

    incident_doc = {"id": "inc-005", "incident_id": "inc-005"}
    cosmos_client = _build_cosmos_client(incident_doc)

    # Events 45 minutes before incident — outside the 30-min default window
    outside_ts = INCIDENT_CREATED_AT - timedelta(minutes=45)

    async def _mock_query(credential, rid, window_start, window_end):
        return [{
            "event_id": "evt-old",
            "operation_name": "Microsoft.Compute/virtualMachines/write",
            "caller": "admin@example.com",
            "status": "Succeeded",
            "event_timestamp": outside_ts,
        }]

    with patch(
        "services.api_gateway.change_correlator._query_activity_log_for_resource",
        side_effect=_mock_query,
    ):
        await correlate_incident_changes(
            incident_id="inc-005",
            resource_id=RESOURCE_ID,
            incident_created_at=INCIDENT_CREATED_AT,
            credential=MagicMock(),
            cosmos_client=cosmos_client,
        )

    db = cosmos_client.get_database_client.return_value
    container = db.get_container_client.return_value
    call_args = container.replace_item.call_args
    written_doc = call_args[0][1] if call_args[0] else call_args[1].get("body", call_args[0][1])
    assert written_doc["top_changes"] == []


# ---------------------------------------------------------------------------
# 14. CHANGE_CORRELATOR_ENABLED=false — Activity Log never queried
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlator_disabled_env():
    from services.api_gateway import change_correlator as cc

    query_calls = []

    async def _mock_query(credential, rid, window_start, window_end):
        query_calls.append(rid)
        return []

    # Temporarily disable the correlator via module attribute
    original = cc.CORRELATOR_ENABLED
    cc.CORRELATOR_ENABLED = False
    try:
        with patch(
            "services.api_gateway.change_correlator._query_activity_log_for_resource",
            side_effect=_mock_query,
        ):
            await cc.correlate_incident_changes(
                incident_id="inc-disabled",
                resource_id=RESOURCE_ID,
                incident_created_at=INCIDENT_CREATED_AT,
                credential=MagicMock(),
                cosmos_client=MagicMock(),
            )
    finally:
        cc.CORRELATOR_ENABLED = original

    assert query_calls == [], "Activity Log should not be queried when correlator is disabled"
