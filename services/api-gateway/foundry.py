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
# Domain system prompts — used directly for chat.completions fallback.
# Foundry list_versions() does not reliably filter by name, so we maintain
# prompts locally to avoid cross-domain instruction contamination.
# ---------------------------------------------------------------------------

_DOMAIN_SYSTEM_PROMPTS: dict[str, str] = {
    "compute_agent": (
        "You are an Azure AIOps specialist for compute resources (Virtual Machines, VMSS, AKS, disks). "
        "Help operators understand VM health, CPU/memory metrics, activity logs, resource health, "
        "OS versions, and scale set status. Be concise and structured."
    ),
    "network_agent": (
        "You are an Azure AIOps specialist for networking (VNets, NSGs, load balancers, DNS, "
        "ExpressRoute, VPN, network peering, flow logs). Help operators diagnose connectivity issues, "
        "review NSG rules, and understand network topology. Be concise and structured."
    ),
    "storage_agent": (
        "You are an Azure AIOps specialist for storage (Blob, File Shares, Data Lake, ADLS, "
        "Storage Accounts, Managed Disks). Help operators check storage health, diagnose errors, "
        "review diagnostics, and understand usage patterns. Be concise and structured."
    ),
    "security_agent": (
        "You are an Azure AIOps specialist for security (Microsoft Defender, Key Vault, RBAC, "
        "security alerts, identity drift, Secure Score, policy compliance). Help operators understand "
        "security posture and investigate alerts. Be concise and structured."
    ),
    "database_agent": (
        "You are an Azure AIOps specialist for databases (Cosmos DB, PostgreSQL, Azure SQL, "
        "elastic pools, DTU/RU consumption). Help operators diagnose performance issues, check "
        "resource health, and review metrics. Be concise and structured."
    ),
    "messaging_agent": (
        "You are an Azure AIOps specialist for messaging (Service Bus, Event Hubs, queues, "
        "topics, dead-letter queues, consumer groups, throughput units). Help operators investigate "
        "message backlogs, errors, and throughput issues. Be concise and structured."
    ),
    "appservice_agent": (
        "You are an Azure AIOps specialist for App Service (Web Apps, Function Apps, App Service Plans). "
        "Help operators diagnose deployment issues, review logs, check health, and understand "
        "scaling behaviour. Be concise and structured."
    ),
    "containerapps_agent": (
        "You are an Azure AIOps specialist for Container Apps (managed environments, Container Apps, "
        "revisions, replicas). Help operators diagnose startup failures, scaling issues, and "
        "container health. Be concise and structured."
    ),
    "arc_agent": (
        "You are an Azure AIOps specialist for Azure Arc (Arc-enabled servers, Arc Kubernetes, "
        "Arc SQL Managed Instance, Arc PostgreSQL, connected clusters, hybrid machines). "
        "Help operators manage and diagnose hybrid infrastructure. Be concise and structured."
    ),
    "patch_agent": (
        "You are an Azure AIOps specialist for patch management (Azure Update Manager, patch "
        "compliance, missing patches, Windows/Linux updates, security patches). Help operators "
        "assess and remediate patching gaps. Be concise and structured."
    ),
    "eol_agent": (
        "You are an Azure AIOps specialist for end-of-life detection (outdated software, "
        "deprecated OS versions, software lifecycle, unsupported versions). Help operators "
        "identify EOL resources and plan upgrades. Be concise and structured."
    ),
    "finops_agent": (
        "You are an Azure AIOps specialist for FinOps and cloud cost management (cost breakdown, "
        "billing, budgets, idle resources, reserved instances, savings plans, rightsizing, burn rate). "
        "Help operators understand and optimise cloud spend. Be concise and structured."
    ),
    "sre_agent": (
        "You are an Azure AIOps SRE specialist for availability, reliability, and cross-domain "
        "correlation (service health, Advisor recommendations, change analysis, performance baselines). "
        "Help operators triage and investigate infrastructure incidents. Be concise and structured."
    ),
}


def _get_domain_instructions(domain_agent_tool: str) -> tuple[str, str]:
    """Return (model, instructions) for a domain agent tool name."""
    instructions = _DOMAIN_SYSTEM_PROMPTS.get(
        domain_agent_tool,
        f"You are an Azure AIOps specialist for the {domain_agent_tool.replace('_', ' ')} domain. "
        "Answer Azure infrastructure questions helpfully and concisely.",
    )
    return "gpt-4.1", instructions


