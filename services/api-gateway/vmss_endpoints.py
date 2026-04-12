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


def _log_sdk_availability() -> None:
    logger.info("vmss_endpoints: azure-mgmt-resourcegraph available=%s", _ARG_AVAILABLE)


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
    health_state = iff(tostring(properties.provisioningState) =~ 'Succeeded', 'available', iff(tostring(properties.provisioningState) =~ 'Failed', 'degraded', 'unknown')),
    autoscale_enabled = tobool(coalesce(tobool(properties.automaticRepairsPolicy.enabled), false)),
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
        except Exception:
            pass

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_detail: resource_id=%s instances=%d duration_ms=%.1f", resource_id[:60], len(instances), duration_ms)
        return {
            "id": resource_id,
            "name": vmss.name or vmss_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "location": vmss.location or "",
            "sku": vmss.sku.name if vmss.sku else "",
            "instance_count": int(vmss.sku.capacity or 0) if vmss.sku else 0,
            "healthy_instance_count": int(vmss.sku.capacity or 0) if vmss.sku else 0,
            "os_type": (vmss.virtual_machine_profile.storage_profile.os_disk.os_type.value
                        if vmss.virtual_machine_profile and vmss.virtual_machine_profile.storage_profile
                        and vmss.virtual_machine_profile.storage_profile.os_disk
                        and vmss.virtual_machine_profile.storage_profile.os_disk.os_type
                        else ""),
            "os_image_version": " ".join(filter(None, [
                (vmss.virtual_machine_profile.storage_profile.image_reference.offer
                 if vmss.virtual_machine_profile and vmss.virtual_machine_profile.storage_profile
                 and vmss.virtual_machine_profile.storage_profile.image_reference else ""),
                (vmss.virtual_machine_profile.storage_profile.image_reference.sku
                 if vmss.virtual_machine_profile and vmss.virtual_machine_profile.storage_profile
                 and vmss.virtual_machine_profile.storage_profile.image_reference else ""),
            ])).strip(),
            "power_state": "running",
            "health_state": ("available" if vmss.provisioning_state == "Succeeded"
                             else "degraded" if vmss.provisioning_state == "Failed"
                             else "unknown"),
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
            "fetch_error": str(exc),
        }


@router.get("/{resource_id_base64}/metrics")
async def get_vmss_metrics(
    resource_id_base64: str,
    timespan: str = Query("PT24H"),
    interval: str = Query("PT5M"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get Azure Monitor metrics for a VMSS."""
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"resource_id": "", "timespan": timespan, "interval": interval, "metrics": []}

    # Return empty metrics stub — real metrics implementation deferred to Phase 36
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("vmss_metrics: resource_id=%s timespan=%s duration_ms=%.1f", resource_id[:60], timespan, duration_ms)
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
