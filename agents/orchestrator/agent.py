"""Orchestrator Agent — incident classifier and domain router (AGENT-001, AGENT-002, TRIAGE-001).

The Orchestrator is the central dispatcher for all Azure infrastructure incidents.
It classifies incoming incidents by domain, routes to the correct specialist agent
via connected-agent tools, and manages cross-domain escalations.

Requirements:
    AGENT-001: All routing via connected-agent tools registered on the Foundry agent.
    AGENT-002: Typed JSON envelope (IncidentMessage) for all inter-agent messages.
    TRIAGE-001: Every incident MUST be classified before handoff.

Safety constraints:
    - MUST NOT query Azure resources directly.
    - MUST NOT propose or execute any remediation action.
    - MUST preserve correlation_id through all handoff messages (AUDIT-001).
    - MUST NOT skip classification for any incident.
    - MUST NOT use wildcard tool permissions.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from agent_framework import ChatAgent, ai_function

from shared.auth import get_foundry_client
from shared.envelope import IncidentMessage, validate_envelope
from shared.otel import setup_telemetry
from shared.routing import classify_query_text

try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import A2APreviewTool, PromptAgentDefinition
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]
    A2APreviewTool = None  # type: ignore[assignment,misc]
    PromptAgentDefinition = None  # type: ignore[assignment,misc]

# Telemetry tracer for the orchestrator service
tracer = setup_telemetry("aiops-orchestrator-agent")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

ORCHESTRATOR_SYSTEM_PROMPT = """You are the AAP Orchestrator Agent, the central dispatcher for the Azure AIOps platform.

You handle TWO types of input:
  A) Automated incident alerts from the detection plane (structured JSON payloads).
  B) Conversational operator queries typed in the web UI or Teams (natural language).

In BOTH cases you MUST route to a domain agent — you NEVER answer from your own knowledge.

---

## Routing Rules

### Domain → agent tool mapping
Call the matching connected-agent tool to route the query:
- compute   → `compute_agent`   (VMs, VMSS, AKS, App Service, disks)
- network   → `network_agent`   (VNets, NSGs, load balancers, DNS, ExpressRoute)
- storage   → `storage_agent`   (Blob, Files, ADLS Gen2, managed disks)
- security  → `security_agent`  (Defender, Key Vault, RBAC drift, identity)
- arc       → `arc_agent`       (Arc-enabled servers, Arc Kubernetes, Arc data services)
- patch     → `patch_agent`     (Update Manager, patch compliance, missing patches, Windows/Linux update)
- eol       → `eol_agent`       (End-of-life software, software lifecycle, unsupported versions, EOL dates, upgrade planning)
- database  → `database_agent`  (Cosmos DB, PostgreSQL Flexible Server, Azure SQL Database health and performance)
- app-service      → `appservice_agent`    (App Service plans, Web Apps, Function Apps health and diagnostics)
- container-apps  → `containerapps_agent` (Azure Container Apps, Container Apps Environments, platform agent self-monitoring)
- sre       → `sre_agent`       (cross-domain, SLA, reliability, incidents with no clear domain)

### Type A — Structured incident payloads
1. Use the `domain` field when present and unambiguous.
2. When `domain` is absent or ambiguous, call `classify_incident_domain` with
   `affected_resources`, `detection_rule`, and `kql_evidence`.
3. Call the matching domain agent tool with the incident details.

### Type B — Conversational operator queries
Conversational queries may arrive either as raw natural language or as a JSON
`operator_query` envelope from the API gateway.

When the input is an `operator_query` envelope:
- Read the operator question from `payload.message`
- Treat `payload.domain_hint` as the primary routing signal when present
- Preserve `payload.message` verbatim when calling the domain agent tool
- Preserve `payload.subscription_ids` as query scope context

For natural-language queries, determine the domain from the **topic** of the message:
- Mentions "arc", "arc-enabled", "hybrid", "arc server", "arc enabled servers",
    "connected cluster", "arc sql", "arc postgres" → call `arc_agent`
- Mentions "patch", "patching", "update manager", "patch compliance", "missing patches",
    "windows update", "security patch" → call `patch_agent`
- Mentions "end of life", "eol", "end-of-life", "outdated software", "software lifecycle",
    "unsupported version", "lifecycle status", "deprecated version" → call `eol_agent`
- Mentions "cosmos", "cosmosdb", "cosmos db", "postgresql", "postgres", "azure sql",
    "sql database", "rdbms", "throughput", "request units", "ru/s", "dtu",
    "elastic pool", "flexibleservers" → call `database_agent`
