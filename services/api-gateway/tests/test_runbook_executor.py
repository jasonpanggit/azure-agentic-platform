from __future__ import annotations
"""Tests for RunbookExecutor — Phase 62 Runbook Automation Studio."""

import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
import services.api_gateway.runbook_executor as rex

# Skip Jinja2-dependent tests when the library is not installed
try:
    import jinja2 as _jinja2_check  # noqa: F401
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False

jinja2_required = pytest.mark.skipif(not _JINJA2_AVAILABLE, reason="jinja2 not installed")

from services.api_gateway.runbook_executor import (
    AVAILABLE_TOOLS,
    BUILTIN_RUNBOOKS,
    AutomationStep,
    AutomationRunbook,
    RunbookExecutor,
    resolve_parameters,
)


# ---------------------------------------------------------------------------
# test_jinja2_template_resolution
# ---------------------------------------------------------------------------


@jinja2_required
def test_jinja2_template_resolution_basic():
    """Resolve simple Jinja2 variables from incident_context."""
    template = {
        "resource_id": "{{ incident.resource_id }}",
        "subscription_id": "{{ incident.subscription_id }}",
        "static": "hello",
    }
    context = {"resource_id": "/subscriptions/abc/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1", "subscription_id": "abc-123"}
    result = resolve_parameters(template, context)
    assert result["resource_id"] == context["resource_id"]
    assert result["subscription_id"] == context["subscription_id"]
    assert result["static"] == "hello"


@jinja2_required
def test_jinja2_template_resolution_default_filter():
    """Jinja2 default filter returns fallback for missing keys."""
    template = {"node": "{{ incident.node_name | default('fallback-node') }}"}
    context = {}  # node_name not set
    result = resolve_parameters(template, context)
    assert result["node"] == "fallback-node"


@jinja2_required
def test_jinja2_template_resolution_non_string_values():
    """Non-string values (int, dict) are passed through without rendering."""
    template = {
        "timeout": 30,
        "flags": {"debug": True},
        "resource": "{{ incident.resource_id }}",
    }
    context = {"resource_id": "res-001"}
    result = resolve_parameters(template, context)
    assert result["timeout"] == 30
    assert result["flags"] == {"debug": True}
    assert result["resource"] == "res-001"


# ---------------------------------------------------------------------------
# test_step_requires_approval_creates_approval_record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_requires_approval_creates_approval_record():
    """Steps with require_approval=True should emit awaiting_approval event and create record."""
    runbook_id = "vm_high_cpu_response"
    incident_context = {
        "resource_id": "/subscriptions/abc/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        "subscription_id": "abc-123",
    }

    created_approvals = []

    def fake_create_approval(step_id, tool_name, runbook_id, incident_context, resolved_params):
        record = {"id": str(uuid.uuid4()), "step_id": step_id, "status": "pending"}
        created_approvals.append(record)
        return record

    with patch.object(rex, "_create_approval_record", side_effect=fake_create_approval):
        with patch.object(rex, "_write_wal_record"):
            executor = RunbookExecutor()
            events = []
            async for event in executor.execute(runbook_id, incident_context, dry_run=False):
                events.append(event)

    approval_events = [e for e in events if e.get("status") == "awaiting_approval"]
    assert len(approval_events) > 0, "Expected at least one awaiting_approval event"
    assert len(created_approvals) > 0, "Expected approval records to be created"
    for evt in approval_events:
        assert "approval_id" in evt


# ---------------------------------------------------------------------------
# test_on_failure_abort_stops_execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_failure_abort_stops_execution():
    """When a step fails with on_failure=abort, execution stops immediately."""
    runbook_id = "test_abort_runbook"
    original = dict(rex.BUILTIN_RUNBOOKS)

    rex.BUILTIN_RUNBOOKS[runbook_id] = {
        "runbook_id": runbook_id,
        "name": "Abort Test",
        "description": "Test abort",
        "domain": "ops",
        "automation_steps": [
            {
                "step_id": "step_a",
                "tool_name": "failing_tool",
                "parameters_template": {},
                "require_approval": False,
                "on_failure": "abort",
            },
            {
                "step_id": "step_b",
                "tool_name": "should_not_run",
                "parameters_template": {},
                "require_approval": False,
                "on_failure": "abort",
            },
        ],
    }

    try:
        executor = RunbookExecutor()

        async def _fail(*args, **kwargs):
            raise RuntimeError("simulated failure")

        events = []
        with patch.object(executor, "_execute_step", side_effect=_fail):
            with patch.object(rex, "_write_wal_record"):
                async for event in executor.execute(runbook_id, {}, dry_run=False):
                    events.append(event)

        step_ids_executed = [e.get("step_id") for e in events if e.get("type") == "step"]
        abort_events = [e for e in events if e.get("type") == "runbook_aborted"]

        assert "step_b" not in step_ids_executed, "step_b should not run after abort"
        assert len(abort_events) == 1, "Expected one runbook_aborted event"
    finally:
        rex.BUILTIN_RUNBOOKS = original


