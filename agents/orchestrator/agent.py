"""Orchestrator Agent — incident classifier and domain router (AGENT-001, AGENT-002, TRIAGE-001).

The Orchestrator is the central dispatcher for all Azure infrastructure incidents.
It classifies incoming incidents by domain, routes to the correct specialist agent
via HandoffOrchestrator, and manages cross-domain escalations.

Requirements:
    AGENT-001: All routing via HandoffOrchestrator handoff mechanism.
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

import os
from typing import List, Optional

from agent_framework import AgentTarget, HandoffOrchestrator, ai_function

from agents.shared.auth import get_credential, get_foundry_client
from agents.shared.envelope import IncidentMessage, validate_envelope
from agents.shared.otel import setup_telemetry

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
- sre       → sre-agent      (cross-domain, SLA, reliability, incidents with no clear domain)

### Type A — Structured incident payloads
1. Use the `domain` field when present and unambiguous.
2. When `domain` is absent or ambiguous, call `classify_incident_domain` with
   `affected_resources`, `detection_rule`, and `kql_evidence`.
3. Hand off via HandoffOrchestrator with a typed envelope (AGENT-002).

### Type B — Conversational operator queries
For natural-language queries, determine the domain from the **topic** of the message:
- Mentions "arc", "arc-enabled", "hybrid", "arc server", "arc kubernetes",
  "connected cluster", "arc sql", "arc postgres" → **arc-agent**
- Mentions "vm", "virtual machine", "aks", "app service", "compute", "cpu", "disk" → **compute-agent**
- Mentions "network", "vnet", "nsg", "load balancer", "dns", "expressroute" → **network-agent**
- Mentions "storage", "blob", "file share", "datalake" → **storage-agent**
- Mentions "defender", "key vault", "keyvault", "rbac", "security", "identity" → **security-agent**
- Topic is ambiguous or spans multiple domains → **sre-agent**

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
        # For conversational queries the API gateway passes the raw user message
        # as detection_rule. Scan it for domain keywords before falling back to sre.
        rule_lower = detection_rule.lower()
        if any(k in rule_lower for k in ("arc", "arc-enabled", "arc enabled", "hybrid", "hybridcompute",
                                          "arc server", "arc kubernetes", "connected cluster",
                                          "arc sql", "arc postgres")):
            return {"domain": "arc", "confidence": "medium",
                    "reason": "No affected_resources; arc keyword found in query text."}
        if any(k in rule_lower for k in ("vm", "virtual machine", "compute", "cpu", "disk",
                                          "aks", "app service", "function app", "container")):
            return {"domain": "compute", "confidence": "medium",
                    "reason": "No affected_resources; compute keyword found in query text."}
        if any(k in rule_lower for k in ("network", "vnet", "nsg", "subnet", "load balancer",
                                          "dns", "expressroute", "vpn", "firewall", "cdn")):
            return {"domain": "network", "confidence": "medium",
                    "reason": "No affected_resources; network keyword found in query text."}
        if any(k in rule_lower for k in ("storage", "blob", "file share", "datalake", "adls")):
            return {"domain": "storage", "confidence": "medium",
                    "reason": "No affected_resources; storage keyword found in query text."}
        if any(k in rule_lower for k in ("defender", "keyvault", "key vault", "rbac",
                                          "security", "identity", "credential")):
            return {"domain": "security", "confidence": "medium",
                    "reason": "No affected_resources; security keyword found in query text."}
        return {
            "domain": "sre",
            "confidence": "low",
            "reason": "No affected_resources and no domain keyword found; defaulting to SRE.",
        }

    domain_votes: dict = {}
    for resource_id in affected_resources:
        lower = resource_id.lower()
        for prefix, domain in RESOURCE_TYPE_TO_DOMAIN.items():
            if f"/{prefix}/" in lower or lower.startswith(prefix):
                domain_votes[domain] = domain_votes.get(domain, 0) + 1
                break

    if not domain_votes:
        # Fall back to detection rule keyword matching
        rule_lower = detection_rule.lower()
        if any(k in rule_lower for k in ("vm", "cpu", "disk", "compute", "app", "aks")):
            return {"domain": "compute", "confidence": "medium", "reason": "Detection rule keyword match."}
        if any(k in rule_lower for k in ("nsg", "vnet", "network", "lb", "dns", "bgp", "expressroute")):
            return {"domain": "network", "confidence": "medium", "reason": "Detection rule keyword match."}
        if any(k in rule_lower for k in ("storage", "blob", "datalake", "throttl")):
            return {"domain": "storage", "confidence": "medium", "reason": "Detection rule keyword match."}
        if any(k in rule_lower for k in ("defender", "keyvault", "rbac", "security", "identity")):
            return {"domain": "security", "confidence": "medium", "reason": "Detection rule keyword match."}
        if any(k in rule_lower for k in ("arc", "hybrid", "k8s", "kubernetes")):
            return {"domain": "arc", "confidence": "medium", "reason": "Detection rule keyword match."}
        return {
            "domain": "sre",
            "confidence": "low",
            "reason": "Unable to classify from resource types or detection rule; defaulting to SRE.",
        }

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


def create_orchestrator() -> HandoffOrchestrator:
    """Create and configure the HandoffOrchestrator instance.

    Registers all 6 domain agent targets with their Foundry agent IDs
    sourced from environment variables set by the Terraform agent-apps module.

    Returns:
        Configured HandoffOrchestrator ready to accept incident messages.
    """
    client = get_foundry_client()

    orchestrator = HandoffOrchestrator(
        name="orchestrator-agent",
        description="Central incident dispatcher — classifies and routes to domain agents.",
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        client=client,
        tools=[classify_incident_domain],
    )

    # Register all 6 domain agent targets (AGENT-001)
    orchestrator.add_target(
        AgentTarget(
            name=DOMAIN_AGENT_MAP["compute"],
            agent_id=os.environ.get("COMPUTE_AGENT_ID", ""),
            description="Azure compute domain specialist (VMs, VMSS, AKS, App Service).",
        )
    )
    orchestrator.add_target(
        AgentTarget(
            name=DOMAIN_AGENT_MAP["network"],
            agent_id=os.environ.get("NETWORK_AGENT_ID", ""),
            description="Azure network domain specialist (VNets, NSGs, load balancers, DNS).",
        )
    )
    orchestrator.add_target(
        AgentTarget(
            name=DOMAIN_AGENT_MAP["storage"],
            agent_id=os.environ.get("STORAGE_AGENT_ID", ""),
            description="Azure storage domain specialist (Blob, Files, ADLS Gen2, managed disks).",
        )
    )
    orchestrator.add_target(
        AgentTarget(
            name=DOMAIN_AGENT_MAP["security"],
            agent_id=os.environ.get("SECURITY_AGENT_ID", ""),
            description="Azure security domain specialist (Defender, Key Vault, RBAC drift).",
        )
    )
    orchestrator.add_target(
        AgentTarget(
            name=DOMAIN_AGENT_MAP["sre"],
            agent_id=os.environ.get("SRE_AGENT_ID", ""),
            description="SRE generalist — cross-domain monitoring, SLA tracking, and incident fallback.",
        )
    )
    orchestrator.add_target(
        AgentTarget(
            name=DOMAIN_AGENT_MAP["arc"],
            agent_id=os.environ.get("ARC_AGENT_ID", ""),
            description="Azure Arc domain specialist (Arc-enabled servers, Arc Kubernetes, Arc data services).",
        )
    )

    return orchestrator


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    orchestrator = create_orchestrator()
    orchestrator.serve()
