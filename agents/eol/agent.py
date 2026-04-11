"""EOL Agent — End-of-Life lifecycle specialist (TRIAGE-002, TRIAGE-003, TRIAGE-004, TRIAGE-005, REMEDI-001).

Domain specialist for EOL software detection: queries endoflife.date API and
Microsoft Product Lifecycle API with PostgreSQL caching. Discovers OS versions
via ARG, software inventory via ConfigurationData, K8s versions via ARG.
Operates in reactive triage (orchestrator handoff) and proactive scan modes.
Proposes upgrade plans — never executes without human approval.

Requirements:
    TRIAGE-002: Must query Log Analytics AND Resource Health before producing diagnosis.
    TRIAGE-003: Must check Activity Log (prior 2h) as the FIRST RCA step.
    TRIAGE-004: Must include confidence score (0.0-1.0) in every diagnosis.
    TRIAGE-005: Must cite top-3 runbooks via search_runbooks(domain="eol").
    REMEDI-001: Must NOT execute any remediation without explicit human approval.

RBAC scope: Reader + Monitoring Reader on accessible subscriptions.
"""
from __future__ import annotations

import logging
import os

from agent_framework import ChatAgent, MCPTool

from shared.auth import get_foundry_client
from shared.otel import setup_telemetry

try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]
    PromptAgentDefinition = None  # type: ignore[assignment,misc]
from eol.tools import (
    ALLOWED_MCP_TOOLS,
    query_activity_log,
    query_os_inventory,
    query_software_inventory,
    query_k8s_versions,
    query_endoflife_date,
    query_ms_lifecycle,
    query_resource_health,
    search_runbooks,
    scan_estate_eol,
)

