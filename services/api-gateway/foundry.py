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

    return AgentsClient(endpoint=endpoint, credential=credential)


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
        "ORCHESTRATOR_AGENT_NAME", "aap-orchestrator"
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
