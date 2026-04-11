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
import os
import time
import urllib.request
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

# Lazy import — azure-mgmt-compute may not be installed in all envs
try:
    from azure.mgmt.compute import ComputeManagementClient
    from azure.mgmt.compute.models import RunCommandInput
except ImportError:
    ComputeManagementClient = None  # type: ignore[assignment,misc]
    RunCommandInput = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-containerservice for AKS tools
try:
    from azure.mgmt.containerservice import ContainerServiceClient
except ImportError:
    ContainerServiceClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-cosmos may not be installed in all envs
try:
    from azure.cosmos import CosmosClient
except ImportError:
    CosmosClient = None  # type: ignore[assignment,misc]

# Lazy import — ForecasterClient from api-gateway (co-located in container image)
try:
    from services.api_gateway.forecaster import ForecasterClient
except ImportError:
    ForecasterClient = None  # type: ignore[assignment,misc]

from shared.approval_manager import create_approval_record

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
        start_time = time.monotonic()
        logger.info(
            "query_os_version: called | resources=%d subscriptions=%d",
            len(resource_ids),
            len(subscription_ids),
        )
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

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_os_version: complete | machines=%d duration_ms=%.0f",
                len(all_machines),
                duration_ms,
            )
            return {
                "resource_ids": resource_ids,
                "machines": all_machines,
                "total_count": len(all_machines),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_os_version: failed | resources=%s error=%s duration_ms=%.0f",
                resource_ids,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_ids": resource_ids,
                "machines": [],
                "total_count": 0,
                "query_status": "error",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Phase 32 — New Azure VM tools
# ---------------------------------------------------------------------------


@ai_function
def query_vm_extensions(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """List extensions installed on an Azure VM with provisioning state and version.

    Args:
        resource_group: Resource group name.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with 'extensions' list (name, type, provisioning_state, version).
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vm_extensions",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            if ComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-compute not installed", "extensions": [], "duration_ms": duration_ms}

            credential = get_credential()
            client = ComputeManagementClient(credential, subscription_id)

            raw = client.virtual_machine_extensions.list(resource_group, vm_name)
            extensions = []
            for ext in (raw.value or []):
                extensions.append({
                    "name": ext.name,
                    "type": getattr(ext, "type_properties_type", ext.type) or "",
                    "provisioning_state": getattr(ext.properties, "provisioning_state", "Unknown"),
                    "type_handler_version": getattr(ext.properties, "type_handler_version", ""),
                    "auto_upgrade_minor_version": getattr(
                        ext.properties, "auto_upgrade_minor_version", None
                    ),
                })
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {"extensions": extensions, "vm_name": vm_name, "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_vm_extensions error: %s", exc)
            return {"error": str(exc), "extensions": [], "duration_ms": duration_ms}


@ai_function
def query_boot_diagnostics(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Retrieve boot diagnostics data for an Azure VM (screenshot URI + serial log URI).

    Args:
        resource_group: Resource group name.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'screenshot_uri' and 'serial_log_uri'.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_boot_diagnostics",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            if ComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-compute not installed", "duration_ms": duration_ms}

            credential = get_credential()
            client = ComputeManagementClient(credential, subscription_id)

            result = client.virtual_machines.retrieve_boot_diagnostics_data(
                resource_group, vm_name
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "screenshot_uri": result.console_screenshot_blob_uri or "",
                "serial_log_uri": result.serial_console_log_blob_uri or "",
                "vm_name": vm_name,
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_boot_diagnostics error: %s", exc)
            return {"error": str(exc), "screenshot_uri": "", "serial_log_uri": "", "duration_ms": duration_ms}


@ai_function
def query_vm_sku_options(
    subscription_id: str,
    location: str,
    sku_family: str,
    thread_id: str,
) -> Dict[str, Any]:
    """List available VM SKUs in a region for rightsizing recommendations.

    Call this BEFORE propose_vm_resize to identify valid target SKUs.
    This is a diagnostic read — no changes are made.

    Args:
        subscription_id: Azure subscription ID.
        location: Azure region (e.g. "eastus").
        sku_family: SKU family prefix to filter (e.g. "Standard_D").
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'skus' list (name, tier, vcpus, memory_gb).
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vm_sku_options",
        tool_parameters={"location": location, "sku_family": sku_family},
        correlation_id=subscription_id,
        thread_id=thread_id,
    ):
        try:
            if ComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-compute not installed", "skus": [], "duration_ms": duration_ms}

            credential = get_credential()
            client = ComputeManagementClient(credential, subscription_id)

            skus = []
            for sku in client.resource_skus.list(filter=f"location eq '{location}'"):
                if sku.resource_type != "virtualMachines":
                    continue
                if sku_family and not sku.name.startswith(sku_family):
                    continue
                capabilities = {c.name: c.value for c in (sku.capabilities or [])}
                skus.append({
                    "name": sku.name,
                    "tier": sku.tier or "",
                    "vcpus": capabilities.get("vCPUs", ""),
                    "memory_gb": capabilities.get("MemoryGB", ""),
                })
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {"skus": skus[:20], "location": location, "sku_family": sku_family, "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_vm_sku_options error: %s", exc)
            return {"error": str(exc), "skus": [], "duration_ms": duration_ms}


@ai_function
def query_disk_health(
    resource_group: str,
    disk_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query disk state, IOPS, throughput, and encryption status.

    Args:
        resource_group: Resource group name.
        disk_name: Managed disk name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with disk_state, disk_size_gb, iops, throughput_mbps, encryption_type.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_disk_health",
        tool_parameters={"resource_group": resource_group, "disk_name": disk_name},
        correlation_id=disk_name,
        thread_id=thread_id,
    ):
        try:
            if ComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-compute not installed", "duration_ms": duration_ms}

            credential = get_credential()
            client = ComputeManagementClient(credential, subscription_id)

            disk = client.disks.get(resource_group, disk_name)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "disk_name": disk_name,
                "disk_state": disk.disk_state or "Unknown",
                "disk_size_gb": disk.disk_size_gb,
                "provisioning_state": disk.provisioning_state or "Unknown",
                "iops_read_write": disk.disk_iops_read_write,
                "throughput_mbps": disk.disk_m_bps_read_write,
                "encryption_type": getattr(
                    getattr(disk, "encryption", None), "type", "Unknown"
                ),
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_disk_health error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# Phase 32 — HITL remediation proposal tools (no ARM mutations)
# ---------------------------------------------------------------------------


@ai_function
def propose_vm_restart(
    resource_id: str,
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose a VM restart — creates HITL ApprovalRecord (no ARM call).

    REMEDI-001: This tool ONLY creates an approval record. The restart
    is executed by RemediationExecutor AFTER human approval.

    Returns:
        Dict with approval_id and status="pending_approval".
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="propose_vm_restart",
        tool_parameters={"vm_name": vm_name, "reason": reason},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            proposal = {
                "action": "vm_restart",
                "resource_id": resource_id,
                "resource_group": resource_group,
                "vm_name": vm_name,
                "subscription_id": subscription_id,
                "reason": reason,
                "description": f"Restart VM '{vm_name}' to resolve: {reason}",
                "target_resources": [resource_id],
                "estimated_impact": "~2-5 min downtime",
                "reversible": True,
            }

            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id=incident_id,
                agent_name="compute-agent",
                proposal=proposal,
                resource_snapshot={"vm_name": vm_name, "resource_id": resource_id},
                risk_level="medium",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"VM restart proposal created for '{vm_name}'. Awaiting human approval.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("propose_vm_restart error: %s", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}


@ai_function
def propose_vm_resize(
    resource_id: str,
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    current_sku: str,
    target_sku: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose a VM resize — creates HITL ApprovalRecord (no ARM call).

    Call query_vm_sku_options FIRST to identify a valid target_sku.
    REMEDI-001: No ARM call. Approval required before execution.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="propose_vm_resize",
        tool_parameters={"vm_name": vm_name, "target_sku": target_sku},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            proposal = {
                "action": "vm_resize",
                "resource_id": resource_id,
                "resource_group": resource_group,
                "vm_name": vm_name,
                "subscription_id": subscription_id,
                "current_sku": current_sku,
                "target_sku": target_sku,
                "reason": reason,
                "description": f"Resize VM '{vm_name}' from {current_sku} to {target_sku}: {reason}",
                "target_resources": [resource_id],
                "estimated_impact": "~5-10 min downtime (deallocate/resize/start)",
                "reversible": True,
            }

            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id=incident_id,
                agent_name="compute-agent",
                proposal=proposal,
                resource_snapshot={"vm_name": vm_name, "current_sku": current_sku, "target_sku": target_sku},
                risk_level="high",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"VM resize proposal: {vm_name} ({current_sku} -> {target_sku}). Awaiting approval.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("propose_vm_resize error: %s", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}


@ai_function
def propose_vm_redeploy(
    resource_id: str,
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose a VM redeploy to a different host — creates HITL ApprovalRecord.

    Use when host-level issues are suspected. Redeploy is irreversible
    (new host allocation; IP/disk are preserved).
    REMEDI-001: No ARM call. Approval required before execution.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="propose_vm_redeploy",
        tool_parameters={"vm_name": vm_name, "reason": reason},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            proposal = {
                "action": "vm_redeploy",
                "resource_id": resource_id,
                "resource_group": resource_group,
                "vm_name": vm_name,
                "subscription_id": subscription_id,
                "reason": reason,
                "description": f"Redeploy VM '{vm_name}' to new host: {reason}",
                "target_resources": [resource_id],
                "estimated_impact": "~10 min downtime",
                "reversible": False,
            }

            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id=incident_id,
                agent_name="compute-agent",
                proposal=proposal,
                resource_snapshot={"vm_name": vm_name, "resource_id": resource_id},
                risk_level="high",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"VM redeploy proposal created for '{vm_name}'. Awaiting approval.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("propose_vm_redeploy error: %s", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# Phase 32 — VMSS tools
# ---------------------------------------------------------------------------


@ai_function
def query_vmss_instances(
    resource_group: str,
    vmss_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """List VMSS instances with health state, power state, and provisioning status.

    Args:
        resource_group: Resource group name.
        vmss_name: VMSS name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'instances' list (instance_id, provisioning_state, vm_id).
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vmss_instances",
        tool_parameters={"resource_group": resource_group, "vmss_name": vmss_name},
        correlation_id=vmss_name,
        thread_id=thread_id,
    ):
        try:
            if ComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-compute not installed", "instances": [], "duration_ms": duration_ms}

            credential = get_credential()
            client = ComputeManagementClient(credential, subscription_id)

            instances = []
            for inst in client.virtual_machine_scale_set_vms.list(resource_group, vmss_name):
                instances.append({
                    "instance_id": inst.instance_id,
                    "provisioning_state": getattr(inst, "provisioning_state", "Unknown"),
                    "vm_id": inst.vm_id or "",
                })
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {"instances": instances, "vmss_name": vmss_name, "count": len(instances), "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_vmss_instances error: %s", exc)
            return {"error": str(exc), "instances": [], "duration_ms": duration_ms}


@ai_function
def query_vmss_autoscale(
    resource_group: str,
    vmss_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query current autoscale settings and recent scale events for a VMSS.

    Args:
        resource_group: Resource group name.
        vmss_name: VMSS name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'autoscale_settings' list.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vmss_autoscale",
        tool_parameters={"resource_group": resource_group, "vmss_name": vmss_name},
        correlation_id=vmss_name,
        thread_id=thread_id,
    ):
        try:
            if MonitorManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-monitor not installed", "autoscale_settings": [], "duration_ms": duration_ms}

            credential = get_credential()
            client = MonitorManagementClient(credential, subscription_id)

            settings = []
            for s in client.autoscale_settings.list_by_resource_group(resource_group):
                if vmss_name.lower() not in (s.name or "").lower() and \
                   vmss_name.lower() not in str(getattr(s, "target_resource_uri", "")).lower():
                    continue
                profiles = []
                for p in (s.profiles or []):
                    cap = getattr(p, "capacity", None)
                    profiles.append({
                        "name": p.name,
                        "min_count": str(getattr(cap, "minimum", "")) if cap else "",
                        "max_count": str(getattr(cap, "maximum", "")) if cap else "",
                        "default_count": str(getattr(cap, "default", "")) if cap else "",
                    })
                settings.append({"name": s.name, "enabled": s.enabled, "profiles": profiles})
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {"autoscale_settings": settings, "vmss_name": vmss_name, "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_vmss_autoscale error: %s", exc)
            return {"error": str(exc), "autoscale_settings": [], "duration_ms": duration_ms}


@ai_function
def query_vmss_rolling_upgrade(
    resource_group: str,
    vmss_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query rolling upgrade status for a VMSS — policy, progress, and failed instances.

    Args:
        resource_group: Resource group name.
        vmss_name: VMSS name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with running, failed, pending instance counts and provisioning state.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vmss_rolling_upgrade",
        tool_parameters={"resource_group": resource_group, "vmss_name": vmss_name},
        correlation_id=vmss_name,
        thread_id=thread_id,
    ):
        try:
            if ComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-compute not installed", "duration_ms": duration_ms}

            credential = get_credential()
            client = ComputeManagementClient(credential, subscription_id)

            upgrade = client.virtual_machine_scale_set_rolling_upgrades.get_latest(
                resource_group, vmss_name
            )
            progress = upgrade.progress
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "running_instance_count": getattr(progress, "successful_instance_count", 0),
                "failed_instance_count": getattr(progress, "failed_instance_count", 0),
                "pending_instance_count": getattr(progress, "pending_instance_count", 0),
                "provisioning_state": upgrade.provisioning_state or "Unknown",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_vmss_rolling_upgrade error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}


@ai_function
def propose_vmss_scale(
    resource_id: str,
    resource_group: str,
    vmss_name: str,
    subscription_id: str,
    current_capacity: int,
    target_capacity: int,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose manual VMSS scale-out or scale-in — HITL ApprovalRecord only.

    REMEDI-001: No ARM call. Approval required before execution.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="propose_vmss_scale",
        tool_parameters={"vmss_name": vmss_name, "target_capacity": target_capacity},
        correlation_id=vmss_name,
        thread_id=thread_id,
    ):
        try:
            proposal = {
                "action": "vmss_scale",
                "resource_id": resource_id,
                "vmss_name": vmss_name,
                "current_capacity": current_capacity,
                "target_capacity": target_capacity,
                "reason": reason,
                "description": f"Scale VMSS '{vmss_name}' from {current_capacity} to {target_capacity}: {reason}",
                "target_resources": [resource_id],
                "estimated_impact": "New instances take ~5 min to become healthy",
                "reversible": True,
            }

            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id=incident_id,
                agent_name="compute-agent",
                proposal=proposal,
                resource_snapshot={"vmss_name": vmss_name, "current_capacity": current_capacity},
                risk_level="medium",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"VMSS scale proposal: {vmss_name} {current_capacity}->{target_capacity}. Awaiting approval.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("propose_vmss_scale error: %s", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# Phase 32 — AKS tools
# ---------------------------------------------------------------------------


@ai_function
def query_aks_cluster_health(
    resource_group: str,
    cluster_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query AKS cluster health — API server status, provisioning state, Kubernetes version.

    Args:
        resource_group: Resource group name.
        cluster_name: AKS cluster name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with provisioning_state, kubernetes_version, power_state, fqdn.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_aks_cluster_health",
        tool_parameters={"resource_group": resource_group, "cluster_name": cluster_name},
        correlation_id=cluster_name,
        thread_id=thread_id,
    ):
        try:
            if ContainerServiceClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-containerservice not installed", "duration_ms": duration_ms}

            credential = get_credential()
            client = ContainerServiceClient(credential, subscription_id)

            cluster = client.managed_clusters.get(resource_group, cluster_name)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "cluster_name": cluster_name,
                "provisioning_state": getattr(cluster, "provisioning_state", "Unknown"),
                "kubernetes_version": getattr(cluster, "kubernetes_version", "Unknown"),
                "power_state": getattr(getattr(cluster, "power_state", None), "code", "Unknown"),
                "fqdn": getattr(cluster, "fqdn", "") or "",
                "enable_rbac": getattr(cluster, "enable_rbac", None),
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_aks_cluster_health error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}


@ai_function
def query_aks_node_pools(
    resource_group: str,
    cluster_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """List AKS node pools with status, count, VM size, and OS type.

    Args:
        resource_group: Resource group name.
        cluster_name: AKS cluster name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'node_pools' list.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_aks_node_pools",
        tool_parameters={"resource_group": resource_group, "cluster_name": cluster_name},
        correlation_id=cluster_name,
        thread_id=thread_id,
    ):
        try:
            if ContainerServiceClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-containerservice not installed", "node_pools": [], "duration_ms": duration_ms}

            credential = get_credential()
            client = ContainerServiceClient(credential, subscription_id)

            node_pools = []
            for np in client.agent_pools.list(resource_group, cluster_name):
                node_pools.append({
                    "name": np.name,
                    "count": getattr(np, "count", 0),
                    "vm_size": getattr(np, "vm_size", ""),
                    "provisioning_state": getattr(np, "provisioning_state", "Unknown"),
                    "os_type": getattr(np, "os_type", "Linux"),
                    "mode": getattr(np, "mode", "User"),
                })
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {"node_pools": node_pools, "cluster_name": cluster_name, "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_aks_node_pools error: %s", exc)
            return {"error": str(exc), "node_pools": [], "duration_ms": duration_ms}


@ai_function
def query_aks_upgrade_profile(
    resource_group: str,
    cluster_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query available Kubernetes upgrades for an AKS cluster.

    Args:
        resource_group: Resource group name.
        cluster_name: AKS cluster name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with current_version and available_upgrades list.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_aks_upgrade_profile",
        tool_parameters={"resource_group": resource_group, "cluster_name": cluster_name},
        correlation_id=cluster_name,
        thread_id=thread_id,
    ):
        try:
            if ContainerServiceClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-containerservice not installed", "duration_ms": duration_ms}

            credential = get_credential()
            client = ContainerServiceClient(credential, subscription_id)

            upgrade = client.managed_clusters.get_upgrade_profile(resource_group, cluster_name)
            cp = upgrade.control_plane_profile
            current_version = getattr(cp, "kubernetes_version", "Unknown")
            available = []
            for u in (getattr(cp, "upgrades", None) or []):
                available.append({
                    "kubernetes_version": getattr(u, "kubernetes_version", ""),
                    "is_preview": getattr(u, "is_preview", False),
                })
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "current_version": current_version,
                "available_upgrades": available,
                "cluster_name": cluster_name,
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_aks_upgrade_profile error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}


@ai_function
def propose_aks_node_pool_scale(
    resource_id: str,
    resource_group: str,
    cluster_name: str,
    node_pool_name: str,
    subscription_id: str,
    target_count: int,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose scaling an AKS node pool — HITL ApprovalRecord only.

    REMEDI-001: No ARM call. Approval required before execution.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="propose_aks_node_pool_scale",
        tool_parameters={"cluster_name": cluster_name, "node_pool_name": node_pool_name, "target_count": target_count},
        correlation_id=cluster_name,
        thread_id=thread_id,
    ):
        try:
            proposal = {
                "action": "aks_node_pool_scale",
                "resource_id": resource_id,
                "cluster_name": cluster_name,
                "node_pool_name": node_pool_name,
                "target_count": target_count,
                "reason": reason,
                "description": f"Scale AKS node pool '{node_pool_name}' in '{cluster_name}' to {target_count} nodes: {reason}",
                "target_resources": [resource_id],
                "estimated_impact": "New nodes take ~5-10 min to become ready",
                "reversible": True,
            }

            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id=incident_id,
                agent_name="compute-agent",
                proposal=proposal,
                resource_snapshot={"cluster_name": cluster_name, "node_pool_name": node_pool_name},
                risk_level="medium",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"AKS node pool scale proposal: {node_pool_name} -> {target_count}. Awaiting approval.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("propose_aks_node_pool_scale error: %s", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# Phase 36 — In-Guest Diagnostic tools
# ---------------------------------------------------------------------------

BLOCKED_COMMANDS_LINUX: List[str] = [
    "rm", "kill", "shutdown", "reboot", "halt", "poweroff", "init",
    "format", "fdisk", "dd", "mkfs", "parted", "wipefs",
    "systemctl stop", "systemctl disable", "systemctl mask",
    "apt", "apt-get", "yum", "dnf", "pip", "pip3",
    "curl -X DELETE", "wget --post",
    "chmod 000", "chown root",
    "iptables -F", "iptables -X",
    "userdel", "groupdel", "passwd",
    "mount", "umount",
    "> /dev/sda", "of=/dev/",
]

BLOCKED_COMMANDS_WINDOWS: List[str] = [
    "Remove-Item", "Stop-Computer", "Restart-Computer",
    "Format-Volume", "Clear-Disk",
    "Stop-Service", "Disable-Service",
    "Install-Package", "Install-Module",
    "Set-ExecutionPolicy Unrestricted",
    "Remove-WindowsFeature",
]

MAX_SCRIPT_LENGTH = 1500


@ai_function
def execute_run_command(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    script: str,
    os_type: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Execute a read-only diagnostic command on an Azure VM via Run Command API.

    Safety: destructive commands are blocked by a hard block list. Script
    length is limited to 1500 characters. Only diagnostic/read operations
    should be submitted.

    Args:
        resource_group: Resource group name.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        script: Shell or PowerShell script to execute (max 1500 chars).
        os_type: "Linux" or "Windows".
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with stdout, stderr, and execution metadata.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="execute_run_command",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name, "os_type": os_type},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            # Validate os_type
            if os_type not in ("Linux", "Windows"):
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": f"Invalid os_type '{os_type}'. Must be 'Linux' or 'Windows'.",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            # Validate script length
            if len(script) > MAX_SCRIPT_LENGTH:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": f"Script length {len(script)} exceeds maximum {MAX_SCRIPT_LENGTH} characters.",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            # Check block list
            blocked = BLOCKED_COMMANDS_LINUX if os_type == "Linux" else BLOCKED_COMMANDS_WINDOWS
            for line in script.splitlines():
                line_lower = line.lower()
                for cmd in blocked:
                    if cmd.lower() in line_lower:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        return {
                            "error": f"Script contains blocked command: '{cmd}'",
                            "blocked_command": cmd,
                            "query_status": "error",
                            "duration_ms": duration_ms,
                        }

            # SDK guard
            if ComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-compute not installed", "query_status": "error", "duration_ms": duration_ms}

            credential = get_credential()
            client = ComputeManagementClient(credential, subscription_id)

            command_id = "RunShellScript" if os_type == "Linux" else "RunPowerShellScript"
            parameters = RunCommandInput(
                command_id=command_id,
                script=script.splitlines(),
            )

            poller = client.virtual_machines.begin_run_command(
                resource_group, vm_name, parameters
            )
            result = poller.result()

            stdout = result.value[0].message if result.value and len(result.value) > 0 else ""
            stderr = result.value[1].message if result.value and len(result.value) > 1 else ""

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "execute_run_command: complete | vm=%s os=%s duration_ms=%d",
                vm_name,
                os_type,
                duration_ms,
            )
            return {
                "vm_name": vm_name,
                "os_type": os_type,
                "stdout": stdout,
                "stderr": stderr,
                "command_id": command_id,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("execute_run_command error: %s", exc)
            return {
                "error": str(exc),
                "vm_name": vm_name,
                "query_status": "error",
                "duration_ms": duration_ms,
            }


SERIAL_LOG_PATTERNS: Dict[str, List[str]] = {
    "kernel_panic": ["Kernel panic", "BUG: unable to handle"],
    "oom_kill": ["Out of memory: Kill process", "oom-kill", "oom_reaper"],
    "disk_error": ["I/O error", "EXT4-fs error", "XFS error", "blk_update_request: I/O error"],
    "fs_corruption": ["FILESYSTEM CORRUPTION DETECTED", "fsck"],
}

SERIAL_LOG_MAX_BYTES = 50 * 1024  # 50KB
SERIAL_LOG_EXCERPT_MAX_CHARS = 200


@ai_function
def parse_boot_diagnostics_serial_log(
    serial_log_uri: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Download and parse a VM serial console log for OS-level boot errors.

    Detects kernel panics, OOM kills, disk I/O errors, and filesystem
    corruption. Downloads at most 50KB from the serial log URI (typically
    obtained from query_boot_diagnostics).

    Args:
        serial_log_uri: SAS URI for the serial console log blob.
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with detected_events list, summary counts, and metadata.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="parse_boot_diagnostics_serial_log",
        tool_parameters={"serial_log_uri_length": len(serial_log_uri) if serial_log_uri else 0},
        correlation_id="",
        thread_id=thread_id,
    ):
        try:
            if not serial_log_uri:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "serial_log_uri is empty",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            # Download first 50KB
            response = urllib.request.urlopen(serial_log_uri)  # noqa: S310
            content_bytes = response.read(SERIAL_LOG_MAX_BYTES)
            content = content_bytes.decode("utf-8", errors="replace")

            lines = content.splitlines()
            detected_events: List[Dict[str, Any]] = []

            for line_idx, line in enumerate(lines):
                line_lower = line.lower()
                for category, patterns in SERIAL_LOG_PATTERNS.items():
                    for pattern in patterns:
                        if pattern.lower() in line_lower:
                            detected_events.append({
                                "type": category,
                                "line_number": line_idx + 1,
                                "excerpt": line[:SERIAL_LOG_EXCERPT_MAX_CHARS].strip(),
                            })
                            break  # one match per category per line

            summary: Dict[str, int] = {
                "kernel_panic": 0,
                "oom_kill": 0,
                "disk_error": 0,
                "fs_corruption": 0,
            }
            for event in detected_events:
                summary[event["type"]] += 1

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "parse_boot_diagnostics_serial_log: complete | events=%d size=%d duration_ms=%d",
                len(detected_events),
                len(content_bytes),
                duration_ms,
            )
            return {
                "detected_events": detected_events,
                "summary": summary,
                "serial_log_size_bytes": len(content_bytes),
                "truncated": len(content_bytes) >= SERIAL_LOG_MAX_BYTES,
                "total_events": len(detected_events),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("parse_boot_diagnostics_serial_log error: %s", exc)
            return {
                "error": str(exc),
                "query_status": "error",
                "duration_ms": duration_ms,
            }


@ai_function
def query_vm_guest_health(
    resource_id: str,
    workspace_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query VM guest health via Heartbeat table and InsightsMetrics (AMA).

    Classifies heartbeat status as healthy (<5 min), stale (5-15 min),
    or offline (>15 min / no rows). Also retrieves latest CPU, memory,
    and disk metrics from the AMA InsightsMetrics table.

    Args:
        resource_id: Azure resource ID of the VM.
        workspace_id: Log Analytics workspace ID.
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with heartbeat_status, last_heartbeat_minutes_ago, and
        latest CPU/memory/disk metrics.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vm_guest_health",
        tool_parameters={"resource_id": resource_id},
        correlation_id=resource_id,
        thread_id=thread_id,
    ):
        try:
            if not workspace_id:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "query_status": "skipped",
                    "reason": "workspace_id is empty",
                    "duration_ms": duration_ms,
                }

            if LogsQueryClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-monitor-query not installed",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            client = LogsQueryClient(credential)

            # Heartbeat query
            heartbeat_kql = (
                "Heartbeat"
                f' | where _ResourceId =~ "{resource_id}"'
                " | where TimeGenerated > ago(15m)"
                " | summarize LastHeartbeat = max(TimeGenerated)"
                " | extend MinutesAgo = datetime_diff('minute', now(), LastHeartbeat)"
            )

            heartbeat_response = client.query_workspace(
                workspace_id=workspace_id,
                query=heartbeat_kql,
                timespan="PT15M",
            )

            minutes_ago: Optional[int] = None
            heartbeat_status = "offline"

            if heartbeat_response.status == LogsQueryStatus.SUCCESS:
                for table in heartbeat_response.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        row_dict = dict(zip(col_names, row))
                        val = row_dict.get("MinutesAgo")
                        if val is not None:
                            minutes_ago = int(float(str(val)))
                            if minutes_ago < 5:
                                heartbeat_status = "healthy"
                            elif minutes_ago <= 15:
                                heartbeat_status = "stale"
                            else:
                                heartbeat_status = "offline"

            # Guest metrics query
            metrics_kql = (
                "InsightsMetrics"
                f' | where _ResourceId =~ "{resource_id}"'
                " | where TimeGenerated > ago(5m)"
                ' | where Namespace in ("Processor", "Memory", "LogicalDisk")'
                " | summarize"
                '     cpu_pct = avgif(Val, Namespace == "Processor" and Name == "UtilizationPercentage"),'
                '     available_memory_mb = avgif(Val, Namespace == "Memory" and Name == "AvailableMB"),'
                '     disk_free_pct = avgif(Val, Namespace == "LogicalDisk" and Name == "FreeSpacePercentage")'
            )

            metrics_response = client.query_workspace(
                workspace_id=workspace_id,
                query=metrics_kql,
                timespan="PT5M",
            )

            cpu_pct: Optional[float] = None
            available_memory_mb: Optional[float] = None
            disk_free_pct: Optional[float] = None

            if metrics_response.status == LogsQueryStatus.SUCCESS:
                for table in metrics_response.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        row_dict = dict(zip(col_names, row))
                        cpu_val = row_dict.get("cpu_pct")
                        mem_val = row_dict.get("available_memory_mb")
                        disk_val = row_dict.get("disk_free_pct")
                        if cpu_val is not None and str(cpu_val) != "":
                            cpu_pct = float(str(cpu_val))
                        if mem_val is not None and str(mem_val) != "":
                            available_memory_mb = float(str(mem_val))
                        if disk_val is not None and str(disk_val) != "":
                            disk_free_pct = float(str(disk_val))

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "query_vm_guest_health: complete | resource=%s heartbeat=%s duration_ms=%d",
                resource_id,
                heartbeat_status,
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "heartbeat_status": heartbeat_status,
                "last_heartbeat_minutes_ago": minutes_ago,
                "cpu_utilization_pct": cpu_pct,
                "available_memory_mb": available_memory_mb,
                "disk_free_pct": disk_free_pct,
                "ama_data_available": cpu_pct is not None or available_memory_mb is not None,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_vm_guest_health error: %s", exc)
            return {
                "error": str(exc),
                "resource_id": resource_id,
                "query_status": "error",
                "duration_ms": duration_ms,
            }


def _safe_float(val: Any) -> Optional[float]:
    """Convert a value to float, returning None for empty or None values."""
    if val is None:
        return None
    s = str(val)
    if s == "":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


@ai_function
def query_ama_guest_metrics(
    resource_id: str,
    workspace_id: str,
    timespan_hours: int = 24,
    thread_id: str = "",
) -> Dict[str, Any]:
    """Query AMA InsightsMetrics for hourly CPU, memory, and disk IOPS buckets.

    Returns time-series data binned into 1-hour buckets with cpu_p50,
    cpu_p95, memory_avg_mb, and disk_iops for trend analysis and
    capacity planning.

    Args:
        resource_id: Azure resource ID of the VM.
        workspace_id: Log Analytics workspace ID.
        timespan_hours: Look-back window in hours (default: 24).
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with buckets list (hourly aggregations) and metadata.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_ama_guest_metrics",
        tool_parameters={"resource_id": resource_id, "timespan_hours": timespan_hours},
        correlation_id=resource_id,
        thread_id=thread_id,
    ):
        try:
            if not workspace_id:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "query_status": "skipped",
                    "reason": "workspace_id is empty",
                    "duration_ms": duration_ms,
                }

            if LogsQueryClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-monitor-query not installed",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            client = LogsQueryClient(credential)

            kql = (
                "InsightsMetrics"
                f' | where _ResourceId =~ "{resource_id}"'
                f" | where TimeGenerated > ago({timespan_hours}h)"
                ' | where Namespace in ("Processor", "Memory", "LogicalDisk")'
                " | summarize"
                '     cpu_p50 = percentile(iff(Namespace == "Processor" and Name == "UtilizationPercentage", Val, real(null)), 50),'
                '     cpu_p95 = percentile(iff(Namespace == "Processor" and Name == "UtilizationPercentage", Val, real(null)), 95),'
                '     memory_avg_mb = avg(iff(Namespace == "Memory" and Name == "AvailableMB", Val, real(null))),'
                '     disk_iops = avg(iff(Namespace == "LogicalDisk" and Name == "TransfersPerSecond", Val, real(null)))'
                "     by bin(TimeGenerated, 1h)"
                " | order by TimeGenerated asc"
            )

            response = client.query_workspace(
                workspace_id=workspace_id,
                query=kql,
                timespan=f"PT{timespan_hours}H",
            )

            buckets: List[Dict[str, Any]] = []

            if response.status == LogsQueryStatus.SUCCESS:
                for table in response.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        row_dict = dict(zip(col_names, [str(v) if v is not None else None for v in row]))
                        buckets.append({
                            "timestamp": row_dict.get("TimeGenerated"),
                            "cpu_p50": _safe_float(row_dict.get("cpu_p50")),
                            "cpu_p95": _safe_float(row_dict.get("cpu_p95")),
                            "memory_avg_mb": _safe_float(row_dict.get("memory_avg_mb")),
                            "disk_iops": _safe_float(row_dict.get("disk_iops")),
                        })

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "query_ama_guest_metrics: complete | resource=%s buckets=%d duration_ms=%d",
                resource_id,
                len(buckets),
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "workspace_id": workspace_id,
                "timespan_hours": timespan_hours,
                "buckets": buckets,
                "total_buckets": len(buckets),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_ama_guest_metrics error: %s", exc)
            return {
                "error": str(exc),
                "resource_id": resource_id,
                "query_status": "error",
                "duration_ms": duration_ms,
            }
