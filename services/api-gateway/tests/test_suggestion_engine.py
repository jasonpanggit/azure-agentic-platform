from __future__ import annotations
"""Unit tests for suggestion_engine.py — pattern detection sweep and suggestion CRUD."""

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _make_cosmos(audit_records: list[dict], suggestions: list[dict] | None = None) -> MagicMock:
    """Build a mock CosmosClient whose containers return controlled data.

    audit_records  — returned by remediation_audit container's query_items
    suggestions    — returned by policy_suggestions container's query_items
                     (defaults to [] so _suggestion_exists returns False)
    """
    if suggestions is None:
        suggestions = []

    audit_container = MagicMock()
    audit_container.query_items.return_value = audit_records

    suggestions_container = MagicMock()
    suggestions_container.query_items.return_value = suggestions
    suggestions_container.upsert_item.return_value = None

    def _get_container(name: str) -> MagicMock:
        if name == "remediation_audit":
            return audit_container
        return suggestions_container  # policy_suggestions (and any other)

    mock_db = MagicMock()
    mock_db.get_container_client.side_effect = _get_container

    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.return_value = mock_db

    return mock_cosmos


def _hitl_record(action: str, verification_result: str = "RESOLVED") -> dict:
    """Build a minimal HITL-approved remediation_audit record."""
    return {
        "id": str(uuid.uuid4()),
        "proposed_action": action,
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        "verification_result": verification_result,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        # No auto_approved_by_policy field → HITL approved
    }


# ---------------------------------------------------------------------------
# Test 1: no qualifying patterns (< threshold)
# ---------------------------------------------------------------------------


async def test_sweep_no_qualifying_patterns():
    """Fewer than SUGGESTION_APPROVAL_THRESHOLD records → no suggestions created."""
    from services.api_gateway.suggestion_engine import run_suggestion_sweep

    # Only 4 records for restart_vm (threshold defaults to 5)
    records = [_hitl_record("restart_vm") for _ in range(4)]
    mock_cosmos = _make_cosmos(records)

    with patch("services.api_gateway.suggestion_engine.SUGGESTION_APPROVAL_THRESHOLD", 5):
        result = await run_suggestion_sweep(mock_cosmos)

    assert result == []
    # upsert should never have been called
    suggestions_container = mock_cosmos.get_database_client.return_value.get_container_client("policy_suggestions")
    suggestions_container.upsert_item.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: creates suggestion when threshold met with 0 rollbacks
# ---------------------------------------------------------------------------


async def test_sweep_creates_suggestion():
    """5+ HITL-approved records for restart_vm with 0 rollbacks → one suggestion."""
    from services.api_gateway.suggestion_engine import run_suggestion_sweep

    records = [_hitl_record("restart_vm") for _ in range(5)]
    mock_cosmos = _make_cosmos(records)

    with patch("services.api_gateway.suggestion_engine.SUGGESTION_APPROVAL_THRESHOLD", 5):
        result = await run_suggestion_sweep(mock_cosmos)

    assert len(result) == 1
    suggestion = result[0]
    assert suggestion["action_class"] == "restart_vm"
    assert suggestion["approval_count"] == 5
    assert suggestion["rollback_count"] == 0
    assert suggestion["dismissed"] is False
    assert suggestion["converted_to_policy_id"] is None
    assert "Consider creating a policy for" in suggestion["message"]

    # upsert_item should have been called once
    suggestions_container = mock_cosmos.get_database_client.return_value.get_container_client("policy_suggestions")
    suggestions_container.upsert_item.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3: skip when any rollback present
# ---------------------------------------------------------------------------


async def test_sweep_skips_if_rollback_present():
    """5 records but 1 has verification_result=DEGRADED → no suggestion (rollback present)."""
    from services.api_gateway.suggestion_engine import run_suggestion_sweep

    records = [_hitl_record("restart_vm") for _ in range(4)]
    records.append(_hitl_record("restart_vm", verification_result="DEGRADED"))
    mock_cosmos = _make_cosmos(records)

    with patch("services.api_gateway.suggestion_engine.SUGGESTION_APPROVAL_THRESHOLD", 5):
        result = await run_suggestion_sweep(mock_cosmos)

    assert result == []
    suggestions_container = mock_cosmos.get_database_client.return_value.get_container_client("policy_suggestions")
    suggestions_container.upsert_item.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: auto-approved records excluded from suggestion count
# ---------------------------------------------------------------------------


