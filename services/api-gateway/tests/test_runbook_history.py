from __future__ import annotations
"""Tests for runbook_history_service.py (Phase 85).

Covers:
- _extract_resource_name: parsing Azure resource IDs
- _record_to_execution: mapping Cosmos docs to RunbookExecution
- get_execution_history: filters, success/failure
- get_runbook_stats: aggregation, empty data, error handling
- get_execution_by_incident: happy path, error handling
"""
import os

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.runbook_history_service import (
    RunbookExecution,
    RunbookStats,
    _extract_resource_name,
    _record_to_execution,
    get_execution_by_incident,
    get_execution_history,
    get_runbook_stats,
)


# ---------------------------------------------------------------------------
# _extract_resource_name
# ---------------------------------------------------------------------------

class TestExtractResourceName:
    def test_standard_resource_id(self):
        rid = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/myvm"
        assert _extract_resource_name(rid) == "myvm"

    def test_trailing_slash(self):
        rid = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/myvm/"
        assert _extract_resource_name(rid) == "myvm"

    def test_empty_string(self):
        assert _extract_resource_name("") == ""

    def test_simple_name(self):
        assert _extract_resource_name("myvm") == "myvm"


# ---------------------------------------------------------------------------
# _record_to_execution
# ---------------------------------------------------------------------------

class TestRecordToExecution:
    def _make_doc(self, **overrides):
        base = {
            "id": "exec-1",
            "incident_id": "inc-123",
            "action_name": "restart_vm",
            "action_class": "SAFE",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/myvm",
            "resource_group": "rg",
            "subscription_id": "sub-1",
            "status": "RESOLVED",
            "executed_at": "2026-04-17T10:00:00Z",
            "duration_ms": 5000,
            "approved_by": "operator@contoso.com",
            "rollback_available": True,
            "pre_check_passed": True,
            "notes": "Completed ok",
        }
        base.update(overrides)
        return base

    def test_basic_mapping(self):
        doc = self._make_doc()
        e = _record_to_execution(doc)
        assert e.execution_id == "exec-1"
        assert e.incident_id == "inc-123"
        assert e.action_name == "restart_vm"
        assert e.action_class == "SAFE"
        assert e.resource_name == "myvm"
        assert e.status == "RESOLVED"
        assert e.success is True
        assert e.duration_ms == 5000

    def test_success_resolved(self):
        e = _record_to_execution(self._make_doc(status="RESOLVED"))
        assert e.success is True

    def test_success_improved(self):
        e = _record_to_execution(self._make_doc(status="IMPROVED"))
        assert e.success is True

    def test_failure_degraded(self):
        e = _record_to_execution(self._make_doc(status="DEGRADED"))
        assert e.success is False

    def test_failure_timeout(self):
        e = _record_to_execution(self._make_doc(status="TIMEOUT"))
        assert e.success is False

    def test_failure_blocked(self):
        e = _record_to_execution(self._make_doc(status="BLOCKED"))
        assert e.success is False

    def test_missing_optional_fields(self):
        doc = {"id": "exec-2", "status": "RESOLVED"}
        e = _record_to_execution(doc)
        assert e.execution_id == "exec-2"
        assert e.action_name == ""
        assert e.duration_ms == 0
        assert e.approved_by == ""


# ---------------------------------------------------------------------------
# get_execution_history
# ---------------------------------------------------------------------------

def _make_cosmos_client(items):
    container = MagicMock()
    container.query_items.return_value = iter(items)
    db = MagicMock()
    db.get_container_client.return_value = container
    client = MagicMock()
    client.get_database_client.return_value = db
    return client


class TestGetExecutionHistory:
    def _make_doc(self, execution_id="exec-1", status="RESOLVED", action_class="SAFE", subscription_id="sub-1"):
        return {
            "id": execution_id,
            "incident_id": "inc-1",
            "action_name": "restart_vm",
            "action_class": action_class,
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            "resource_group": "rg",
            "subscription_id": subscription_id,
            "status": status,
            "executed_at": "2026-04-17T10:00:00Z",
            "duration_ms": 1000,
            "approved_by": "user@contoso.com",
            "rollback_available": False,
            "pre_check_passed": True,
            "notes": "",
        }

    def test_returns_executions(self):
        docs = [self._make_doc("e1"), self._make_doc("e2")]
        client = _make_cosmos_client(docs)
        result = get_execution_history(client, "aap")
        assert len(result) == 2
        assert result[0].execution_id == "e1"

    def test_returns_empty_on_cosmos_error(self):
        client = MagicMock()
        client.get_database_client.side_effect = Exception("Cosmos unreachable")
        result = get_execution_history(client, "aap")
        assert result == []

    def test_never_raises(self):
        result = get_execution_history(None, "aap")
        assert isinstance(result, list)

    def test_with_subscription_filter(self):
        container = MagicMock()
        container.query_items.return_value = iter([self._make_doc()])
        db = MagicMock()
        db.get_container_client.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        result = get_execution_history(client, "aap", subscription_ids=["sub-1"])
        assert len(result) == 1
        # Verify query was called with parameters
        call_kwargs = container.query_items.call_args
        assert call_kwargs is not None

    def test_with_action_class_filter(self):
        container = MagicMock()
        container.query_items.return_value = iter([self._make_doc(action_class="DESTRUCTIVE")])
        db = MagicMock()
        db.get_container_client.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        result = get_execution_history(client, "aap", action_class="DESTRUCTIVE")
        assert result[0].action_class == "DESTRUCTIVE"

    def test_with_status_filter(self):
        container = MagicMock()
        container.query_items.return_value = iter([self._make_doc(status="DEGRADED")])
        db = MagicMock()
        db.get_container_client.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        result = get_execution_history(client, "aap", status="DEGRADED")
        assert result[0].status == "DEGRADED"

    def test_limit_respected_in_query(self):
        container = MagicMock()
        container.query_items.return_value = iter([])
        db = MagicMock()
        db.get_container_client.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        get_execution_history(client, "aap", limit=25)
        query_str = container.query_items.call_args[1].get("query") or container.query_items.call_args[0][0]
        assert "25" in query_str


