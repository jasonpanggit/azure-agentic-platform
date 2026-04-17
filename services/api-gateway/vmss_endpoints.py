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

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential
from services.api_gateway.federation import resolve_subscription_ids

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


# ---------------------------------------------------------------------------
# Metrics constants
# ---------------------------------------------------------------------------

VMSS_DEFAULT_METRICS = [
    "Percentage CPU",
    "Available Memory Bytes",
    "Disk Read Bytes",
    "Disk Write Bytes",
    "Disk Read Operations/Sec",
    "Disk Write Operations/Sec",
    "Network In Total",
    "Network Out Total",
    "VM Scale Set VM Instance Count",
    "OS Disk Queue Depth",
]


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


def _enum_value(obj: Any, default: str) -> str:
    """Safely extract a string value from an Azure SDK enum or plain string.

    Azure SDK enums expose a `.value` attribute containing the canonical string
    (e.g. ``OperatingSystemTypes.linux.value == "Linux"``). Calling ``str()``
    on the enum object produces the full qualified name which is wrong for display.
    """
    if obj is None:
        return default
    if hasattr(obj, "value"):
        return obj.value or default
    return str(obj) or default


def _extract_os_image_version(offer: str, sku: str, gallery_id: str) -> str:
    """Return a human-readable OS image version string.

    Priority:
    1. Marketplace image  → ``"<offer> <sku>"``   (e.g. ``"UbuntuServer 18.04-LTS"``)
    2. Shared Image Gallery → last ``versions/<ver>`` segment of the ARM resource ID
       (e.g. ``.../versions/202603.12.1`` → ``"202603.12.1"``)
    3. Empty string when neither is available.
    """
    offer = (offer or "").strip()
    sku = (sku or "").strip()
    if offer and sku:
        return f"{offer} {sku}"
    if offer:
        return offer
    gallery_id = (gallery_id or "").strip()
    if gallery_id:
        parts = gallery_id.split("/")
        try:
            ver_idx = next(i for i, p in enumerate(parts) if p.lower() == "versions")
            return parts[ver_idx + 1] if ver_idx + 1 < len(parts) else ""
        except StopIteration:
            pass
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


def _get_vmss_instance_counts(
    subscription_ids: List[str],
    credential: Any,
) -> Dict[str, int]:
    """Query ARG for actual VMSS VM instance counts.

    Returns a dict mapping parent VMSS resource_id.lower() → running instance
    count.  Falls back to empty dict on any error.  This supplements
    ``sku.capacity`` which may be 0 for AKS-managed VMSS.
    """
    if not _ARG_AVAILABLE:
        return {}

    kql = """Resources
| where type =~ 'microsoft.compute/virtualmachinescalesets/virtualmachines'
| extend vmssId = tolower(strcat_array(array_slice(split(id, '/'), 0, 8), '/'))
| summarize instance_count = count() by vmssId"""

    try:
        client = ResourceGraphClient(credential)
        request = QueryRequest(subscriptions=subscription_ids, query=kql)
        response = client.resources(request)
        rows = response.data or []
        return {
            r.get("vmssId", "").lower(): int(r.get("instance_count", 0) or 0)
            for r in rows
        }
    except Exception as exc:
        logger.debug("vmss_instance_counts: failed error=%s", exc)
        return {}