def _classify_domain(message: str) -> str:
    """Fast keyword-based domain routing — mirrors the orchestrator's routing rules.

    Returns the domain agent tool name (e.g. 'compute_agent'). Falls back to
    'sre_agent' for ambiguous queries. Avoids a round-trip LLM call for routing.
    """
    import re
    msg = message.lower()

    # Arc (must check before generic "server" / "machine" terms)
    if re.search(r"arc[\s-]?enabled|arc[\s-]?server|arc[\s-]?kubernetes|arc[\s-]?sql|arc[\s-]?postgres|connected.cluster|hybrid.machine", msg):
        return "arc_agent"
    # Patch / update
    if re.search(r"\bpatch\b|patching|update.manager|patch.compliance|missing.patch|windows.update|security.patch|linux.update", msg):
        return "patch_agent"
    # EOL
    if re.search(r"end.of.life|\beol\b|outdated.software|software.lifecycle|unsupported.version|lifecycle.status|deprecated.version", msg):
        return "eol_agent"
    # Database
    if re.search(r"\bcosmos\b|cosmosdb|cosmos.db|\bpostgresql\b|\bpostgres\b|azure.sql|sql.database|\bdtu\b|elastic.pool|flexibleserver|request.unit|\bru/s\b", msg):
        return "database_agent"
    # App Service
    if re.search(r"app.service|web.app|function.app|azure.function|app.service.plan|\bwebapp\b|\bfunc.app\b", msg):
        return "appservice_agent"
    # Container Apps
    if re.search(r"container.app|containerapps|managed.environment|container.apps.environment", msg):
        return "containerapps_agent"
    # Messaging
    if re.search(r"service.bus|servicebus|\bqueue\b|dead.letter|\bdlq\b|\btopic\b|event.hub|eventhub|consumer.group|throughput.unit", msg):
        return "messaging_agent"
    # FinOps
    if re.search(r"\bcost\b|\bspend\b|\bbilling\b|finops|\bbudget\b|idle.resource|reserved.instance|\bri.utiliz|savings.plan|cost.breakdown|cloud.cost|rightsizing|burn.rate|overspend", msg):
        return "finops_agent"
    # Security
    if re.search(r"\bdefender\b|key.vault|keyvault|\brbac\b|security.alert|identity.drift|secure.score|policy.compliance", msg):
        return "security_agent"
    # Network
    if re.search(r"\bvnet\b|\bnsg\b|load.balancer|\bdns\b|expressroute|network.peering|flow.log|\bvpn\b", msg):
        return "network_agent"
    # Storage
    if re.search(r"\bblob\b|file.share|datalake|storage.account|adls|managed.disk", msg):
        return "storage_agent"
    # Compute (VMs — broad fallback for "show my virtual machines" etc.)
    if re.search(r"\bvm\b|virtual.machine|\baks\b|\bcpu\b|compute|\bdisk\b|\bvmss\b|scale.set", msg):
        return "compute_agent"
    # Default
    return "sre_agent"


# ---------------------------------------------------------------------------
# Conversation history — keyed by thread/response ID so multi-turn chat
# replays prior messages and maintains context across requests.
# Limited to 20 turns (user+assistant pairs) to cap token usage.
# ---------------------------------------------------------------------------

_CONVERSATION_HISTORY: dict[str, list[dict[str, str]]] = {}
_CONVERSATION_HISTORY_LIMIT = 20  # max turns (user+assistant pairs)


# ---------------------------------------------------------------------------
# Chat dispatch (operator → orchestrator, with thread continuity)
# ---------------------------------------------------------------------------


