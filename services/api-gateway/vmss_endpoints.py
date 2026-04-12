"""VMSS inventory and chat endpoints.

GET  /api/v1/vmss                          — list VMSS in subscriptions via ARG
GET  /api/v1/vmss/{resource_id_base64}     — VMSS detail including instances
GET  /api/v1/vmss/{resource_id_base64}/metrics — Azure Monitor metrics
POST /api/v1/vmss/{resource_id_base64}/chat    — resource-scoped chat

When the Azure SDK packages are unavailable, all list endpoints return empty
structured responses matching the shape the frontend expects.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from services.api_gateway.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vmss", tags=["vmss"])

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]
    _ARG_AVAILABLE = True
except ImportError:
    _ARG_AVAILABLE = False
    logger.warning("azure-mgmt-resourcegraph not available — VMSS list returns empty")

try:
    from azure.mgmt.resourcehealth import ResourceHealthMgmtClient as _RHClient  # type: ignore[import]
except ImportError:
    try:
        from azure.mgmt.resourcehealth import MicrosoftResourceHealth as _RHClient  # type: ignore[import,no-redef]
    except ImportError:
        _RHClient = None  # type: ignore[assignment,misc]

# VMSS platform metric names for Azure Monitor queries.
# NOTE: "VM Scale Set VM Instance Count" is NOT a metric — it is vmss.sku.capacity (ARM property).
# VmAvailabilityMetric is the per-instance availability signal for VMSS.
_VMSS_METRIC_NAMES = [
    "Percentage CPU",
    "Available Memory Bytes",
    "Network In Total",
    "Network Out Total",
    "Disk Read Bytes",
    "Disk Write Bytes",
    "Disk Read Operations/Sec",
    "Disk Write Operations/Sec",
    "VmAvailabilityMetric",
    "OS Disk Queue Depth",
]


def _log_sdk_availability() -> None:
    logger.info(
        "vmss_endpoints: azure-mgmt-resourcegraph available=%s resource-health available=%s",
        _ARG_AVAILABLE, _RHClient is not None,
    )


_log_sdk_availability()


def _decode_resource_id(encoded: str) -> str:
    """Decode base64url-encoded ARM resource ID."""
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    try:
        return base64.urlsafe_b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Invalid resource ID encoding: {exc}") from exc


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from ARM resource ID."""
    parts = resource_id.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "subscriptions" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _get_vmss_health_states(
    resource_ids: List[str],
    credential: Any,
) -> Dict[str, str]:
    """Fetch Resource Health availability states for a list of VMSS resource IDs.

    Modelled on vm_inventory._get_health_states_sync().  Returns a dict mapping
    resource_id.lower() → availability_state string (e.g. "Available",
    "Unavailable", "Unknown").  Returns {} when the Resource Health SDK is
    unavailable or any unrecoverable error occurs.
    """
    if _RHClient is None:
        return {}

    results: Dict[str, str] = {}
    for rid in resource_ids:
        parts = rid.split("/")
        try:
            idx = [p.lower() for p in parts].index("subscriptions")
            sub_id = parts[idx + 1]
        except (ValueError, IndexError):
            results[rid.lower()] = "Unknown"
            continue
        try:
            client = _RHClient(credential, sub_id)
            status = client.availability_statuses.get_by_resource(
                resource_uri=rid,
                expand="recommendedActions",
            )
            raw_state = (
                status.properties.availability_state
                if status.properties and status.properties.availability_state
                else None
            )
            if raw_state is None:
                state = "Unknown"
            elif hasattr(raw_state, "value"):
                state = raw_state.value
            else:
                state = str(raw_state)
            results[rid.lower()] = state
        except Exception as exc:
            logger.debug("vmss_health: failed resource=%s error=%s", rid[:80], exc)
            results[rid.lower()] = "Unknown"

    return results


