"""Container Apps Agent — operational diagnostics for Azure Container Apps.

Surfaces health, performance, log analysis, and HITL-gated scale and revision
proposals for all Container Apps workloads including platform-internal agents.

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

from containerapps.tools import (
    ALLOWED_MCP_TOOLS,
    get_container_app_health,
    get_container_app_logs,
    get_container_app_metrics,
    list_container_apps,
    propose_container_app_revision_activate,
    propose_container_app_scale,
)

tracer = setup_telemetry("aiops-containerapps-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

CONTAINERAPPS_AGENT_SYSTEM_PROMPT = """You are the AAP Container Apps Agent, a specialist for Azure Container Apps
infrastructure — including the platform's own operational agents.

## Scope

You diagnose health, performance, and reliability issues across:
- **Azure Container Apps** — provisioning state, replica health, active revision,
  ingress configuration, CPU/memory metrics, console log analysis
- **Container Apps Environments** — managed environment connectivity and health
- **Platform self-monitoring** — the AAP agents themselves run as Container Apps;
  you can diagnose platform agent issues via the same toolset

## Mandatory Triage Workflow (TRIAGE-002, TRIAGE-004)

**For every Container Apps incident, follow this workflow in order:**

### Single-app incidents

1. **App health first:** Call `get_container_app_health` — provisioning state,
   replica count, active revision, ingress FQDN, managed environment ID.
   Required before any metric queries.

2. **Performance metrics (TRIAGE-002):** Call `get_container_app_metrics` —
   request_count, avg_response_time_ms, replica_count_avg, cpu_percent,
   memory_percent. High cpu_percent (>80%) or replica_count_avg near max_replicas
   indicates scale pressure.

3. **Log evidence (TRIAGE-002):** Call `get_container_app_logs` with severity="Error"
   to surface recent exceptions. Combine with metrics for root-cause analysis.

4. **Hypothesis with confidence (TRIAGE-004):** Combine ARM state, metrics, and log
   data into a root-cause hypothesis. Include `confidence_score` (0.0–1.0).

5. **Scale proposal:** If replica saturation is confirmed, call
   `propose_container_app_scale` with new min/max and justification.
   **MUST NOT execute — approval required (REMEDI-001).**

6. **Revision activation proposal:** If a recent deployment is causing errors and a
   prior revision is known-good, call `propose_container_app_revision_activate`.
   **MUST NOT execute — approval required (REMEDI-001).**

### Multi-app / overview requests

1. Call `list_container_apps` for the resource group to enumerate all apps.
2. Identify apps with non-running provisioning_state or missing active_revision_name.
3. Follow the single-app workflow for each degraded app.

## Safety Constraints

- MUST NOT modify any Azure resource — Reader + Monitoring Reader roles only.
- MUST NOT execute any scale, revision, or configuration change — proposals only (REMEDI-001).
  All proposals require explicit human approval before any action is taken.
- MUST NOT use wildcard tool permissions.
- MUST include confidence score (0.0–1.0) in every diagnosis (TRIAGE-004).
- MUST query both Azure Monitor metrics AND logs before finalising diagnosis (TRIAGE-002).
- RBAC scope: Reader + Monitoring Reader across all subscriptions.

## Allowed Tools

{allowed_tools}
""".format(
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS
        + [
            "list_container_apps",
            "get_container_app_health",
            "get_container_app_metrics",
            "get_container_app_logs",
            "propose_container_app_scale",
            "propose_container_app_revision_activate",
        ]
    )
)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_containerapps_agent() -> ChatAgent:
    """Create and configure the Container Apps ChatAgent instance.

    Returns:
        ChatAgent configured with Container Apps tools and system prompt.
    """
    logger.info("create_containerapps_agent: initialising Foundry client")
    client = get_foundry_client()

    agent = ChatAgent(
        name="containerapps-agent",
        description=(
            "Container Apps specialist — operational diagnostics, metrics, log analysis, "
            "and HITL-gated scale and revision proposals."
        ),
        instructions=CONTAINERAPPS_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            list_container_apps,
            get_container_app_health,
            get_container_app_metrics,
            get_container_app_logs,
            propose_container_app_scale,
            propose_container_app_revision_activate,
        ],
    )
    logger.info("create_containerapps_agent: ChatAgent created successfully")
    return agent


def create_containerapps_agent_version(project: "AIProjectClient") -> object:
    """Register the Container Apps Agent as a versioned PromptAgentDefinition in Foundry.

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
        agent_name="aap-containerapps-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=CONTAINERAPPS_AGENT_SYSTEM_PROMPT,
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("containerapps")
    _logger.info("containerapps: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("containerapps: creating agent and binding to agentserver")
    from_agent_framework(create_containerapps_agent()).run()
    _logger.info("containerapps: agentserver exited")
