"""Compute Agent tool functions — Azure Monitor and Resource Health wrappers.

Provides @ai_function tools for querying Activity Log, Log Analytics,
Resource Health, Azure Monitor metrics, and ARG OS version inventory for
compute resources.

Allowed MCP tools (explicit allowlist — no wildcards):
    compute.list_vms, compute.get_vm, compute.list_disks,
    monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status,
    advisor.list_recommendations,
    appservice.list_apps, appservice.get_app
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

# Lazy import — azure-mgmt-resourcegraph may not be installed in all envs
try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
except ImportError:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    QueryRequestOptions = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-monitor may not be installed in all envs
try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-monitor-query may not be installed in all envs
try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-resourcehealth may not be installed in all envs
try:
    from azure.mgmt.resourcehealth import MicrosoftResourceHealth
except ImportError:
    MicrosoftResourceHealth = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-compute-agent")
logger = logging.getLogger(__name__)

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


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-monitor": "azure.mgmt.monitor",
        "azure-monitor-query": "azure.monitor.query",
        "azure-mgmt-resourcehealth": "azure.mgmt.resourcehealth",
        "azure-mgmt-resourcegraph": "azure.mgmt.resourcegraph",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("compute_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "compute_tools: sdk_missing | package=%s — tool will return error", pkg
            )


_log_sdk_availability()


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an Azure resource ID.

    Args:
        resource_id: Azure resource ID in the form
            /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}

    Returns:
        Subscription ID string (lowercase).

    Raises:
        ValueError: If the subscription segment cannot be found.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot extract subscription_id from resource_id: {resource_id}"
        )


@ai_function
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
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            start = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
            all_entries: List[Dict[str, Any]] = []

            for resource_id in resource_ids:
                sub_id = _extract_subscription_id(resource_id)
                client = MonitorManagementClient(credential, sub_id)
                filter_str = (
                    f"eventTimestamp ge '{start.isoformat()}' "
                    f"and resourceId eq '{resource_id}'"
                )
                events = client.activity_logs.list(filter=filter_str)
                for event in events:
                    all_entries.append(
                        {
                            "eventTimestamp": (
                                event.event_timestamp.isoformat()
                                if event.event_timestamp
                                else None
                            ),
                            "operationName": (
                                event.operation_name.value
                                if event.operation_name
                                else None
                            ),
                            "caller": event.caller,
                            "status": (
                                event.status.value if event.status else None
                            ),
                            "resourceId": event.resource_id,
                            "level": (
                                event.level.value if event.level else None
                            ),
                            "description": event.description,
                        }
                    )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_activity_log: complete | resources=%d entries=%d duration_ms=%.0f",
                len(resource_ids),
                len(all_entries),
                duration_ms,
            )
            return {
                "resource_ids": resource_ids,
                "timespan_hours": timespan_hours,
                "entries": all_entries,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_activity_log: failed | resources=%s error=%s duration_ms=%.0f",
                resource_ids,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_ids": resource_ids,
                "timespan_hours": timespan_hours,
                "entries": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
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
            query_status (str): "success", "skipped", "partial", or "error".
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
        start_time = time.monotonic()

        # Guard: empty workspace_id means no Log Analytics configured — skip gracefully
        if not workspace_id:
            logger.warning(
                "query_log_analytics: skipped | workspace_id is empty — no Log Analytics workspace configured"
            )
            return {
                "workspace_id": workspace_id,
                "kql_query": kql_query,
                "timespan": timespan,
                "rows": [],
                "query_status": "skipped",
            }

        try:
            if LogsQueryClient is None:
                raise ImportError("azure-monitor-query is not installed")

            credential = get_credential()
            client = LogsQueryClient(credential)
            response = client.query_workspace(
                workspace_id=workspace_id,
                query=kql_query,
                timespan=timespan,
            )

            if response.status == LogsQueryStatus.SUCCESS:
                rows: List[Dict[str, Any]] = []
                for table in response.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        rows.append(
                            dict(
                                zip(
                                    col_names,
                                    [str(v) if v is not None else None for v in row],
                                )
                            )
                        )
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.info(
                    "query_log_analytics: complete | workspace=%s rows=%d duration_ms=%.0f",
                    workspace_id,
                    len(rows),
                    duration_ms,
                )
                return {
                    "workspace_id": workspace_id,
                    "kql_query": kql_query,
                    "timespan": timespan,
                    "rows": rows,
                    "query_status": "success",
                }
            else:
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.warning(
                    "query_log_analytics: partial | workspace=%s duration_ms=%.0f error=%s",
                    workspace_id,
                    duration_ms,
                    response.partial_error,
                )
                return {
                    "workspace_id": workspace_id,
                    "kql_query": kql_query,
                    "timespan": timespan,
                    "rows": [],
                    "query_status": "partial",
                    "partial_error": str(response.partial_error),
                }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_log_analytics: failed | workspace=%s error=%s duration_ms=%.0f",
                workspace_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "workspace_id": workspace_id,
                "kql_query": kql_query,
                "timespan": timespan,
                "rows": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
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
            reason_type (str): Reason classification.
            occurred_time (str | None): ISO 8601 timestamp of the health event.
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
        start_time = time.monotonic()
        try:
            if MicrosoftResourceHealth is None:
                raise ImportError("azure-mgmt-resourcehealth is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(resource_id)
            client = MicrosoftResourceHealth(credential, sub_id)
            status = client.availability_statuses.get_by_resource(
                resource_uri=resource_id,
                expand="recommendedActions",
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            availability_state = (
                status.properties.availability_state.value
                if status.properties.availability_state
                else "Unknown"
            )
            logger.info(
                "query_resource_health: complete | resource=%s state=%s duration_ms=%.0f",
                resource_id,
                availability_state,
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "availability_state": availability_state,
                "summary": status.properties.summary,
                "reason_type": status.properties.reason_type,
                "occurred_time": (
                    status.properties.occurred_time.isoformat()
                    if status.properties.occurred_time
                    else None
                ),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_resource_health: failed | resource=%s error=%s duration_ms=%.0f",
                resource_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_id": resource_id,
                "availability_state": "Unknown",
                "summary": None,
                "reason_type": None,
                "occurred_time": None,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
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
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(resource_id)
            client = MonitorManagementClient(credential, sub_id)
            response = client.metrics.list(
                resource_uri=resource_id,
                metricnames=",".join(metric_names),
                timespan=timespan,
                interval=interval,
                aggregation="Average,Maximum,Minimum",
            )

            metrics_out: List[Dict[str, Any]] = []
            for metric in response.value:
                timeseries: List[Dict[str, Any]] = []
                for ts in metric.timeseries:
                    for dp in ts.data:
                        if dp.time_stamp:
                            timeseries.append(
                                {
                                    "timestamp": dp.time_stamp.isoformat(),
                                    "average": dp.average,
                                    "maximum": dp.maximum,
                                    "minimum": dp.minimum,
                                }
                            )
                metrics_out.append(
                    {
                        "name": metric.name.value if metric.name else None,
                        "unit": metric.unit.value if metric.unit else None,
                        "timeseries": timeseries,
                    }
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_monitor_metrics: complete | resource=%s metrics=%d duration_ms=%.0f",
                resource_id,
                len(metrics_out),
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "metric_names": metric_names,
                "timespan": timespan,
                "interval": interval,
                "metrics": metrics_out,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_monitor_metrics: failed | resource=%s error=%s duration_ms=%.0f",
                resource_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_id": resource_id,
                "metric_names": metric_names,
                "timespan": timespan,
                "interval": interval,
                "metrics": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_os_version(
    resource_ids: List[str],
    subscription_ids: List[str],
) -> Dict[str, Any]:
    """Query ARG for OS version details for specific compute resources.

    Covers both Azure VMs (microsoft.compute/virtualmachines) using
    instanceView osName with imageReference sku as fallback, and
    Arc-enabled servers (microsoft.hybridcompute/machines) using
    properties.osName and properties.osSku.

    Use this tool when the triage workflow identifies a potential EOL OS
    issue and the compute agent needs OS version context before routing
    to the EOL agent.

    Args:
        resource_ids: List of Azure resource IDs to query (VMs or Arc machines).
        subscription_ids: List of subscription IDs that contain the resources.

    Returns:
        Dict with keys:
            resource_ids (list): Resources queried.
            machines (list): Per-machine dicts with id, name, resourceGroup,
                subscriptionId, osName, osVersion, osType, osSku (Arc),
                imageReferenceSku (VM fallback), resourceType.
            total_count (int): Number of machines returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_ids": resource_ids, "subscription_ids": subscription_ids}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_os_version",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            if ResourceGraphClient is None:
                raise ImportError("azure-mgmt-resourcegraph is not installed")

            credential = get_credential()
            client = ResourceGraphClient(credential)

            ids_str = ", ".join(f'"{rid}"' for rid in resource_ids)

            # Azure VMs — instanceView osName + imageReference sku as fallback
            vm_kql = (
                'resources | where type == "microsoft.compute/virtualmachines"'
                " | extend osName = tostring(properties.extended.instanceView.osName),"
                " osVersion = tostring(properties.extended.instanceView.osVersion),"
                " osType = tostring(properties.storageProfile.osDisk.osType),"
                " publisher = tostring(properties.storageProfile.imageReference.publisher),"
                " offer = tostring(properties.storageProfile.imageReference.offer),"
                " imageReferenceSku = tostring(properties.storageProfile.imageReference.sku)"
                f" | where id in~ ({ids_str})"
                " | project id, name, resourceGroup, subscriptionId, osName, osVersion,"
                " osType, publisher, offer, imageReferenceSku"
                ' | extend resourceType = "vm"'
            )

            # Arc-enabled servers — properties.osName and properties.osSku
            arc_kql = (
                'resources | where type == "microsoft.hybridcompute/machines"'
                " | extend osName = tostring(properties.osName),"
                " osVersion = tostring(properties.osVersion),"
                " osType = tostring(properties.osType),"
                " osSku = tostring(properties.osSku),"
                " status = tostring(properties.status)"
                f" | where id in~ ({ids_str})"
                " | project id, name, resourceGroup, subscriptionId, osName, osVersion,"
                " osType, osSku, status"
                ' | extend resourceType = "arc"'
            )

            all_machines: List[Dict[str, Any]] = []

            for kql in [vm_kql, arc_kql]:
                skip_token: Optional[str] = None
                while True:
                    options = (
                        QueryRequestOptions(skip_token=skip_token) if skip_token else None
                    )
                    request = QueryRequest(
                        subscriptions=subscription_ids,
                        query=kql,
                        options=options,
                    )
                    response = client.resources(request)
                    all_machines.extend(response.data)
                    skip_token = response.skip_token
                    if not skip_token:
                        break

            return {
                "resource_ids": resource_ids,
                "machines": all_machines,
                "total_count": len(all_machines),
                "query_status": "success",
            }
        except Exception as e:
            return {
                "resource_ids": resource_ids,
                "machines": [],
                "total_count": 0,
                "query_status": "error",
                "error": str(e),
            }