def _enrich_aks_vmss_node_counts(
    vmss_list: List[Dict[str, Any]],
    credential: Any,
) -> None:
    """Enrich instance_count / healthy_instance_count for AKS-managed VMSS in-place.

    AKS-managed VMSS live in resource groups that start with "MC_" and have
    sku.capacity == 0 in ARG because AKS controls scaling internally.  This
    helper calls ``agent_pools.list()`` for each unique (subscription, cluster)
    pair and patches the matching VMSS items that still show instance_count == 0
    after the ARG VM count query.

    Non-AKS or already-correct items are left unchanged.  All errors are
    swallowed so the list endpoint still returns ARG data if AKS calls fail.
    """
    try:
        from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]
    except ImportError:
        return

    # Find AKS-managed VMSS items that still show instance_count == 0
    aks_items = [
        item for item in vmss_list
        if item.get("resource_group", "").upper().startswith("MC_")
        and item.get("instance_count", 0) == 0
    ]
    if not aks_items:
        return

    # Build unique (subscription_id, original_rg, cluster_name) tuples
    # MC_<original-rg>_<cluster-name>_<location>
    cluster_map: Dict[str, Any] = {}  # key = "sub/rg/cluster"
    for item in aks_items:
        mc_rg = item.get("resource_group", "")
        sub_id = item.get("subscription_id", "")
        parts = mc_rg.split("_")
        if len(parts) < 4:
            continue
        # e.g. MC_rg-srelab-australiaeast_aks-srelab_australiaeast
        original_rg = parts[1]
        cluster_name = parts[2]
        key = f"{sub_id}/{original_rg}/{cluster_name}"
        if key not in cluster_map:
            cluster_map[key] = {"sub_id": sub_id, "original_rg": original_rg, "cluster_name": cluster_name, "pools": []}

    # Fetch agent pools for each cluster
    for key, info in cluster_map.items():
        try:
            aks_client = ContainerServiceClient(credential, info["sub_id"])
            pools = list(aks_client.agent_pools.list(info["original_rg"], info["cluster_name"]))
            cluster_map[key]["pools"] = pools
        except Exception as exc:
            logger.debug("vmss_list: aks agent_pools.list failed cluster=%s error=%s", key, exc)

    # Match pools to VMSS items by pool name appearing in VMSS name
    for item in aks_items:
        mc_rg = item.get("resource_group", "")
        sub_id = item.get("subscription_id", "")
        parts = mc_rg.split("_")
        if len(parts) < 4:
            continue
        original_rg = parts[1]
        cluster_name = parts[2]
        key = f"{sub_id}/{original_rg}/{cluster_name}"
        pools = cluster_map.get(key, {}).get("pools", [])
        vmss_name = (item.get("name") or "").lower()
        for pool in pools:
            pool_name = (pool.name or "").lower()
            if pool_name and f"-{pool_name}-" in vmss_name:
                pool_count = pool.count or 0
                power_code = getattr(getattr(pool, "power_state", None), "code", None)
                running = pool_count if (power_code and power_code.lower() == "running") else 0
                item["instance_count"] = pool_count
                item["healthy_instance_count"] = running
                break


def _fetch_single_metric_vmss(
    client: Any,
    resource_id: str,
    metric_name: str,
    timespan: str,
    interval: str,
) -> Optional[Dict[str, Any]]:
    """Fetch a single VMSS metric from Azure Monitor.

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
        return None
    except Exception as exc:
        logger.warning(
            "vmss_metrics: skipping metric=%r | error=%s", metric_name, exc
        )
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
    reply: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_vmss(
    subscriptions: Optional[str] = Query(
        None,
        description="Comma-separated subscription IDs. Omit to query all registered subscriptions.",
    ),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _token: str = Depends(verify_token),
    request: Request = None,
) -> Dict[str, Any]:
    """List VMSS across subscriptions via Azure Resource Graph.

    Returns structured empty response when ARG SDK unavailable.
    """
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscriptions, request)

    if not _ARG_AVAILABLE or not subscription_ids:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_list: sdk_unavailable duration_ms=%.1f", duration_ms)
        return {"vmss": [], "total": 0}

    try:
        import asyncio
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        credential = DefaultAzureCredential()
        client = ResourceGraphClient(credential)

        kql = """Resources