# ---------------------------------------------------------------------------
# get_runbook_stats
# ---------------------------------------------------------------------------

class TestGetRunbookStats:
    def _make_docs(self):
        now = datetime.now(timezone.utc)
        return [
            {
                "id": f"exec-{i}",
                "incident_id": "inc-1",
                "action_name": "restart_vm" if i % 2 == 0 else "scale_vmss",
                "action_class": "SAFE",
                "resource_id": f"/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm{i}",
                "resource_group": "rg",
                "subscription_id": "sub-1",
                "status": "RESOLVED" if i < 3 else "DEGRADED",
                "executed_at": (now - timedelta(hours=i)).isoformat(),
                "duration_ms": 1000 + i * 100,
                "approved_by": "user@contoso.com",
                "rollback_available": False,
                "pre_check_passed": True,
                "notes": "",
            }
            for i in range(5)
        ]

    def test_basic_stats(self):
        client = _make_cosmos_client(self._make_docs())
        stats = get_runbook_stats(client, "aap", days=7)
        assert stats.total_executions == 5
        assert 0.0 <= stats.success_rate <= 1.0
        assert stats.avg_duration_ms > 0

    def test_success_rate_all_resolved(self):
        docs = [
            {**d, "status": "RESOLVED"}
            for d in self._make_docs()
        ]
        client = _make_cosmos_client(docs)
        stats = get_runbook_stats(client, "aap")
        assert stats.success_rate == 1.0

    def test_success_rate_all_degraded(self):
        docs = [
            {**d, "status": "DEGRADED"}
            for d in self._make_docs()
        ]
        client = _make_cosmos_client(docs)
        stats = get_runbook_stats(client, "aap")
        assert stats.success_rate == 0.0

    def test_empty_result(self):
        client = _make_cosmos_client([])
        stats = get_runbook_stats(client, "aap")
        assert stats.total_executions == 0
        assert stats.success_rate == 0.0
        assert stats.avg_duration_ms == 0.0
        assert stats.by_action == {}
        assert stats.recent_failures == []

    def test_recent_failures_capped_at_5(self):
        docs = [
            {**d, "status": "DEGRADED"}
            for d in self._make_docs()
        ] * 2  # 10 degraded
        client = _make_cosmos_client(docs)
        stats = get_runbook_stats(client, "aap")
        assert len(stats.recent_failures) <= 5

    def test_by_action_keys(self):
        client = _make_cosmos_client(self._make_docs())
        stats = get_runbook_stats(client, "aap")
        assert "restart_vm" in stats.by_action or "scale_vmss" in stats.by_action

    def test_never_raises_on_error(self):
        client = MagicMock()
        client.get_database_client.side_effect = RuntimeError("boom")
        stats = get_runbook_stats(client, "aap")
        assert isinstance(stats, RunbookStats)
        assert stats.total_executions == 0

    def test_never_raises_on_none_client(self):
        stats = get_runbook_stats(None, "aap")
        assert isinstance(stats, RunbookStats)


# ---------------------------------------------------------------------------
# get_execution_by_incident
# ---------------------------------------------------------------------------

class TestGetExecutionByIncident:
    def _make_doc(self, execution_id="exec-1"):
        return {
            "id": execution_id,
            "incident_id": "inc-42",
            "action_name": "restart_vm",
            "action_class": "SAFE",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            "resource_group": "rg",
            "subscription_id": "sub-1",
            "status": "RESOLVED",
            "executed_at": "2026-04-17T10:00:00Z",
            "duration_ms": 2000,
            "approved_by": "user@contoso.com",
            "rollback_available": True,
            "pre_check_passed": True,
            "notes": "ok",
        }

    def test_returns_executions_for_incident(self):
        docs = [self._make_doc("e1"), self._make_doc("e2")]
        client = _make_cosmos_client(docs)
        result = get_execution_by_incident(client, "aap", "inc-42")
        assert len(result) == 2
        assert all(e.incident_id == "inc-42" for e in result)

    def test_returns_empty_list_on_not_found(self):
        client = _make_cosmos_client([])
        result = get_execution_by_incident(client, "aap", "inc-999")
        assert result == []

    def test_never_raises_on_cosmos_error(self):
        client = MagicMock()
        client.get_database_client.side_effect = Exception("Cosmos down")
        result = get_execution_by_incident(client, "aap", "inc-1")
        assert result == []

    def test_never_raises_on_none_client(self):
        result = get_execution_by_incident(None, "aap", "inc-1")
        assert isinstance(result, list)

    def test_query_uses_incident_id_param(self):
        container = MagicMock()
        container.query_items.return_value = iter([])
        db = MagicMock()
        db.get_container_client.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        get_execution_by_incident(client, "aap", "inc-42")
        params = container.query_items.call_args[1].get("parameters") or []
        assert any(p.get("value") == "inc-42" for p in params)
