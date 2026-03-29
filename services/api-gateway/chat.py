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
from typing import Optional

from services.api_gateway.azure_tools import AzureToolRequest, call_azure_tool
from services.api_gateway.foundry import _get_foundry_client
from services.api_gateway.instrumentation import agent_span, foundry_span, mcp_span
from services.api_gateway.models import ChatRequest

logger = logging.getLogger(__name__)


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

    # Resolve thread_id (TEAMS-004)
    thread_id = request.thread_id

    if not thread_id and request.incident_id:
        # Look up thread_id from Cosmos DB incident record
        thread_id = await _lookup_thread_by_incident(request.incident_id)

    if thread_id:
        # Continue existing thread (TEAMS-004)
        logger.info("Continuing thread %s for user %s", thread_id, effective_user_id)
    else:
        # Create new thread
        with foundry_span("create_thread") as span:
            thread = client.threads.create()
            thread_id = thread.id
            span.set_attribute("foundry.thread_id", thread_id)
        logger.info(
            "Created chat thread %s for user %s", thread_id, effective_user_id
        )

    # Build message content — prepend subscription context if provided so the
    # agent can call Azure MCP tools without asking for clarification.
    message_content = request.message
    if request.subscription_ids:
        subs_csv = ", ".join(request.subscription_ids)
        message_content = (
            f"[Context: Azure subscription IDs in scope: {subs_csv}]\n\n"
            f"{request.message}"
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

    return {"thread_id": thread_id, "run_id": run.id}


async def get_chat_result(
    thread_id: str, run_id: Optional[str] = None
) -> dict[str, str]:
    """Poll Foundry for the latest run status on a thread.

    Handles the `requires_action / submit_tool_outputs` flow for the
    azure_tools function: when the orchestrator calls azure_tools, Foundry
    pauses the run. We execute the tool locally via stdio MCP and submit
    the output back to Foundry.

    Returns the run status and, when completed, the assistant's reply text.
    The caller (stream route) should poll until run_status is terminal
    (completed | failed | cancelled | expired).

    Args:
        thread_id: Foundry thread ID.
        run_id: Optional specific run ID to poll. When provided, targets
            exactly this run instead of guessing which is latest.

    Returns:
        Dict with "thread_id", "run_status", and optionally "reply".
    """
    client = _get_foundry_client()

    # If a specific run_id was provided, retrieve it directly.
    # Retry up to 3 times with a short delay — Foundry may not expose the run
    # immediately after creation (propagation delay of ~1-2 seconds).
    if run_id:
        latest_run = None
        for attempt in range(3):
            try:
                latest_run = client.runs.get(thread_id=thread_id, run_id=run_id)
                break
            except Exception as exc:
                if attempt < 2:
                    await asyncio.sleep(1)
                else:
                    logger.warning("Failed to retrieve run %s after 3 attempts: %s", run_id, exc)
                    return {"thread_id": thread_id, "run_status": "not_found", "reply": None}
        if latest_run is None:
            return {"thread_id": thread_id, "run_status": "not_found", "reply": None}
    else:
        # Fallback: list runs and pick the most recent one.
        # Foundry runs.list() returns chronological order (oldest first),
        # so the LAST element is the most recent run.
        runs = client.runs.list(thread_id=thread_id)
        run_list = list(runs)
        if not run_list:
            return {"thread_id": thread_id, "run_status": "not_found", "reply": None}

        latest_run = run_list[-1]

    run_status = latest_run.status

    logger.debug("Thread %s run %s status: %s", thread_id, latest_run.id, run_status)

    if run_status == "requires_action":
        required_action = latest_run.required_action
        if (
            required_action is not None
            and hasattr(required_action, "type")
            and required_action.type == "submit_tool_outputs"
        ):
            tool_calls = required_action.submit_tool_outputs.tool_calls  # type: ignore[attr-defined]
            tool_outputs = []
            for tc in tool_calls:
                fn_name = getattr(tc.function, "name", "") if hasattr(tc, "function") else ""
                fn_args_raw = getattr(tc.function, "arguments", "{}") if hasattr(tc, "function") else "{}"
                logger.info("Executing function tool call: %s (id=%s)", fn_name, tc.id)

                if fn_name == "azure_tools":
                    try:
                        fn_args = json.loads(fn_args_raw)
                        tool_req = AzureToolRequest(
                            tool_name=fn_args.get("tool_name", "compute"),
                            arguments=fn_args.get("arguments", {}),
                        )
                        result = await call_azure_tool(tool_req)
                        output = result.content
                    except Exception as exc:
                        logger.error("azure_tools execution failed: %s", exc)
                        output = f"Error calling azure_tools: {exc}"
                else:
                    output = f"Unknown function: {fn_name}"

                tool_outputs.append({"tool_call_id": tc.id, "output": output})

            logger.info(
                "Submitting %d tool output(s) for thread %s run %s",
                len(tool_outputs),
                thread_id,
                latest_run.id,
            )
            try:
                with mcp_span("tool_approval", thread_id=thread_id) as mspan:
                    mspan.set_attribute("mcp.tool_calls_count", str(len(tool_outputs)))
                    client.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=latest_run.id,
                        tool_outputs=tool_outputs,
                    )
                return {"thread_id": thread_id, "run_status": "in_progress", "reply": None}
            except Exception as exc:
                logger.warning("Failed to submit tool outputs: %s", exc)

    reply = None
    if run_status == "completed":
        # Fetch the last assistant message
        with foundry_span("list_messages", thread_id=thread_id):
            messages = client.messages.list(thread_id=thread_id)
        for msg in messages:
            if msg.role == "assistant":
                # Extract text from the first text content block
                for block in msg.content:
                    if hasattr(block, "text") and hasattr(block.text, "value"):
                        reply = block.text.value
                        break
                if reply:
                    break

    return {"thread_id": thread_id, "run_status": run_status, "reply": reply}
