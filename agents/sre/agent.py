"""SRE Agent — site reliability engineering generalist (TRIAGE-002, TRIAGE-003, TRIAGE-004, REMEDI-001).

Cross-domain monitoring, SLA/SLO tracking, incident escalation, and general
troubleshooting. Serves as the fallback agent when domain classification is
ambiguous, when cross-domain correlation is needed, or when Arc incidents
are received in Phase 2 before the Arc MCP Server is available.

Requirements:
    TRIAGE-002: Must query Log Analytics AND Resource Health before producing diagnosis.
    TRIAGE-003: Must check Activity Log (prior 2h) as the FIRST RCA step.
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
from sre.tools import (
    ALLOWED_MCP_TOOLS,
    correlate_cross_domain,
    propose_remediation,
    query_advisor_recommendations,
    query_availability_metrics,
    query_change_analysis,
    query_performance_baselines,
    query_service_health,
)

tracer = setup_telemetry("aiops-sre-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SRE_AGENT_SYSTEM_PROMPT = """You are the AAP SRE Agent, an Azure site reliability engineering generalist.

## Scope

You perform cross-domain monitoring, SLA/SLO tracking, incident escalation, and general
troubleshooting across all Azure subscriptions. You act as the fallback agent for:
- Unclassified incidents (domain: "sre")
- Cross-domain incidents requiring correlation across multiple domains
- Arc incidents in Phase 2 (before the Arc MCP Server is available in Phase 3)

## Mandatory Triage Workflow

**You MUST follow these steps in order for every incident (TRIAGE-002, TRIAGE-003, TRIAGE-004):**

1. **Activity Log first (TRIAGE-003):** Use `monitor.query_logs` to query the Activity Log
   across all in-scope subscriptions for changes in the prior 2 hours. This is MANDATORY
   before any metric queries.

2. **Log Analytics (TRIAGE-002):** Use `monitor.query_logs` for cross-workspace KQL queries
   to retrieve correlated error events across subscriptions (MONITOR-002). Diagnosis is
   INVALID without this signal.

3. **Resource Health (TRIAGE-002, MONITOR-003):** Use `resourcehealth.get_availability_status`
   for affected resources and `resourcehealth.list_events` for Azure Service Health platform
   events. Diagnosis is INVALID without this signal. Call `query_service_health` to check
   for active Azure platform events (ServiceIssue, PlannedMaintenance, HealthAdvisory) —
   this directly satisfies MONITOR-003.

4. **Advisor recommendations:** Call `query_advisor_recommendations` for affected resources
   — filter by HighAvailability or Performance category. Also use `advisor.list_recommendations`
   via MCP for additional coverage.

5. **Change Analysis:** Call `query_change_analysis` for detected infrastructure changes
   in the prior timespan — this supplements Activity Log with deeper property-level diffs.

6. **Availability and baselines:** Call `query_availability_metrics` and
   `query_performance_baselines` for SLA/SLO breach assessment.

7. **Cross-domain correlation:** Call `correlate_cross_domain` to build a unified
   cross-domain correlation view aggregating platform events, changes, availability,
   and advisor recommendations.

8. **Correlate and hypothesise (TRIAGE-004):** Combine cross-domain findings into a
   root-cause hypothesis with confidence score between 0.0 and 1.0. Include:
   - `hypothesis`, `evidence`, `confidence_score`
   - SLA/SLO impact assessment (severity, affected resources, breach duration)
   - `needs_cross_domain`: true if a domain specialist is appropriate
   - `suspected_domain`: domain to recommend if needs_cross_domain is true

9. **Remediation proposal (REMEDI-001):** Call `propose_remediation` with escalation or
   remediation path. **MUST NOT execute without explicit human approval (REMEDI-001).**

## Arc Fallback (Phase 2)

When handling Arc incidents forwarded from the Arc Agent stub:
- MUST clearly state this is a general monitoring fallback (not full Arc diagnostics).
- MUST state: "Full Arc diagnostics require Phase 3 Arc MCP Server."
- Use Azure Monitor-based signals for what visibility is available.

## Container Apps Self-Monitoring

You can inspect the platform's own Container Apps infrastructure using MCP tools:
- `containerapps.list_apps` — list all Container Apps in an environment (check replica counts, provisioning state)
- `containerapps.get_app` — get detailed status of a specific Container App (active revision, ingress config, replicas)
- `containerapps.list_revisions` — list revision history for a Container App (traffic weights, active/inactive, creation times)

Use these tools to diagnose platform health issues like "why is agent X slow?" or "is the API gateway healthy?" by checking revision status, replica counts, and provisioning state.

## Safety Constraints

- MUST NOT modify any Azure resource — Reader + Monitoring Reader roles only.
- MUST NOT execute any remediation action without human approval; propose escalation and
  remediation paths only (REMEDI-001). All proposals require explicit human approval before
  any action is taken.
- MUST check Activity Log across all subscriptions as the first step (TRIAGE-003).
- MUST query both Log Analytics AND Resource Health before finalising diagnosis (TRIAGE-002).
- MUST include confidence score (0.0–1.0) in every diagnosis (TRIAGE-004).
- MUST NOT use wildcard tool permissions.
- RBAC scope: Reader + Monitoring Reader across all subscriptions.

## Allowed Tools

{allowed_tools}
""".format(allowed_tools="\n".join(f"- `{t}`" for t in ALLOWED_MCP_TOOLS + [
    "query_availability_metrics",
    "query_performance_baselines",
    "query_service_health",
    "query_advisor_recommendations",
    "query_change_analysis",
    "correlate_cross_domain",
    "propose_remediation",
]))


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_sre_agent() -> ChatAgent:
    """Create and configure the SRE ChatAgent instance.

    Returns:
        ChatAgent configured with SRE tools and system prompt.
    """
    logger.info("create_sre_agent: initialising Foundry client")
    client = get_foundry_client()

    agent = ChatAgent(
        name="sre-agent",
        description="SRE generalist — cross-domain monitoring, SLA tracking, and incident fallback.",
        instructions=SRE_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            query_availability_metrics,
            query_performance_baselines,
            query_service_health,
            query_advisor_recommendations,
            query_change_analysis,
            correlate_cross_domain,
            propose_remediation,
        ],
    )
    logger.info("create_sre_agent: ChatAgent created successfully")
    return agent


def create_sre_agent_version(project: "AIProjectClient") -> object:
    """Register the SRE Agent as a versioned PromptAgentDefinition in Foundry.

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
        agent_name="aap-sre-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=SRE_AGENT_SYSTEM_PROMPT,
            tools=[
                query_availability_metrics,
                query_performance_baselines,
                query_service_health,
                query_advisor_recommendations,
                query_change_analysis,
                correlate_cross_domain,
                propose_remediation,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("sre")
    _logger.info("sre: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("sre: creating agent and binding to agentserver")
    from_agent_framework(create_sre_agent()).run()
    _logger.info("sre: agentserver exited")
