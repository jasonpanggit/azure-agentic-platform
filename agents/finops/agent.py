"""FinOps Agent — Azure Cost Management operational diagnostics.

Surfaces subscription cost breakdown, per-resource cost analysis, idle resource
detection with HITL-gated VM deallocation proposals, reserved instance utilisation,
cost forecasting vs budget, and top cost driver ranking.

Requirements:
    TRIAGE-004: Must include confidence score (0.0–1.0) in every diagnosis.
    REMEDI-001: Must NOT execute any remediation without explicit human approval.
    FINOPS-001: Subscription cost breakdown by ResourceGroup, ResourceType, or ServiceName.
    FINOPS-002: Idle VM detection with HITL deallocation proposals + estimated monthly savings.
    FINOPS-003: Current-month forecast vs budget with burn rate flag at >110%.

RBAC scope: Cost Management Reader on subscription scope; Reader + Monitoring Reader for
idle resource detection (enforced by Terraform).
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

from finops.tools import (
    ALLOWED_MCP_TOOLS,
    get_cost_forecast,
    get_reserved_instance_utilisation,
    get_resource_cost,
    get_subscription_cost_breakdown,
    get_top_cost_drivers,
    identify_idle_resources,
)

tracer = setup_telemetry("aiops-finops-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

FINOPS_AGENT_SYSTEM_PROMPT = """You are the AAP FinOps Agent, a specialist for Azure cost optimisation and spend analysis.

## Scope

You surface actionable Azure cost insights across:
- **Subscription cost breakdown** — spend by ResourceGroup, ResourceType, or ServiceName
- **Top cost drivers** — ranked services by spend with trend context
- **Cost forecasting** — current-month spend vs budget, burn rate calculation and overage alerts
- **Idle resource detection** — VMs with CPU <2% AND network <1MB/s over 72h with estimated monthly savings
- **Reserved instance utilisation** — RI/savings plan benefit estimation via amortized-delta method
- **Per-resource cost drill-down** — AmortizedCost for a specific Azure resource
- **HITL-gated VM deallocation proposals** — propose VM deallocation after confirming idleness; never execute directly (REMEDI-001)

## Mandatory Workflow (FINOPS-001, FINOPS-002, FINOPS-003, TRIAGE-004)

**For every FinOps investigation, follow this workflow in order:**

1. **Spend overview (FINOPS-001):** Call `get_subscription_cost_breakdown` with `group_by="ResourceGroup"` (default) to establish current-period spend distribution. Use `group_by="ServiceName"` for service-level analysis.

2. **Top drivers:** Call `get_top_cost_drivers(subscription_id, n=10, days=30)` to identify the highest-cost services. This establishes the cost-saving priority order.

3. **Forecast vs budget (FINOPS-003):** Call `get_cost_forecast(subscription_id, budget_name)` to determine:
   - Current month-to-date spend
   - Projected month-end total
   - Burn rate as % of budget
   - **Alert if burn_rate_pct > 110%**

4. **Idle resources (FINOPS-002):** Call `identify_idle_resources(subscription_id)` to find VMs that are:
   - CPU < 2% average over 72h
   - Network < 1MB/s average over 72h
   Each idle VM result includes `estimated_monthly_savings_usd` and an `approval_id` for HITL deallocation.

5. **RI utilisation:** Call `get_reserved_instance_utilisation(subscription_id)` to estimate RI benefit consumed (amortized − actual cost delta). Note: uses subscription-scope approximation; no Billing Reader role required.

6. **Per-resource drill-down:** If the operator asks about a specific resource, call `get_resource_cost(subscription_id, resource_id, days=30)` for AmortizedCost (includes RI amortization).

7. **Hypothesis with confidence (TRIAGE-004):** Synthesise all findings into prioritised cost-saving recommendations with:
   - Total estimated savings potential (USD/month)
   - Confidence score (0.0–1.0) for each recommendation
   - Always include `data_lag_note` from cost query responses in your output

## Safety Constraints

- MUST NOT execute VM deallocation directly — always surface the `approval_id` from `identify_idle_resources` and direct operators to approve via the HITL workflow (REMEDI-001)
- MUST include `data_lag_note` ("Azure Cost Management data has a 24–48 hour reporting lag...") in ALL cost-related responses — present this clearly to operators
- MUST include `estimated_monthly_savings_usd` for every idle resource proposal — operators need the business case
- MUST NOT recommend RI purchasing — deferred (RI purchasing requires marketplace integration)
- MUST cap `identify_idle_resources` at 50 VMs per invocation (API throttling protection)
- MUST validate `group_by` is one of: ResourceGroup, ResourceType, ServiceName
- MUST include confidence_score (0.0–1.0) in every diagnosis (TRIAGE-004)
- Severity for cost proposals = LOW (no operational risk; VM deallocation is reversible)
- RI utilisation method: amortized-delta (subscription scope, no Billing Reader required)

## Allowed Tools

{allowed_tools}
""".format(
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS
        + [
            "get_subscription_cost_breakdown",
            "get_resource_cost",
            "identify_idle_resources",
            "get_reserved_instance_utilisation",
            "get_cost_forecast",
            "get_top_cost_drivers",
        ]
    )
)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_finops_agent() -> ChatAgent:
    """Create and configure the FinOps ChatAgent instance.

    Returns:
        ChatAgent configured with Cost Management tools and system prompt.
    """
    logger.info("create_finops_agent: initialising Foundry client")
    client = get_foundry_client()

    agent = ChatAgent(
        name="finops-agent",
        description=(
            "FinOps specialist — Azure cost breakdown, idle resource detection, "
            "RI utilisation, budget forecasting, and HITL-gated VM deallocation proposals."
        ),
        instructions=FINOPS_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            get_subscription_cost_breakdown,
            get_resource_cost,
            identify_idle_resources,
            get_reserved_instance_utilisation,
            get_cost_forecast,
            get_top_cost_drivers,
        ],
    )
    logger.info("create_finops_agent: ChatAgent created successfully")
    return agent


def create_finops_agent_version(project: "AIProjectClient") -> object:
    """Register the FinOps Agent as a versioned PromptAgentDefinition in Foundry.

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
        agent_name="aap-finops-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=FINOPS_AGENT_SYSTEM_PROMPT,
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("finops")
    _logger.info("finops: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("finops: creating agent and binding to agentserver")
    from_agent_framework(create_finops_agent()).run()
    _logger.info("finops: agentserver exited")
