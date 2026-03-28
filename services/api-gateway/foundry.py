"""Foundry thread creation and Orchestrator dispatch (DETECT-004, D-11).

Creates a Foundry conversation thread for each incident, posts the
incident as a typed message envelope (AGENT-002), and dispatches
to the Orchestrator agent.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from services.api_gateway.models import IncidentPayload

logger = logging.getLogger(__name__)


def _get_foundry_client() -> AIProjectClient:
    """Create an AIProjectClient using DefaultAzureCredential.

    Reads AZURE_PROJECT_ENDPOINT from environment, falling back to
    FOUNDRY_ACCOUNT_ENDPOINT for backward compatibility with the
    Terraform agent-apps module which uses the latter name.
    """
    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise ValueError(
            "AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) "
            "environment variable is required."
        )

    return AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )


async def create_foundry_thread(payload: IncidentPayload) -> dict[str, str]:
    """Create a Foundry thread and dispatch incident to the Orchestrator.

    Steps:
    1. Create a new conversation thread in Foundry.
    2. Post the incident as a typed envelope message (AGENT-002).
    3. Start a run with the Orchestrator agent.
    4. Return thread_id and run_id.

    Args:
        payload: Validated incident payload from the API.

    Returns:
        Dict with "thread_id" and "run_id" keys.
    """
    client = _get_foundry_client()
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")

    if not orchestrator_agent_id:
        raise ValueError(
            "ORCHESTRATOR_AGENT_ID environment variable is required."
        )

    # Create thread
    thread = client.agents.create_thread()
    logger.info(
        "Created Foundry thread %s for incident %s",
        thread.id,
        payload.incident_id,
    )

    # Build typed envelope message (AGENT-002)
    now = datetime.now(timezone.utc).isoformat()
    envelope = {
        "correlation_id": payload.incident_id,
        "thread_id": thread.id,
        "source_agent": "api-gateway",
        "target_agent": "orchestrator",
        "message_type": "incident_handoff",
        "payload": payload.model_dump(),
        "timestamp": now,
    }

    # Post incident as first message
    client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=json.dumps(envelope),
    )

    # Dispatch to Orchestrator agent
    run = client.agents.create_run(
        thread_id=thread.id,
        assistant_id=orchestrator_agent_id,
    )

    logger.info(
        "Dispatched incident %s to Orchestrator (run %s)",
        payload.incident_id,
        run.id,
    )

    return {"thread_id": thread.id, "run_id": run.id}
