"""Arc Agent — Azure Arc resource specialist (Phase 3, TRIAGE-006).

Domain specialist for Azure Arc-enabled resources: Arc Servers
(HybridCompute), Arc Kubernetes (ConnectedClusters), and Arc Data Services.

Mounts the custom Arc MCP Server via MCPTool — the Arc MCP Server is an
internal Container App built in Phase 3 that fills the Azure MCP Server's
Arc coverage gap (AGENT-005).

Requirements:
    TRIAGE-006: Performs Arc-specific triage using Arc MCP Server tools:
        connectivity check → extension health → GitOps status → diagnosis.
    TRIAGE-002: Must query Log Analytics AND Resource Health before diagnosis.
    TRIAGE-003: Must check Activity Log (prior 2h) as FIRST RCA step.
    TRIAGE-004: Must include confidence score (0.0–1.0) in every diagnosis.
    REMEDI-001: Must NOT execute any remediation without human approval.
    AGENT-005: Mounts Arc MCP Server tools via MCPTool; ALLOWED_MCP_TOOLS
        is non-empty explicit list (not the Phase 2 empty stub list).

RBAC scope: Reader on Arc subscriptions (enforced by Terraform).
Arc MCP Server: ARC_MCP_SERVER_URL environment variable (required).
"""
from __future__ import annotations

import logging
import os

from agent_framework import ChatAgent
from azure.ai.projects.models import MCPTool

from shared.auth import get_foundry_client
from shared.otel import setup_telemetry

try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]
    PromptAgentDefinition = None  # type: ignore[assignment,misc]
from arc.tools import (
    ALLOWED_MCP_TOOLS,
    query_activity_log,
    query_log_analytics,
    query_resource_health,
)

