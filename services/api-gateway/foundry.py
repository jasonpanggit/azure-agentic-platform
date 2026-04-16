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
# Chat dispatch (operator → orchestrator, with thread continuity)
# ---------------------------------------------------------------------------


async def dispatch_chat_to_orchestrator(
    message: str,
    credential: Optional[DefaultAzureCredential] = None,
    conversation_id: Optional[str] = None,
) -> dict[str, str]:
    """Dispatch an operator chat message via single-hop chat.completions.

    The Foundry Agent Service (both threads/runs and responses APIs) is non-functional
    due to a broken capability host. Fallback: use chat.completions directly with
    the domain agent's system prompt.

    Fast path (single LLM call):
    1. Keyword classify the message → domain agent (no LLM routing call)
    2. Domain agent chat.completions → reply

    Agent instructions are cached after first fetch — subsequent requests skip
    the list_versions() API calls entirely.

    Returns:
        Dict with "response_id", "thread_id", "run_id", "status", and "reply" keys.
    """
    import uuid

    loop = asyncio.get_running_loop()

    # Fast keyword routing — no LLM call needed
    domain_agent_tool = _classify_domain(message)
    domain_agent_name = f"aap-{domain_agent_tool.replace('_agent', '-agent')}"
    logger.info("Keyword-routed to: %s", domain_agent_name)

    # Load domain-specific system prompt from local map — no Foundry API call needed.
    # list_versions() does not reliably filter by agent name and causes cross-domain
    # instruction contamination (e.g. storage prompt returned for compute queries).
    domain_model, domain_instructions = _get_domain_instructions(domain_agent_tool)

    # Use the account-level endpoint (cognitiveservices.azure.com) for chat.completions.
    # The project-scoped endpoint (services.ai.azure.com/api/projects/...) returns HTTP 500
    # on every responses.create() call — this is a known Foundry Preview issue.
    openai_client = _get_openai_client()

    with foundry_span("chat_completions_domain") as span:
        span.set_attribute("agent.name", domain_agent_name)
        span.set_attribute("foundry.routed_to", domain_agent_name)
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
        "Chat complete (agent=%s, reply_len=%d)",
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
