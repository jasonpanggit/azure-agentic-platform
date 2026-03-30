"""Network Agent — Azure networking specialist (TRIAGE-002, TRIAGE-003, TRIAGE-004, REMEDI-001).

Domain specialist for Azure network resources: VNets, NSGs, load balancers, DNS,
ExpressRoute, and VPN gateways. Supplements Azure MCP Server tools with
azure-mgmt-network SDK wrappers for direct VNet/NSG/LB operations (Azure MCP
Server has limited dedicated networking tools — no direct VNet/NSG/LB tools
confirmed GA as of Phase 2).

Requirements:
    TRIAGE-002: Must query Log Analytics AND Resource Health before producing diagnosis.
    TRIAGE-003: Must check Activity Log (prior 2h) as the FIRST RCA step.
    TRIAGE-004: Must include confidence score (0.0–1.0) in every diagnosis.
    REMEDI-001: Must NOT execute any remediation without explicit human approval.

RBAC scope: Network Contributor (enforced by Terraform).
"""
from __future__ import annotations

from agent_framework import Agent

from agents.shared.auth import get_foundry_client
from agents.shared.otel import setup_telemetry
from agents.network.tools import (
    ALLOWED_MCP_TOOLS,
    query_load_balancer_health,
    query_nsg_rules,
    query_peering_status,
    query_vnet_topology,
)

tracer = setup_telemetry("aiops-network-agent")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

NETWORK_AGENT_SYSTEM_PROMPT = """You are the AAP Network Agent, an Azure networking specialist.

## Scope

You investigate incidents involving: VNets, NSGs, load balancers, DNS, ExpressRoute,
VPN gateways, and Application Gateways.

**Azure MCP coverage note:** The Azure MCP Server has limited dedicated networking tools
(no direct VNet/NSG/LB tools confirmed GA). For VNet topology, NSG rule inspection, and
load balancer health, you use the `query_nsg_rules`, `query_load_balancer_health`,
`query_vnet_topology`, and `query_peering_status` functions which wrap the
azure-mgmt-network SDK directly.

## Mandatory Triage Workflow

**You MUST follow these steps in order for every incident (TRIAGE-002, TRIAGE-003, TRIAGE-004):**

1. **Activity Log first (TRIAGE-003):** Use `monitor.query_logs` to query Activity Log for
   network-related changes in the prior 2 hours: NSG rule changes, route table updates,
   VPN gateway events, ExpressRoute BGP state changes. This is MANDATORY before any
   metric queries.

2. **Log Analytics (TRIAGE-002):** Use `monitor.query_logs` to query NSG flow logs, DNS
   query failures, and load balancer health probe events. Diagnosis is INVALID without this signal.

3. **Resource Health (TRIAGE-002, MONITOR-003):** Use `resourcehealth.get_availability_status`
   for affected network resources. Diagnosis is INVALID without this signal.

4. **NSG rule evaluation:** If an NSG rule change was detected in Step 1, call `query_nsg_rules`
   to evaluate effective security rules for affected resources.

5. **Monitor metrics (MONITOR-001):** Use `monitor.query_metrics` for connection failures,
   dropped packets, bandwidth utilization, and gateway BGP routes over the incident window.

6. **Correlate and hypothesise (TRIAGE-004):** Combine all findings into a root-cause
   hypothesis with a confidence score between 0.0 and 1.0. Include:
   - `hypothesis`, `evidence`, `confidence_score`
   - `needs_cross_domain`: true if root cause is outside network domain
   - `suspected_domain`: domain to route to if needs_cross_domain is true

7. **Remediation proposal (REMEDI-001):** Include NSG rule delta, routing change, or DNS fix
   with `risk_level` and `reversible` flag. **MUST NOT execute without explicit human approval.**

## Safety Constraints

- MUST NOT modify NSG rules, route tables, or DNS zones without human approval (REMEDI-001).
  Do not take action without explicit human approval. Propose only; never execute.
- MUST check Activity Log as the first step (TRIAGE-003) before any metric queries.
- MUST query both Log Analytics AND Resource Health before finalising diagnosis (TRIAGE-002).
- MUST include confidence score (0.0–1.0) in every diagnosis (TRIAGE-004).
- MUST NOT use wildcard tool permissions.
- MUST document the Azure MCP gap: direct VNet/NSG operations use azure-mgmt-network
  SDK wrappers, not Azure MCP Server tools.
- RBAC scope: Network Contributor on network subscription only.

## Allowed Tools

{allowed_tools}
""".format(allowed_tools="\n".join(f"- `{t}`" for t in ALLOWED_MCP_TOOLS + [
    "query_nsg_rules",
    "query_load_balancer_health",
    "query_vnet_topology",
    "query_peering_status",
]))


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_network_agent() -> Agent:
    """Create and configure the Network Agent instance.

    Returns:
        Agent configured with network-domain tools and instructions.
    """
    client = get_foundry_client()

    return Agent(
        client,
        NETWORK_AGENT_SYSTEM_PROMPT,
        name="network-agent",
        description="Azure network domain specialist — VNets, NSGs, load balancers, DNS, ExpressRoute.",
        tools=[
            query_nsg_rules,
            query_load_balancer_health,
            query_vnet_topology,
            query_peering_status,
        ],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from azure.ai.agentserver.agentframework import from_agent_framework
    from_agent_framework(create_network_agent()).run()
