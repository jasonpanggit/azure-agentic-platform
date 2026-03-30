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
from typing import Optional

from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential

from services.api_gateway.instrumentation import agent_span, foundry_span
from services.api_gateway.models import IncidentPayload

logger = logging.getLogger(__name__)


def _get_foundry_client(credential: Optional[DefaultAzureCredential] = None) -> AgentsClient:
    """Create an AgentsClient using DefaultAzureCredential.

    Accepts an optional pre-initialized credential (from app.state singleton).
    Falls back to creating a new DefaultAzureCredential when not provided
    (backward compatibility for direct calls outside the FastAPI lifespan).

    Reads AZURE_PROJECT_ENDPOINT from environment, falling back to
    FOUNDRY_ACCOUNT_ENDPOINT for backward compatibility with the
    Terraform agent-apps module which uses the latter name.

    Note: azure-ai-projects 2.x moved thread/run/message operations to
    the azure-ai-agents package (AgentsClient). The client exposes
    .threads, .messages, and .runs sub-operation groups.
    """
    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise ValueError(
            "AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) "
            "environment variable is required."
        )

    if credential is None:
        credential = DefaultAzureCredential()

    return AgentsClient(
        endpoint=endpoint,
        credential=credential,
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
    with foundry_span("create_thread") as span:
        thread = client.threads.create()
        span.set_attribute("foundry.thread_id", thread.id)
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
    with foundry_span("post_message", thread_id=thread.id) as span:
        client.messages.create(
            thread_id=thread.id,
            role="user",
            content=json.dumps(envelope),
        )

    # Dispatch to Orchestrator agent
    with agent_span("orchestrator", domain=payload.domain, correlation_id=payload.incident_id):
        with foundry_span("create_run", thread_id=thread.id, agent_id=orchestrator_agent_id) as span:
            run = client.runs.create(
                thread_id=thread.id,
                agent_id=orchestrator_agent_id,
            )
            span.set_attribute("foundry.run_id", run.id)

    logger.info(
        "Dispatched incident %s to Orchestrator (run %s)",
        payload.incident_id,
        run.id,
    )

    return {"thread_id": thread.id, "run_id": run.id}