tracer = setup_telemetry("aiops-arc-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — TRIAGE-006 workflow
# ---------------------------------------------------------------------------

ARC_AGENT_SYSTEM_PROMPT = """You are the AAP Arc Agent — domain specialist for Azure Arc-enabled resources.

## Scope

You investigate incidents involving:
  - Arc-enabled Servers (Microsoft.HybridCompute/machines)
  - Arc-enabled Kubernetes clusters (Microsoft.Kubernetes/connectedClusters)
  - Arc-enabled Data Services (SQL Managed Instance, PostgreSQL)

## Mandatory Triage Workflow (TRIAGE-006)

**You MUST follow these steps IN ORDER for every incident:**

### Step 1 — Activity Log first (TRIAGE-003)
Call `query_activity_log` for all affected resources with a 2-hour look-back window.
Check for: Arc agent upgrades, extension installs/removals, RBAC changes, policy
assignments, connectivity policy changes. This is MANDATORY before any Arc MCP
Server calls.

### Step 2 — Arc Connectivity Check (MONITOR-004)
Call `arc_servers_list` or `arc_k8s_list` for the affected subscription(s).
Identify: status (Connected/Disconnected/Error), last_status_change, agent_version,
prolonged_disconnection flag. For K8s clusters: check connectivity_status and
last_connectivity_time.

### Step 3 — Extension Health Check (MONITOR-005)
For any Arc server with status != 'Connected', call `arc_extensions_list` for that
machine. Check: AMA (AzureMonitorWindowsAgent/LinuxAgent), VM Insights (DependencyAgent),
Change Tracking, Azure Policy (GuestConfiguration). Note any with provisioning_state
!= 'Succeeded' or status_level == 'Error'.

### Step 4 — GitOps Reconciliation Status (MONITOR-006, K8s clusters only)
If the incident involves an Arc K8s cluster, call `arc_k8s_gitops_status` for the
cluster. Check: flux_detected (True/False), compliance_state for each Flux
configuration (Compliant/NonCompliant/Pending/Suspended).

### Step 5 — Log Analytics and Resource Health (TRIAGE-002)
Call `query_log_analytics` for Arc Heartbeat / connectivity events.
Call `query_resource_health` for each affected Arc resource.
Diagnosis is INVALID without both signals (TRIAGE-002).

### Step 6 — Structured Triage Summary (TRIAGE-004)
Produce a structured diagnosis with ALL of the following fields:
  - `hypothesis`: natural-language root cause description
  - `evidence`: list of supporting items from Steps 1–5
  - `confidence_score`: float 0.0–1.0
  - `connectivity_findings`: summary from Step 2
  - `extension_health_findings`: summary from Step 3 (or "N/A — not a server incident")
  - `gitops_findings`: summary from Step 4 (or "N/A — not a K8s incident")
  - `needs_cross_domain`: true if root cause is outside Arc domain
  - `suspected_domain`: domain to route to if needs_cross_domain is true

### Step 7 — Remediation Proposal (REMEDI-001)
If a clear remediation path exists, propose it with: description, target_resources,
estimated_impact, risk_level (low/medium/high/critical), reversibility statement.
**MUST NOT execute without explicit human approval (REMEDI-001).**

## Safety Constraints

- MUST NOT attempt to reconnect an Arc agent, reinstall extensions, or modify K8s
  resources without human approval (REMEDI-001).
- MUST NOT use the Azure MCP Server for Arc resources — it has a confirmed coverage
  gap. Use Arc MCP Server tools only.
- MUST complete all 5 diagnostic steps before producing a diagnosis.
- MUST NOT produce a diagnosis with confidence_score > 0.3 based only on Activity Log
  without Arc MCP Server tool results.

## Allowed Tools

{allowed_tools}
""".format(
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS
        + ["query_activity_log", "query_log_analytics", "query_resource_health"]
    )
)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_arc_agent() -> ChatAgent:
    """Create and configure the Arc Agent with Arc MCP Server tooling.

    Mounts the custom Arc MCP Server as a MCPTool when ARC_MCP_SERVER_URL
    is set. When absent the agent starts without MCP tooling (degraded mode).

    Returns:
        ChatAgent configured with Arc domain tools and TRIAGE-006 prompt.
    """
    arc_mcp_server_url = os.environ.get("ARC_MCP_SERVER_URL")

    logger.info("create_arc_agent: initialising Foundry client")
    client = get_foundry_client()

    # Base tools available without Arc MCP Server
    tools = [
        query_activity_log,
        query_log_analytics,
        query_resource_health,
    ]

    # Mount the Arc MCP Server via MCPTool when available (AGENT-005)
    if arc_mcp_server_url:
        logger.info("create_arc_agent: ARC_MCP_SERVER_URL set, mounting Arc MCP Server")
        arc_mcp_tool = MCPTool(
            server_label="arc-mcp",
            server_url=arc_mcp_server_url,
            allowed_tools=ALLOWED_MCP_TOOLS,
        )
        tools.append(arc_mcp_tool)
    else:
        logger.warning("create_arc_agent: ARC_MCP_SERVER_URL not set — starting in degraded mode (no Arc MCP tooling)")

    agent = ChatAgent(
        name="arc-agent",
        description=(
            "Azure Arc domain specialist — Arc Servers, Arc K8s, Arc Data Services. "
            "Uses custom Arc MCP Server for ARM-native Arc tooling (Phase 3)."
        ),
        instructions=ARC_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=tools,
    )
    logger.info("create_arc_agent: ChatAgent created successfully")
    return agent


def create_arc_agent_version(project: "AIProjectClient") -> object:
    """Register the Arc Agent as a versioned PromptAgentDefinition in Foundry.

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
        agent_name="aap-arc-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=ARC_AGENT_SYSTEM_PROMPT,
            tools=[
                query_activity_log,
                query_log_analytics,
                query_resource_health,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("arc")
    _logger.info("arc: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("arc: creating agent and binding to agentserver")
    from_agent_framework(create_arc_agent()).run()
    _logger.info("arc: agentserver exited")
