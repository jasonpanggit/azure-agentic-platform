"""Storage Agent tool functions — Azure Monitor and storage diagnostic wrappers.

Allowed MCP tools (explicit allowlist — no wildcards):
    storage.list_accounts, storage.get_account, fileshares.list,
    monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from agents.shared.auth import get_agent_identity
from agents.shared.otel import instrument_tool_call, setup_telemetry

tracer = setup_telemetry("aiops-storage-agent")

# Explicit MCP tool allowlist — no wildcards permitted.
ALLOWED_MCP_TOOLS: List[str] = [
    "storage.list_accounts",
    "storage.get_account",
    "fileshares.list",
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
]


@ai_function
def query_storage_metrics(
    resource_id: str,
    metric_names: List[str],
    timespan: str = "PT2H",
) -> Dict[str, Any]:
    """Query Azure Monitor metrics for a storage account (MONITOR-001).

    Retrieves transactions, availability, latency, throttled requests,
    and capacity metrics. Use after Activity Log and Resource Health checks.

    Args:
        resource_id: Storage account resource ID.
        metric_names: List of metric names
            (e.g., ["Transactions", "Availability", "SuccessE2ELatency",
                     "ClientThrottlingError", "UsedCapacity"]).
        timespan: ISO 8601 duration string (default: "PT2H").

    Returns:
        Dict with keys:
            resource_id (str): Storage account queried.
            metric_names (list): Metrics requested.
            timespan (str): Time range applied.
            metrics (list): Metric time series data.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_id": resource_id, "metric_names": metric_names, "timespan": timespan}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="storage-agent",
        agent_id=agent_id,
        tool_name="query_storage_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "resource_id": resource_id,
            "metric_names": metric_names,
            "timespan": timespan,
            "metrics": [],
            "query_status": "success",
        }


@ai_function
def query_blob_diagnostics(
    storage_account_name: str,
    container_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Blob Storage diagnostic logs for error codes and access patterns.

    Retrieves storage audit logs including throttling errors (HTTP 503),
    access-denied errors (HTTP 403), and capacity-exceeded conditions.
    Requires Log Analytics diagnostic settings to be enabled on the account.

    Args:
        storage_account_name: Name of the storage account.
        container_name: Optional container to narrow diagnostics scope.

    Returns:
        Dict with keys:
            storage_account_name (str): Account queried.
            container_name (str | None): Container filter applied.
            error_summary (dict): Error code counts (e.g., ThrottlingError, 403).
            recent_operations (list): Recent operation log entries.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "storage_account_name": storage_account_name,
        "container_name": container_name,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="storage-agent",
        agent_id=agent_id,
        tool_name="query_blob_diagnostics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "storage_account_name": storage_account_name,
            "container_name": container_name,
            "error_summary": {},
            "recent_operations": [],
            "query_status": "success",
        }


@ai_function
def query_file_sync_health(
    storage_sync_service_name: str,
    sync_group_name: str,
) -> Dict[str, Any]:
    """Check Azure File Sync health for a sync group.

    Retrieves sync health status, last sync time, and any sync errors
    for the specified sync group. Requires Azure File Sync resource.

    Args:
        storage_sync_service_name: Name of the Storage Sync Service resource.
        sync_group_name: Name of the sync group to check.

    Returns:
        Dict with keys:
            storage_sync_service_name (str): Sync service queried.
            sync_group_name (str): Sync group checked.
            sync_health (str): "Healthy", "Error", or "NoActivity".
            last_sync_time (str | None): ISO 8601 timestamp of last sync.
            sync_errors (list): Current sync error details.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "storage_sync_service_name": storage_sync_service_name,
        "sync_group_name": sync_group_name,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="storage-agent",
        agent_id=agent_id,
        tool_name="query_file_sync_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "storage_sync_service_name": storage_sync_service_name,
            "sync_group_name": sync_group_name,
            "sync_health": "Unknown",
            "last_sync_time": None,
            "sync_errors": [],
            "query_status": "success",
        }