async def test_sweep_skips_auto_approved():
    """Records with auto_approved_by_policy set are excluded by the Cosmos query.

    We simulate this by having the audit container return only 3 records
    (as if the query filtered out 2 auto-approved ones). With threshold=5
    no suggestion should be created.
    """
    from services.api_gateway.suggestion_engine import run_suggestion_sweep

    # Only 3 HITL-approved records returned (auto-approved ones excluded by query)
    hitl_records = [_hitl_record("restart_vm") for _ in range(3)]
    mock_cosmos = _make_cosmos(hitl_records)

    with patch("services.api_gateway.suggestion_engine.SUGGESTION_APPROVAL_THRESHOLD", 5):
        result = await run_suggestion_sweep(mock_cosmos)

    # Threshold not met → no suggestion
    assert result == []

    # Verify the query sent to Cosmos includes the auto_approved_by_policy exclusion
    audit_container = mock_cosmos.get_database_client.return_value.get_container_client("remediation_audit")
    call_args = audit_container.query_items.call_args
    query_text: str = call_args[1].get("query") or call_args[0][0]
    assert "auto_approved_by_policy" in query_text


# ---------------------------------------------------------------------------
# Test 5: get_pending_suggestions returns only non-dismissed unconverted items
# ---------------------------------------------------------------------------


async def test_get_pending_suggestions():
    """get_pending_suggestions returns only non-dismissed suggestions without converted_to_policy_id."""
    from services.api_gateway.suggestion_engine import get_pending_suggestions

    pending = [
        {
            "id": str(uuid.uuid4()),
            "action_class": "restart_vm",
            "resource_pattern": {},
            "approval_count": 6,
            "rollback_count": 0,
            "suggested_at": datetime.now(timezone.utc).isoformat(),
            "dismissed": False,
            "converted_to_policy_id": None,
            "message": "Consider creating a policy for 'restart_vm'",
        }
    ]
    mock_cosmos = _make_cosmos(audit_records=[], suggestions=pending)

    result = await get_pending_suggestions(mock_cosmos)

    assert len(result) == 1
    assert result[0]["action_class"] == "restart_vm"

    # Confirm the query filters for dismissed=false and no converted_to_policy_id
    suggestions_container = mock_cosmos.get_database_client.return_value.get_container_client("policy_suggestions")
    call_args = suggestions_container.query_items.call_args
    query_text: str = call_args[1].get("query") or call_args[0][0]
    assert "dismissed" in query_text
    assert "converted_to_policy_id" in query_text


# ---------------------------------------------------------------------------
# Test 6: dismiss_suggestion sets dismissed=True on the Cosmos record
# ---------------------------------------------------------------------------


async def test_dismiss_suggestion_success():
    """dismiss_suggestion reads the item, sets dismissed=True, and calls replace_item."""
    from services.api_gateway.suggestion_engine import dismiss_suggestion

    suggestion_id = str(uuid.uuid4())
    action_class = "restart_vm"

    existing = {
        "id": suggestion_id,
        "action_class": action_class,
        "dismissed": False,
        "converted_to_policy_id": None,
        "approval_count": 5,
        "rollback_count": 0,
        "suggested_at": datetime.now(timezone.utc).isoformat(),
        "message": "Consider creating a policy for 'restart_vm'",
        "resource_pattern": {},
    }

    suggestions_container = MagicMock()
    suggestions_container.read_item.return_value = dict(existing)  # mutable copy
    suggestions_container.replace_item.return_value = None

    mock_db = MagicMock()
    mock_db.get_container_client.return_value = suggestions_container

    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.return_value = mock_db

    result = await dismiss_suggestion(mock_cosmos, suggestion_id, action_class)

    assert result is True
    suggestions_container.read_item.assert_called_once_with(
        item=suggestion_id, partition_key=action_class
    )
    replace_call_body = suggestions_container.replace_item.call_args[1]["body"]
    assert replace_call_body["dismissed"] is True


# ---------------------------------------------------------------------------
# Test 7 (bonus): convert_suggestion_to_policy links the policy_id
# ---------------------------------------------------------------------------


async def test_convert_suggestion_to_policy():
    """convert_suggestion_to_policy sets converted_to_policy_id on the Cosmos record."""
    from services.api_gateway.suggestion_engine import convert_suggestion_to_policy

    suggestion_id = str(uuid.uuid4())
    policy_id = str(uuid.uuid4())
    action_class = "restart_vm"

    existing = {
        "id": suggestion_id,
        "action_class": action_class,
        "dismissed": False,
        "converted_to_policy_id": None,
        "approval_count": 5,
        "rollback_count": 0,
        "suggested_at": datetime.now(timezone.utc).isoformat(),
        "message": "Consider creating a policy for 'restart_vm'",
        "resource_pattern": {},
    }

    suggestions_container = MagicMock()
    suggestions_container.read_item.return_value = dict(existing)
    suggestions_container.replace_item.return_value = None

    mock_db = MagicMock()
    mock_db.get_container_client.return_value = suggestions_container

    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.return_value = mock_db

    result = await convert_suggestion_to_policy(mock_cosmos, suggestion_id, action_class, policy_id)

    assert result is True
    replace_call_body = suggestions_container.replace_item.call_args[1]["body"]
    assert replace_call_body["converted_to_policy_id"] == policy_id
