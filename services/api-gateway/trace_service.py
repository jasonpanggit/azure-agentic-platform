"""Trace service — capture and query Foundry run step traces.

Captures run steps from Foundry Agent Service after a run completes and
persists them to Cosmos DB (agent_traces container, TTL 7 days).

All errors are caught and logged — this is fire-and-forget, never raises.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TRACE_TTL_SECONDS = 604800  # 7 days


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iso_from_timestamp(ts: Any) -> Optional[str]:
    """Convert a Unix timestamp (int/float) or datetime to ISO-8601 string."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return str(ts)


def _extract_token_usage(run: Any) -> dict:
    """Extract token usage from a completed run object."""
    usage = getattr(run, "usage", None)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


def _parse_step(step: Any) -> dict:
    """Parse a RunStep object into a serialisable dict."""
    step_type = str(getattr(step, "type", "")).lower().replace("runsteptype.", "")
    status = str(getattr(step, "status", "")).lower().replace("runstepstatus.", "")
    created_at = _iso_from_timestamp(getattr(step, "created_at", None))

    parsed: dict = {
        "step_id": getattr(step, "id", ""),
        "type": step_type,
        "status": status,
        "created_at": created_at,
        "tool_calls": [],
    }

    if step_type == "tool_calls":
        details = getattr(step, "step_details", None)
        raw_calls = getattr(details, "tool_calls", []) if details else []
        tool_calls = []
        for tc in raw_calls:
            tc_type = str(getattr(tc, "type", "function")).lower().replace("toolcalltype.", "")
            fn = getattr(tc, "function", None)
            call_dict: dict = {
                "id": getattr(tc, "id", ""),
                "type": tc_type,
                "name": getattr(fn, "name", "") if fn else "",
                "arguments": getattr(fn, "arguments", "") if fn else "",
                "output": getattr(fn, "output", None) if fn else None,
                "duration_ms": None,
            }
            tool_calls.append(call_dict)
        parsed["tool_calls"] = tool_calls

    return parsed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def capture_run_trace(
    *,
    agents_client: Any,
    thread_id: str,
    run_id: str,
    incident_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    agent_name: str = "orchestrator",
    cosmos_client: Optional[Any] = None,
    cosmos_database_name: str = "aap",
    run_duration_ms: Optional[float] = None,
) -> Optional[dict]:
    """Fetch run steps from Foundry and persist to Cosmos.

    Returns the trace dict on success, None on unrecoverable error.
    Never raises — all exceptions are caught and logged.
    """
    try:
        from azure.ai.agents import AgentsClient  # noqa: F401 — validates import
    except ImportError:
        logger.warning("capture_run_trace: azure-ai-agents not installed; skipping trace capture")
        return None

    try:
        loop = asyncio.get_running_loop()

        # Fetch run (for token usage) and run steps in executor (sync SDK)
        try:
            run_obj = await loop.run_in_executor(
                None,
                lambda: agents_client.runs.get(thread_id=thread_id, run_id=run_id),
            )
        except Exception as exc:
            logger.warning("capture_run_trace: failed to get run %s/%s: %s", thread_id, run_id, exc)
            run_obj = None

        try:
            raw_steps = await loop.run_in_executor(
                None,
                lambda: list(agents_client.runs.list_steps(thread_id=thread_id, run_id=run_id)),
            )
        except Exception as exc:
            logger.warning("capture_run_trace: failed to list steps %s/%s: %s", thread_id, run_id, exc)
            raw_steps = []

        # Parse steps
        steps = [_parse_step(s) for s in raw_steps]
        total_tool_calls = sum(len(s["tool_calls"]) for s in steps)

        # Token usage from run object
        token_usage = _extract_token_usage(run_obj) if run_obj else {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0
        }

        now = datetime.now(timezone.utc).isoformat()
        trace = {
            "id": f"{thread_id}_{run_id}",
            "thread_id": thread_id,
            "run_id": run_id,
            "incident_id": incident_id,
            "conversation_id": conversation_id,
            "agent_name": agent_name,
            "captured_at": now,
            "steps": steps,
            "token_usage": token_usage,
            "total_tool_calls": total_tool_calls,
            "duration_ms": run_duration_ms,
            "ttl": _TRACE_TTL_SECONDS,
        }

        # Persist to Cosmos (fire-and-forget friendly — log and continue on error)
        if cosmos_client is not None:
            try:
                db = cosmos_client.get_database_client(cosmos_database_name)
                container = db.get_container_client("agent_traces")
                await loop.run_in_executor(
                    None,
                    lambda: container.upsert_item(trace),
                )
                logger.info(
                    "capture_run_trace: persisted trace %s (%d steps, %d tool calls)",
                    trace["id"], len(steps), total_tool_calls,
                )
            except Exception as exc:
                logger.warning("capture_run_trace: failed to persist trace to Cosmos: %s", exc)
        else:
            logger.debug("capture_run_trace: no cosmos_client; trace not persisted")

        return trace

    except Exception as exc:
        logger.error("capture_run_trace: unexpected error for %s/%s: %s", thread_id, run_id, exc)
        return None


async def get_traces(
    cosmos_client: Any,
    cosmos_database_name: str,
    *,
    thread_id: Optional[str] = None,
    incident_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Query traces from Cosmos. Returns (traces, total_count)."""
    if cosmos_client is None:
        return [], 0

    try:
        loop = asyncio.get_running_loop()

        where_clauses = ["1=1"]
        parameters: list[dict] = []

        if thread_id:
            where_clauses.append("c.thread_id = @thread_id")
            parameters.append({"name": "@thread_id", "value": thread_id})
        if incident_id:
            where_clauses.append("c.incident_id = @incident_id")
            parameters.append({"name": "@incident_id", "value": incident_id})

        where = " AND ".join(where_clauses)

        count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {where}"
        data_query = (
            f"SELECT c.id, c.thread_id, c.run_id, c.incident_id, c.conversation_id, "
            f"c.agent_name, c.captured_at, c.total_tool_calls, c.duration_ms, c.token_usage "
            f"FROM c WHERE {where} ORDER BY c.captured_at DESC OFFSET {offset} LIMIT {limit}"
        )

        db = cosmos_client.get_database_client(cosmos_database_name)
        container = db.get_container_client("agent_traces")

        def _query():
            count_items = list(container.query_items(
                query=count_query,
                parameters=parameters,
                enable_cross_partition_query=True,
            ))
            total = count_items[0] if count_items else 0

            items = list(container.query_items(
                query=data_query,
                parameters=parameters,
                enable_cross_partition_query=True,
            ))
            return items, total

        items, total = await loop.run_in_executor(None, _query)
        return items, int(total)

    except Exception as exc:
        logger.warning("get_traces: query failed: %s", exc)
        return [], 0


async def get_trace_by_id(
    cosmos_client: Any,
    cosmos_database_name: str,
    thread_id: str,
    run_id: str,
) -> Optional[dict]:
    """Get a single trace by thread_id + run_id."""
    if cosmos_client is None:
        return None

    try:
        loop = asyncio.get_running_loop()
        item_id = f"{thread_id}_{run_id}"

        db = cosmos_client.get_database_client(cosmos_database_name)
        container = db.get_container_client("agent_traces")

        def _read():
            return container.read_item(item=item_id, partition_key=thread_id)

        item = await loop.run_in_executor(None, _read)
        return item

    except Exception as exc:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError  # type: ignore[attr-defined]
        if isinstance(exc, CosmosResourceNotFoundError):
            return None
        logger.warning("get_trace_by_id: failed to read %s/%s: %s", thread_id, run_id, exc)
        return None
