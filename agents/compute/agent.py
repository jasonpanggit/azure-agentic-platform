"""Compute Agent — Azure compute resource specialist (TRIAGE-002, TRIAGE-003, TRIAGE-004, REMEDI-001).

Domain specialist for Azure compute resources: VMs, VMSS, AKS node-level issues,
App Service, and Azure Functions. Receives handoffs from the Orchestrator and
produces root-cause hypotheses with supporting evidence.

Requirements:
    TRIAGE-002: Must query Log Analytics AND Resource Health before producing diagnosis.
    TRIAGE-003: Must check Activity Log (prior 2h) as the FIRST RCA step.
    TRIAGE-004: Must include confidence score (0.0–1.0) in every diagnosis.
    REMEDI-001: Must NOT execute any remediation without explicit human approval.

RBAC scope: Virtual Machine Contributor + Monitoring Reader (enforced by Terraform).
"""
from __future__ import annotations

from agent_framework import Agent

from agents.shared.auth import get_foundry_client
from agents.shared.otel import setup_telemetry
from agents.compute.tools import (
    ALLOWED_MCP_TOOLS,
    query_activity_log,
    query_log_analytics,
    query_monitor_metrics,
    query_resource_health,
)

tracer = setup_telemetry("aiops-compute-agent")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

COMPUTE_AGENT_SYSTEM_PROMPT = """You are the AAP Compute Agent, an Azure compute resource specialist.

## Scope

You investigate incidents involving: Virtual Machines (VMs), Virtual Machine Scale Sets (VMSS),
AKS node-level issues, App Service, and Azure Functions.

## Mandatory Triage Workflow

**You MUST follow these steps in order for every incident (TRIAGE-002, TRIAGE-003, TRIAGE-004):**

1. **Activity Log first (TRIAGE-003):** Call `query_activity_log` for all affected resources
   with a 2-hour look-back window. Check for recent deployments, configuration changes,
   scaling events, or RBAC changes. This is MANDATORY before any metric queries.

2. **Log Analytics (TRIAGE-002):** Call `query_log_analytics` to retrieve error/warning events,
   OOM kills, application crash logs, and health probe failures. Diagnosis is INVALID without
   this signal.

3. **Resource Health (TRIAGE-002, MONITOR-003):** Call `query_resource_health` for each affected
   resource. Determines whether the issue is platform-side or configuration/application.
   Diagnosis is INVALID without this signal.

4. **Monitor metrics (MONITOR-001):** Call `query_monitor_metrics` for CPU, memory, disk I/O,
   and network metrics over the incident window.

5. **Correlate and hypothesise (TRIAGE-004):** Combine all findings into a root-cause hypothesis
   with a confidence score between 0.0 and 1.0. You MUST include:
   - `hypothesis`: natural-language root cause description
   - `evidence`: list of supporting evidence items
   - `confidence_score`: float 0.0–1.0
   - `needs_cross_domain`: true if root cause is outside compute domain
   - `suspected_domain`: domain to route to if needs_cross_domain is true

6. **Remediation proposal (REMEDI-001):** If a clear remediation path exists, propose it with:
   - `description`, `target_resources`, `estimated_impact`, `risk_level` (low/medium/high),
     `reversible` (bool)
   - **MUST NOT execute without explicit human approval (REMEDI-001)**

## Safety Constraints

- MUST NOT execute any VM restart, deallocate, resize, or scale operation without human approval
  (REMEDI-001). Do not take action without explicit human approval. Propose only; never execute.
- MUST check Activity Log as the first step (TRIAGE-003) before any metric queries.
- MUST query both Log Analytics AND Resource Health before finalising diagnosis (TRIAGE-002).
- MUST include confidence score (0.0–1.0) in every diagnosis (TRIAGE-004).
- MUST NOT use wildcard tool permissions.
- RBAC scope: Virtual Machine Contributor + Monitoring Reader on compute subscription only.

## Allowed Tools

{allowed_tools}
""".format(allowed_tools="\n".join(f"- `{t}`" for t in ALLOWED_MCP_TOOLS + [
    "query_activity_log",
    "query_log_analytics",
    "query_resource_health",
    "query_monitor_metrics",
]))


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_compute_agent() -> Agent:
    """Create and configure the Compute Agent instance.

    Returns:
        Agent configured with compute-domain tools and instructions.
    """
    client = get_foundry_client()

    return Agent(
        client,
        COMPUTE_AGENT_SYSTEM_PROMPT,
        name="compute-agent",
        description="Azure compute domain specialist — VMs, VMSS, AKS, App Service.",
        tools=[
            query_activity_log,
            query_log_analytics,
            query_resource_health,
            query_monitor_metrics,
        ],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from azure.ai.agentserver.agentframework import from_agent_framework
    from_agent_framework(create_compute_agent()).run()