| where type =~ 'microsoft.compute/virtualmachinescalesets'
| project id, name, resourceGroup, subscriptionId, location,
    sku = tostring(sku.name),
    instance_count = toint(coalesce(toint(sku.capacity), 0)),
    os_type = tostring(properties.virtualMachineProfile.storageProfile.osDisk.osType),
    os_image_offer = tostring(properties.virtualMachineProfile.storageProfile.imageReference.offer),
    os_image_sku = tostring(properties.virtualMachineProfile.storageProfile.imageReference.sku),
    os_image_gallery_id = tostring(properties.virtualMachineProfile.storageProfile.imageReference.id),
    power_state = 'running',
    health_state = iff(tostring(properties.provisioningState) =~ 'Succeeded', 'available', iff(tostring(properties.provisioningState) =~ 'Failed', 'degraded', 'unknown')),
    autoscale_raw = tostring(properties.automaticRepairsPolicy.enabled),
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
                "instance_count": r.get("instance_count", 0) or 0,
                "healthy_instance_count": r.get("instance_count", 0) or 0,
                "os_type": r.get("os_type", ""),
                # Prefer Marketplace offer+sku; fall back to gallery image version
                # extracted from the ARM path (e.g. ".../versions/202603.12.1")
                "os_image_version": _extract_os_image_version(
                    r.get("os_image_offer") or "",
                    r.get("os_image_sku") or "",
                    r.get("os_image_gallery_id") or "",
                ),
                "power_state": r.get("power_state", "running"),
                "health_state": r.get("health_state", "unknown"),
                # autoscale_raw is a string "true"/"false"/"" from ARG — normalise to bool
                "autoscale_enabled": str(r.get("autoscale_raw", "")).lower() == "true",
                "active_alert_count": r.get("active_alert_count", 0) or 0,
            }
            for r in rows
        ]

        # Enrich instance counts from ARG VMSS VM query (sku.capacity is
        # unreliable for AKS-managed VMSS — may report 0)
        if vmss_list:
            import asyncio
            loop = asyncio.get_event_loop()
            instance_counts = await loop.run_in_executor(
                None, _get_vmss_instance_counts, subscription_ids, credential
            )
            for item in vmss_list:
                real_count = instance_counts.get(item["id"].lower(), 0)
                if real_count > 0 and item["instance_count"] == 0:
                    item["instance_count"] = real_count
                    item["healthy_instance_count"] = real_count

            # Enrich health_state from Resource Health API (best-effort).
            # Only overwrite the ARG-derived health when Resource Health returns a
            # definitive state (not "unknown").  This prevents AKS-managed VMSS
            # (where Resource Health often returns "Unknown") from losing the
            # provisioningState-derived "available" signal.
            resource_ids = [item["id"] for item in vmss_list if item["id"]]
            health_map = await loop.run_in_executor(
                None, _get_vmss_health_states, resource_ids, credential
            )
            for item in vmss_list:
                rh_state = health_map.get(item["id"].lower(), "unknown").lower()
                if rh_state != "unknown":
                    # Resource Health gave a definitive answer — use it
                    item["health_state"] = rh_state
                    if rh_state == "available":
                        item["power_state"] = "Running"
                    else:
                        item["power_state"] = rh_state.capitalize()
                # else: keep the ARG-derived health_state (from provisioningState)

        # Enrich instance_count for AKS-managed VMSS (sku.capacity==0 in ARG).
        # Runs best-effort after the ARG VM count query — only patches items
        # still showing 0 by querying the AKS agent pools API directly.
        if vmss_list:
            await asyncio.get_event_loop().run_in_executor(
                None, _enrich_aks_vmss_node_counts, vmss_list, credential
            )

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
        instances_paged = compute_client.virtual_machine_scale_set_vms.list(
            resource_group, vmss_name, expand="instanceView"
        )
        def _derive_instance_fields(inst: Any) -> Dict[str, str]:
            """Extract power_state and health_state from instance view statuses.

            Azure instance view statuses list looks like:
              [ProvisioningState/succeeded, PowerState/running]
            The Application Health extension populates vmHealth when present;
            for AKS-managed nodes it is always None because the extension is
            not installed.  We fall back to deriving health from the two
            well-known status codes.
            """
            power_state = "unknown"
            health_state = "unknown"
            iv = inst.instance_view

            if iv and iv.statuses:
                # Find the PowerState/* status entry explicitly rather than
                # assuming it is always the last element.
                for s in iv.statuses:
                    code = (s.code or "").lower()
                    if code.startswith("powerstate/"):
                        power_state = s.display_status or code
                    # PowerState/running and ProvisioningState/succeeded together
                    # indicate the instance is healthy at the infrastructure layer.
                if not any(
                    (s.code or "").lower().startswith("powerstate/") for s in iv.statuses
                ):
                    # No explicit power state — fall back to last status
                    power_state = iv.statuses[-1].display_status or "unknown"

                # Derive health from vmHealth extension first, then fall back to
                # provisioning + power state.
                if iv.vm_health and iv.vm_health.status:
                    health_code = (iv.vm_health.status.code or "").lower()
                    # Check "unhealthy" before "healthy" — "unhealthy" contains "healthy"
                    if "unhealthy" in health_code:
                        health_state = "unhealthy"
                    elif "healthy" in health_code:
                        health_state = "healthy"
                    else:
                        health_state = health_code
                else:
                    # No Application Health extension: derive from status codes.
                    prov_ok = any(
                        (s.code or "").lower() == "provisioningstate/succeeded"
                        for s in iv.statuses
                    )
                    running = "running" in power_state.lower()
                    if prov_ok and running:
                        health_state = "healthy"
                    elif not prov_ok:
                        health_state = "degraded"

            return {"power_state": power_state, "health_state": health_state}

        instances = [
            {
                "instance_id": inst.instance_id or "",
                "name": inst.name or "",
                **_derive_instance_fields(inst),
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
        # AKS-managed VMSS: sku.capacity == 0 and instances list is empty because AKS controls
        # node counts via its own API. Fall back to the AKS agent pools API when we detect we
        # are inside an AKS managed resource group (starts with "MC_" case-insensitively).
        sku_capacity = int(vmss.sku.capacity or 0) if vmss.sku else 0
        is_aks_managed = resource_group.upper().startswith("MC_")
        if is_aks_managed and sku_capacity == 0:
            # Parse cluster name from MC_<rg>_<cluster>_<location> convention.
            # Splitting on "_" gives: ['MC', 'rg-name', 'cluster-name', 'location']
            # so original_rg = mc_parts[1] and cluster = mc_parts[2].
            mc_parts = resource_group.split("_")
            # e.g. MC_rg-srelab-australiaeast_aks-srelab_australiaeast → aks-srelab
            aks_cluster_name = mc_parts[2] if len(mc_parts) >= 4 else (mc_parts[-2] if len(mc_parts) >= 3 else "")
            # Original resource group is just the second segment (index 1)
            original_rg = mc_parts[1] if len(mc_parts) >= 4 else ""
            aks_total = 0
            aks_running = 0
            try:
                from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]
                aks_client = ContainerServiceClient(credential, subscription_id)
                for pool in aks_client.agent_pools.list(original_rg, aks_cluster_name):
                    # VMSS names follow pattern: aks-<poolname>-<hash>-vmss
                    # Match by checking for "-<poolname>-" substring in vmss_name
                    if pool.name and f"-{pool.name}-" in vmss_name.lower():
                        count = pool.count or 0
                        aks_total += count
                        power_code = getattr(getattr(pool, "power_state", None), "code", None)
                        if power_code and power_code.lower() == "running":
                            aks_running += count
            except Exception as aks_exc:
                logger.debug("vmss_detail: aks agent_pools fallback failed error=%s", aks_exc)
            total = aks_total
            running_count = aks_running
        else:
            total = len(instances) if sku_capacity == 0 and instances else sku_capacity
            running_count = sum(
                1 for inst in instances
                if "running" in (inst.get("power_state") or "").lower()
            )
        healthy_instance_count = running_count if total > 0 else 0

        # Derive health_state from healthy ratio.
        # For AKS-managed VMSS with 0 nodes: if the VMSS itself provisioned successfully,
        # treat as "available" (empty pool is a valid scaled-to-zero state, not "unknown").
        vmss_provisioning_state = (vmss.provisioning_state or "").lower()
        if total == 0:
            if is_aks_managed and vmss_provisioning_state == "succeeded":
                health_state = "available"
            else:
                health_state = "unknown"
        elif healthy_instance_count == total:
            health_state = "available"
        elif healthy_instance_count == 0:
            health_state = "unavailable"
        else:
            health_state = "degraded"

        # Enrich health_state from Resource Health API (best-effort, non-blocking)
        # Only override when Resource Health returns a definitive (non-unknown) state.
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            health_map = await loop.run_in_executor(
                None, _get_vmss_health_states, [resource_id], credential
            )
            rh_state = health_map.get(resource_id.lower(), "unknown").lower()
            if rh_state and rh_state != "unknown":
                health_state = rh_state
        except Exception as rh_exc:
            logger.debug("vmss_detail: resource_health enrichment failed error=%s", rh_exc)

        # Extract OS type and image version from the VMSS model
        os_type_val = ""
        os_image_version_val = ""
        if vmss.virtual_machine_profile and vmss.virtual_machine_profile.storage_profile:
            sp = vmss.virtual_machine_profile.storage_profile
            if sp.os_disk and sp.os_disk.os_type:
                # Use _enum_value to avoid SDK enum object leak (e.g. "OperatingSystemTypes.Linux")
                os_type_val = _enum_value(sp.os_disk.os_type, "")
            if sp.image_reference:
                ref = sp.image_reference
                os_image_version_val = _extract_os_image_version(
                    ref.offer or "",
                    ref.sku or "",
                    ref.id or "",
                )

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
            "os_type": os_type_val,
            "os_image_version": os_image_version_val,
            "power_state": "running",
            "health_state": health_state,
            "autoscale_enabled": autoscale_settings.get("enabled", False),
            "active_alert_count": 0,
            "min_count": autoscale_settings["min_count"],
            "max_count": autoscale_settings["max_count"],
            "upgrade_policy": (_enum_value(vmss.upgrade_policy.mode, "") if vmss.upgrade_policy else ""),
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
    metrics: str = Query(
        ",".join(VMSS_DEFAULT_METRICS[:8]),
        description="Comma-separated Azure Monitor metric names",
    ),
    timespan: str = Query("PT24H", description="ISO 8601 duration"),
    interval: str = Query("PT5M", description="ISO 8601 interval"),
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

    subscription_id = _extract_subscription_id(resource_id)
    if not subscription_id:
        return {"resource_id": resource_id, "timespan": timespan, "interval": interval, "metrics": []}

    metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    logger.info(
        "vmss_metrics: request | resource=%s metrics=%d timespan=%s",
        resource_id[-60:], len(metric_names), timespan,
    )

    try:
        import asyncio
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]

        credential = DefaultAzureCredential()
        client = MonitorManagementClient(credential, subscription_id)
        loop = asyncio.get_event_loop()

        tasks = [
            loop.run_in_executor(
                None,
                _fetch_single_metric_vmss,
                client,
                resource_id,
                name,
                timespan,
                interval,
            )
            for name in metric_names
        ]
        results = await asyncio.gather(*tasks)
        metrics_out = [r for r in results if r is not None]

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "vmss_metrics: complete | resource=%s requested=%d returned=%d duration_ms=%.0f",
            resource_id[-60:], len(metric_names), len(metrics_out), duration_ms,
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
            "vmss_metrics: failed | resource=%s error=%s duration_ms=%.0f",
            resource_id[-60:], exc, duration_ms,
        )
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "interval": interval,
            "metrics": [],
            "fetch_error": str(exc),
        }


