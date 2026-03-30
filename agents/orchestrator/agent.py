"""Orchestrator Agent — incident classifier and domain router (AGENT-001, AGENT-002, TRIAGE-001).

The Orchestrator is the central dispatcher for all Azure infrastructure incidents.
It classifies incoming incidents by domain and routes to the correct specialist agent
via the Foundry thread mechanism. Domain agents are invoked as separate Foundry-hosted
agents (each running in their own Container App) — routing happens by the api-gateway
reading the orchestrator's classification result and dispatching to the appropriate
domain agent endpoint.

Requirements:
    AGENT-001: All routing via Foundry handoff mechanism (orchestrator outputs target domain;
               api-gateway dispatches to domain agent Container App).
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

from typing import List, Optional

from agent_framework import Agent, tool

from shared.auth import get_foundry_client
from shared.envelope import IncidentMessage, validate_envelope
from shared.otel import setup_telemetry
from shared.routing import classify_query_text

# Telemetry tracer for the orchestrator service
tracer = setup_telemetry("aiops-orchestrator-agent")

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

### Domain → agent mapping
- compute   → compute-agent  (VMs, VMSS, AKS, App Service, disks)
- network   → network-agent  (VNets, NSGs, load balancers, DNS, ExpressRoute)
- storage   → storage-agent  (Blob, Files, ADLS Gen2, managed disks)
- security  → security-agent (Defender, Key Vault, RBAC drift, identity)
- arc       → arc-agent      (Arc-enabled servers, Arc Kubernetes, Arc data services)
- patch     → patch-agent    (Azure Update Manager, patch compliance, missing patches, KB articles, reboot-pending)
- sre       → sre-agent      (cross-domain, SLA, reliability, incidents with no clear domain)

### Type A — Structured incident payloads
1. Use the `domain` field when present and unambiguous.
2. When `domain` is absent or ambiguous, call `classify_incident_domain` with
   `affected_resources`, `detection_rule`, and `kql_evidence`.
3. Hand off with a typed envelope (AGENT-002).

### Type B — Conversational operator queries
Conversational queries may arrive either as raw natural language or as a JSON
`operator_query` envelope from the API gateway.

When the input is an `operator_query` envelope:
- Read the operator question from `payload.message`
- Treat `payload.domain_hint` as the primary routing signal when present
- Preserve `payload.message` verbatim when handing off to the target domain agent
- Preserve `payload.subscription_ids` as query scope context

For natural-language queries, determine the domain from the **topic** of the message:
- Mentions "arc", "arc-enabled", "hybrid", "arc server", "arc enabled servers",
    "connected cluster", "arc sql", "arc postgres" → **arc-agent**
- Mentions "vm", "virtual machine", "aks", "app service", "compute", "cpu", "disk" → **compute-agent**
- Mentions "network", "vnet", "nsg", "load balancer", "dns", "expressroute" → **network-agent**
- Mentions "storage", "blob", "file share", "datalake" → **storage-agent**
- Mentions "defender", "key vault", "keyvault", "rbac", "security", "identity" → **security-agent**
- Mentions "patch", "patching", "update manager", "windows update", "missing patches",
    "patch compliance", "patch status", "kb article", "hotfix" → **patch-agent**
- Topic is ambiguous or spans multiple domains → **sre-agent**

Important disambiguation rule:
- "Arc-enabled servers" and "Arc servers" are Azure Arc resources, not Azure IaaS virtual machines.
    Route those queries to **arc-agent**, even if the message also contains words like
    "servers", "machines", or "show/list my".

Do NOT attempt to answer the query yourself. Route it immediately.
Pass the operator's original question verbatim as the handoff payload so the domain agent can execute it.

---

## Strict Constraints

- MUST NOT query Azure resources directly — all queries are delegated to domain agents.
- MUST NOT answer operator queries from your own knowledge — always route.
- MUST NOT propose or execute remediation actions of any kind.
- MUST preserve `correlation_id` through all messages (AUDIT-001).
- Tool allowlist: `foundry.create_message`, `foundry.list_messages`, `classify_incident_domain`.
"""

# ---------------------------------------------------------------------------
# Domain → agent name mapping (AGENT-001)
# ---------------------------------------------------------------------------

DOMAIN_AGENT_MAP: dict = {
    "compute": "compute-agent",
    "network": "network-agent",
    "storage": "storage-agent",
    "security": "security-agent",
    "sre": "sre-agent",
    "arc": "arc-agent",
    "patch": "patch-agent",
}

# ---------------------------------------------------------------------------
# Resource type → domain classification map (TRIAGE-001)
# ---------------------------------------------------------------------------

RESOURCE_TYPE_TO_DOMAIN: dict = {
    "microsoft.compute": "compute",
    "microsoft.containerservice": "compute",
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
}


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


@tool
def classify_incident_domain(
    affected_resources: List[str],
    detection_rule: str,
    kql_evidence: Optional[str] = None,
) -> dict:
    """Classify an incident's domain by inspecting affected resource types.

    Used when the incident payload does not contain an unambiguous `domain`
    field (TRIAGE-001). Examines resource type prefixes from resource IDs
    and maps them to compute / network / storage / security / arc / patch / sre.

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
        return classify_query_text(detection_rule)

    top_domain = max(domain_votes, key=lambda d: domain_votes[d])
    total_votes = sum(domain_votes.values())
    top_votes = domain_votes[top_domain]
    confidence = "high" if top_votes == total_votes else ("medium" if top_votes / total_votes >= 0.5 else "low")

    return {
        "domain": top_domain,
        "confidence": confidence,
        "reason": (
            f"Resource type analysis: {top_votes}/{total_votes} resources "
            f"classified as '{top_domain}'."
        ),
    }


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_orchestrator() -> Agent:
    """Create and configure the Orchestrator Agent instance.

    Returns an Agent that classifies incidents and outputs routing decisions.
    Domain agents are invoked as separate Foundry-hosted agents (each running
    in their own Container App). The api-gateway reads the orchestrator's
    classification output and dispatches to the appropriate domain agent
    endpoint — routing is NOT performed by the orchestrator directly (AGENT-001).

    Environment variables (set by Terraform agent-apps module):
        COMPUTE_AGENT_ID, NETWORK_AGENT_ID, STORAGE_AGENT_ID,
        SECURITY_AGENT_ID, SRE_AGENT_ID, ARC_AGENT_ID, PATCH_AGENT_ID

    Returns:
        Agent configured with classify_incident_domain tool and routing
        instructions.
    """
    client = get_foundry_client()

    return Agent(
        client,
        ORCHESTRATOR_SYSTEM_PROMPT,
        name="orchestrator-agent",
        description="Central incident dispatcher — classifies and routes to domain agents.",
        tools=[classify_incident_domain],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from azure.ai.agentserver.agentframework import from_agent_framework
    from_agent_framework(create_orchestrator()).run()