# ---------------------------------------------------------------------------
# test_on_failure_continue_skips_to_next_step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_failure_continue_skips_to_next_step():
    """When a step fails with on_failure=continue, next step still executes."""
    runbook_id = "test_continue_runbook"
    original = dict(rex.BUILTIN_RUNBOOKS)

    rex.BUILTIN_RUNBOOKS[runbook_id] = {
        "runbook_id": runbook_id,
        "name": "Continue Test",
        "description": "Test continue on failure",
        "domain": "ops",
        "automation_steps": [
            {
                "step_id": "step_fail",
                "tool_name": "failing_tool",
                "parameters_template": {},
                "require_approval": False,
                "on_failure": "continue",
            },
            {
                "step_id": "step_ok",
                "tool_name": "succeeding_tool",
                "parameters_template": {},
                "require_approval": False,
                "on_failure": "abort",
            },
        ],
    }

    call_count = 0

    async def _sometimes_fail(tool_name, resolved_params, dry_run=False):
        nonlocal call_count
        call_count += 1
        if tool_name == "failing_tool":
            raise RuntimeError("deliberate failure")
        return {"ok": True}

    try:
        executor = RunbookExecutor()
        events = []
        with patch.object(executor, "_execute_step", side_effect=_sometimes_fail):
            with patch.object(rex, "_write_wal_record"):
                async for event in executor.execute(runbook_id, {}, dry_run=False):
                    events.append(event)

        step_ids = [e.get("step_id") for e in events if e.get("type") == "step"]
        success_events = [e for e in events if e.get("type") == "step" and e.get("status") == "success"]
        complete_events = [e for e in events if e.get("type") == "runbook_complete"]

        assert "step_ok" in step_ids, "step_ok should have been reached after continue"
        assert len(success_events) >= 1
        assert len(complete_events) == 1
    finally:
        rex.BUILTIN_RUNBOOKS = original


# ---------------------------------------------------------------------------
# test_builtin_runbooks_defined
# ---------------------------------------------------------------------------


def test_builtin_runbooks_defined():
    """All five built-in runbooks must be present and valid."""
    expected_ids = {
        "vm_high_cpu_response",
        "disk_full_cleanup",
        "aks_node_drain",
        "service_bus_dlq_drain",
        "certificate_renewal",
    }
    assert expected_ids.issubset(set(BUILTIN_RUNBOOKS.keys())), (
        f"Missing runbooks: {expected_ids - set(BUILTIN_RUNBOOKS.keys())}"
    )
    for rb_id in expected_ids:
        rb = BUILTIN_RUNBOOKS[rb_id]
        assert rb.get("runbook_id") == rb_id
        assert len(rb.get("automation_steps", [])) >= 2, f"{rb_id} should have at least 2 steps"


def test_builtin_runbooks_have_required_fields():
    """Each automation step must have tool_name and on_failure."""
    for rb_id, rb in BUILTIN_RUNBOOKS.items():
        for step in rb.get("automation_steps", []):
            assert "tool_name" in step, f"{rb_id}: step missing tool_name"
            assert "on_failure" in step, f"{rb_id}: step missing on_failure"
            assert step["on_failure"] in {"abort", "continue", "rollback"}, (
                f"{rb_id}: invalid on_failure value '{step['on_failure']}'"
            )


# ---------------------------------------------------------------------------
# test_execute_endpoint_streams_steps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_endpoint_streams_steps_dry_run():
    """Dry run execution emits runbook_start + step events + runbook_complete."""
    runbook_id = "certificate_renewal"
    incident_context = {
        "resource_id": "/subscriptions/abc/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv1",
        "subscription_id": "abc-123",
        "keyvault_name": "kv1",
        "certificate_name": "my-cert",
    }

    executor = RunbookExecutor()
    events = []
    with patch.object(rex, "_write_wal_record"):
        with patch.object(rex, "_create_approval_record", return_value={"id": "appr-test"}):
            async for event in executor.execute(runbook_id, incident_context, dry_run=True):
                events.append(event)

    types = [e.get("type") for e in events]
    assert "runbook_start" in types, "Expected runbook_start event"
    # dry_run=True skips approval gates and executes all steps
    step_events = [e for e in events if e.get("type") == "step"]
    assert len(step_events) >= 1, "Expected at least one step event in dry run"
    # All dry-run step results should have dry_run=True
    for se in step_events:
        if se.get("result"):
            assert se["result"].get("dry_run") is True


@pytest.mark.asyncio
async def test_execute_unknown_runbook_returns_error():
    """Executing an unknown runbook ID should yield an error event."""
    executor = RunbookExecutor()
    events = []
    async for event in executor.execute("nonexistent_runbook", {}, dry_run=True):
        events.append(event)

    assert len(events) == 1
    assert events[0].get("type") == "error"
    assert "not found" in events[0].get("message", "").lower()


# ---------------------------------------------------------------------------
# test available_tools list
# ---------------------------------------------------------------------------


def test_available_tools_list_not_empty():
    """AVAILABLE_TOOLS must have at least 10 entries."""
    assert len(AVAILABLE_TOOLS) >= 10
    for tool in AVAILABLE_TOOLS:
        assert "tool_name" in tool
        assert "description" in tool
        assert "domain" in tool


# ---------------------------------------------------------------------------
# test AutomationStep model defaults
# ---------------------------------------------------------------------------


def test_automation_step_defaults():
    """AutomationStep should default require_approval=True and on_failure=abort."""
    step = AutomationStep(tool_name="some_tool")
    assert step.require_approval is True
    assert step.on_failure == "abort"
    assert step.parameters_template == {}
    assert step.condition is None
    assert step.step_id is not None
