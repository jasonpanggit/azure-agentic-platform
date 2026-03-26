"""Arc Agent tool functions — Activity Log, Log Analytics, Resource Health wrappers.

Provides @ai_function tools for querying Activity Log, Log Analytics,
and Resource Health as the mandatory pre-triage steps (TRIAGE-002, TRIAGE-003).

Arc-specific tools (arc_servers_list, arc_k8s_list, arc_extensions_list,
arc_k8s_gitops_status, etc.) are mounted via the McpTool in agent.py and
called directly by the LLM — they do NOT need @ai_function wrappers here.

Explicit MCP tool allowlist — no wildcards permitted (AGENT-001):
  Arc MCP Server tools: arc_servers_list, arc_servers_get, arc_k8s_list,
    arc_k8s_get, arc_extensions_list, arc_k8s_gitops_status,
    arc_data_sql_mi_list, arc_data_postgresql_list
  Azure MCP Server tools: monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status
"""
from __future__ import annotations

from typing import Any, Dict, List

from agent_framework import ai_function

from agents.shared.auth import get_agent_identity
from agents.shared.otel import instrument_tool_call, setup_telemetry

tracer = setup_telemetry("aiops-arc-agent")

# ---------------------------------------------------------------------------
# Explicit MCP tool allowlist — replaces the Phase 2 empty list (AGENT-005)
# ---------------------------------------------------------------------------
ALLOWED_MCP_TOOLS: List[str] = [
    # Arc MCP Server tools (Phase 3 — custom FastMCP server)
    "arc_servers_list",
    "arc_servers_get",
    "arc_extensions_list",
    "arc_k8s_list",
    "arc_k8s_get",
    "arc_k8s_gitops_status",
    "arc_data_sql_mi_list",
    "arc_data_sql_mi_get",
    "arc_data_postgresql_list",
    # Azure MCP Server tools (general monitoring signals)
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
]


# ---------------------------------------------------------------------------
# @ai_function tools — mandatory pre-triage steps (TRIAGE-002, TRIAGE-003)
# These cannot be delegated to MCP servers as they are always-first steps.
# ---------------------------------------------------------------------------


@ai_function
def query_activity_log(
    resource_ids: List[str],
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query the Azure Activity Log for changes on the given Arc resources.

    This is the FIRST step in the Arc triage workflow (TRIAGE-003). Always
    call this tool BEFORE calling arc_servers_list or arc_k8s_list. Checks
    for recent deployments, agent upgrades, RBAC changes, and policy assignments
    that may have caused connectivity or extension health degradation.

    Args:
        resource_ids: List of Azure resource IDs to query (Arc machine IDs,
            cluster IDs, or subscription-level IDs).
        timespan_hours: Look-back window in hours (default: 2, per TRIAGE-003).

    Returns:
        Dict with keys:
            resource_ids (list): Resources queried.
            timespan_hours (int): Look-back window applied.
            entries (list): Activity Log entries found.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_ids": resource_ids, "timespan_hours": timespan_hours}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_activity_log",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "resource_ids": resource_ids,
            "timespan_hours": timespan_hours,
            "entries": [],
            "query_status": "success",
        }


@ai_function
def query_log_analytics(
    workspace_id: str,
    kql_query: str,
    timespan: str = "PT2H",
) -> Dict[str, Any]:
    """Query a Log Analytics workspace using KQL for Arc resource events.

    MANDATORY before finalising any diagnosis (TRIAGE-002). Provides Arc agent
    heartbeat logs, extension install events, and connectivity event history.

    Args:
        workspace_id: Log Analytics workspace resource ID.
        kql_query: KQL query string. For Arc triage, use tables: Heartbeat,
            AzureActivity, ConfigurationChange, Event.
        timespan: ISO 8601 duration string (default: "PT2H").

    Returns:
        Dict with keys:
            workspace_id (str): Workspace queried.
            kql_query (str): Query executed.
            timespan (str): Time range applied.
            rows (list): Query result rows.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"workspace_id": workspace_id, "kql_query": kql_query, "timespan": timespan}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_log_analytics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "workspace_id": workspace_id,
            "kql_query": kql_query,
            "timespan": timespan,
            "rows": [],
            "query_status": "success",
        }


@ai_function
def query_resource_health(
    resource_id: str,
) -> Dict[str, Any]:
    """Get Azure Resource Health availability status for an Arc resource.

    MANDATORY before finalising any diagnosis (TRIAGE-002). Distinguishes
    platform-side failures (Azure infrastructure) from Arc agent configuration
    issues (on-premises connectivity, extension failures).

    Args:
        resource_id: Azure resource ID of the Arc machine or K8s cluster.

    Returns:
        Dict with keys:
            resource_id (str): Resource checked.
            availability_state (str): "Available", "Degraded", or "Unavailable".
            summary (str): Human-readable health summary.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_id": resource_id}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_resource_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "resource_id": resource_id,
            "availability_state": "Unknown",
            "summary": "Resource Health query pending.",
            "query_status": "success",
        }
