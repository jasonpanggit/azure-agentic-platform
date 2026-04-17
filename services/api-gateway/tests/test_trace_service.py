from __future__ import annotations
"""Tests for Phase 71: Agent Trace Service."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_gateway.trace_service import (
    _extract_token_usage,
    _iso_from_timestamp,
    _parse_step,
    capture_run_trace,
    get_trace_by_id,
    get_traces,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_call(
    call_id: str = "call_abc",
    name: str = "get_vm_health",
    arguments: str = '{"resource_id": "/sub/x/vm/y"}',
    output: Optional[str] = '{"status": "healthy"}',
) -> MagicMock:
    fn = MagicMock()
    fn.name = name
    fn.arguments = arguments
    fn.output = output
    tc = MagicMock()
    tc.id = call_id
    tc.type = "function"
    tc.function = fn
    return tc


def _make_step(
    step_id: str = "step_001",
    step_type: str = "tool_calls",
    status: str = "completed",
    tool_calls: Optional[list] = None,
) -> MagicMock:
    details = MagicMock()
    details.tool_calls = tool_calls or []
    step = MagicMock()
    step.id = step_id
    step.type = step_type
    step.status = status
    step.created_at = 1_700_000_000
    step.step_details = details
    return step


def _make_run(
    run_id: str = "run_xyz",
    thread_id: str = "thread_abc",
    prompt_tokens: int = 1240,
    completion_tokens: int = 380,
) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens
    run = MagicMock()
    run.id = run_id
    run.thread_id = thread_id
    run.usage = usage
    return run


def _make_agents_client(run=None, steps=None) -> MagicMock:
    client = MagicMock()
    client.runs.get.return_value = run or _make_run()
    client.runs.list_steps.return_value = steps or []
    return client


def _make_cosmos_client(upsert_raises: Optional[Exception] = None) -> MagicMock:
    container = MagicMock()
    if upsert_raises:
        container.upsert_item.side_effect = upsert_raises
    else:
        container.upsert_item.return_value = {}
    db = MagicMock()
    db.get_container_client.return_value = container
    cosmos = MagicMock()
    cosmos.get_database_client.return_value = db
    return cosmos


# ---------------------------------------------------------------------------
# _iso_from_timestamp
# ---------------------------------------------------------------------------


class TestIsoFromTimestamp:
    def test_int_timestamp(self):
        result = _iso_from_timestamp(1_700_000_000)
        assert "2023" in result or "T" in result  # valid ISO string

    def test_datetime_obj(self):
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert _iso_from_timestamp(dt) == "2026-01-01T12:00:00+00:00"

    def test_none_returns_none(self):
        assert _iso_from_timestamp(None) is None

    def test_invalid_falls_back_to_str(self):
        result = _iso_from_timestamp("not-a-timestamp")
        assert result is not None


# ---------------------------------------------------------------------------
# _extract_token_usage
# ---------------------------------------------------------------------------


class TestExtractTokenUsage:
    def test_happy_path(self):
        run = _make_run(prompt_tokens=100, completion_tokens=50)
        usage = _extract_token_usage(run)
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 50
        assert usage["total_tokens"] == 150

    def test_no_usage_returns_zeros(self):
        run = MagicMock()
        run.usage = None
        usage = _extract_token_usage(run)
        assert usage["total_tokens"] == 0


# ---------------------------------------------------------------------------
# _parse_step
# ---------------------------------------------------------------------------


class TestParseStep:
    def test_tool_call_step(self):
        tc = _make_tool_call()
        step = _make_step(tool_calls=[tc])
        parsed = _parse_step(step)
        assert parsed["type"] == "tool_calls"
        assert parsed["status"] == "completed"
        assert len(parsed["tool_calls"]) == 1
        assert parsed["tool_calls"][0]["name"] == "get_vm_health"
        assert parsed["tool_calls"][0]["arguments"] == '{"resource_id": "/sub/x/vm/y"}'

    def test_message_creation_step(self):
        step = _make_step(step_type="message_creation", tool_calls=[])
        parsed = _parse_step(step)
        assert parsed["type"] == "message_creation"
        assert parsed["tool_calls"] == []

    def test_step_id_preserved(self):
        step = _make_step(step_id="step_custom")
        parsed = _parse_step(step)
        assert parsed["step_id"] == "step_custom"


# ---------------------------------------------------------------------------
# capture_run_trace
# ---------------------------------------------------------------------------


class TestCaptureRunTrace:
    @pytest.mark.asyncio
    async def test_happy_path_with_tool_calls(self):
        tc = _make_tool_call()
        step = _make_step(tool_calls=[tc])
        run = _make_run(prompt_tokens=500, completion_tokens=200)
        agents = _make_agents_client(run=run, steps=[step])
        cosmos = _make_cosmos_client()

        trace = await capture_run_trace(
            agents_client=agents,
            thread_id="thread_001",
            run_id="run_001",
            agent_name="orchestrator",
            cosmos_client=cosmos,
            cosmos_database_name="aap",
        )

        assert trace is not None
        assert trace["thread_id"] == "thread_001"
        assert trace["run_id"] == "run_001"
        assert trace["agent_name"] == "orchestrator"
        assert trace["total_tool_calls"] == 1
        assert trace["token_usage"]["total_tokens"] == 700
        assert len(trace["steps"]) == 1
        assert trace["id"] == "thread_001_run_001"

    @pytest.mark.asyncio
    async def test_empty_steps(self):
        run = _make_run()
        agents = _make_agents_client(run=run, steps=[])
        cosmos = _make_cosmos_client()

        trace = await capture_run_trace(
            agents_client=agents,
            thread_id="thread_002",
            run_id="run_002",
            cosmos_client=cosmos,
            cosmos_database_name="aap",
        )

        assert trace is not None
        assert trace["steps"] == []
        assert trace["total_tool_calls"] == 0

    @pytest.mark.asyncio
    async def test_cosmos_unavailable_still_returns_trace(self):
        tc = _make_tool_call()
        step = _make_step(tool_calls=[tc])
        run = _make_run()
        agents = _make_agents_client(run=run, steps=[step])

        trace = await capture_run_trace(
            agents_client=agents,
            thread_id="thread_003",
            run_id="run_003",
            cosmos_client=None,
        )

        assert trace is not None
        assert trace["total_tool_calls"] == 1

    @pytest.mark.asyncio
    async def test_cosmos_write_failure_does_not_raise(self):
        agents = _make_agents_client(steps=[_make_step()])
        cosmos = _make_cosmos_client(upsert_raises=Exception("Cosmos down"))

        trace = await capture_run_trace(
            agents_client=agents,
            thread_id="thread_004",
            run_id="run_004",
            cosmos_client=cosmos,
        )

        # Should still return trace even when Cosmos write fails
        assert trace is not None

    @pytest.mark.asyncio
    async def test_azure_ai_agents_import_error_returns_none(self):
        agents = _make_agents_client()

        with patch.dict("sys.modules", {"azure.ai.agents": None}):
            trace = await capture_run_trace(
                agents_client=agents,
                thread_id="thread_005",
                run_id="run_005",
            )

        assert trace is None

    @pytest.mark.asyncio
    async def test_incident_id_and_conversation_id_stored(self):
        agents = _make_agents_client(steps=[])
        cosmos = _make_cosmos_client()

        trace = await capture_run_trace(
            agents_client=agents,
            thread_id="thread_006",
            run_id="run_006",
            incident_id="inc-001",
            conversation_id="conv-abc",
            cosmos_client=cosmos,
        )

        assert trace is not None
        assert trace["incident_id"] == "inc-001"
        assert trace["conversation_id"] == "conv-abc"

    @pytest.mark.asyncio
    async def test_run_duration_ms_stored(self):
        agents = _make_agents_client(steps=[])
        cosmos = _make_cosmos_client()

        trace = await capture_run_trace(
            agents_client=agents,
            thread_id="thread_007",
            run_id="run_007",
            run_duration_ms=4200.0,
            cosmos_client=cosmos,
        )

        assert trace is not None
        assert trace["duration_ms"] == 4200.0

    @pytest.mark.asyncio
    async def test_list_steps_failure_returns_empty_steps(self):
        run = _make_run()
        agents = MagicMock()
        agents.runs.get.return_value = run
        agents.runs.list_steps.side_effect = Exception("list_steps failed")

        trace = await capture_run_trace(
            agents_client=agents,
            thread_id="thread_008",
            run_id="run_008",
        )

        assert trace is not None
        assert trace["steps"] == []

    @pytest.mark.asyncio
    async def test_ttl_set_on_trace(self):
        agents = _make_agents_client(steps=[])

        trace = await capture_run_trace(
            agents_client=agents,
            thread_id="thread_009",
            run_id="run_009",
        )

        assert trace is not None
        assert trace["ttl"] == 604800


# ---------------------------------------------------------------------------
# get_traces
# ---------------------------------------------------------------------------


class TestGetTraces:
    def _make_cosmos_with_query(
        self, items: list, total: int = 0, raises: Optional[Exception] = None
    ) -> MagicMock:
        container = MagicMock()
        call_count = [0]

        def _query_items(**kwargs):
            call_count[0] += 1
            if raises:
                raise raises
            # First call = count query, second = data query
            if call_count[0] == 1:
                return [total]
            return items

        container.query_items.side_effect = _query_items
        db = MagicMock()
        db.get_container_client.return_value = container
        cosmos = MagicMock()
        cosmos.get_database_client.return_value = db
        return cosmos

    @pytest.mark.asyncio
    async def test_happy_path(self):
        items = [{"id": "t1", "agent_name": "orchestrator", "captured_at": "2026-01-01T00:00:00+00:00"}]
        cosmos = self._make_cosmos_with_query(items=items, total=1)

        traces, total = await get_traces(cosmos, "aap")
        assert total == 1
        assert len(traces) == 1

    @pytest.mark.asyncio
    async def test_cosmos_none_returns_empty(self):
        traces, total = await get_traces(None, "aap")
        assert traces == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_cosmos_unavailable_returns_empty(self):
        cosmos = self._make_cosmos_with_query(items=[], raises=Exception("timeout"))
        traces, total = await get_traces(cosmos, "aap")
        assert traces == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_thread_id_filter(self):
        items = [{"id": "t_filtered"}]
        cosmos = self._make_cosmos_with_query(items=items, total=1)

        traces, total = await get_traces(cosmos, "aap", thread_id="thread_abc")
        assert total == 1


# ---------------------------------------------------------------------------
# get_trace_by_id
# ---------------------------------------------------------------------------


class TestGetTraceById:
    def _make_cosmos_read(
        self, item: Optional[dict] = None, raises: Optional[Exception] = None
    ) -> MagicMock:
        container = MagicMock()
        if raises:
            container.read_item.side_effect = raises
        else:
            container.read_item.return_value = item or {}
        db = MagicMock()
        db.get_container_client.return_value = container
        cosmos = MagicMock()
        cosmos.get_database_client.return_value = db
        return cosmos

    @pytest.mark.asyncio
    async def test_found(self):
        item = {"id": "thread_x_run_y", "thread_id": "thread_x", "run_id": "run_y"}
        cosmos = self._make_cosmos_read(item=item)

        result = await get_trace_by_id(cosmos, "aap", "thread_x", "run_y")
        assert result == item

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError  # type: ignore

        cosmos = self._make_cosmos_read(raises=CosmosResourceNotFoundError(message="not found", response=None, error=None))  # type: ignore[call-arg]

        result = await get_trace_by_id(cosmos, "aap", "thread_x", "run_missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_cosmos_none_returns_none(self):
        result = await get_trace_by_id(None, "aap", "thread_x", "run_y")
        assert result is None

    @pytest.mark.asyncio
    async def test_generic_error_returns_none(self):
        cosmos = self._make_cosmos_read(raises=Exception("network error"))

        result = await get_trace_by_id(cosmos, "aap", "thread_x", "run_y")
        assert result is None