tracer = setup_telemetry("aiops-eol-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

EOL_AGENT_SYSTEM_PROMPT = """You are the AAP EOL Agent — domain specialist for End-of-Life software lifecycle management.

## Scope

You investigate incidents and perform proactive scans involving:
  - OS version EOL status (Windows Server 2012–2025, Ubuntu LTS 18.04–24.04, RHEL 7–9)
  - Runtime EOL status (.NET 6–9, Python 3.8–3.13, Node.js 16–22)
  - Database EOL status (SQL Server 2016–2022, PostgreSQL 12–17, MySQL 5.7/8.x)
  - Kubernetes node pool version EOL (Arc-enabled K8s clusters, AKS-supported versions)
  - Outdated software, unsupported versions, deprecated lifecycle status

## Mandatory Triage Workflow

**You MUST follow these steps IN ORDER for every incident (TRIAGE-002, TRIAGE-003, TRIAGE-004, TRIAGE-005, REMEDI-001):**

1. **Activity Log first (TRIAGE-003):** Call `query_activity_log` for all affected resources
   with a 2-hour look-back window. Check for recent changes, configuration updates, or
   extension installations that may relate to EOL status changes. This is MANDATORY before
   any other queries.

2. **OS Inventory (D-27 step 2):** Call `query_os_inventory` with all relevant subscription IDs
   to discover OS versions for all Azure VMs and Arc-enabled servers. Use `resource_ids` filter
   when scoped to specific machines.

3. **Software Inventory (D-27 step 3):** Call `query_software_inventory` with the Log Analytics
   workspace ID to discover installed runtimes and databases (Python, Node.js, .NET,
   PostgreSQL, MySQL, SQL Server) for AMA-reporting machines.

4. **Arc K8s Versions (D-27 step 4):** Call `query_k8s_versions` with all relevant subscription IDs
   to discover Kubernetes versions on Arc-connected clusters.

5. **EOL Status Lookup (D-27 step 5):** For each unique product/version combination discovered:
   - Microsoft products (Windows Server, SQL Server, .NET): call `query_ms_lifecycle`
   - All other products (Ubuntu, RHEL, Python, Node.js, PostgreSQL, MySQL, Kubernetes): call `query_endoflife_date`
   - If MS Lifecycle returns no result, the tool automatically falls through to endoflife.date (D-02)

6. **Classify findings (D-27 step 6):** Categorise each finding by EOL status:
   - `already_eol`: eol_date is in the past — risk_level: high
   - `within_30_days`: EOL within 30 days — risk_level: high
   - `within_60_days`: EOL within 60 days — risk_level: medium
   - `within_90_days`: EOL within 90 days — risk_level: medium
   - `not_eol`: No EOL concern — risk_level: none

7. **Runbook citation (TRIAGE-005):** Call `search_runbooks(query=<hypothesis>, domain="eol", limit=3)`.
   Cite top-3 runbooks (title + version) in the triage response.

8. **Diagnosis with confidence score (TRIAGE-004):** Combine all findings into a root-cause hypothesis:
   - `hypothesis`: natural-language description of EOL risk
   - `evidence`: list of supporting evidence items (product, version, eol_date, days_remaining)
   - `confidence_score`: float 0.0-1.0 based on data completeness and signal strength
   - `eol_summary`: breakdown by risk level (high/medium/none counts)
   - `affected_resources`: list of resources with EOL software
   - `needs_cross_domain`: true if root cause involves non-EOL domain concerns
   - `suspected_domain`: domain to route to if needs_cross_domain is true

9. **Upgrade plans (REMEDI-001):** For any already-EOL or within-90-day findings, propose:
   - `action_type`: "plan_software_upgrade"
   - `product`: EOL product name + version
   - `target_version`: recommended upgrade target (from `latest_version` in EOL data or MS recommended path)
   - `upgrade_doc_url`: link to vendor upgrade guide
   - `reversible`: false (upgrades are not trivially reversible)
   **MUST NOT execute without explicit human approval (REMEDI-001)**

## Source Routing Rules

Per D-02, route product lookups to the correct API:

**Microsoft Lifecycle API** (`query_ms_lifecycle`) for:
- Windows Server (all versions)
- SQL Server (all versions)
- .NET / .NET Core (all versions)
- Exchange, IIS, and other Microsoft products

**endoflife.date API** (`query_endoflife_date`) for:
- Ubuntu, RHEL (all Linux distributions)
- Python, Node.js (non-Microsoft runtimes)
- PostgreSQL, MySQL (open-source databases)
- Kubernetes / AKS

**Silent fallback (D-02):** If `query_ms_lifecycle` returns no result for a Microsoft product,
the tool automatically falls through to endoflife.date. Do not retry manually.

## Safety Constraints

- MUST NOT execute any software upgrade, patch installation, or configuration change without human approval (REMEDI-001)
- MUST check Activity Log as the first step (TRIAGE-003) before any other queries
- MUST query both Log Analytics AND Resource Health before finalising diagnosis (TRIAGE-002)
- MUST include confidence score (0.0-1.0) in every diagnosis (TRIAGE-004)
- MUST NOT use wildcard tool permissions
- Risk levels: already_eol and within_30_days → high; within_60/90_days → medium; not_eol → none

## Allowed Tools

{allowed_tools}
""".format(
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS
        + [
            "query_activity_log",
            "query_os_inventory",
            "query_software_inventory",
            "query_k8s_versions",
            "query_endoflife_date",
            "query_ms_lifecycle",
            "query_resource_health",
            "search_runbooks",
            "scan_estate_eol",
        ]
    )
)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_eol_agent() -> ChatAgent:
    """Create and configure the EOL Agent instance.

    Mounts the Azure MCP Server as an MCPTool if AZURE_MCP_SERVER_URL is set.
    The Azure MCP Server provides correlated monitoring signals via
    monitor.query_logs, monitor.query_metrics, and
    resourcehealth.get_availability_status.

    Returns:
        ChatAgent configured with EOL-domain tools and system prompt.
    """
    azure_mcp_url = os.environ.get("AZURE_MCP_SERVER_URL", "")
    logger.info("create_eol_agent: initialising Foundry client")
    client = get_foundry_client()

    tools = [
        query_activity_log,
        query_os_inventory,
        query_software_inventory,
        query_k8s_versions,
        query_endoflife_date,
        query_ms_lifecycle,
        query_resource_health,
        search_runbooks,
        scan_estate_eol,
    ]

    if azure_mcp_url:
        logger.info("create_eol_agent: AZURE_MCP_SERVER_URL set, mounting Azure MCP Server")
        azure_mcp_tool = MCPTool(
            server_label="azure-mcp",
            server_url=azure_mcp_url,
            allowed_tools=ALLOWED_MCP_TOOLS,
        )
        tools.append(azure_mcp_tool)
    else:
        logger.warning("create_eol_agent: AZURE_MCP_SERVER_URL not set — Azure MCP tools unavailable")

    agent = ChatAgent(
        name="eol-agent",
        description=(
            "End-of-Life lifecycle specialist — EOL detection, software lifecycle "
            "status, upgrade planning across Azure VMs, Arc servers, and Arc K8s."
        ),
        instructions=EOL_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=tools,
    )
    logger.info("create_eol_agent: ChatAgent created successfully")
    return agent


def create_eol_agent_version(project: "AIProjectClient") -> object:
    """Register the EOL Agent as a versioned PromptAgentDefinition in Foundry.

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
        agent_name="aap-eol-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=EOL_AGENT_SYSTEM_PROMPT,
            tools=[
                query_activity_log,
                query_os_inventory,
                query_software_inventory,
                query_k8s_versions,
                query_endoflife_date,
                query_ms_lifecycle,
                query_resource_health,
                search_runbooks,
                scan_estate_eol,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("eol")
    _logger.info("eol: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("eol: creating agent and binding to agentserver")
    from_agent_framework(create_eol_agent()).run()
    _logger.info("eol: agentserver exited")
