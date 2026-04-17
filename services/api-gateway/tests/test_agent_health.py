from __future__ import annotations
"""Tests for Phase 70: Agent Health Monitor."""
import os

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_gateway.agent_health import (
    KNOWN_AGENTS,
    AgentHealthMonitor,
    AgentHealthRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    name: str = "compute",
    status: str = "healthy",
    consecutive_failures: int = 0,
    last_healthy: Optional[str] = "2026-04-17T00:00:00+00:00",
    endpoint: str = "http://compute:8000",
    error: Optional[str] = None,
    latency_ms: Optional[float] = 42.0,
) -> AgentHealthRecord:
    return AgentHealthRecord(
        name=name,
        container_app="ca-compute-prod",
        status=status,
        last_checked="2026-04-17T00:00:00+00:00",
        last_healthy=last_healthy,
        consecutive_failures=consecutive_failures,
        latency_ms=latency_ms,
        endpoint=endpoint,
        error=error,
    )


def _make_monitor(cosmos_client=None, incident_callback=None) -> AgentHealthMonitor:
    if incident_callback is None:
        incident_callback = AsyncMock()
    return AgentHealthMonitor(
        cosmos_client=cosmos_client,
        cosmos_database_name="aap",
        incident_callback=incident_callback,
    )


# ---------------------------------------------------------------------------
# AgentHealthRecord tests
# ---------------------------------------------------------------------------

class TestAgentHealthRecord:
    def test_status_from_failures_zero(self):
        assert AgentHealthRecord._status_from_failures(0, "http://x") == "healthy"

    def test_status_from_failures_one(self):
        assert AgentHealthRecord._status_from_failures(1, "http://x") == "degraded"

    def test_status_from_failures_two(self):
        assert AgentHealthRecord._status_from_failures(2, "http://x") == "degraded"

    def test_status_from_failures_three(self):
        assert AgentHealthRecord._status_from_failures(3, "http://x") == "offline"

    def test_status_from_failures_five(self):
        assert AgentHealthRecord._status_from_failures(5, "http://x") == "offline"

    def test_status_unknown_when_no_endpoint(self):
        assert AgentHealthRecord._status_from_failures(0, "") == "unknown"
        assert AgentHealthRecord._status_from_failures(3, "") == "unknown"

    def test_to_dict_includes_id(self):
        r = _make_record(name="arc")
        d = r.to_dict()
        assert d["id"] == "arc"
        assert d["name"] == "arc"


# ---------------------------------------------------------------------------
# AgentHealthMonitor.get_all / get_one
# ---------------------------------------------------------------------------

class TestGetters:
    def test_get_all_empty(self):
        monitor = _make_monitor()
        assert monitor.get_all() == []

    def test_get_all_returns_dicts(self):
        monitor = _make_monitor()
        monitor._cache["compute"] = _make_record(name="compute")
        result = monitor.get_all()
        assert len(result) == 1
        assert result[0]["name"] == "compute"

    def test_get_one_found(self):
        monitor = _make_monitor()
        monitor._cache["sre"] = _make_record(name="sre")
        result = monitor.get_one("sre")
        assert result is not None
        assert result["name"] == "sre"

    def test_get_one_not_found(self):
        monitor = _make_monitor()
        assert monitor.get_one("nonexistent") is None


# ---------------------------------------------------------------------------
# check_agent
# ---------------------------------------------------------------------------

class TestCheckAgent:
    @pytest.mark.asyncio
    async def test_check_agent_success_200(self):
        monitor = _make_monitor()
        agent_cfg = {"name": "compute", "container_app": "ca-compute-prod", "env_var": "COMPUTE_ENDPOINT"}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.dict("os.environ", {"COMPUTE_ENDPOINT": "http://compute:8000"}):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                record = await monitor.check_agent(agent_cfg)

        assert record.status == "healthy"
        assert record.consecutive_failures == 0
        assert record.latency_ms is not None
        assert record.error is None

    @pytest.mark.asyncio
    async def test_check_agent_timeout_increments_failures(self):
        monitor = _make_monitor()
        agent_cfg = {"name": "compute", "container_app": "ca-compute-prod", "env_var": "COMPUTE_ENDPOINT"}

        with patch.dict("os.environ", {"COMPUTE_ENDPOINT": "http://compute:8000"}):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(side_effect=Exception("timeout"))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                record = await monitor.check_agent(agent_cfg)

        assert record.status == "degraded"
        assert record.consecutive_failures == 1
        assert record.error is not None

    @pytest.mark.asyncio
    async def test_check_agent_no_endpoint_returns_unknown(self):
        monitor = _make_monitor()
        agent_cfg = {"name": "compute", "container_app": "ca-compute-prod", "env_var": "COMPUTE_ENDPOINT_MISSING"}

        with patch.dict("os.environ", {}, clear=False):
            # Ensure COMPUTE_ENDPOINT_MISSING is absent
            import os
            os.environ.pop("COMPUTE_ENDPOINT_MISSING", None)
            record = await monitor.check_agent(agent_cfg)

        assert record.status == "unknown"
        assert record.endpoint == ""

    @pytest.mark.asyncio
    async def test_check_agent_http_500_increments_failures(self):
        monitor = _make_monitor()
        agent_cfg = {"name": "compute", "container_app": "ca-compute-prod", "env_var": "COMPUTE_ENDPOINT"}

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch.dict("os.environ", {"COMPUTE_ENDPOINT": "http://compute:8000"}):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                record = await monitor.check_agent(agent_cfg)

        assert record.status == "degraded"
        assert record.consecutive_failures == 1
        assert "500" in record.error


