"""Foundry Responses API dispatch — Orchestrator invocation (Phase 29, 2.0.x migration).

Replaces the Phase 1-28 threads/runs pattern (AgentsClient) with the
Foundry Responses API. Each incident creates a single responses.create()
call with the Orchestrator agent reference.

Key change from 1.x:
- OLD: AgentsClient -> client.threads.create() -> client.runs.create()
- NEW: AIProjectClient -> project.get_openai_client() -> openai.responses.create()
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


# ---------------------------------------------------------------------------
# Backward-compat: _get_foundry_client returns AgentsClient
# Used by chat.py, vm_chat.py, approvals.py for thread/message/run ops
# ---------------------------------------------------------------------------


def _get_foundry_client(credential: Optional[DefaultAzureCredential] = None):
    """Create an AgentsClient using DefaultAzureCredential.

    Backward-compatible function preserved for chat.py, vm_chat.py,
    and approvals.py which use client.threads, client.messages,
    and client.runs sub-operation groups.

    For new incident dispatch, use dispatch_to_orchestrator() instead.
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
        # Foundry run-status calls can take >5s under load — use a generous
        # read timeout so the poll doesn't abort prematurely.
        connection_timeout=10,
        read_timeout=30,
    )


# ---------------------------------------------------------------------------
# Phase 29: AIProjectClient + Responses API
# ---------------------------------------------------------------------------


def _get_foundry_project(credential: Optional[DefaultAzureCredential] = None):
    """Create AIProjectClient using DefaultAzureCredential.

    Reads AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT for compatibility).
    """
    try:
        from azure.ai.projects import AIProjectClient
    except ImportError as exc:
        raise ImportError(
            "azure-ai-projects>=2.0.1 required. "
            "Install with: pip install 'azure-ai-projects>=2.0.1'"
        ) from exc

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


def _get_openai_client(project=None):
    """Get the OpenAI-compatible client from AIProjectClient for Responses API."""
    if project is None:
        project = _get_foundry_project()
    return project.get_openai_client()


def build_incident_message(payload: IncidentPayload) -> str:
    """Build the typed envelope message (AGENT-002) for the Orchestrator.

    Returns a JSON string with correlation_id, source_agent, message_type,
    and the full incident payload.
    """
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


async def dispatch_to_orchestrator(
    payload: IncidentPayload,
    credential: Optional[DefaultAzureCredential] = None,
) -> dict[str, str]:
    """Dispatch an incident to the Orchestrator via the Foundry Responses API.

    Replaces the Phase 1-28 threads/runs pattern. Creates a single
    responses.create() call — no thread or run lifecycle to manage.

    Args:
        payload: Validated incident payload.
        credential: Optional pre-initialized credential.

    Returns:
        Dict with "response_id" and "status" keys.
    """
    orchestrator_agent_name = os.environ.get(
        "ORCHESTRATOR_AGENT_NAME", "orchestrator-agent"
    )

    openai_client = _get_openai_client(_get_foundry_project(credential))
    message = build_incident_message(payload)

    with agent_span(
        "orchestrator", domain=payload.domain, correlation_id=payload.incident_id
    ):
        with foundry_span("responses_create") as span:
            response = openai_client.responses.create(
                input=message,
                extra_body={
                    "agent_reference": {
                        "name": orchestrator_agent_name,
                        "type": "agent_reference",
                    }
                },
            )
            span.set_attribute("foundry.response_id", response.id)
            span.set_attribute("incident.id", payload.incident_id)
            span.set_attribute("incident.domain", payload.domain)
            span.set_attribute("agent.name", orchestrator_agent_name)

    logger.info(
        "Dispatched incident %s to Orchestrator (response %s, status %s)",
        payload.incident_id,
        response.id,
        response.status,
    )

    return {"response_id": response.id, "status": response.status}


async def dispatch_chat_to_orchestrator(
    message: str,
    credential: Optional[DefaultAzureCredential] = None,
    conversation_id: Optional[str] = None,
) -> dict[str, str]:
    """Dispatch an operator chat message to the Orchestrator via the Responses API.

    Uses the same Responses API path as dispatch_to_orchestrator() but accepts
    a plain message string rather than a structured IncidentPayload.  The
    Responses API is synchronous — it blocks until the agent produces a reply,
    so the caller gets the final answer in one round trip with no polling.

    Args:
        message: The operator's chat message (plain text or JSON envelope).
        credential: Optional pre-initialized credential.
        conversation_id: Optional conversation/thread ID for continuity context.

    Returns:
        Dict with "response_id", "status", and "reply" keys.
        reply is the agent's text output, or None if the response was empty.
    """
    import asyncio as _asyncio

    orchestrator_agent_name = os.environ.get(
        "ORCHESTRATOR_AGENT_NAME", "orchestrator-agent"
    )

    project = _get_foundry_project(credential)
    openai_client = _get_openai_client(project)

    loop = _asyncio.get_running_loop()

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
            # output is a list of content blocks; find the first text value
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
        "status": response.status,
        "reply": reply,
    }


# ---------------------------------------------------------------------------
# Backward-compat alias — callers that import create_foundry_thread
# can be migrated incrementally
# ---------------------------------------------------------------------------


async def create_foundry_thread(payload: IncidentPayload) -> dict[str, str]:
    """Backward-compat alias for dispatch_to_orchestrator.

    The old 'thread_id' key is mapped to 'response_id' for callers
    that haven't yet been updated. Remove once all callers are updated.
    """
    result = await dispatch_to_orchestrator(payload)
    # Map to old key names for backward compatibility
    return {
        "thread_id": result["response_id"],  # callers that use thread_id
        "run_id": result["response_id"],
        **result,
    }
