"""VMSS Chat function-calling tools.

Live Azure SDK tool functions exposed to the LLM via chat.completions
function calling. Each function is intentionally narrow and never raises —
errors are returned as structured dicts so the LLM can report them cleanly.

Tools:
  get_vmss_info          — VMSS capacity/sku/provisioning state via ARG KQL
  get_vmss_instances     — List VM instances with power state (capped at 20)
  get_vmss_metrics       — CPU, memory, disk, network metrics via Azure Monitor
  get_vmss_autoscale     — Autoscale settings targeting this VMSS resource
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_subscription_id(resource_id: str) -> str:
    parts = resource_id.lower().split("/")
    idx = parts.index("subscriptions")
    return resource_id.split("/")[idx + 1]


def _extract_resource_group(resource_id: str) -> str:
    parts = resource_id.split("/")
    lower = [p.lower() for p in parts]
    try:
        idx = lower.index("resourcegroups")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return ""


def _str_val(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return obj.value if hasattr(obj, "value") else str(obj)


# ---------------------------------------------------------------------------
# Tool: get_vmss_info
# ---------------------------------------------------------------------------

def get_vmss_info(resource_id: str, credential: Any) -> dict:
    """Fetch VMSS basic info via Azure Resource Graph ARG KQL.

    Args:
        resource_id: Full ARM resource ID of the VMSS.
        credential: DefaultAzureCredential instance.

    Returns:
        Dict with name, location, sku_name, capacity, provisioning_state or error.
    """
    start = time.monotonic()
    try:
        from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
        from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        kql = f"""Resources
| where type =~ 'microsoft.compute/virtualmachinescalesets'
| where id =~ '{resource_id}'
| project name, location,
    sku_name = tostring(sku.name),
    capacity = toint(sku.capacity),
    provisioning_state = tostring(properties.provisioningState)
"""
        client = ResourceGraphClient(credential)
        resp = client.resources(QueryRequest(subscriptions=[sub_id], query=kql.strip()))

        if not resp.data:
            return {"query_status": "not_found", "resource_id": resource_id}

        row = resp.data[0]
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "vmss_chat_tools: get_vmss_info | resource=%s duration_ms=%d",
            resource_id[-60:], duration_ms,
        )
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "name": row.get("name"),
            "location": row.get("location"),
            "sku_name": row.get("sku_name"),
            "capacity": row.get("capacity"),
            "provisioning_state": row.get("provisioning_state"),
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "vmss_chat_tools: get_vmss_info failed | resource=%s error=%s duration_ms=%d",
            resource_id[-60:], exc, duration_ms,
        )
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Tool: get_vmss_instances
# ---------------------------------------------------------------------------

def get_vmss_instances(resource_id: str, credential: Any, max_instances: int = 20) -> dict:
    """List VM instances in a VMSS with power state from instanceView.

    Args:
        resource_id: Full ARM resource ID of the VMSS.
        credential: DefaultAzureCredential instance.
        max_instances: Maximum number of instances to return (default 20).

    Returns:
        Dict with instances list (instance_id, name, power_state, provisioning_state) or error.
    """
    start = time.monotonic()
    try:
        from azure.mgmt.compute import ComputeManagementClient  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        resource_group = _extract_resource_group(resource_id)
        vmss_name = resource_id.split("/")[-1]

        client = ComputeManagementClient(credential, sub_id)
        instances_paged = client.virtual_machine_scale_set_vms.list(
            resource_group, vmss_name, expand="instanceView"
        )

        instances = []
        for inst in instances_paged:
            power_state = "unknown"
            iv = inst.instance_view
            if iv and iv.statuses:
                for s in iv.statuses:
                    code = (s.code or "").lower()
                    if code.startswith("powerstate/"):
                        power_state = s.display_status or code
                        break

            instances.append({
                "instance_id": inst.instance_id or "",
                "name": inst.name or "",
                "power_state": power_state,
                "provisioning_state": inst.provisioning_state or "unknown",
            })

            if len(instances) >= max_instances:
                break

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "vmss_chat_tools: get_vmss_instances | resource=%s instances=%d duration_ms=%d",
            resource_id[-60:], len(instances), duration_ms,
        )
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "instance_count": len(instances),
            "capped_at": max_instances,
            "instances": instances,
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "vmss_chat_tools: get_vmss_instances failed | resource=%s error=%s duration_ms=%d",
            resource_id[-60:], exc, duration_ms,
        )
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Tool: get_vmss_metrics
# ---------------------------------------------------------------------------

def get_vmss_metrics(
    resource_id: str,
    credential: Any,
    metric_names: Optional[list[str]] = None,
    timespan_hours: int = 1,
    interval: str = "PT5M",
) -> dict:
    """Fetch Azure Monitor platform metrics for a VMSS.

    Args:
        resource_id: Full ARM resource ID of the VMSS.
        credential: DefaultAzureCredential instance.
        metric_names: List of metric names. Defaults to standard VMSS metrics.
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

        results: dict[str, Any] = {}
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
        logger.info(
            "vmss_chat_tools: get_vmss_metrics | resource=%s metrics=%d duration_ms=%d",
            resource_id[-60:], len(results), duration_ms,
        )
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "timespan_hours": timespan_hours,
            "interval": interval,
            "metrics": results,
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "vmss_chat_tools: get_vmss_metrics failed | resource=%s error=%s duration_ms=%d",
            resource_id[-60:], exc, duration_ms,
        )
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Tool: get_vmss_autoscale
# ---------------------------------------------------------------------------