- Mentions "app service", "web app", "function app", "function apps", "app service plan",
    "site", "webapp", "azure functions", "func app" → call `appservice_agent`
- Mentions "container app", "container apps", "containerapps", "managed environment",
    "container apps environment", "ca-" agent, "platform agent" → call `containerapps_agent`
- Mentions "service bus", "servicebus", "queue", "dead letter", "dlq", "topic",
    "subscription", "event hub", "eventhub", "consumer group", "consumer lag",
    "messaging namespace", "throughput units" → call `messaging_agent`
- Mentions "vm", "virtual machine", "aks", "compute", "cpu", "disk" → call `compute_agent`
- Mentions "network", "vnet", "nsg", "load balancer", "dns", "expressroute" → call `network_agent`
- Mentions "storage", "blob", "file share", "datalake" → call `storage_agent`
- Mentions "defender", "key vault", "keyvault", "rbac", "security", "identity" → call `security_agent`
- Topic is ambiguous or spans multiple domains → call `sre_agent`

Container Apps disambiguation rule:
- "Container Apps" and "containerapps" are Azure Container Apps resources, NOT generic compute.
    Route those queries to `containerapps_agent`, even if the message contains words like
    "container", "replica", or "scale".

Important disambiguation rule:
- "Arc-enabled servers" and "Arc servers" are Azure Arc resources, not Azure IaaS virtual machines.
    Route those queries to `arc_agent`, even if the message also contains words like
    "servers", "machines", or "show/list my".

Do NOT attempt to answer the query yourself. Route it immediately by calling the appropriate agent tool.
Pass the operator's original question verbatim as the argument to the domain agent tool.

---

## Strict Constraints

- MUST NOT query Azure resources directly — all queries are delegated to domain agents.
- MUST NOT answer operator queries from your own knowledge — always route by calling a domain agent tool.
- MUST NOT propose or execute remediation actions of any kind.
- MUST preserve `correlation_id` through all messages (AUDIT-001).
- Tool allowlist: `compute_agent`, `network_agent`, `storage_agent`, `security_agent`,
    `arc_agent`, `sre_agent`, `patch_agent`, `eol_agent`, `database_agent`,
    `appservice_agent`, `containerapps_agent`, `messaging_agent`, `classify_incident_domain`.