def _fetch_single_metric(
    client: Any,
    resource_id: str,
    metric_name: str,
    timespan: str,
    interval: str,
) -> Optional[Dict[str, Any]]:
    """Fetch a single metric from Azure Monitor for a VMSS resource.

    Returns a parsed metric dict ``{name, unit, timeseries}`` or ``None`` when
    the metric is unsupported or returns no data.  Exceptions are caught
    per-metric so one unsupported metric cannot poison the whole batch.
    """
    try:
        response = client.metrics.list(
            resource_uri=resource_id,
            metricnames=metric_name,
            timespan=timespan,
            interval=interval,
            aggregation="Average,Maximum,Minimum",
        )
        for metric in response.value:
            timeseries = []
            for ts in metric.timeseries:
                for dp in ts.data:
                    if dp.time_stamp:
                        timeseries.append({
                            "timestamp": dp.time_stamp.isoformat(),
                            "average": dp.average,
                            "maximum": dp.maximum,
                            "minimum": dp.minimum,
                        })
            name_val = (
                metric.name.value if hasattr(metric.name, "value")
                else str(metric.name) if metric.name else None
            )
            unit_val = (
                metric.unit.value if hasattr(metric.unit, "value")
                else str(metric.unit) if metric.unit else None
            )
            return {"name": name_val, "unit": unit_val, "timeseries": timeseries}
        # response.value was empty — metric unsupported for this SKU
        return None
    except Exception as exc:
        logger.warning("vmss_metrics: skipping metric=%r error=%s", metric_name, exc)
        return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class VMSSChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None


