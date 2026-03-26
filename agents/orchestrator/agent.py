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

ORCHESTRATOR_SYSTEM_PROMPT = """You are the AAP Orchestrator Agent, the central dispatcher for Azure infrastructure incidents.

## Responsibilities

1. **Classify every incident** by domain before routing (TRIAGE-001).
   - Use the `domain` field from the incident payload when present and unambiguous.
   - When `domain` is absent or ambiguous, call `classify_incident_domain` with the
     `affected_resources`, `detection_rule`, and `kql_evidence` from the incident payload.

2. **Route to the correct domain agent** via HandoffOrchestrator handoff (AGENT-001):
   - compute   → compute-agent
   - network   → network-agent
   - storage   → storage-agent
   - security  → security-agent
   - arc       → arc-agent
   - sre       → sre-agent (fallback for unclassified or cross-domain incidents)

3. **Preserve the typed message envelope** (AGENT-002): every handoff message MUST
   include `correlation_id`, `thread_id`, `source_agent`, `target_agent`,
   `message_type: "incident_handoff"`.

4. **Handle cross-domain re-routing**: if a domain agent returns `needs_cross_domain: true`,
   extract `suspected_domain` and re-route with the original payload plus the domain
   agent's findings appended.

5. **Aggregate responses**: once all domain agents have replied, return a consolidated
   diagnosis response to the originating Foundry thread.

## Strict Constraints

- MUST NOT query Azure resources directly — all queries are delegated to domain agents.
- MUST NOT propose or execute remediation actions of any kind.
- MUST NOT skip the classification step — classify EVERY incident before handoff.
- MUST preserve `correlation_id` through all messages for end-to-end tracing (AUDIT-001).
- Tool allowlist: `foundry.create_message`, `foundry.list_messages`, `classify_incident_domain`.
  No other tools permitted.
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
        return {
            "domain": "sre",
            "confidence": "low",
            "reason": "No affected_resources provided; defaulting to SRE fallback.",
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
            description="Azure Arc domain specialist (stub in Phase 2; full capabilities in Phase 3).",
        )
    )

    return orchestrator


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    orchestrator = create_orchestrator()
    orchestrator.serve()