"""

# ---------------------------------------------------------------------------
# Domain → agent tool name mapping (AGENT-001)
# Tool names use underscores to match Foundry connected-agent name pattern ^[a-zA-Z_]+$
# ---------------------------------------------------------------------------

DOMAIN_AGENT_MAP: dict = {
    "compute": "compute_agent",
    "network": "network_agent",
    "storage": "storage_agent",
    "security": "security_agent",
    "sre": "sre_agent",
    "arc": "arc_agent",
    "patch": "patch_agent",
    "eol": "eol_agent",
    "database": "database_agent",
    "app-service": "appservice_agent",
    "container-apps": "containerapps_agent",
    "messaging": "messaging_agent",
}

# ---------------------------------------------------------------------------
# Resource type → domain classification map (TRIAGE-001)
# ---------------------------------------------------------------------------

RESOURCE_TYPE_TO_DOMAIN: dict = {
    "microsoft.compute": "compute",
    "microsoft.containerservice": "compute",
    "microsoft.web/sites": "app-service",
    "microsoft.web/serverfarms": "app-service",
    "microsoft.web": "compute",
    "microsoft.network": "network",
    "microsoft.cdn": "network",
    "microsoft.storage": "storage",
    "microsoft.datalakestore": "storage",
    "microsoft.security": "security",
    "microsoft.keyvault": "security",
    "microsoft.hybridcompute": "arc",
    "microsoft.kubernetes": "arc",
    "microsoft.maintenance": "patch",
    "microsoft.lifecycle": "eol",
    "microsoft.documentdb": "database",
    "microsoft.dbforpostgresql": "database",
    "microsoft.sql": "database",
    "microsoft.app/containerapps": "container-apps",
    "microsoft.app/managedenvironments": "container-apps",
    "microsoft.servicebus": "messaging",
    "microsoft.eventhub": "messaging",
}


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


@ai_function
def classify_incident_domain(
    affected_resources: List[str],
    detection_rule: str,
    kql_evidence: Optional[str] = None,
) -> dict:
    """Classify an incident's domain by inspecting affected resource types.

    Used when the incident payload does not contain an unambiguous `domain`
    field (TRIAGE-001). Examines resource type prefixes from resource IDs
    and maps them to compute / network / storage / security / arc / sre.

    Args:
        affected_resources: List of Azure resource IDs from the incident payload.
        detection_rule: Alert detection rule name (used as a tiebreaker hint).
        kql_evidence: Optional KQL query excerpt for additional context.

    Returns:
        Dict with keys:
            domain (str): Classified domain name.
            confidence (str): "high" | "medium" | "low".
            reason (str): Short explanation of classification decision.
    """
    if not affected_resources:
        logger.info(
            "classify_incident_domain: no resources provided, falling back to rule keyword match | rule=%s",
            detection_rule,
        )
        return classify_query_text(detection_rule)

    domain_votes: dict = {}
    for resource_id in affected_resources:
        lower = resource_id.lower()
        for prefix, domain in RESOURCE_TYPE_TO_DOMAIN.items():
            if f"/{prefix}/" in lower or lower.startswith(prefix):
                domain_votes[domain] = domain_votes.get(domain, 0) + 1
                break

    if not domain_votes:
        # Fall back to detection rule keyword matching
        logger.info(
            "classify_incident_domain: no resource type match, falling back to rule keyword match | rule=%s resources=%s",
            detection_rule,
            affected_resources,
        )
        return classify_query_text(detection_rule)

    top_domain = max(domain_votes, key=lambda d: domain_votes[d])
    total_votes = sum(domain_votes.values())
    top_votes = domain_votes[top_domain]
    confidence = (
        "high"
        if top_votes == total_votes
        else ("medium" if top_votes / total_votes >= 0.5 else "low")
    )

    result = {
        "domain": top_domain,
        "confidence": confidence,
        "reason": (
            f"Resource type analysis: {top_votes}/{total_votes} resources "
            f"classified as '{top_domain}'."
        ),
    }
    logger.info(
        "classify_incident_domain: classified | domain=%s confidence=%s votes=%s rule=%s",
        top_domain,
        confidence,
        domain_votes,
        detection_rule,
    )
    return result


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_orchestrator() -> ChatAgent:
    """Create and configure the Orchestrator ChatAgent instance.

    The orchestrator is a single ChatAgent with a classify_incident_domain tool.
    Domain routing to specialist agents happens via connected-agent tools registered
    on the Foundry agent definition — domain agent IDs are wired at Foundry level.

    Returns:
        ChatAgent configured with the orchestrator system prompt and classification tool.
    """
    logger.info("create_orchestrator: initialising Foundry client")
    client = get_foundry_client()

    agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID", "<not set>")
    project_endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT", "<not set>")
    logger.info(
        "create_orchestrator: config | agent_id=%s project_endpoint=%s",
        agent_id,
        project_endpoint,
    )

    agent = ChatAgent(
        chat_client=client,
        instructions=ORCHESTRATOR_SYSTEM_PROMPT,
        name="orchestrator-agent",
        description="Central incident dispatcher — classifies and routes to domain agents.",
        tools=[classify_incident_domain],
    )
    logger.info("create_orchestrator: ChatAgent created successfully")
    return agent


# ---------------------------------------------------------------------------
# A2A Registration (Phase 29)
# ---------------------------------------------------------------------------

# Domain agents registered as A2A connections in Foundry
_A2A_DOMAINS = [
    "compute", "patch", "network", "security",
    "arc", "sre", "eol", "storage", "database", "appservice", "containerapps",
    "messaging",  # Phase 49
]


def create_orchestrator_agent_version(project: "AIProjectClient") -> object:
    """Register the Orchestrator as a versioned agent with A2A domain connections.

    Each domain agent is wired as an A2APreviewTool, making the full
    orchestrator -> domain topology visible in the Foundry portal.

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).

    Returns:
        AgentVersion for the orchestrator.
    """
    if A2APreviewTool is None or PromptAgentDefinition is None:
        raise ImportError(
            "azure-ai-projects>=2.0.1 required. "
            "Install with: pip install 'azure-ai-projects>=2.0.1'"
        )

    a2a_tools = []
    for domain in _A2A_DOMAINS:
        conn = project.connections.get(f"aap-{domain}-agent-connection")
        a2a_tools.append(A2APreviewTool(project_connection_id=conn.id))

    return project.agents.create_version(
        agent_name="aap-orchestrator",
        definition=PromptAgentDefinition(
            model=os.environ.get("ORCHESTRATOR_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=ORCHESTRATOR_SYSTEM_PROMPT,
            tools=a2a_tools,
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("orchestrator")
    _logger.info("orchestrator: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("orchestrator: creating agent and binding to agentserver")
    from_agent_framework(create_orchestrator()).run()
    _logger.info("orchestrator: agentserver exited")