# ---------------------------------------------------------------------------
# check_all
# ---------------------------------------------------------------------------

class TestCheckAll:
    @pytest.mark.asyncio
    async def test_check_all_returns_all_agents(self):
        monitor = _make_monitor()

        async def _fake_check(agent):
            return _make_record(name=agent["name"], status="unknown", endpoint="")

        with patch.object(monitor, "check_agent", side_effect=_fake_check):
            records = await monitor.check_all()

        assert len(records) == len(KNOWN_AGENTS)
        names = {r.name for r in records}
        assert names == {a["name"] for a in KNOWN_AGENTS}


# ---------------------------------------------------------------------------
# _should_raise_incident
# ---------------------------------------------------------------------------

class TestShouldRaiseIncident:
    def test_three_failures_first_time_true(self):
        monitor = _make_monitor()
        record = _make_record(consecutive_failures=3, status="offline")
        assert monitor._should_raise_incident(record, None) is True

    def test_two_failures_false(self):
        monitor = _make_monitor()
        record = _make_record(consecutive_failures=2, status="degraded")
        assert monitor._should_raise_incident(record, None) is False

    def test_five_failures_first_time_true(self):
        monitor = _make_monitor()
        record = _make_record(consecutive_failures=5, status="offline")
        assert monitor._should_raise_incident(record, None) is True

    def test_already_at_three_no_re_fire(self):
        monitor = _make_monitor()
        record = _make_record(consecutive_failures=3, status="offline")
        previous = _make_record(consecutive_failures=3, status="offline")
        assert monitor._should_raise_incident(record, previous) is False

    def test_transition_2_to_3_fires(self):
        monitor = _make_monitor()
        record = _make_record(consecutive_failures=3, status="offline")
        previous = _make_record(consecutive_failures=2, status="degraded")
        assert monitor._should_raise_incident(record, previous) is True

    def test_four_failures_false(self):
        monitor = _make_monitor()
        record = _make_record(consecutive_failures=4, status="offline")
        assert monitor._should_raise_incident(record, None) is False


# ---------------------------------------------------------------------------
# run_health_loop
# ---------------------------------------------------------------------------

class TestRunHealthLoop:
    @pytest.mark.asyncio
    async def test_loop_calls_check_all_and_updates_cache(self):
        monitor = _make_monitor()
        records = [_make_record(name=a["name"], status="healthy") for a in KNOWN_AGENTS]

        call_count = 0

        async def _fake_check_all():
            nonlocal call_count
            call_count += 1
            return records

        with patch.object(monitor, "check_agent"):
            with patch.object(monitor, "check_all", side_effect=_fake_check_all):
                with patch.object(monitor, "_persist_record", new_callable=AsyncMock):
                    # Run loop but cancel after first iteration
                    task = asyncio.create_task(monitor.run_health_loop(interval_seconds=3600))
                    await asyncio.sleep(0.1)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        assert call_count >= 1
        assert len(monitor._cache) == len(KNOWN_AGENTS)

    @pytest.mark.asyncio
    async def test_loop_continues_on_exception(self):
        monitor = _make_monitor()
        call_count = 0

        async def _failing_check_all():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        with patch.object(monitor, "check_all", side_effect=_failing_check_all):
            task = asyncio.create_task(monitor.run_health_loop(interval_seconds=0))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should have been called multiple times without crashing the loop
        assert call_count >= 1


# ---------------------------------------------------------------------------
# Cosmos unavailable — graceful fallback
# ---------------------------------------------------------------------------

class TestCosmosUnavailable:
    @pytest.mark.asyncio
    async def test_persist_record_no_cosmos_is_noop(self):
        monitor = _make_monitor(cosmos_client=None)
        record = _make_record()
        # Should not raise
        await monitor._persist_record(record)

    @pytest.mark.asyncio
    async def test_persist_record_cosmos_error_is_noop(self):
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.side_effect = Exception("connection refused")
        monitor = _make_monitor(cosmos_client=mock_cosmos)
        record = _make_record()
        # Should not raise
        await monitor._persist_record(record)


# ---------------------------------------------------------------------------
# Incident callback invoked at threshold
# ---------------------------------------------------------------------------

class TestIncidentCallback:
    @pytest.mark.asyncio
    async def test_incident_callback_invoked_at_three_failures(self):
        callback = AsyncMock()
        monitor = _make_monitor(incident_callback=callback)

        record = _make_record(name="network", consecutive_failures=3, status="offline")
        previous = _make_record(name="network", consecutive_failures=2, status="degraded")
        monitor._cache["network"] = previous

        await monitor._emit_incident(record)
        callback.assert_awaited_once()
        payload = callback.call_args[0][0]
        assert payload["severity"] == "Sev1"
        assert "network" in payload["title"]
        assert payload["domain"] == "platform"

    @pytest.mark.asyncio
    async def test_incident_callback_sev0_at_five_failures(self):
        callback = AsyncMock()
        monitor = _make_monitor(incident_callback=callback)

        record = _make_record(name="arc", consecutive_failures=5, status="offline")
        await monitor._emit_incident(record)
        payload = callback.call_args[0][0]
        assert payload["severity"] == "Sev0"

    @pytest.mark.asyncio
    async def test_incident_callback_exception_does_not_raise(self):
        callback = AsyncMock(side_effect=Exception("callback failed"))
        monitor = _make_monitor(incident_callback=callback)
        record = _make_record(name="sre", consecutive_failures=3, status="offline")
        # Should not raise
        await monitor._emit_incident(record)
