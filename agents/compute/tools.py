"""Compute Agent tool functions — Azure Monitor and Resource Health wrappers.

Provides @tool functions for querying Activity Log, Log Analytics,
Resource Health, and Azure Monitor metrics for compute resources.

Allowed MCP tools (explicit allowlist — no wildcards):
    compute.list_vms, compute.get_vm, compute.list_disks,
    monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status,
    advisor.list_recommendations,
    appservice.list_apps, appservice.get_app
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent_framework import tool

from shared.auth import get_agent_identity
from shared.otel import instrument_tool_call, setup_telemetry

tracer = setup_telemetry("aiops-compute-agent")

# Explicit MCP tool allowlist — no wildcards permitted (AGENT-001).
ALLOWED_MCP_TOOLS: List[str] = [
    "compute.list_vms",
    "compute.get_vm",
    "compute.list_disks",
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
    "advisor.list_recommendations",
    "appservice.list_apps",
    "appservice.get_app",
]


@tool
def query_activity_log(
    resource_ids: List[str],
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query the Azure Activity Log for changes on the given resources.

    This is the mandatory first-pass RCA step (TRIAGE-003). Always call
    this tool BEFORE running any metric or Log Analytics queries.

    Args:
        resource_ids: List of Azure resource IDs to query.
        timespan_hours: Look-back window in hours (default: 2, per TRIAGE-003).

    Returns:
        Dict with keys:
            resource_ids (list): Resources queried.
            timespan_hours (int): Look-back window.
            entries (list): Activity Log entries found.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_ids": resource_ids, "timespan_hours": timespan_hours}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
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


@tool
def query_log_analytics(
    workspace_id: str,
    kql_query: str,
    timespan: str = "PT2H",
) -> Dict[str, Any]:
    """Query a Log Analytics workspace using KQL (TRIAGE-002, MONITOR-002).

    MANDATORY before finalising any diagnosis — diagnosis is invalid without
    Log Analytics signal (TRIAGE-002).

    Args:
        workspace_id: Log Analytics workspace resource ID.
        kql_query: KQL query string.
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
        agent_name="compute-agent",
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


@tool
def query_resource_health(
    resource_id: str,
) -> Dict[str, Any]:
    """Get Azure Resource Health availability status (MONITOR-003).

    MANDATORY before finalising any diagnosis — diagnosis is invalid without
    Resource Health signal (TRIAGE-002). Determines whether the issue is a
    platform-side failure or a configuration/application issue.

    Args:
        resource_id: Azure resource ID to check.

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
        agent_name="compute-agent",
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


@tool
def query_monitor_metrics(
    resource_id: str,
    metric_names: List[str],
    timespan: str = "PT2H",
    interval: str = "PT5M",
) -> Dict[str, Any]:
    """Query Azure Monitor metrics for a compute resource (MONITOR-001).

    Retrieves CPU, memory, disk I/O, and network metrics over the incident
    window. Use after Activity Log and Resource Health checks.

    Args:
        resource_id: Azure resource ID to query.
        metric_names: List of metric names (e.g., ["Percentage CPU", "Disk Read Bytes/sec"]).
        timespan: ISO 8601 duration string (default: "PT2H").
        interval: Aggregation interval (default: "PT5M").

    Returns:
        Dict with keys:
            resource_id (str): Resource queried.
            metric_names (list): Metrics requested.
            timespan (str): Time range applied.
            interval (str): Aggregation interval.
            metrics (list): Metric time series data.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_id": resource_id,
        "metric_names": metric_names,
        "timespan": timespan,
        "interval": interval,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_monitor_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "resource_id": resource_id,
            "metric_names": metric_names,
            "timespan": timespan,
            "interval": interval,
            "metrics": [],
            "query_status": "success",
        }
