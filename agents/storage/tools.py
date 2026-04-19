"""Storage Agent tool functions — Azure Monitor and storage diagnostic wrappers.

Allowed MCP tools (explicit allowlist — v2 namespace names, no wildcards):
    storage, fileshares, monitor, resourcehealth
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from agents.shared.subscription_utils import extract_subscription_id as _extract_subscription_id
from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

logger = logging.getLogger(__name__)

tracer = setup_telemetry("aiops-storage-agent")

# Lazy imports — packages may not be installed in all envs
try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.storagesync import StorageSyncManagementClient
except ImportError:
    StorageSyncManagementClient = None  # type: ignore[assignment,misc]

# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "storage",
    "fileshares",
    "monitor",
    "resourcehealth",
]


def _parse_timespan_hours(timespan: str) -> int:
    """Parse a simple ISO 8601 duration string into hours. Defaults to 2."""
    if timespan.startswith("PT") and timespan.endswith("H"):
        try:
            return int(timespan[2:-1])
        except ValueError:
            pass
    elif timespan == "P1D":
        return 24
    return 2


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
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(resource_id)
            client = MonitorManagementClient(credential, sub_id)

            end_dt = datetime.now(timezone.utc)
            hours = _parse_timespan_hours(timespan)
            start_dt = end_dt - timedelta(hours=hours)

            metrics_data: List[Dict[str, Any]] = []
            for metric_name in metric_names:
                try:
                    result = client.metrics.list(
                        resource_uri=resource_id,
                        timespan=f"{start_dt.isoformat()}/{end_dt.isoformat()}",
                        interval="PT5M",
                        metricnames=metric_name,
                        aggregation="Average,Total,Count",
                    )
                    for metric in result.value:
                        series = []
                        for ts in metric.timeseries or []:
                            for dp in ts.data or []:
                                series.append({
                                    "timestamp": dp.time_stamp.isoformat() if dp.time_stamp else None,
                                    "average": dp.average,
                                    "total": dp.total,
                                    "count": dp.count,
                                })
                        metrics_data.append({
                            "name": metric.name.value if metric.name else metric_name,
                            "unit": metric.unit.value if metric.unit else None,
                            "timeseries": series,
                        })
                except Exception as metric_err:
                    metrics_data.append({"name": metric_name, "error": str(metric_err)})

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_storage_metrics: complete | resource=%s metrics=%d duration_ms=%.0f",
                resource_id, len(metrics_data), duration_ms,
            )
            return {
                "resource_id": resource_id,
                "metric_names": metric_names,
                "timespan": timespan,
                "metrics": metrics_data,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_storage_metrics: failed | resource=%s error=%s duration_ms=%.0f",
                resource_id, e, duration_ms, exc_info=True,
            )
            return {
                "resource_id": resource_id,
                "metric_names": metric_names,
                "timespan": timespan,
                "metrics": [],
                "query_status": "error",
                "error": str(e),
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
        start_time = time.monotonic()
        try:
            if LogsQueryClient is None:
                raise ImportError("azure-monitor-query is not installed")

            credential = get_credential()
            logs_client = LogsQueryClient(credential)

            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(hours=2)

            container_filter = (
                f'| where Uri contains "/{container_name}/"' if container_name else ""
            )

            error_kql = f"""
StorageBlobLogs
| where TimeGenerated >= datetime('{start_dt.isoformat()}')
| where AccountName == '{storage_account_name}'
{container_filter}
| where StatusCode >= 400
| summarize Count = count() by StatusCode = tostring(StatusCode), ErrorCode
| order by Count desc
| take 50
"""

            ops_kql = f"""
