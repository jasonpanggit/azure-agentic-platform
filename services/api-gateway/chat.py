"""Chat endpoint — operator-initiated conversations (D-06, TEAMS-004).

Creates a Foundry thread for ad-hoc operator queries, separate
from detection-plane incident ingestion (POST /api/v1/incidents).
Supports thread continuation for cross-surface thread sharing (TEAMS-004).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from agents.shared.routing import classify_query_text

from services.api_gateway.foundry import _get_foundry_client
from services.api_gateway.instrumentation import agent_span, foundry_span, mcp_span
from services.api_gateway.models import ChatRequest

logger = logging.getLogger(__name__)


def _build_operator_query_envelope(
    *,
    thread_id: str,
    request: ChatRequest,
    initiated_by: str,
) -> str:
    """Build a structured operator-query envelope for orchestrator routing."""
    classification = classify_query_text(request.message)
    payload: dict[str, object] = {
        "message": request.message,
        "initiated_by": initiated_by,
        "domain_hint": classification["domain"],
        "classification_confidence": classification["confidence"],
        "classification_reason": classification["reason"],
    }

    # Use provided subscription IDs, or fall back to the platform default subscription
    # so the orchestrator always has subscription context without asking the operator.
    subscription_ids = request.subscription_ids or []
    if not subscription_ids:
        default_sub = os.environ.get("DEFAULT_SUBSCRIPTION_ID")
        if default_sub:
            subscription_ids = [default_sub]
    if subscription_ids:
        payload["subscription_ids"] = subscription_ids

    envelope = {
        "correlation_id": request.incident_id or thread_id,
        "thread_id": thread_id,
        "source_agent": "api-gateway",
        "target_agent": "orchestrator",
        "message_type": "operator_query",
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(envelope)


async def _lookup_thread_by_incident(incident_id: str) -> Optional[str]:
    """Look up Foundry thread_id from Cosmos DB incident record."""
    try:
        from services.api_gateway.incidents_list import _get_incidents_container

        container = _get_incidents_container()
        query = "SELECT c.thread_id FROM c WHERE c.incident_id = @incident_id"
        items = list(
            container.query_items(
                query=query,
                parameters=[{"name": "@incident_id", "value": incident_id}],
                enable_cross_partition_query=True,
            )
        )
        if items and items[0].get("thread_id"):
            return items[0]["thread_id"]
    except Exception as exc:
        logger.warning(
            "Failed to look up thread for incident %s: %s", incident_id, exc
        )
    return None


async def create_chat_thread(request: ChatRequest, user_id: str) -> dict[str, str]:
    """Create or continue a Foundry thread for an operator chat session.

    Supports three modes (TEAMS-004):
    1. thread_id provided: Continue existing thread (skip creation).
    2. incident_id provided (no thread_id): Look up thread from Cosmos DB.
    3. Neither provided: Create a new Foundry thread (default).

    Args:
        request: Validated chat request.
        user_id: Authenticated operator's user ID from Entra token.

    Returns:
        Dict with "thread_id" and "run_id" keys.
    """
    client = _get_foundry_client()
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")

    if not orchestrator_agent_id:
        raise ValueError("ORCHESTRATOR_AGENT_ID environment variable is required.")

    # Determine user identity -- request.user_id takes precedence (D-07)
    effective_user_id = request.user_id or user_id
    logger.info(
        "create_chat_thread: user=%s thread_id=%s incident_id=%s message=%.120s",
        effective_user_id,
        request.thread_id or "<new>",
        request.incident_id or "<none>",
        request.message,
    )

    # Resolve thread_id (TEAMS-004)
    thread_id = request.thread_id

    if not thread_id and request.incident_id:
        # Look up thread_id from Cosmos DB incident record
        thread_id = await _lookup_thread_by_incident(request.incident_id)

    if thread_id:
        # Continue existing thread (TEAMS-004)
        # Cancel any active runs first — Foundry rejects new messages on a thread
        # that has an in-progress run (raises HttpResponseError).
        logger.info("Continuing thread %s for user %s", thread_id, effective_user_id)
        try:
            runs = list(client.runs.list(thread_id=thread_id))
            active_statuses = {"queued", "in_progress", "requires_action", "cancelling"}
            for run in runs:
                if run.status in active_statuses:
                    logger.info(
                        "Cancelling active run %s (status=%s) on thread %s",
                        run.id,
                        run.status,
                        thread_id,
                    )
                    try:
                        client.runs.cancel(thread_id=thread_id, run_id=run.id)
                    except Exception as cancel_exc:
                        logger.warning("Failed to cancel run %s: %s", run.id, cancel_exc)
            # Brief wait for cancellation to propagate
            if runs and any(r.status in active_statuses for r in runs):
                await asyncio.sleep(1)
        except Exception as list_exc:
            logger.warning("Failed to list/cancel runs for thread %s: %s", thread_id, list_exc)
    else:
        # Create new thread
        with foundry_span("create_thread") as span:
            thread = client.threads.create()
            thread_id = thread.id
            span.set_attribute("foundry.thread_id", thread_id)
        logger.info(
            "Created chat thread %s for user %s", thread_id, effective_user_id
        )

    message_content = _build_operator_query_envelope(
        thread_id=thread_id,
        request=request,
        initiated_by=effective_user_id,
    )

    with foundry_span("post_message", thread_id=thread_id) as span:
        client.messages.create(
            thread_id=thread_id,
            role="user",
            content=message_content,
        )

    with agent_span("orchestrator", correlation_id=request.incident_id or ""):
        with foundry_span("create_run", thread_id=thread_id) as span:
            run = client.runs.create(
                thread_id=thread_id,
                agent_id=orchestrator_agent_id,
            )
            span.set_attribute("foundry.run_id", run.id)

    logger.info(
        "create_chat_thread: dispatched | thread_id=%s run_id=%s agent_id=%s",
        thread_id,
        run.id,
        orchestrator_agent_id,
    )
    return {"thread_id": thread_id, "run_id": run.id}


async def _submit_mcp_approval(
    endpoint: str,
    thread_id: str,
    run_id: str,
    tool_calls: list,
) -> bool:
    """Submit auto-approval for Foundry MCP tool calls via REST.

    The SDK doesn't expose submit_tool_approval; call the REST endpoint directly.
    Returns True on success.
    """
    import requests as _requests
    from azure.identity import DefaultAzureCredential

    approvals = [{"tool_call_id": tc.id, "approve": True} for tc in tool_calls]
    logger.info(
        "Auto-approving %d MCP tool call(s) for thread %s run %s",
        len(approvals), thread_id, run_id,
    )
    try:
        _token = DefaultAzureCredential().get_token("https://ai.azure.com/.default")
        _headers = {
            "Authorization": f"Bearer {_token.token}",
            "Content-Type": "application/json",
        }
        _url = f"{endpoint}/threads/{thread_id}/runs/{run_id}/submit_tool_outputs?api-version=2025-05-15-preview"
        _resp = _requests.post(_url, headers=_headers, json={"tool_approvals": approvals})
        if _resp.status_code in (200, 201):
            return True
        logger.warning("Failed to submit tool approvals: %s %s", _resp.status_code, _resp.text[:200])
    except Exception as exc:
        logger.warning("Exception submitting tool approvals: %s", exc)
    return False


async def get_chat_result(
    thread_id: str, run_id: Optional[str] = None
) -> dict[str, str]:
    """Return the current status of a Foundry run (single-shot, non-blocking).

    Called repeatedly by the SSE stream route which owns the polling loop.
    This function fetches the run once and returns immediately — it does NOT
    block waiting for completion.

    Args:
        thread_id: Foundry thread ID.
        run_id: Specific run ID to poll.

    Returns:
        Dict with "thread_id", "run_status", and optionally "reply".
    """
    client = _get_foundry_client()
    terminal = {"completed", "failed", "cancelled", "expired"}

    # Fetch run status — try once, return not_found if unavailable
    try:
        latest_run = client.runs.get(thread_id=thread_id, run_id=run_id)
    except Exception as exc:
        logger.warning("Run %s not found: %s", run_id, exc)
        return {"thread_id": thread_id, "run_status": "not_found", "reply": None}

    run_status = str(
        latest_run.status.value
        if hasattr(latest_run.status, "value")
        else latest_run.status
    )
    logger.info("Thread %s run %s status: %s", thread_id, latest_run.id, run_status)

    # If requires_action, auto-approve MCP tool calls so run can proceed
    if run_status == "requires_action":
        required_action = latest_run.required_action
        if required_action is not None and hasattr(required_action, "type"):
            endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
                "FOUNDRY_ACCOUNT_ENDPOINT", ""
            )
            if required_action.type == "submit_tool_approval":
                tool_calls = required_action.submit_tool_approval.tool_calls  # type: ignore
                await _submit_mcp_approval(endpoint, thread_id, latest_run.id, tool_calls)
            elif required_action.type == "submit_tool_outputs":
                tool_calls = required_action.submit_tool_outputs.tool_calls  # type: ignore
                outputs = [{"tool_call_id": tc.id, "output": "Not supported"} for tc in tool_calls]
                try:
                    client.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=latest_run.id,
                        tool_outputs=outputs,
                    )
                except Exception as exc:
                    logger.warning("Failed to submit tool outputs: %s", exc)

    # Return non-terminal status immediately — caller polls again
    if run_status not in terminal:
        return {"thread_id": thread_id, "run_status": run_status, "reply": None}

    reply = None
    if run_status == "completed":
        with foundry_span("list_messages", thread_id=thread_id):
            messages = client.messages.list(thread_id=thread_id)
        for msg in messages:
            if msg.role == "assistant":
                for block in msg.content:
                    if hasattr(block, "text") and hasattr(block.text, "value"):
                        reply = block.text.value
                        break
                if reply:
                    break

    return {"thread_id": thread_id, "run_status": run_status, "reply": reply}
