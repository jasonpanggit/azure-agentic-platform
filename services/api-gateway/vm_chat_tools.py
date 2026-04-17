"""VM Chat function-calling tools.

Live Azure SDK tool functions exposed to the LLM via chat.completions
function calling. Each function is intentionally narrow and never raises —
errors are returned as structured dicts so the LLM can report them cleanly.

Tools:
  get_vm_metrics         — CPU, memory, disk, network metrics via Azure Monitor
  get_activity_logs      — ARM activity log events for the VM
  get_resource_health    — Azure Resource Health availability state
  get_vm_power_state     — Current power state via Resource Graph ARG
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subscription ID helper
# ---------------------------------------------------------------------------

def _extract_subscription_id(resource_id: str) -> str:
    parts = resource_id.lower().split("/")
    idx = parts.index("subscriptions")
    return resource_id.split("/")[idx + 1]


# ---------------------------------------------------------------------------
# SDK enum compat helper
# ---------------------------------------------------------------------------

def _str_val(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return obj.value if hasattr(obj, "value") else str(obj)


# ---------------------------------------------------------------------------
# Tool: get_vm_metrics
# ---------------------------------------------------------------------------

def get_vm_metrics(
    resource_id: str,
    credential: Any,
    metric_names: Optional[list[str]] = None,
    timespan_hours: int = 1,
    interval: str = "PT5M",
) -> dict:
    """Fetch Azure Monitor platform metrics for a VM.

    Args:
        resource_id: Full ARM resource ID of the VM.
        credential: DefaultAzureCredential instance.
        metric_names: List of metric names. Defaults to CPU + memory + disk + network.
        timespan_hours: How many hours back to query (default 1).
        interval: ISO 8601 granularity (default PT5M = 5-minute buckets).

    Returns:
        Dict with metrics data or error.
    """
    if metric_names is None:
        metric_names = [
            "Percentage CPU",
            "Available Memory Bytes",
            "Disk Read Bytes",
            "Disk Write Bytes",
            "Network In Total",
            "Network Out Total",
        ]

    start = time.monotonic()
    try:
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        client = MonitorManagementClient(credential, sub_id)

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=timespan_hours)
        timespan = f"{start_time.isoformat()}/{end_time.isoformat()}"

        response = client.metrics.list(
            resource_uri=resource_id,
            metricnames=",".join(metric_names),
            timespan=timespan,
            interval=interval,
            aggregation="Average,Maximum,Minimum",
        )

        results: dict[str, list] = {}
        for metric in response.value:
            name = _str_val(metric.name) or "unknown"
            unit = _str_val(metric.unit) or ""
            datapoints = []
            for ts in metric.timeseries:
                for dp in ts.data:
                    if dp.time_stamp and (dp.average is not None or dp.maximum is not None):
                        datapoints.append({
                            "timestamp": dp.time_stamp.isoformat(),
                            "average": round(dp.average, 2) if dp.average is not None else None,
                            "maximum": round(dp.maximum, 2) if dp.maximum is not None else None,
                            "minimum": round(dp.minimum, 2) if dp.minimum is not None else None,
                        })
            results[name] = {"unit": unit, "datapoints": datapoints[-12:]}  # last 12 points

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("vm_chat_tools: get_vm_metrics | resource=%s metrics=%d duration_ms=%d",
                    resource_id[-60:], len(results), duration_ms)
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "timespan_hours": timespan_hours,
            "interval": interval,
            "metrics": results,
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("vm_chat_tools: get_vm_metrics failed | resource=%s error=%s duration_ms=%d",
                       resource_id[-60:], exc, duration_ms)
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Tool: get_activity_logs
# ---------------------------------------------------------------------------

def get_activity_logs(
    resource_id: str,
    credential: Any,
    timespan_hours: int = 24,
    max_events: int = 20,
) -> dict:
    """Fetch ARM activity log events for a VM.

    Args:
        resource_id: Full ARM resource ID of the VM.
        credential: DefaultAzureCredential instance.
        timespan_hours: How many hours back to query (default 24).
        max_events: Maximum number of events to return (default 20).

    Returns:
        Dict with activity log events or error.
    """
    start = time.monotonic()
    try:
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        client = MonitorManagementClient(credential, sub_id)

        since = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
        filter_str = (
            f"eventTimestamp ge '{since.isoformat()}' "
            f"and resourceId eq '{resource_id}'"
        )

        events = []
        for event in client.activity_logs.list(filter=filter_str):
            events.append({
                "timestamp": event.event_timestamp.isoformat() if event.event_timestamp else None,
                "operation": _str_val(event.operation_name),
                "caller": event.caller,
                "status": _str_val(event.status),
                "level": _str_val(event.level),
                "description": event.description,
            })
            if len(events) >= max_events:
                break

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("vm_chat_tools: get_activity_logs | resource=%s events=%d duration_ms=%d",
                    resource_id[-60:], len(events), duration_ms)
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "timespan_hours": timespan_hours,
            "event_count": len(events),
            "events": events,
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("vm_chat_tools: get_activity_logs failed | resource=%s error=%s duration_ms=%d",
                       resource_id[-60:], exc, duration_ms)
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Tool: get_resource_health
# ---------------------------------------------------------------------------

def get_resource_health(resource_id: str, credential: Any) -> dict:
    """Fetch Azure Resource Health availability state for a VM.

    Args:
        resource_id: Full ARM resource ID of the VM.
        credential: DefaultAzureCredential instance.

    Returns:
        Dict with health state, summary, and reason or error.
    """
    start = time.monotonic()
    try:
        try:
            from azure.mgmt.resourcehealth import ResourceHealthMgmtClient as _RHClient  # type: ignore[import]
        except ImportError:
            from azure.mgmt.resourcehealth import MicrosoftResourceHealth as _RHClient  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        client = _RHClient(credential, sub_id)
        status = client.availability_statuses.get_by_resource(
            resource_uri=resource_id,
            expand="recommendedActions",
        )

        props = status.properties
        raw_state = props.availability_state
        health_state = raw_state.value if hasattr(raw_state, "value") else str(raw_state)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("vm_chat_tools: get_resource_health | resource=%s state=%s duration_ms=%d",
                    resource_id[-60:], health_state, duration_ms)
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "health_state": health_state,
            "summary": props.summary,
            "reason_type": getattr(props, "reason_type", None),
            "occurred_time": getattr(props, "occurred_time", None) and props.occurred_time.isoformat(),
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("vm_chat_tools: get_resource_health failed | resource=%s error=%s duration_ms=%d",
                       resource_id[-60:], exc, duration_ms)
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Tool: get_vm_power_state
# ---------------------------------------------------------------------------

def get_vm_power_state(resource_id: str, credential: Any) -> dict:
    """Fetch current VM power state via Azure Resource Graph.

    Args:
        resource_id: Full ARM resource ID of the VM.
        credential: DefaultAzureCredential instance.

    Returns:
        Dict with power state (running/stopped/deallocated/unknown) or error.
    """
    start = time.monotonic()
    try:
        from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
        from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        kql = f"""
Resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines')
| where id =~ '{resource_id}'
| extend powerState = iff(
    type =~ 'microsoft.compute/virtualmachines',
    tostring(properties.extended.instanceView.powerState.displayStatus),
    tostring(properties.status.powerState)
  )
| extend vmSize = tostring(properties.hardwareProfile.vmSize)
| extend osType = tostring(properties.storageProfile.osDisk.osType)
| project id, name, location, vmSize, osType, powerState
"""
        client = ResourceGraphClient(credential)
        resp = client.resources(QueryRequest(subscriptions=[sub_id], query=kql.strip()))

        if not resp.data:
            return {"query_status": "not_found", "resource_id": resource_id}

        row = resp.data[0]
        raw_state = str(row.get("powerState", "")).lower()
        if "running" in raw_state:
            power_state = "running"
        elif "deallocated" in raw_state:
            power_state = "deallocated"
        elif "stopped" in raw_state:
            power_state = "stopped"
        else:
            power_state = raw_state or "unknown"

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("vm_chat_tools: get_vm_power_state | resource=%s state=%s duration_ms=%d",
                    resource_id[-60:], power_state, duration_ms)
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "name": row.get("name"),
            "location": row.get("location"),
            "vm_size": row.get("vmSize"),
            "os_type": row.get("osType"),
            "power_state": power_state,
            "power_state_raw": row.get("powerState"),
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("vm_chat_tools: get_vm_power_state failed | resource=%s error=%s duration_ms=%d",
                       resource_id[-60:], exc, duration_ms)
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# OpenAI function schemas
# ---------------------------------------------------------------------------

VM_CHAT_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_vm_metrics",
            "description": (
                "Fetch live Azure Monitor platform metrics for a VM: CPU percentage, "
                "available memory bytes, disk read/write bytes, network in/out. "
                "Use this when the user asks about performance, utilization, CPU usage, "
                "memory, disk I/O, or network throughput."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Metric names to fetch. Defaults to all standard metrics if omitted. "
                            "Valid values: 'Percentage CPU', 'Available Memory Bytes', "
                            "'Disk Read Bytes', 'Disk Write Bytes', "
                            "'Network In Total', 'Network Out Total'."
                        ),
                    },
                    "timespan_hours": {
                        "type": "integer",
                        "description": "How many hours back to query. Default 1. Use 24 for daily trend.",
                        "default": 1,
                    },
                    "interval": {
                        "type": "string",
                        "description": "Metric granularity as ISO 8601 duration. Default PT5M (5 min). Use PT1H for hourly.",
                        "default": "PT5M",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity_logs",
            "description": (
                "Fetch ARM activity log events for a VM: who did what, when, and whether it succeeded. "
                "Use this when the user asks about recent changes, operations, who restarted the VM, "
                "deployment history, or why something changed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timespan_hours": {
                        "type": "integer",
                        "description": "How many hours back to query. Default 24.",
                        "default": 24,
                    },
                    "max_events": {
                        "type": "integer",
                        "description": "Maximum number of events to return. Default 20.",
                        "default": 20,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_resource_health",
            "description": (
                "Fetch Azure Resource Health availability state for a VM: Available, Unavailable, "
                "Degraded, or Unknown. Includes summary and reason. "
                "Use this when the user asks about VM health, whether it is up/down, "
                "Azure platform issues, or resource health."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vm_power_state",
            "description": (
                "Fetch the current VM power state from Azure Resource Graph: "
                "running, stopped, deallocated, or unknown. Also returns VM size and OS type. "
                "Use this when the user asks if the VM is running, its current state, or VM details."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher — called by vm_chat.py when the LLM requests a tool
# ---------------------------------------------------------------------------

def dispatch_tool_call(
    tool_name: str,
    tool_args: dict,
    resource_id: str,
    credential: Any,
) -> str:
    """Execute a tool call and return result as a JSON string for the LLM."""
    logger.info("vm_chat_tools: dispatch | tool=%s args=%s", tool_name, tool_args)

    if tool_name == "get_vm_metrics":
        result = get_vm_metrics(
            resource_id=resource_id,
            credential=credential,
            metric_names=tool_args.get("metric_names"),
            timespan_hours=tool_args.get("timespan_hours", 1),
            interval=tool_args.get("interval", "PT5M"),
        )
    elif tool_name == "get_activity_logs":
        result = get_activity_logs(
            resource_id=resource_id,
            credential=credential,
            timespan_hours=tool_args.get("timespan_hours", 24),
            max_events=tool_args.get("max_events", 20),
        )
    elif tool_name == "get_resource_health":
        result = get_resource_health(resource_id=resource_id, credential=credential)
    elif tool_name == "get_vm_power_state":
        result = get_vm_power_state(resource_id=resource_id, credential=credential)
    else:
        result = {"query_status": "error", "error": f"Unknown tool: {tool_name}"}

    return json.dumps(result, default=str)
