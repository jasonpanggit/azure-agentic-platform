"""Foundry Agent Service dispatch — Orchestrator invocation via AIProjectClient.

Uses azure-ai-projects>=2.0.1 AIProjectClient.agents.* for all Foundry
operations (create_thread, create_message, create_and_process_run, etc.).

Replaces two broken patterns:
- Phase 1-28: azure-ai-agents.AgentsClient (separate SDK, deprecated path)
- Phase 29 attempt: openai_client.responses.create() with agent_reference
  (wrong API — causes 500 server_error from Foundry)

Correct path: AIProjectClient.agents.* (azure-ai-projects>=2.0.1)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from azure.identity import DefaultAzureCredential

from services.api_gateway.instrumentation import agent_span, foundry_span
from services.api_gateway.models import IncidentPayload

try:
    from azure.ai.projects import AIProjectClient
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AIProjectClient factory (shared)
# ---------------------------------------------------------------------------


def _get_foundry_project(credential: Optional[DefaultAzureCredential] = None):
    """Create AIProjectClient using DefaultAzureCredential.

    Reads AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT for compat).
    """
    if AIProjectClient is None:
        raise ImportError(
            "azure-ai-projects>=2.0.1 required. "
            "Install with: pip install 'azure-ai-projects>=2.0.1'"
        )

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise ValueError(
            "AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) env var required."
        )

    if credential is None:
        credential = DefaultAzureCredential()

    return AIProjectClient(endpoint=endpoint, credential=credential)


def _get_agents_client(project=None):
    """Return the agents sub-client from AIProjectClient."""
    if project is None:
        project = _get_foundry_project()
    return project.agents


# ---------------------------------------------------------------------------
# Backward-compat: _get_foundry_client now returns the agents sub-client
# from AIProjectClient so existing callers (approvals.py, etc.) continue
# to work without changes.
# ---------------------------------------------------------------------------


def _get_foundry_client(credential: Optional[DefaultAzureCredential] = None):
    """Return AIProjectClient.agents — the Foundry Agent Service client.

    Backward-compatible shim: callers that previously used AgentsClient
    (client.threads, client.messages, client.runs) now get the equivalent
    AIProjectClient.agents namespace which exposes the same operations.
    """
    return _get_agents_client(_get_foundry_project(credential))


# ---------------------------------------------------------------------------
# Message envelope helpers
# ---------------------------------------------------------------------------


def build_incident_message(payload: IncidentPayload) -> str:
    """Build the typed envelope message (AGENT-002) for the Orchestrator."""
    now = datetime.now(timezone.utc).isoformat()
    envelope = {
        "correlation_id": payload.incident_id,
        "source_agent": "api-gateway",
        "target_agent": "orchestrator",
        "message_type": "incident_handoff",
        "payload": payload.model_dump(),
        "timestamp": now,
    }
    return json.dumps(envelope)


# ---------------------------------------------------------------------------
# Incident dispatch
# ---------------------------------------------------------------------------


async def dispatch_to_orchestrator(
    payload: IncidentPayload,
    credential: Optional[DefaultAzureCredential] = None,
) -> dict[str, str]:
    """Dispatch an incident to the Orchestrator via AIProjectClient.agents.

    Creates a thread, posts the incident envelope, runs the orchestrator agent,
    and waits for completion. Returns thread_id and run_id.
    """
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")
    if not orchestrator_agent_id:
        raise ValueError("ORCHESTRATOR_AGENT_ID environment variable is required.")

    loop = asyncio.get_running_loop()
    agents = _get_agents_client(_get_foundry_project(credential))
    message = build_incident_message(payload)

    with agent_span(
        "orchestrator", domain=payload.domain, correlation_id=payload.incident_id
    ):
        with foundry_span("agents_create_thread_and_run") as span:
            # create_thread_and_run is a single blocking call — thread + first run
            run = await loop.run_in_executor(
                None,
                lambda: agents.create_thread_and_run(
                    agent_id=orchestrator_agent_id,
                    thread={
                        "messages": [
                            {"role": "user", "content": message}
                        ]
                    },
                ),
            )
            span.set_attribute("foundry.thread_id", run.thread_id)
            span.set_attribute("foundry.run_id", run.id)
            span.set_attribute("incident.id", payload.incident_id)
            span.set_attribute("incident.domain", payload.domain)

    logger.info(
        "Dispatched incident %s to Orchestrator (thread %s, run %s, status %s)",
        payload.incident_id,
        run.thread_id,
        run.id,
        run.status,
    )

    return {"thread_id": run.thread_id, "run_id": run.id, "status": run.status}


# ---------------------------------------------------------------------------
# Chat dispatch (operator → orchestrator, with thread continuity)
# ---------------------------------------------------------------------------


async def dispatch_chat_to_orchestrator(
    message: str,
    credential: Optional[DefaultAzureCredential] = None,
    conversation_id: Optional[str] = None,
) -> dict[str, str]:
    """Dispatch an operator chat message to the Orchestrator.

    If conversation_id (thread_id) is provided, continues the existing thread.
    Otherwise creates a new thread.

    Uses create_and_process_run for blocking execution — waits until the agent
    completes and returns the reply text.

    Returns:
        Dict with "thread_id", "run_id", "status", and "reply" keys.
    """
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")
    if not orchestrator_agent_id:
        raise ValueError("ORCHESTRATOR_AGENT_ID environment variable is required.")

    loop = asyncio.get_running_loop()
    agents = _get_agents_client(_get_foundry_project(credential))

    with foundry_span("agents_chat_dispatch") as span:
        # Get or create thread
        if conversation_id:
            thread_id = conversation_id
            logger.debug("dispatch_chat: continuing thread %s", thread_id)
        else:
            thread = await loop.run_in_executor(None, agents.create_thread)
            thread_id = thread.id
            logger.debug("dispatch_chat: created new thread %s", thread_id)

        # Post the user message
        await loop.run_in_executor(
            None,
            lambda: agents.create_message(
                thread_id=thread_id,
                role="user",
                content=message,
            ),
        )

        # Run to completion (blocking)
        run = await loop.run_in_executor(
            None,
            lambda: agents.create_and_process_run(
                thread_id=thread_id,
                agent_id=orchestrator_agent_id,
            ),
        )

        span.set_attribute("foundry.thread_id", thread_id)
        span.set_attribute("foundry.run_id", run.id)
        span.set_attribute("foundry.run_status", run.status)

    # Extract the latest assistant message as the reply
    reply: Optional[str] = None
    try:
        messages = await loop.run_in_executor(
            None,
            lambda: list(agents.list_messages(thread_id=thread_id)),
        )
        # Messages are newest-first; find the first assistant message
        for msg in messages:
            role = getattr(msg, "role", None)
            if role == "assistant":
                content = getattr(msg, "content", [])
                if isinstance(content, list):
                    for block in content:
                        text = getattr(block, "text", None)
                        if text:
                            reply = getattr(text, "value", None) or str(text)
                            break
                elif isinstance(content, str):
                    reply = content
                if reply:
                    break
    except Exception as exc:
        logger.warning("Could not extract reply from thread messages: %s", exc)

    logger.info(
        "Chat dispatched to Orchestrator (thread %s, run %s, status %s, reply_len %d)",
        thread_id,
        run.id,
        run.status,
        len(reply) if reply else 0,
    )

    return {
        "thread_id": thread_id,
        "run_id": run.id,
        "status": run.status,
        "reply": reply,
    }


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------


async def create_foundry_thread(payload: IncidentPayload) -> dict[str, str]:
    """Backward-compat alias for dispatch_to_orchestrator."""
    return await dispatch_to_orchestrator(payload)
