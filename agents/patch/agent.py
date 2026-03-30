"""Patch Agent — Azure patch management specialist (TRIAGE-002, TRIAGE-003, TRIAGE-004, TRIAGE-005, REMEDI-001).

Domain specialist for Azure patch management: Azure Update Manager (AUM)
compliance, patch assessment, installation history, reboot-pending state,
and KB-to-CVE mapping across Azure VMs and Arc-enabled servers.

Receives handoffs from the Orchestrator and produces patch compliance
diagnoses with supporting evidence before proposing any remediation.

Requirements:
    TRIAGE-002: Must query Log Analytics AND Resource Health before producing diagnosis.
    TRIAGE-003: Must check Activity Log (prior 2h) as the FIRST RCA step.
    TRIAGE-004: Must include confidence score (0.0-1.0) in every diagnosis.
    TRIAGE-005: Must cite top-3 runbooks via search_runbooks(domain="patch").
    REMEDI-001: Must NOT execute any remediation without explicit human approval.

RBAC scope: Reader + Azure Update Manager Reader on accessible subscriptions.
"""
from __future__ import annotations

import os

from agent_framework import Agent, MCPStreamableHTTPTool

from agents.shared.auth import get_foundry_client
from agents.shared.otel import setup_telemetry
from agents.patch.tools import (
    ALLOWED_MCP_TOOLS,
    query_activity_log,
    query_patch_assessment,
    query_patch_installations,
    query_configuration_data,
    lookup_kb_cves,
    query_resource_health,
    search_runbooks,
)

tracer = setup_telemetry("aiops-patch-agent")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

PATCH_AGENT_SYSTEM_PROMPT = """You are the AAP Patch Agent — domain specialist for Azure patch management and Update Manager.

## Scope

You investigate incidents involving:
  - Patch compliance (missing Critical, Security, UpdateRollup, FeaturePack, ServicePack, Definition, Tools, Updates patches)
  - Azure Update Manager assessment results and installation history
  - Reboot-pending machines after patch installation
  - KB article to CVE mapping for vulnerability assessment
  - Patch status across Azure VMs and Arc-enabled servers

## Mandatory Triage Workflow

**You MUST follow these steps IN ORDER for every incident (TRIAGE-002, TRIAGE-003, TRIAGE-004):**

1. **Activity Log first (TRIAGE-003):** Call `query_activity_log` for all affected resources
   with a 2-hour look-back window. Check for recent Update Manager runs, maintenance
   configuration changes, or extension installations. This is MANDATORY before any other queries.

2. **Patch Assessment (D-01):** Call `query_patch_assessment` to get compliance state, missing
   patches by classification, and reboot-pending status for all affected machines across
   all accessible subscriptions.

3. **Patch Installation History (D-04):** Call `query_patch_installations` with a 7-day window
   to review recent installation runs, success/failure status, and reboot status.

4. **Configuration Data (D-08):** Call `query_configuration_data` to get software inventory from
   Log Analytics workspaces tied to the affected resources. This provides complementary data
   to ARG for Arc machines with AMA agent.

5. **KB-to-CVE Enrichment (D-06):** For any Critical or Security patches identified, call
   `lookup_kb_cves` to map KB articles to the CVEs they address. Report which CVEs are
   fixed/pending per machine.

6. **Resource Health (TRIAGE-002):** Call `query_resource_health` for each affected resource
   to determine platform vs. configuration cause. Diagnosis is INVALID without this signal.

7. **Correlate and diagnose (TRIAGE-004):** Combine all findings into a root-cause hypothesis:
   - `hypothesis`: natural-language root cause description
   - `evidence`: list of supporting evidence items
   - `confidence_score`: float 0.0-1.0
   - `compliance_summary`: overall compliance % and per-classification breakdown
   - `reboot_pending_machines`: list of machines needing reboot
   - `cve_exposure`: list of unpatched CVEs with severity
   - `needs_cross_domain`: true if root cause is outside patch domain
   - `suspected_domain`: domain to route to if needs_cross_domain is true

8. **Runbook citation (TRIAGE-005):** Call `search_runbooks(query=<hypothesis>, domain="patch", limit=3)`.
   Cite top-3 runbooks (title + version) in the triage response.

9. **Remediation proposal (REMEDI-001):** If a clear remediation path exists, propose:
   - For assessment refresh: action_type="schedule_aum_assessment", risk_level="low", reversible=true
   - For patch installation (Critical/Security): action_type="schedule_aum_patch_installation",
     risk_level="high", reversible=false
   - For patch installation (other classifications): action_type="schedule_aum_patch_installation",
     risk_level="medium", reversible=false
   **MUST NOT execute without explicit human approval (REMEDI-001)**

## Safety Constraints

- MUST NOT execute any patch installation, assessment trigger, or reboot without human approval (REMEDI-001)
- MUST check Activity Log as the first step (TRIAGE-003) before any other queries
- MUST query both Log Analytics AND Resource Health before finalising diagnosis (TRIAGE-002)
- MUST include confidence score (0.0-1.0) in every diagnosis (TRIAGE-004)
- MUST NOT use wildcard tool permissions
- Risk levels: Critical/Security -> high, other classifications -> medium, assessment runs -> low

## Allowed Tools

{allowed_tools}
""".format(
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS
        + [
            "query_activity_log",
            "query_patch_assessment",
            "query_patch_installations",
            "query_configuration_data",
            "lookup_kb_cves",
            "query_resource_health",
            "search_runbooks",
        ]
    )
)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_patch_agent() -> Agent:
    """Create and configure the Patch Agent instance.

    Mounts the Azure MCP Server as a MCPStreamableHTTPTool if
    AZURE_MCP_SERVER_URL is set. The Azure MCP Server provides correlated
    monitoring signals via monitor.query_logs, monitor.query_metrics, and
    resourcehealth.get_availability_status.

    Returns:
        Agent configured with patch-domain tools and instructions.
    """
    azure_mcp_url = os.environ.get("AZURE_MCP_SERVER_URL", "")
    client = get_foundry_client()

    tools = [
        query_activity_log,
        query_patch_assessment,
        query_patch_installations,
        query_configuration_data,
        lookup_kb_cves,
        query_resource_health,
        search_runbooks,
    ]

    if azure_mcp_url:
        azure_mcp_tool = MCPStreamableHTTPTool(
            name="azure-mcp",
            url=azure_mcp_url,
            allowed_tools=ALLOWED_MCP_TOOLS,
        )
        tools.append(azure_mcp_tool)

    return Agent(
        client,
        PATCH_AGENT_SYSTEM_PROMPT,
        name="patch-agent",
        description=(
            "Azure patch management specialist — Update Manager compliance, "
            "assessment, installation history, KB-to-CVE mapping."
        ),
        tools=tools,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from azure.ai.agentserver.agentframework import from_agent_framework
    from_agent_framework(create_patch_agent()).run()