@router.post("/{resource_id_base64}/chat")
async def vmss_chat(
    resource_id_base64: str,
    request: VMSSChatRequest,
    credential=Depends(get_credential),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Resource-scoped chat for VMSS investigation with live function calling."""
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    try:
        import json
        import uuid
        from services.api_gateway.foundry import (
            _CONVERSATION_HISTORY,
            _CONVERSATION_HISTORY_LIMIT,
            _get_domain_instructions,
            _get_openai_client,
        )
        from services.api_gateway.vmss_chat_tools import VMSS_CHAT_TOOL_SCHEMAS, dispatch_tool_call

        vmss_name = resource_id.rstrip("/").split("/")[-1]
        _, base_instructions = _get_domain_instructions("compute_agent")
        system_prompt = (
            f"{base_instructions}\n\n"
            f"You are investigating a specific VM Scale Set:\n"
            f"  Name: {vmss_name}\n"
            f"  Resource ID: {resource_id}\n\n"
            "You have live tools to fetch real-time data for this scale set. "
            "Use them whenever the user asks about instances, metrics, health, or autoscale. "
            "Do NOT say data is unavailable without first trying the relevant tool."
        )

        history_key = request.thread_id or None
        prior_history = _CONVERSATION_HISTORY.get(history_key, []) if history_key else []
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(prior_history)
        messages.append({"role": "user", "content": request.message})

        openai_client = _get_openai_client()
        response_id = f"chat-{uuid.uuid4().hex[:16]}"
        loop = __import__("asyncio").get_running_loop()
        reply: Optional[str] = None

        for _round in range(5):
            response = await loop.run_in_executor(
                None,
                lambda m=messages: openai_client.chat.completions.create(
                    model="gpt-4.1",
                    messages=m,
                    tools=VMSS_CHAT_TOOL_SCHEMAS,
                    tool_choice="auto",
                    max_tokens=1500,
                ),
            )
            choice = response.choices[0]
            if choice.finish_reason == "stop" or not choice.message.tool_calls:
                reply = choice.message.content
                break
            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                try:
                    tool_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    tool_args = {}
                tool_result = await loop.run_in_executor(
                    None,
                    lambda tn=tc.function.name, ta=tool_args: dispatch_tool_call(tn, ta, resource_id, credential),
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})
        else:
            messages.append({"role": "user", "content": "Please summarise your findings so far."})
            final = await loop.run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(model="gpt-4.1", messages=messages, max_tokens=1000),
            )
            reply = final.choices[0].message.content

        new_key = history_key or response_id
        history = list(_CONVERSATION_HISTORY.get(new_key, []))
        history.extend([{"role": "user", "content": request.message}, {"role": "assistant", "content": reply or ""}])
        max_msgs = _CONVERSATION_HISTORY_LIMIT * 2
        _CONVERSATION_HISTORY[new_key] = history[-max_msgs:]

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_chat: thread_id=%s duration_ms=%.1f", new_key, duration_ms)
        return VMSSChatResponse(thread_id=new_key, run_id=response_id, status="created", reply=reply).model_dump()

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("vmss_chat: error=%s duration_ms=%.1f", exc, duration_ms, exc_info=True)
        return {"error": str(exc)}