class VMSSChatResponse(BaseModel):
    thread_id: str
    run_id: str
    status: str = "created"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_vmss(
    subscriptions: str = Query(..., description="Comma-separated subscription IDs"),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """List VMSS across subscriptions via Azure Resource Graph.

    Returns structured empty response when ARG SDK unavailable.
    """
    start_time = time.monotonic()
    subscription_ids = [s.strip() for s in subscriptions.split(",") if s.strip()]

    if not _ARG_AVAILABLE or not subscription_ids:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_list: sdk_unavailable duration_ms=%.1f", duration_ms)
        return {"vmss": [], "total": 0}

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        credential = DefaultAzureCredential()
        client = ResourceGraphClient(credential)

        kql = """Resources
| where type =~ 'microsoft.compute/virtualmachinescalesets'
| project id, name, resourceGroup, subscriptionId, location,
    sku = tostring(sku.name),
    instance_count = toint(sku.capacity),
    os_type = tostring(properties.virtualMachineProfile.storageProfile.osDisk.osType),
    os_image_version = strcat(
        tostring(properties.virtualMachineProfile.storageProfile.imageReference.offer),
        ' ',
        tostring(properties.virtualMachineProfile.storageProfile.imageReference.sku)
    ),
    power_state = 'running',
    health_state = 'unknown',
    autoscale_enabled = false,
    active_alert_count = 0"""

        if search:
            search_safe = search.replace("'", "")
            kql += f"\n| where name contains '{search_safe}'"

        kql += f"\n| limit {limit}"

        request = QueryRequest(subscriptions=subscription_ids, query=kql)
        response = client.resources(request)
        rows = response.data or []

        vmss_list = [
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "resource_group": r.get("resourceGroup", ""),
                "subscription_id": r.get("subscriptionId", ""),
                "location": r.get("location", ""),
                "sku": r.get("sku", ""),
                "instance_count": r.get("instance_count", 0),
                "healthy_instance_count": r.get("instance_count", 0),
                "os_type": r.get("os_type", ""),
                "os_image_version": (r.get("os_image_version") or "").strip(),
                "power_state": r.get("power_state", "running"),
                "health_state": r.get("health_state", "unknown"),
                "autoscale_enabled": r.get("autoscale_enabled", False),
                "active_alert_count": r.get("active_alert_count", 0),
            }
            for r in rows
        ]

        # Enrich health_state from Resource Health API (best-effort, falls back to "unknown")
        if vmss_list:
            import asyncio
            resource_ids = [item["id"] for item in vmss_list if item["id"]]
            loop = asyncio.get_event_loop()
            health_map = await loop.run_in_executor(
                None, _get_vmss_health_states, resource_ids, credential
            )
            for item in vmss_list:
                state = health_map.get(item["id"].lower(), "unknown")
                item["health_state"] = state.lower()
                # Derive power_state from health_state
                if state.lower() == "available":
                    item["power_state"] = "Running"
                elif state.lower() != "unknown":
                    item["power_state"] = state.capitalize()

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_list: total=%d duration_ms=%.1f", len(vmss_list), duration_ms)
        return {"vmss": vmss_list, "total": len(vmss_list)}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("vmss_list: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"vmss": [], "total": 0}


@router.get("/{resource_id_base64}")
async def get_vmss_detail(
    resource_id_base64: str,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get VMSS detail including instances and autoscale config.

    Returns structured stub when SDK unavailable.
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    if not _ARG_AVAILABLE:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_detail: sdk_unavailable resource_id=%s duration_ms=%.1f", resource_id[:60], duration_ms)
        return {
            "id": resource_id,
            "name": resource_id.split("/")[-1],
            "resource_group": "",
            "subscription_id": _extract_subscription_id(resource_id),
            "location": "",
            "sku": "",
            "instance_count": 0,
            "healthy_instance_count": 0,
            "os_type": "",
            "os_image_version": "",
            "power_state": "unknown",
            "health_state": "unknown",
            "autoscale_enabled": False,
            "active_alert_count": 0,
            "min_count": 0,
            "max_count": 0,
            "upgrade_policy": "",
            "health_summary": None,
            "active_incidents": [],
            "instances": [],
        }

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.compute import ComputeManagementClient  # type: ignore[import]
        credential = DefaultAzureCredential()
        subscription_id = _extract_subscription_id(resource_id)
        parts = resource_id.split("/")
        rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
        resource_group = parts[rg_index + 1] if rg_index >= 0 else ""
        vmss_name = parts[-1]

        compute_client = ComputeManagementClient(credential, subscription_id)
        vmss = compute_client.virtual_machine_scale_sets.get(resource_group, vmss_name)
        instances_paged = compute_client.virtual_machine_scale_set_vms.list(resource_group, vmss_name)
        instances = [
            {
                "instance_id": inst.instance_id or "",
                "name": inst.name or "",
                "power_state": (inst.instance_view.statuses[-1].display_status if inst.instance_view and inst.instance_view.statuses else "unknown"),
                "health_state": "unknown",
                "provisioning_state": inst.provisioning_state or "unknown",
            }
            for inst in instances_paged
        ]

        autoscale_settings: Dict[str, Any] = {"min_count": 1, "max_count": 10}
        try:
            from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]
            monitor_client = MonitorManagementClient(credential, subscription_id)
            settings = list(monitor_client.autoscale_settings.list_by_resource_group(resource_group))
            for s in settings:
                if resource_id.lower() in (s.target_resource_uri or "").lower():
                    profile = s.profiles[0] if s.profiles else None
                    if profile:
                        autoscale_settings["min_count"] = int(profile.capacity.minimum or 1)
                        autoscale_settings["max_count"] = int(profile.capacity.maximum or 10)
                    autoscale_settings["enabled"] = True
                    break
        except Exception as autoscale_exc:
            logger.warning("vmss_detail: autoscale query failed error=%s", autoscale_exc)

        # Derive healthy_instance_count from running instances (power_state contains "running")
        total = int(vmss.sku.capacity or 0) if vmss.sku else 0
        running_count = sum(
            1 for inst in instances
            if "running" in (inst.get("power_state") or "").lower()
        )
        healthy_instance_count = running_count if instances else total

        # Derive health_state from healthy ratio
        if total == 0:
            health_state = "unknown"
        elif healthy_instance_count == total:
            health_state = "available"
        elif healthy_instance_count == 0:
            health_state = "unavailable"
        else:
            health_state = "degraded"

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_detail: resource_id=%s instances=%d healthy=%d health_state=%s duration_ms=%.1f", resource_id[:60], len(instances), healthy_instance_count, health_state, duration_ms)
        return {
            "id": resource_id,
            "name": vmss.name or vmss_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "location": vmss.location or "",
            "sku": vmss.sku.name if vmss.sku else "",
            "instance_count": total,
            "healthy_instance_count": healthy_instance_count,
            "os_type": "",
            "os_image_version": "",
            "power_state": "running",
            "health_state": health_state,
            "autoscale_enabled": autoscale_settings.get("enabled", False),
            "active_alert_count": 0,
            "min_count": autoscale_settings["min_count"],
            "max_count": autoscale_settings["max_count"],
            "upgrade_policy": (vmss.upgrade_policy.mode.value if vmss.upgrade_policy and vmss.upgrade_policy.mode else ""),
            "health_summary": None,
            "active_incidents": [],
            "instances": instances,
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("vmss_detail: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"error": str(exc)}


@router.get("/{resource_id_base64}/metrics")
async def get_vmss_metrics(
    resource_id_base64: str,
    timespan: str = Query("PT24H"),
    interval: str = Query("PT5M"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get Azure Monitor metrics for a VMSS.

    Each metric is fetched concurrently.  Falls back to empty metrics list when
    the Monitor SDK is unavailable or the resource returns no data.
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"resource_id": "", "timespan": timespan, "interval": interval, "metrics": []}

    sub_id = _extract_subscription_id(resource_id)
    if not sub_id:
        return {"resource_id": resource_id, "timespan": timespan, "interval": interval, "metrics": []}

    try:
        import asyncio
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]

        credential = DefaultAzureCredential()
        client = MonitorManagementClient(credential, sub_id)
        loop = asyncio.get_event_loop()

        tasks = [
            loop.run_in_executor(
                None,
                _fetch_single_metric,
                client,
                resource_id,
                name,
                timespan,
                interval,
            )
            for name in _VMSS_METRIC_NAMES
        ]
        results = await asyncio.gather(*tasks)
        metrics_out = [r for r in results if r is not None]

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "vmss_metrics: resource=%s requested=%d returned=%d duration_ms=%.0f",
            resource_id[-60:], len(_VMSS_METRIC_NAMES), len(metrics_out), duration_ms,
        )
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "interval": interval,
            "metrics": metrics_out,
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "vmss_metrics: failed resource=%s error=%s duration_ms=%.0f",
            resource_id[-60:], exc, duration_ms,
        )
        return {"resource_id": resource_id, "timespan": timespan, "interval": interval, "metrics": []}


@router.post("/{resource_id_base64}/chat")
async def vmss_chat(
    resource_id_base64: str,
    request: VMSSChatRequest,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Resource-scoped chat for VMSS investigation.

    Routes to the compute agent directly (same as VM chat).
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    try:
        from services.api_gateway.foundry import _get_foundry_client  # type: ignore[import]
        from services.api_gateway.chat import create_chat_thread  # type: ignore[import]

        agent_id = os.environ.get("COMPUTE_AGENT_ID", "")
        if not agent_id:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning("vmss_chat: COMPUTE_AGENT_ID not set duration_ms=%.1f", duration_ms)
            return {"error": "COMPUTE_AGENT_ID not configured"}

        context = f"Resource: {resource_id}\nMessage: {request.message}"
        thread_id, run_id = await create_chat_thread(
            agent_id=agent_id,
            message=context,
            thread_id=request.thread_id,
        )
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_chat: thread_id=%s run_id=%s duration_ms=%.1f", thread_id, run_id, duration_ms)
        return {"thread_id": thread_id, "run_id": run_id, "status": "created"}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("vmss_chat: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"error": str(exc)}
