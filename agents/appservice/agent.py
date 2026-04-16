"""App Service Agent — Web Apps, App Service Plans, and Function Apps diagnostics.

Surfaces health, performance, and execution diagnostics across Azure App Service
and Azure Functions workloads, including HITL-gated restart and scale proposals.

Requirements:
    TRIAGE-002: Must query Azure Monitor metrics AND diagnostic logs before producing diagnosis.
    TRIAGE-004: Must include confidence score (0.0–1.0) in every diagnosis.
    REMEDI-001: Must NOT execute any remediation without explicit human approval.

RBAC scope: Reader + Monitoring Reader across all subscriptions (enforced by Terraform).
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

from appservice.tools import (
    ALLOWED_MCP_TOOLS,
    get_app_service_health,
    get_app_service_metrics,
    get_function_app_health,
    propose_app_service_restart,
    propose_function_app_scale_out,
    query_app_insights_failures,
)

tracer = setup_telemetry("aiops-appservice-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

APPSERVICE_AGENT_SYSTEM_PROMPT = """You are the AAP App Service Agent, a specialist for Azure App Service
and Azure Functions infrastructure.

## Scope

You diagnose health, performance, and reliability issues across:
- **Azure App Service / Web Apps** — site health, plan SKU, SSL certificates, custom domains,
  HTTP metrics, response time, and error rate analysis
- **Azure Function Apps** — runtime health, invocation count, failure rate, execution duration,
  throttling, and scale diagnostics

## Mandatory Triage Workflow (TRIAGE-002, TRIAGE-004)

**For every App Service or Function App incident, follow this workflow in order:**

### Web App / App Service incidents

1. **Site health first:** Call `get_app_service_health` — state, plan, SKU, SSL cert expiry,
   custom domains, worker count. Required before any metric queries.

2. **Performance metrics (TRIAGE-002):** Call `get_app_service_metrics` — requests/sec,
   avg response time ms, http5xx_rate_pct, cpu_percent, memory_percent.
   High http5xx_rate_pct (>1%) or cpu_percent (>80%) indicates resource pressure.

3. **Application Insights failures:** Call `query_app_insights_failures` — top exceptions
   and dependency failures to surface root cause at the application layer.

4. **Hypothesis with confidence (TRIAGE-004):** Combine ARM state, metrics, and App Insights
   data into a root-cause hypothesis. Include `confidence_score` (0.0–1.0).

5. **Restart proposal:** If the site is in a degraded state and a restart is warranted,
   call `propose_app_service_restart` with a clear justification.
   **MUST NOT execute — approval required (REMEDI-001).**

### Function App incidents

1. **Function App health first:** Call `get_function_app_health` — state, runtime version,
   function count, invocation count, failure rate, p95 duration, throttle count.

2. **Application Insights failures (TRIAGE-002):** Call `query_app_insights_failures` —
   top exceptions and dependency failures for the Function App name.

3. **Hypothesis with confidence (TRIAGE-004):** Combine ARM, metrics, and App Insights
   data into a root-cause hypothesis.

4. **Scale-out proposal:** If invocation throttling or high failure rate is confirmed,
   call `propose_function_app_scale_out` with target instances and justification.
   **MUST NOT execute — approval required (REMEDI-001).**

## Safety Constraints

- MUST NOT modify any Azure resource — Reader + Monitoring Reader roles only.
- MUST NOT execute any restart, scale, or configuration change — proposals only (REMEDI-001).
  All proposals require explicit human approval before any action is taken.
- MUST NOT use wildcard tool permissions.
- MUST include confidence score (0.0–1.0) in every diagnosis (TRIAGE-004).
- MUST query both Azure Monitor metrics AND App Insights logs before finalising diagnosis (TRIAGE-002).
- RBAC scope: Reader + Monitoring Reader across all subscriptions.

## Allowed Tools

{allowed_tools}
""".format(
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS
        + [
            "get_app_service_health",
            "get_app_service_metrics",
            "get_function_app_health",
            "query_app_insights_failures",
            "propose_app_service_restart",
            "propose_function_app_scale_out",
        ]
    )
)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_appservice_agent() -> ChatAgent:
    """Create and configure the App Service ChatAgent instance.

    Returns:
        ChatAgent configured with App Service tools and system prompt.
    """
    logger.info("create_appservice_agent: initialising Foundry client")
    client = get_foundry_client()

    agent = ChatAgent(
        name="appservice-agent",
        description=(
            "App Service specialist — Web Apps, App Service Plans, and Function Apps "
            "health, performance, and execution diagnostics."
        ),
        instructions=APPSERVICE_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            get_app_service_health,
            get_app_service_metrics,
            get_function_app_health,
            query_app_insights_failures,
            propose_app_service_restart,
            propose_function_app_scale_out,
        ],
    )
    logger.info("create_appservice_agent: ChatAgent created successfully")
    return agent


def create_appservice_agent_version(project: "AIProjectClient") -> object:
    """Register the App Service Agent as a versioned PromptAgentDefinition in Foundry.

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
        agent_name="aap-appservice-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=APPSERVICE_AGENT_SYSTEM_PROMPT,
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("appservice")
    _logger.info("appservice: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("appservice: creating agent and binding to agentserver")
    from_agent_framework(create_appservice_agent()).run()
    _logger.info("appservice: agentserver exited")
