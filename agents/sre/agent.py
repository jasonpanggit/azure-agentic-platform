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

from agent_framework import Agent

from agents.shared.auth import get_foundry_client
from agents.shared.otel import setup_telemetry
from agents.sre.tools import (
    ALLOWED_MCP_TOOLS,
    propose_remediation,
    query_availability_metrics,
    query_performance_baselines,
)

tracer = setup_telemetry("aiops-sre-agent")

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
   events. Diagnosis is INVALID without this signal.

4. **Application Insights (MONITOR-001):** Use `applicationinsights.query` for end-to-end
   transaction traces and failure rates when web or API resources are involved.

5. **Advisor recommendations:** Use `advisor.list_recommendations` for affected resources.

6. **Availability and baselines:** Call `query_availability_metrics` and
   `query_performance_baselines` for SLA/SLO breach assessment.

7. **Correlate and hypothesise (TRIAGE-004):** Combine cross-domain findings into a
   root-cause hypothesis with confidence score between 0.0 and 1.0. Include:
   - `hypothesis`, `evidence`, `confidence_score`
   - SLA/SLO impact assessment (severity, affected resources, breach duration)
   - `needs_cross_domain`: true if a domain specialist is appropriate
   - `suspected_domain`: domain to recommend if needs_cross_domain is true

8. **Remediation proposal (REMEDI-001):** Call `propose_remediation` with escalation or
   remediation path. **MUST NOT execute without explicit human approval (REMEDI-001).**

## Arc Fallback (Phase 2)

When handling Arc incidents forwarded from the Arc Agent stub:
- MUST clearly state this is a general monitoring fallback (not full Arc diagnostics).
- MUST state: "Full Arc diagnostics require Phase 3 Arc MCP Server."
- Use Azure Monitor-based signals for what visibility is available.

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
    "propose_remediation",
]))


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_sre_agent() -> Agent:
    """Create and configure the SRE Agent instance.

    Returns:
        Agent configured with SRE tools and instructions.
    """
    client = get_foundry_client()

    return Agent(
        client,
        SRE_AGENT_SYSTEM_PROMPT,
        name="sre-agent",
        description="SRE generalist — cross-domain monitoring, SLA tracking, and incident fallback.",
        tools=[
            query_availability_metrics,
            query_performance_baselines,
            propose_remediation,
        ],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from azure.ai.agentserver.agentframework import from_agent_framework
    from_agent_framework(create_sre_agent()).run()
