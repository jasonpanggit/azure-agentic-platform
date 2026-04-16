"""Foundry Agent Service dispatch — Orchestrator invocation.

Chat path: AIProjectClient.get_openai_client() at ACCOUNT level endpoint
  → openai.responses.create() with agent_reference by name.
  The project-scoped endpoint (/api/projects/...) returns 500 on responses.create;
  the account-level endpoint (cognitiveservices.azure.com) works correctly.

Incident dispatch path: AzureAgentsClient.create_thread_and_run() (threads/runs API).
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
    """Get an OpenAI client pointed at the account-level endpoint for Responses API.

    IMPORTANT: The project-scoped endpoint (services.ai.azure.com/api/projects/...)
    returns HTTP 500 on every responses.create() call — this is a known Foundry
    Preview bug. The account-level endpoint (cognitiveservices.azure.com) works.

    We build the client directly using openai.AzureOpenAI with the account endpoint
    rather than AIProjectClient.get_openai_client() which uses the broken project URL.
    """
    try:
        from openai import AzureOpenAI
    except ImportError:
        raise ImportError("openai>=1.0.0 required. Install with: pip install openai")

    account_endpoint = os.environ.get("FOUNDRY_ACCOUNT_ENDPOINT")
    if not account_endpoint:
        # Derive account endpoint from project endpoint
        # https://aap-foundry-prod.services.ai.azure.com/api/projects/... →
        # https://aap-foundry-prod.cognitiveservices.azure.com/
        project_endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT", "")
        # Extract account name from services.ai.azure.com hostname
        import re
        m = re.match(r"https://([^.]+)\.services\.ai\.azure\.com", project_endpoint)
        if m:
            account_name = m.group(1)
            account_endpoint = f"https://{account_name}.cognitiveservices.azure.com/"
        else:
            raise ValueError(
                "FOUNDRY_ACCOUNT_ENDPOINT env var required for Responses API. "
                "Set to https://<account>.cognitiveservices.azure.com/"
            )

    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default").token

    return AzureOpenAI(
        azure_endpoint=account_endpoint,
        api_version="2025-03-01-preview",
        azure_ad_token=token,
    )


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
    """Dispatch an operator chat message via chat.completions two-hop fallback.

    The Foundry Agent Service (both threads/runs and responses APIs) is non-functional
    on this project due to a broken capability host. Fallback: use chat.completions
    directly with each agent's system prompt.

    Two-hop flow:
    1. Orchestrator (chat.completions) → determines domain + routes query
    2. Domain agent (chat.completions) → executes the query and returns reply

    Args:
        message: The operator's chat message.
        credential: Optional Azure credential.
        conversation_id: Ignored in fallback mode (no thread state).

    Returns:
        Dict with "response_id", "thread_id", "run_id", "status", and "reply" keys.
    """
    import uuid

    loop = asyncio.get_running_loop()
    project = _get_foundry_project(credential)
    openai_client = project.get_openai_client()

    # Load all agent definitions once
    def _get_agent_instructions(name: str) -> tuple[str, str]:
        """Return (model, instructions) for named agent."""
        try:
            versions = list(project.agents.list_versions(name))
            if versions:
                d = versions[0].as_dict() if hasattr(versions[0], "as_dict") else dict(versions[0])
                defn = d.get("definition", {})
                return defn.get("model", "gpt-4.1"), defn.get("instructions", "")
        except Exception as exc:
            logger.warning("Could not load agent %s: %s", name, exc)
        return "gpt-4.1", ""

    # Step 1: Ask orchestrator which domain agent to call
    orch_model, orch_instructions = await loop.run_in_executor(
        None, _get_agent_instructions, "aap-orchestrator-agent"
    )

    # Routing prompt: ask orchestrator to identify the domain agent name only
    routing_system = (
        orch_instructions
        + "\n\nIMPORTANT: Respond with ONLY the agent tool name to call (e.g. 'compute_agent', "
        "'network_agent', 'storage_agent', 'security_agent', 'arc_agent', 'sre_agent', "
        "'patch_agent', 'eol_agent', 'database_agent', 'appservice_agent', "
        "'containerapps_agent', 'messaging_agent', 'finops_agent'). "
        "No explanation. Just the agent name."
    )

    with foundry_span("chat_completions_route") as span:
        span.set_attribute("agent.name", "aap-orchestrator-agent")
        route_resp = await loop.run_in_executor(
            None,
            lambda: openai_client.chat.completions.create(
                model=orch_model,
                messages=[
                    {"role": "system", "content": routing_system},
                    {"role": "user", "content": message},
                ],
                max_tokens=20,
                temperature=0,
            ),
        )

    domain_agent_tool = route_resp.choices[0].message.content.strip().lower()
    # Normalize: strip punctuation, extract agent name
    import re
    m = re.search(r"(compute|network|storage|security|arc|sre|patch|eol|database|appservice|containerapps|messaging|finops)_agent", domain_agent_tool)
    domain_agent_tool = m.group(0) if m else "sre_agent"
    domain_agent_name = f"aap-{domain_agent_tool.replace('_agent', '-agent')}"
    logger.info("Orchestrator routed to: %s (%s)", domain_agent_tool, domain_agent_name)
    span.set_attribute("foundry.routed_to", domain_agent_name)

    # Step 2: Call the domain agent with the original message
    domain_model, domain_instructions = await loop.run_in_executor(
        None, _get_agent_instructions, domain_agent_name
    )
    if not domain_instructions:
        domain_instructions = f"You are the {domain_agent_name}. Answer Azure infrastructure questions."

    with foundry_span("chat_completions_domain") as span2:
        span2.set_attribute("agent.name", domain_agent_name)
        domain_resp = await loop.run_in_executor(
            None,
            lambda: openai_client.chat.completions.create(
                model=domain_model,
                messages=[
                    {"role": "system", "content": domain_instructions},
                    {"role": "user", "content": message},
                ],
                max_tokens=1024,
            ),
        )

    reply = domain_resp.choices[0].message.content
    response_id = f"chat-{uuid.uuid4().hex[:16]}"

    logger.info(
        "Chat fallback complete (route=%s, reply_len=%d)",
        domain_agent_name,
        len(reply) if reply else 0,
    )

    return {
        "response_id": response_id,
        "thread_id": response_id,
        "run_id": response_id,
        "status": "completed",
        "reply": reply,
    }


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------


async def create_foundry_thread(payload: IncidentPayload) -> dict[str, str]:
    """Backward-compat alias for dispatch_to_orchestrator."""
    return await dispatch_to_orchestrator(payload)
