"""Chat endpoint — operator-initiated conversations (D-06, TEAMS-004).

Creates a Foundry thread for ad-hoc operator queries, separate
from detection-plane incident ingestion (POST /api/v1/incidents).
Supports thread continuation for cross-surface thread sharing (TEAMS-004).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from services.api_gateway.foundry import _get_foundry_client
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
        thread = client.threads.create()
        thread_id = thread.id
        logger.info(
            "Created chat thread %s for user %s", thread_id, effective_user_id
        )

    now = datetime.now(timezone.utc).isoformat()
    envelope = {
        "correlation_id": f"chat-{thread_id}",
        "thread_id": thread_id,
        "source_agent": "operator",
        "target_agent": "orchestrator",
        "message_type": "incident_handoff",
        "payload": {
            "message": request.message,
            "incident_id": request.incident_id,
            "initiated_by": effective_user_id,
        },
        "timestamp": now,
    }

    client.messages.create(
        thread_id=thread_id,
        role="user",
        content=json.dumps(envelope),
    )

    run = client.runs.create(
        thread_id=thread_id,
        agent_id=orchestrator_agent_id,
    )

    return {"thread_id": thread_id, "run_id": run.id}


async def get_chat_result(thread_id: str) -> dict[str, str]:
    """Poll Foundry for the latest run status on a thread.

    Returns the run status and, when completed, the assistant's reply text.
    The caller (stream route) should poll until run_status is terminal
    (completed | failed | cancelled | expired).

    Args:
        thread_id: Foundry thread ID.

    Returns:
        Dict with "thread_id", "run_status", and optionally "reply".
    """
    client = _get_foundry_client()

    # Get the most recent run on this thread
    runs = client.runs.list(thread_id=thread_id)
    run_list = list(runs)
    if not run_list:
        return {"thread_id": thread_id, "run_status": "not_found", "reply": None}

    latest_run = run_list[0]
    run_status = latest_run.status

    logger.debug("Thread %s run %s status: %s", thread_id, latest_run.id, run_status)

    reply = None
    if run_status == "completed":
        # Fetch the last assistant message
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
