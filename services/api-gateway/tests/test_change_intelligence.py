from __future__ import annotations
"""Tests for change_intelligence_service — Phase 81."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.change_intelligence_service import (
    ChangeRecord,
    _build_record,
    _extract_resource_name,
    _friendly_type,
    _score_impact,
    get_change_summary,
    get_changes,
    persist_changes,
    scan_recent_changes,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc).isoformat()

SAMPLE_ROW: Dict[str, Any] = {
    "change_id": "/subscriptions/sub-123/providers/Microsoft.ResourceGraph/changes/abc-def",
    "subscription_id": "sub-123",
    "resource_id": "/subscriptions/sub-123/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-web-01",
    "resource_type": "microsoft.compute/virtualmachines",
    "change_type": "Delete",
    "changed_by": "admin@contoso.com",
    "timestamp": NOW,
    "resource_group": "rg-prod",
}

SAMPLE_RECORD = ChangeRecord(
    change_id=str(uuid.uuid4()),
    subscription_id="sub-123",
    resource_id="/subscriptions/sub-123/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-web-01",
    resource_name="vm-web-01",
    resource_type="Virtual Machine",
    change_type="Delete",
    changed_by="admin@contoso.com",
    timestamp=NOW,
    resource_group="rg-prod",
    impact_score=0.9,
    impact_reason="Delete on critical resource type: Virtual Machine",
    captured_at=NOW,
)


def _make_cosmos_mock(items: List[Dict[str, Any]]) -> MagicMock:
    container = MagicMock()
    container.query_items.return_value = iter(items)
    db = MagicMock()
    db.get_container_client.return_value = container
    client = MagicMock()
    client.get_database_client.return_value = db
    return client


# ---------------------------------------------------------------------------
# _extract_resource_name
# ---------------------------------------------------------------------------


def test_extract_resource_name_standard():
    rid = "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/my-vm"
    assert _extract_resource_name(rid) == "my-vm"


def test_extract_resource_name_short():
    assert _extract_resource_name("/foo/bar/baz") == "baz"


def test_extract_resource_name_empty():
    assert _extract_resource_name("") == ""


# ---------------------------------------------------------------------------
# _friendly_type
# ---------------------------------------------------------------------------


def test_friendly_type_known():
    assert _friendly_type("microsoft.compute/virtualmachines") == "Virtual Machine"
    assert _friendly_type("microsoft.network/networksecuritygroups") == "NSG"
    assert _friendly_type("microsoft.keyvault/vaults") == "Key Vault"


def test_friendly_type_unknown():
    raw = "microsoft.custom/unknowntype"
    assert _friendly_type(raw) == raw


def test_friendly_type_case_insensitive():
    assert _friendly_type("Microsoft.Compute/VirtualMachines") == "Virtual Machine"


# ---------------------------------------------------------------------------
# _score_impact
# ---------------------------------------------------------------------------


def test_score_delete_critical():
    score, reason = _score_impact("microsoft.compute/virtualmachines", "Delete")
    assert score == 0.9
    assert "Delete" in reason


def test_score_update_nsg():
    score, reason = _score_impact("microsoft.network/networksecuritygroups", "Update")
    assert score == 0.8
    assert "security control" in reason.lower()


def test_score_create_nsg():
    score, reason = _score_impact("microsoft.network/networksecuritygroups", "Create")
    assert score == 0.8


def test_score_update_vm():
    score, reason = _score_impact("microsoft.compute/virtualmachines", "Update")
    assert score == 0.7
    assert "production workload" in reason.lower()


def test_score_create_generic():
    score, reason = _score_impact("microsoft.web/sites", "Create")
    assert score == 0.6
    assert "created" in reason.lower()


def test_score_routine():
    score, reason = _score_impact("microsoft.web/sites", "Update")
    assert score == 0.3
    assert "routine" in reason.lower()


# ---------------------------------------------------------------------------
# _build_record
# ---------------------------------------------------------------------------


def test_build_record_happy_path():
    record = _build_record(SAMPLE_ROW, NOW)
    assert record is not None
    assert record.resource_name == "vm-web-01"
    assert record.change_type == "Delete"
    assert record.impact_score == 0.9
    assert record.subscription_id == "sub-123"


def test_build_record_missing_resource_id():
    row = {**SAMPLE_ROW, "resource_id": ""}
    assert _build_record(row, NOW) is None


def test_build_record_stable_id():
    r1 = _build_record(SAMPLE_ROW, NOW)
    r2 = _build_record(SAMPLE_ROW, NOW)
    assert r1 is not None and r2 is not None
    assert r1.change_id == r2.change_id


# ---------------------------------------------------------------------------
# scan_recent_changes
# ---------------------------------------------------------------------------


def test_scan_no_subscriptions():
    cred = MagicMock()
    result = scan_recent_changes(cred, [])
    assert result == []


def test_scan_no_arg_helper():
    cred = MagicMock()
    with patch("services.api_gateway.change_intelligence_service.run_arg_query", None):
        result = scan_recent_changes(cred, ["sub-123"])
    assert result == []


def test_scan_returns_records():
    cred = MagicMock()
    with patch(
        "services.api_gateway.change_intelligence_service.run_arg_query",
        return_value=[SAMPLE_ROW],
    ):
        records = scan_recent_changes(cred, ["sub-123"], hours=24)
    assert len(records) == 1
    assert records[0].resource_name == "vm-web-01"


def test_scan_arg_exception_returns_empty():
    cred = MagicMock()
    with patch(
        "services.api_gateway.change_intelligence_service.run_arg_query",
        side_effect=RuntimeError("ARG unavailable"),
    ):
        result = scan_recent_changes(cred, ["sub-123"])
    assert result == []


# ---------------------------------------------------------------------------
# persist_changes
# ---------------------------------------------------------------------------


def test_persist_no_records():
    cosmos = _make_cosmos_mock([])
    persist_changes(cosmos, "aap-db", [])
    cosmos.get_database_client.assert_not_called()


def test_persist_upserts_records():
    cosmos = _make_cosmos_mock([])
    persist_changes(cosmos, "aap-db", [SAMPLE_RECORD])
    container = cosmos.get_database_client().get_container_client()
    container.upsert_item.assert_called_once()


def test_persist_cosmos_error_does_not_raise():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = RuntimeError("Cosmos down")
    persist_changes(cosmos, "aap-db", [SAMPLE_RECORD])  # should not raise


# ---------------------------------------------------------------------------
# get_changes
# ---------------------------------------------------------------------------


def _record_doc(record: ChangeRecord) -> Dict[str, Any]:
    return {
        "id": record.change_id,
        "change_id": record.change_id,
        "subscription_id": record.subscription_id,
        "resource_id": record.resource_id,
        "resource_name": record.resource_name,
        "resource_type": record.resource_type,
        "change_type": record.change_type,
        "changed_by": record.changed_by,
        "timestamp": record.timestamp,
        "resource_group": record.resource_group,
        "impact_score": record.impact_score,
        "impact_reason": record.impact_reason,
        "captured_at": record.captured_at,
        "ttl": record.ttl,
    }


def test_get_changes_returns_records():
    cosmos = _make_cosmos_mock([_record_doc(SAMPLE_RECORD)])
    records = get_changes(cosmos, "aap-db")
    assert len(records) == 1
    assert records[0].change_id == SAMPLE_RECORD.change_id


def test_get_changes_cosmos_error_returns_empty():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = RuntimeError("Cosmos down")
    result = get_changes(cosmos, "aap-db")
    assert result == []


# ---------------------------------------------------------------------------
# get_change_summary
# ---------------------------------------------------------------------------


def test_get_change_summary_structure():
    cosmos = _make_cosmos_mock([_record_doc(SAMPLE_RECORD)])
    summary = get_change_summary(cosmos, "aap-db")
    assert "total" in summary
    assert "deletes" in summary
    assert "creates" in summary
    assert "updates" in summary
    assert "high_impact_count" in summary
    assert "top_changers" in summary


def test_get_change_summary_counts():
    docs = [_record_doc(SAMPLE_RECORD)]  # 1 Delete with score 0.9
    cosmos = _make_cosmos_mock(docs)
    summary = get_change_summary(cosmos, "aap-db")
    assert summary["total"] == 1
    assert summary["deletes"] == 1
    assert summary["creates"] == 0
    assert summary["high_impact_count"] == 1


def test_get_change_summary_cosmos_error_returns_defaults():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = RuntimeError("Cosmos down")
    summary = get_change_summary(cosmos, "aap-db")
    assert summary["total"] == 0
    assert summary["high_impact_count"] == 0