async def dispatch_chat_to_orchestrator(
    message: str,
    credential: Optional[DefaultAzureCredential] = None,
    conversation_id: Optional[str] = None,
) -> dict[str, str]:
    """Dispatch an operator chat message via Foundry Agent Service threads/runs.

    Primary path: create_thread_and_run → poll until completed → return reply.
    Thread continuation: if conversation_id is a known thread_id, creates a new
    message on that thread instead of a new thread (preserving agent context).

    Falls back to chat.completions if ORCHESTRATOR_AGENT_ID is not set (local dev).

    Returns:
        Dict with "response_id", "thread_id", "run_id", "status", and "reply" keys.
    """
    import time as _time

    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")

    # -------------------------------------------------------------------
    # Fallback: chat.completions (no ORCHESTRATOR_AGENT_ID, local dev)
    # -------------------------------------------------------------------
    if not orchestrator_agent_id:
        return await _dispatch_chat_completions_fallback(
            message=message,
            conversation_id=conversation_id,
        )

    # -------------------------------------------------------------------
    # Primary path: Foundry Agent Service threads/runs
    # -------------------------------------------------------------------
    loop = asyncio.get_running_loop()
    agents = _get_agents_client(credential)

    _POLL_INTERVAL = 3   # seconds between status checks
    _POLL_TIMEOUT  = 120 # seconds max wait

    with foundry_span("agents_chat_thread_run") as span:
        span.set_attribute("incident.id", conversation_id or "")

        # Thread continuation: add message to existing thread, then create run.
        # New conversation: create thread + run in one call.
        if conversation_id:
            span.set_attribute("foundry.thread_id", conversation_id)
            run = await loop.run_in_executor(
                None,
                lambda: (
                    agents.messages.create(
                        thread_id=conversation_id,
                        role="user",
                        content=message,
                    ),
                    agents.runs.create(
                        thread_id=conversation_id,
                        agent_id=orchestrator_agent_id,
                    ),
                )[1],
            )
            thread_id = conversation_id
        else:
            run = await loop.run_in_executor(
                None,
                lambda: agents.create_thread_and_run(
                    agent_id=orchestrator_agent_id,
                    thread={"messages": [{"role": "user", "content": message}]},
                ),
            )
            thread_id = run.thread_id

        span.set_attribute("foundry.run_id", run.id)

        # Poll until terminal state
        deadline = _time.monotonic() + _POLL_TIMEOUT
        while _time.monotonic() < deadline:
            run = await loop.run_in_executor(
                None,
                lambda: agents.runs.get(thread_id=thread_id, run_id=run.id),
            )
            status_str = str(run.status).lower().replace("runstatus.", "")
            if status_str == "completed":
                break
            if status_str in ("failed", "cancelled", "expired"):
                err = getattr(run, "last_error", None)
                raise RuntimeError(
                    f"Orchestrator run {run.id} {status_str}: {err}"
                )
            await asyncio.sleep(_POLL_INTERVAL)
        else:
            raise TimeoutError(
                f"Orchestrator run {run.id} did not complete within {_POLL_TIMEOUT}s"
            )

        # Retrieve the assistant reply (most recent assistant message)
        msgs = await loop.run_in_executor(
            None,
            lambda: list(agents.messages.list(thread_id=thread_id)),
        )

    reply: Optional[str] = None
    for m in msgs:
        role_str = str(getattr(m, "role", "")).lower().replace("messagerole.", "")
        if role_str in ("agent", "assistant"):
            for c in getattr(m, "content", []):
                text_block = getattr(c, "text", None)
                if text_block is not None:
                    reply = getattr(text_block, "value", None) or str(text_block)
                    break
            if reply:
                break

    logger.info(
        "Chat complete via threads/runs (thread=%s, run=%s, reply_len=%d)",
        thread_id, run.id, len(reply) if reply else 0,
    )

    return {
        "response_id": run.id,
        "thread_id": thread_id,
        "run_id": run.id,
        "status": "completed",
        "reply": reply,
    }


async def _dispatch_chat_completions_fallback(
    message: str,
    conversation_id: Optional[str] = None,
) -> dict[str, str]:
    """Fallback: chat.completions with local domain prompts (no agent tools).

    Used when ORCHESTRATOR_AGENT_ID is not set (local dev / CI without Foundry).
    """
    import uuid

    loop = asyncio.get_running_loop()

    # Extract plain user text from JSON envelope for routing + history
    user_text = message
    try:
        envelope = json.loads(message)
        if isinstance(envelope, dict) and "payload" in envelope:
            payload_msg = envelope["payload"].get("message", "")
            if payload_msg:
                user_text = payload_msg
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    domain_agent_tool = _classify_domain(user_text)
    domain_agent_name = f"aap-{domain_agent_tool.replace('_agent', '-agent')}"
    logger.info("Fallback keyword-routed to: %s (user_text=%r)", domain_agent_name, user_text[:80])

    domain_model, domain_instructions = _get_domain_instructions(domain_agent_tool)
    openai_client = _get_openai_client()

    prior_history = _CONVERSATION_HISTORY.get(conversation_id, []) if conversation_id else []
    messages: list[dict[str, str]] = [{"role": "system", "content": domain_instructions}]
    messages.extend(prior_history)
    messages.append({"role": "user", "content": message})

    with foundry_span("chat_completions_fallback") as span:
        span.set_attribute("agent.name", domain_agent_name)
        span.set_attribute("chat.history_turns", len(prior_history) // 2)
        domain_resp = await loop.run_in_executor(
            None,
            lambda: openai_client.chat.completions.create(
                model=domain_model,
                messages=messages,
                max_tokens=1024,
            ),
        )

    reply = domain_resp.choices[0].message.content
    response_id = f"chat-{uuid.uuid4().hex[:16]}"

    history_key = conversation_id or response_id
    history = list(_CONVERSATION_HISTORY.get(history_key, []))
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply or ""})
    max_messages = _CONVERSATION_HISTORY_LIMIT * 2
    if len(history) > max_messages:
        history = history[-max_messages:]
    _CONVERSATION_HISTORY[history_key] = history

    return {
        "response_id": response_id,
        "thread_id": history_key,
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