def get_vmss_autoscale(resource_id: str, credential: Any) -> dict:
    """Fetch autoscale settings targeting this VMSS.

    Args:
        resource_id: Full ARM resource ID of the VMSS.
        credential: DefaultAzureCredential instance.

    Returns:
        Dict with min_count, max_count, default_count, enabled or
        {"query_status": "no_autoscale"} when no settings found.
    """
    start = time.monotonic()
    try:
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        resource_group = _extract_resource_group(resource_id)

        client = MonitorManagementClient(credential, sub_id)
        settings = list(client.autoscale_settings.list_by_resource_group(resource_group))

        for s in settings:
            target_uri = (s.target_resource_uri or "").lower()
            if resource_id.lower() in target_uri:
                profile = s.profiles[0] if s.profiles else None
                min_count = None
                max_count = None
                default_count = None
                if profile and profile.capacity:
                    cap = profile.capacity
                    min_count = int(cap.minimum) if cap.minimum is not None else None
                    max_count = int(cap.maximum) if cap.maximum is not None else None
                    default_count = int(cap.default) if cap.default is not None else None

                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "vmss_chat_tools: get_vmss_autoscale | resource=%s min=%s max=%s duration_ms=%d",
                    resource_id[-60:], min_count, max_count, duration_ms,
                )
                return {
                    "query_status": "success",
                    "resource_id": resource_id,
                    "enabled": getattr(s, "enabled", True),
                    "min_count": min_count,
                    "max_count": max_count,
                    "default_count": default_count,
                    "profile_count": len(s.profiles) if s.profiles else 0,
                }

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "vmss_chat_tools: get_vmss_autoscale | resource=%s no_autoscale duration_ms=%d",
            resource_id[-60:], duration_ms,
        )
        return {"query_status": "no_autoscale", "resource_id": resource_id}

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "vmss_chat_tools: get_vmss_autoscale failed | resource=%s error=%s duration_ms=%d",
            resource_id[-60:], exc, duration_ms,
        )
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# OpenAI function schemas
# ---------------------------------------------------------------------------

VMSS_CHAT_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_vmss_info",
            "description": (
                "Fetch VMSS basic information from Azure Resource Graph: name, location, "
                "SKU name, capacity (desired instance count), and provisioning state. "
                "Use this when the user asks about the VMSS configuration, SKU, size, "
                "or current capacity."
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
            "name": "get_vmss_instances",
            "description": (
                "List VM instances in the VMSS with their power state and provisioning state. "
                "Power state is read from the instance view (e.g. VM running, VM deallocated). "
                "Capped at 20 instances. Use this when the user asks about individual instances, "
                "which VMs are running, how many are healthy, or instance-level status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_instances": {
                        "type": "integer",
                        "description": "Maximum number of instances to return. Default 20.",
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
            "name": "get_vmss_metrics",
            "description": (
                "Fetch live Azure Monitor platform metrics for the VMSS: CPU percentage, "
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
            "name": "get_vmss_autoscale",
            "description": (
                "Fetch autoscale settings for the VMSS: minimum, maximum, and default instance counts, "
                "and whether autoscale is enabled. Returns no_autoscale status when no settings exist. "
                "Use this when the user asks about autoscaling, scaling rules, min/max capacity, "
                "or why the VMSS scaled up or down."
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
# Tool dispatcher — called by vmss_chat.py when the LLM requests a tool
# ---------------------------------------------------------------------------

def dispatch_tool_call(
    tool_name: str,
    tool_args: dict,
    resource_id: str,
    credential: Any,
) -> str:
    """Execute a tool call and return result as a JSON string for the LLM."""
    logger.info("vmss_chat_tools: dispatch | tool=%s args=%s", tool_name, tool_args)

    if tool_name == "get_vmss_info":
        result = get_vmss_info(resource_id=resource_id, credential=credential)
    elif tool_name == "get_vmss_instances":
        result = get_vmss_instances(
            resource_id=resource_id,
            credential=credential,
            max_instances=tool_args.get("max_instances", 20),
        )
    elif tool_name == "get_vmss_metrics":
        result = get_vmss_metrics(
            resource_id=resource_id,
            credential=credential,
            metric_names=tool_args.get("metric_names"),
            timespan_hours=tool_args.get("timespan_hours", 1),
            interval=tool_args.get("interval", "PT5M"),
        )
    elif tool_name == "get_vmss_autoscale":
        result = get_vmss_autoscale(resource_id=resource_id, credential=credential)
    else:
        result = {"query_status": "error", "error": f"Unknown tool: {tool_name}"}

    return json.dumps(result, default=str)
