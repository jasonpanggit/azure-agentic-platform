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

try:
    from azure.ai.agents import AgentsClient as AzureAgentsClient
except ImportError:
    AzureAgentsClient = None  # type: ignore[assignment,misc]

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


def _get_agents_client(credential: Optional[DefaultAzureCredential] = None):
    """Return an azure.ai.agents.AgentsClient for thread/message/run operations.

    azure-ai-projects 2.0.1 changed AIProjectClient.agents to only handle
    agent CRUD (list/create/delete agents). Thread, message, and run operations
    now live in the separate azure-ai-agents package's AgentsClient, which
    exposes .threads, .messages, .runs sub-clients.
    """
    if AzureAgentsClient is None:
        raise ImportError(
            "azure-ai-agents>=1.1.0 required. "
            "Install with: pip install 'azure-ai-agents>=1.1.0'"
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

    return AzureAgentsClient(endpoint=endpoint, credential=credential)


def _get_openai_client(project=None):
    """Get the OpenAI-compatible client from AIProjectClient for Responses API.

    The Responses API (openai_client.responses.create) is the only path that
    works reliably when the Foundry Agent Service threads/runs backend has
    a broken capability host (ServiceInvocationException on every threads call).
    """
    if project is None:
        project = _get_foundry_project()
    return project.get_openai_client()


def _get_foundry_client(credential: Optional[DefaultAzureCredential] = None):
    """Return an azure.ai.agents.AgentsClient for thread/message/run operations.

    Callers use client.threads.create(), client.messages.create(),
    client.runs.create_and_process(), client.messages.list(), etc.
    """
    return _get_agents_client(credential)


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
    agents = _get_agents_client(credential)
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
    """Dispatch an operator chat message to the Orchestrator via the Responses API.

    Uses the Responses API (openai_client.responses.create) — the only path
    that works when the Foundry Agent Service threads/runs backend returns
    ServiceInvocationException (broken capability host state after re-provisioning).

    The Responses API is synchronous — it blocks until the agent produces a reply,
    so the caller gets the final answer in one round trip with no polling.

    Args:
        message: The operator's chat message (plain text or JSON envelope).
        credential: Optional pre-initialized credential.
        conversation_id: Optional conversation/thread ID for continuity context.

    Returns:
        Dict with "response_id", "thread_id", "run_id", "status", and "reply" keys.
        reply is the agent's text output, or None if the response was empty.
    """
    orchestrator_agent_name = os.environ.get(
        "ORCHESTRATOR_AGENT_NAME", "aap-orchestrator-agent"
    )

    project = _get_foundry_project(credential)
    openai_client = _get_openai_client(project)

    loop = asyncio.get_running_loop()

    def _call_responses():
        kwargs: dict = {
            "input": message,
            "extra_body": {
                "agent_reference": {
                    "name": orchestrator_agent_name,
                    "type": "agent_reference",
                }
            },
        }
        if conversation_id:
            kwargs["extra_body"]["conversation_id"] = conversation_id
        return openai_client.responses.create(**kwargs)

    with foundry_span("responses_create_chat") as span:
        response = await loop.run_in_executor(None, _call_responses)
        span.set_attribute("foundry.response_id", response.id)
        span.set_attribute("agent.name", orchestrator_agent_name)

    # Extract text reply from response output
    reply: Optional[str] = None
    try:
        output = response.output
        if output:
            for block in output:
                if hasattr(block, "content"):
                    for item in block.content:
                        if hasattr(item, "text"):
                            reply = item.text
                            break
                elif hasattr(block, "text"):
                    reply = block.text
                    break
                elif isinstance(block, str):
                    reply = block
                    break
    except Exception as exc:
        logger.warning("Could not extract reply from response output: %s", exc)

    logger.info(
        "Chat dispatched to Orchestrator (response %s, status %s, reply_len %d)",
        response.id,
        response.status,
        len(reply) if reply else 0,
    )

    return {
        "response_id": response.id,
        "thread_id": response.id,  # backward-compat: callers expecting thread_id
        "run_id": response.id,     # backward-compat: callers expecting run_id
        "status": response.status,
        "reply": reply,
    }


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------


async def create_foundry_thread(payload: IncidentPayload) -> dict[str, str]:
    """Backward-compat alias for dispatch_to_orchestrator."""
    return await dispatch_to_orchestrator(payload)
