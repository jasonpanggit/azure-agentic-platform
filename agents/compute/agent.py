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
from compute.tools import (
    ALLOWED_MCP_TOOLS,
    propose_aks_node_pool_scale,
    propose_vm_redeploy,
    propose_vm_resize,
    propose_vm_restart,
    propose_vmss_scale,
    query_aks_cluster_health,
    query_aks_node_pools,
    query_aks_upgrade_profile,
    query_activity_log,
    query_boot_diagnostics,
    query_disk_health,
    query_log_analytics,
    query_monitor_metrics,
    query_os_version,
    query_resource_health,
    query_vm_extensions,
    query_vm_sku_options,
    query_vmss_autoscale,
    query_vmss_instances,
    query_vmss_rolling_upgrade,
)

tracer = setup_telemetry("aiops-compute-agent")
logger = logging.getLogger(__name__)

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
   with a confidence score between 0.0 and 1.0. If OS version is relevant to the hypothesis
   (e.g., suspected EOL OS), call `query_os_version` before routing to the EOL domain.
   You MUST include:
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
    "query_os_version",
    "query_vm_extensions",
    "query_boot_diagnostics",
    "query_vm_sku_options",
    "query_disk_health",
    "propose_vm_restart",
    "propose_vm_resize",
    "propose_vm_redeploy",
    "query_vmss_instances",
    "query_vmss_autoscale",
    "query_vmss_rolling_upgrade",
    "propose_vmss_scale",
    "query_aks_cluster_health",
    "query_aks_node_pools",
    "query_aks_upgrade_profile",
    "propose_aks_node_pool_scale",
]))


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_compute_agent() -> ChatAgent:
    """Create and configure the Compute ChatAgent instance.

    Returns:
        ChatAgent configured with compute-domain tools and system prompt.
    """
    logger.info("create_compute_agent: initialising Foundry client")
    client = get_foundry_client()

    agent = ChatAgent(
        name="compute-agent",
        description="Azure compute domain specialist — VMs, VMSS, AKS, App Service.",
        instructions=COMPUTE_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            query_activity_log,
            query_log_analytics,
            query_resource_health,
            query_monitor_metrics,
            query_os_version,
            query_vm_extensions,
            query_boot_diagnostics,
            query_vm_sku_options,
            query_disk_health,
            propose_vm_restart,
            propose_vm_resize,
            propose_vm_redeploy,
            query_vmss_instances,
            query_vmss_autoscale,
            query_vmss_rolling_upgrade,
            propose_vmss_scale,
            query_aks_cluster_health,
            query_aks_node_pools,
            query_aks_upgrade_profile,
            propose_aks_node_pool_scale,
        ],
    )
    logger.info("create_compute_agent: ChatAgent created successfully")
    return agent


def create_compute_agent_version(project: "AIProjectClient") -> object:
    """Register the Compute Agent as a versioned PromptAgentDefinition in Foundry.

    This makes the agent visible in the Foundry portal (Agents tab) with full
    version history, tool configuration, and playground access.

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
        agent_name="aap-compute-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=COMPUTE_AGENT_SYSTEM_PROMPT,
            tools=[
                query_activity_log,
                query_log_analytics,
                query_resource_health,
                query_monitor_metrics,
                query_os_version,
                query_vm_extensions,
                query_boot_diagnostics,
                query_vm_sku_options,
                query_disk_health,
                propose_vm_restart,
                propose_vm_resize,
                propose_vm_redeploy,
                query_vmss_instances,
                query_vmss_autoscale,
                query_vmss_rolling_upgrade,
                propose_vmss_scale,
                query_aks_cluster_health,
                query_aks_node_pools,
                query_aks_upgrade_profile,
                propose_aks_node_pool_scale,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("compute")
    _logger.info("compute: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("compute: creating agent and binding to agentserver")
    from_agent_framework(create_compute_agent()).run()
    _logger.info("compute: agentserver exited")
