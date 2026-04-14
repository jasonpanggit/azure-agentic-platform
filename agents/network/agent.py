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

import logging
import os

from agent_framework import ChatAgent

from shared.auth import get_foundry_client
from shared.otel import setup_telemetry

try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]
    PromptAgentDefinition = None  # type: ignore[assignment,misc]
from network.tools import (
    ALLOWED_MCP_TOOLS,
    check_connectivity,
    query_expressroute_health,
    query_flow_logs,
    query_load_balancer_health,
    query_nsg_rules,
    query_peering_status,
    query_vnet_topology,
)

tracer = setup_telemetry("aiops-network-agent")
logger = logging.getLogger(__name__)

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

1. **Activity Log first (TRIAGE-003):** Use the `monitor` MCP tool to query Activity Log for
   network-related changes in the prior 2 hours: NSG rule changes, route table updates,
   VPN gateway events, ExpressRoute BGP state changes. This is MANDATORY before any
   metric queries.

2. **Log Analytics (TRIAGE-002):** Use the `monitor` MCP tool to query NSG flow logs, DNS
   query failures, and load balancer health probe events. Diagnosis is INVALID without this signal.

3. **Resource Health (TRIAGE-002, MONITOR-003):** Use the `resourcehealth` MCP tool
   for affected network resources. Diagnosis is INVALID without this signal.

4. **NSG rule evaluation:** If an NSG rule change was detected in Step 1, call `query_nsg_rules`
   to evaluate effective security rules for affected resources.

5. **ExpressRoute health:** If ExpressRoute is involved, call `query_expressroute_health` to
   check circuit provisioning state and BGP peering health.

6. **Connectivity diagnosis:** For connectivity issues, call `check_connectivity` with Network
   Watcher to diagnose reachability between source and destination (hop-by-hop trace).

7. **Flow log configuration:** Call `query_flow_logs` to check NSG flow log configuration for
   affected Network Watcher — verify logging is enabled for forensics.

8. **Monitor metrics (MONITOR-001):** Use the `monitor` MCP tool for connection failures,
   dropped packets, bandwidth utilization, and gateway BGP routes over the incident window.

9. **Correlate and hypothesise (TRIAGE-004):** Combine all findings into a root-cause
   hypothesis with a confidence score between 0.0 and 1.0. Include:
   - `hypothesis`, `evidence`, `confidence_score`
   - `needs_cross_domain`: true if root cause is outside network domain
   - `suspected_domain`: domain to route to if needs_cross_domain is true

10. **Remediation proposal (REMEDI-001):** Include NSG rule delta, routing change, or DNS fix
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
    "query_flow_logs",
    "query_expressroute_health",
    "check_connectivity",
]))


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_network_agent() -> ChatAgent:
    """Create and configure the Network ChatAgent instance.

    Returns:
        ChatAgent configured with network-domain tools and system prompt.
    """
    logger.info("create_network_agent: initialising Foundry client")
    client = get_foundry_client()

    agent = ChatAgent(
        name="network-agent",
        description="Azure network domain specialist — VNets, NSGs, load balancers, DNS, ExpressRoute.",
        instructions=NETWORK_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            query_nsg_rules,
            query_load_balancer_health,
            query_vnet_topology,
            query_peering_status,
            query_flow_logs,
            query_expressroute_health,
            check_connectivity,
        ],
    )
    logger.info("create_network_agent: ChatAgent created successfully")
    return agent


def create_network_agent_version(project: "AIProjectClient") -> object:
    """Register the Network Agent as a versioned PromptAgentDefinition in Foundry.

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).

    Returns:
        AgentVersion object with version.id for environment variable storage.
    """
    if PromptAgentDefinition is None:
        raise ImportError(
            "azure-ai-projects>=2.0.1 required for create_version. "
            "Install with: pip install 'azure-ai-projects>=2.0.1'"
        )

    return project.agents.create_version(
        agent_name="aap-network-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=NETWORK_AGENT_SYSTEM_PROMPT,
            tools=[
                query_nsg_rules,
                query_load_balancer_health,
                query_vnet_topology,
                query_peering_status,
                query_flow_logs,
                query_expressroute_health,
                check_connectivity,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("network")
    _logger.info("network: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("network: creating agent and binding to agentserver")
    from_agent_framework(create_network_agent()).run()
    _logger.info("network: agentserver exited")
