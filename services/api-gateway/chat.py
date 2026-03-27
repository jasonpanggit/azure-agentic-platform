"""Chat endpoint — operator-initiated conversations (D-06).

Creates a Foundry thread for ad-hoc operator queries, separate
from detection-plane incident ingestion (POST /api/v1/incidents).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from services.api_gateway.foundry import _get_foundry_client
from services.api_gateway.models import ChatRequest

logger = logging.getLogger(__name__)


async def create_chat_thread(request: ChatRequest, user_id: str) -> dict[str, str]:
    """Create a Foundry thread for an operator chat session.

    Args:
        request: Validated chat request.
        user_id: Authenticated operator's user ID from Entra token.

    Returns:
        Dict with "thread_id" key.
    """
    client = _get_foundry_client()
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")

    if not orchestrator_agent_id:
        raise ValueError("ORCHESTRATOR_AGENT_ID environment variable is required.")

    thread = client.agents.create_thread()
    logger.info("Created chat thread %s for user %s", thread.id, user_id)

    now = datetime.now(timezone.utc).isoformat()
    envelope = {
        "correlation_id": f"chat-{thread.id}",
        "thread_id": thread.id,
        "source_agent": "operator",
        "target_agent": "orchestrator",
        "message_type": "incident_handoff",
        "payload": {
            "message": request.message,
            "incident_id": request.incident_id,
            "initiated_by": user_id,
        },
        "timestamp": now,
    }

    client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=json.dumps(envelope),
    )

    run = client.agents.create_run(
        thread_id=thread.id,
        assistant_id=orchestrator_agent_id,
    )

    return {"thread_id": thread.id, "run_id": run.id}