StorageBlobLogs
| where TimeGenerated >= datetime('{start_dt.isoformat()}')
| where AccountName == '{storage_account_name}'
{container_filter}
| project TimeGenerated, OperationName, StatusCode, ErrorCode, Uri, CallerIpAddress, DurationMs
| order by TimeGenerated desc
| take 20
"""

            error_summary: Dict[str, Any] = {}
            recent_operations: List[Dict[str, Any]] = []

            # Attempt workspace-less query (requires a workspace ID in practice).
            # Return KQL intent with advisory note when workspace is not configured.
            workspace_id = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID", "")
            if workspace_id:
                try:
                    error_response = logs_client.query_workspace(
                        workspace_id=workspace_id,
                        query=error_kql,
                        timespan=timedelta(hours=2),
                    )
                    if (
                        LogsQueryStatus is not None
                        and error_response.status == LogsQueryStatus.SUCCESS
                        and error_response.tables
                    ):
                        table = error_response.tables[0]
                        cols = [c.name for c in table.columns]
                        for row in table.rows:
                            entry = dict(zip(cols, row))
                            key = f"HTTP{entry.get('StatusCode', 'Unknown')}_{entry.get('ErrorCode', '')}"
                            error_summary[key] = entry.get("Count", 0)

                    ops_response = logs_client.query_workspace(
                        workspace_id=workspace_id,
                        query=ops_kql,
                        timespan=timedelta(hours=2),
                    )
                    if (
                        LogsQueryStatus is not None
                        and ops_response.status == LogsQueryStatus.SUCCESS
                        and ops_response.tables
                    ):
                        table = ops_response.tables[0]
                        cols = [c.name for c in table.columns]
                        recent_operations = [dict(zip(cols, row)) for row in table.rows]
                except Exception as query_err:
                    error_summary = {
                        "note": f"Log Analytics query failed: {query_err}",
                        "kql_available": True,
                    }
            else:
                error_summary = {
                    "note": (
                        "Diagnostic logs query requires LOG_ANALYTICS_WORKSPACE_ID env var "
                        "pointing to a workspace with StorageBlobLogs enabled."
                    ),
                    "kql_available": True,
                    "error_kql": error_kql.strip(),
                    "ops_kql": ops_kql.strip(),
                }

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_blob_diagnostics: complete | account=%s duration_ms=%.0f",
                storage_account_name, duration_ms,
            )
            return {
                "storage_account_name": storage_account_name,
                "container_name": container_name,
                "error_summary": error_summary,
                "recent_operations": recent_operations,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_blob_diagnostics: failed | account=%s error=%s duration_ms=%.0f",
                storage_account_name, e, duration_ms, exc_info=True,
            )
            return {
                "storage_account_name": storage_account_name,
                "container_name": container_name,
                "error_summary": {},
                "recent_operations": [],
                "query_status": "error",
                "error": str(e),
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
        start_time = time.monotonic()
        try:
            if StorageSyncManagementClient is None:
                raise ImportError("azure-mgmt-storagesync is not installed")

            credential = get_credential()
            sub_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
            if not sub_id:
                raise ValueError(
                    "AZURE_SUBSCRIPTION_ID environment variable is required for "
                    "StorageSyncManagementClient"
                )

            sync_client = StorageSyncManagementClient(credential, sub_id)

            # List all storage sync services to find the matching one and its resource group
            resource_group: Optional[str] = None
            for service in sync_client.storage_sync_services.list_by_subscription():
                if service.name == storage_sync_service_name:
                    # Extract resource group from resource ID
                    # ID format: /subscriptions/{sub}/resourceGroups/{rg}/providers/...
                    parts = (service.id or "").split("/")
                    try:
                        rg_index = parts.index("resourceGroups")
                        resource_group = parts[rg_index + 1]
                    except (ValueError, IndexError):
                        pass
                    break

            if resource_group is None:
                return {
                    "storage_sync_service_name": storage_sync_service_name,
                    "sync_group_name": sync_group_name,
                    "sync_health": "Unknown",
                    "last_sync_time": None,
                    "sync_errors": [
                        {
                            "note": (
                                f"Storage Sync Service '{storage_sync_service_name}' not found "
                                f"in subscription {sub_id}."
                            )
                        }
                    ],
                    "query_status": "success",
                }

            # Get sync group details
            sync_group = sync_client.sync_groups.get(
                resource_group_name=resource_group,
                storage_sync_service_name=storage_sync_service_name,
                sync_group_name=sync_group_name,
            )

            # List server endpoints to derive health and last sync time
            server_endpoints = list(
                sync_client.server_endpoints.list_by_sync_group(
                    resource_group_name=resource_group,
                    storage_sync_service_name=storage_sync_service_name,
                    sync_group_name=sync_group_name,
                )
            )

            sync_errors: List[Dict[str, Any]] = []
            last_sync_time: Optional[str] = None
            overall_health = "Healthy"

            for ep in server_endpoints:
                sync_status = getattr(ep, "sync_status", None)
                if sync_status:
                    upload = getattr(sync_status, "upload_status", None)
                    download = getattr(sync_status, "download_status", None)

                    for direction, status_obj in [("upload", upload), ("download", download)]:
                        if status_obj is None:
                            continue
                        health = getattr(status_obj, "health_state", None)
                        last_sync = getattr(status_obj, "last_sync_success", None)

                        if last_sync is not None:
                            ts = last_sync.isoformat() if hasattr(last_sync, "isoformat") else str(last_sync)
                            if last_sync_time is None or ts > last_sync_time:
                                last_sync_time = ts

                        if health and str(health).lower() not in ("healthy", ""):
                            overall_health = "Error"
                            sync_errors.append({
                                "server_endpoint": getattr(ep, "server_local_path", ep.name),
                                "direction": direction,
                                "health_state": str(health),
                                "last_sync_per_item_error_count": getattr(
                                    status_obj, "last_sync_per_item_error_count", None
                                ),
                            })

            if not server_endpoints:
                overall_health = "NoActivity"

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_file_sync_health: complete | service=%s group=%s health=%s duration_ms=%.0f",
                storage_sync_service_name, sync_group_name, overall_health, duration_ms,
            )
            return {
                "storage_sync_service_name": storage_sync_service_name,
                "sync_group_name": sync_group_name,
                "sync_health": overall_health,
                "last_sync_time": last_sync_time,
                "sync_errors": sync_errors,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_file_sync_health: failed | service=%s error=%s duration_ms=%.0f",
                storage_sync_service_name, e, duration_ms, exc_info=True,
            )
            return {
                "storage_sync_service_name": storage_sync_service_name,
                "sync_group_name": sync_group_name,
                "sync_health": "Unknown",
                "last_sync_time": None,
                "sync_errors": [],
                "query_status": "error",
                "error": str(e),
            }
