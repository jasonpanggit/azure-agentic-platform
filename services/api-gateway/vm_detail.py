"""VM detail and metrics endpoints.

GET /api/v1/vms/{resource_id_base64}       — full VM profile
GET /api/v1/vms/{resource_id_base64}/metrics — time-series metric data

resource_id_base64: ARM resource ID base64url-encoded (no padding).
Decode with: base64.urlsafe_b64decode(pad(resource_id_base64)).decode()
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.os_normalizer import normalize_os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vms", tags=["vm-detail"])

DEFAULT_METRICS = [
    "Percentage CPU",
    "Available Memory Bytes",
    "Disk Read Bytes",
    "Disk Write Bytes",
    "Network In Total",
    "Network Out Total",
]


def _decode_resource_id(encoded: str) -> str:
    """Decode a base64url-encoded ARM resource ID.

    Adds padding if necessary (base64url omits = padding).
    Raises ValueError if decoding fails.
    """
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    try:
        return base64.urlsafe_b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Invalid base64url resource ID: {exc}") from exc


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription_id from ARM resource ID."""
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return resource_id.split("/")[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(f"Cannot extract subscription_id from: {resource_id}")


def _get_vm_details_from_arg(
    credential: Any,
    subscription_ids: List[str],
    resource_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch detailed VM info from ARG for a single resource ID.

    Handles both Azure VMs (microsoft.compute/virtualmachines) and
    Arc-enabled servers (microsoft.hybridcompute/machines).
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest

    name = resource_id.rstrip("/").split("/")[-1]
    safe_name = name.replace("'", "''")
    safe_id = resource_id.replace("'", "''")

    kql = f"""
Resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines')
| where name =~ '{safe_name}'
| where id =~ '{safe_id}'
| extend powerState = iff(
    type =~ 'microsoft.compute/virtualmachines',
    tostring(properties.extended.instanceView.powerState.displayStatus),
    tostring(properties.status.powerState)
  )
| extend osType = iff(
    type =~ 'microsoft.compute/virtualmachines',
    tostring(properties.storageProfile.osDisk.osType),
    tostring(properties.osType)
  )
| extend osName = iff(
    type =~ 'microsoft.hybridcompute/machines',
    tostring(properties.osSku),
    iff(
        isnotempty(tostring(properties.osSku)),
        tostring(properties.osSku),
        iff(
            isnotempty(tostring(properties.extended.instanceView.osName)),
            tostring(properties.extended.instanceView.osName),
            iff(
                isnotempty(tostring(properties.storageProfile.imageReference.offer)),
                strcat(
                    tostring(properties.storageProfile.imageReference.offer),
                    ' ',
                    tostring(properties.storageProfile.imageReference.sku)
                ),
                tostring(properties.osType)
            )
        )
    )
  )
| extend vmSize = iff(
    type =~ 'microsoft.compute/virtualmachines',
    tostring(properties.hardwareProfile.vmSize),
    ''
  )
| extend vmType = iff(type =~ 'microsoft.compute/virtualmachines', 'Azure VM', 'Arc VM')
| extend availabilityZones = properties.zones
| project id, name, resourceGroup, subscriptionId, location,
    vmSize, osType, osName, powerState, tags,
    availabilityZones, vmType
| limit 1
"""

    client = ResourceGraphClient(credential)
    req = QueryRequest(subscriptions=subscription_ids, query=kql.strip())
    resp = client.resources(req)
    if resp.data:
        return resp.data[0]
    return None


def _get_resource_health(credential: Any, resource_id: str) -> Dict[str, Any]:
    """Fetch resource health state and summary for a VM."""
    try:
        sub_id = _extract_subscription_id(resource_id)
        from azure.mgmt.resourcehealth import MicrosoftResourceHealth
        client = MicrosoftResourceHealth(credential, sub_id)
        status = client.availability_statuses.get_by_resource(
            resource_uri=resource_id, expand="recommendedActions"
        )
        props = status.properties
        return {
            "health_state": props.availability_state.value if props and props.availability_state else "Unknown",
            "summary": props.summary if props else None,
            "reason_type": props.reason_type if props else None,
        }
    except Exception as exc:
        logger.warning("vm_detail: resource_health failed | error=%s", exc)
        return {"health_state": "Unknown", "summary": None, "reason_type": None}


def _get_active_incidents(cosmos_client: Any, resource_id: str) -> List[Dict[str, Any]]:
    """Fetch active incidents for a VM from Cosmos."""
    import os
    try:
        db_name = os.environ.get("COSMOS_DATABASE", "aap")
        container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
        query = """
            SELECT c.incident_id, c.severity, c.title, c.created_at, c.status, c.investigation_status
            FROM c
            WHERE c.resource_id = @resource_id
            AND c.status IN ('open', 'dispatched', 'investigating')
            ORDER BY c.created_at DESC
            OFFSET 0 LIMIT 10
        """
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@resource_id", "value": resource_id}],
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:
        logger.warning("vm_detail: active_incidents failed | error=%s", exc)
        return []


def _normalize_power_state(raw: str) -> str:
    raw_lower = raw.lower()
    if "running" in raw_lower:
        return "running"
    if "deallocated" in raw_lower:
        return "deallocated"
    if "stopped" in raw_lower:
        return "stopped"
    return "unknown"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{resource_id_base64}")
async def get_vm_detail(
    resource_id_base64: str,
    credential=Depends(get_credential),
    cosmos_client=Depends(get_optional_cosmos_client),
    _user=Depends(verify_token),
) -> Dict[str, Any]:
    """Return full profile for a single VM."""
    start = time.monotonic()

    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info("vm_detail: request | resource=%s", resource_id[-60:])

    # Extract subscription for ARG scope
    try:
        sub_id = _extract_subscription_id(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    import asyncio

    # Parallel: ARG details + resource health
    loop = asyncio.get_event_loop()

    arg_task = loop.run_in_executor(None, _get_vm_details_from_arg, credential, [sub_id], resource_id)
    health_task = loop.run_in_executor(None, _get_resource_health, credential, resource_id)

    arg_row, health = await asyncio.gather(arg_task, health_task)

    if arg_row is None:
        raise HTTPException(status_code=404, detail=f"VM not found: {resource_id}")

    # Active incidents (needs Cosmos, optional)
    active_incidents: List[Dict[str, Any]] = []
    if cosmos_client:
        active_incidents = await loop.run_in_executor(
            None, _get_active_incidents, cosmos_client, resource_id
        )

    duration_ms = (time.monotonic() - start) * 1000
    logger.info("vm_detail: complete | resource=%s duration_ms=%.0f", resource_id[-60:], duration_ms)

    os_raw = arg_row.get("osName", "")
    os_type = arg_row.get("osType", "")
    os_display = normalize_os(os_raw, os_type)

    return {
        "id": resource_id,
        "name": arg_row.get("name", ""),
        "resource_group": arg_row.get("resourceGroup", ""),
        "subscription_id": arg_row.get("subscriptionId", ""),
        "location": arg_row.get("location", ""),
        "size": arg_row.get("vmSize", ""),
        "os_type": os_type,
        "os_name": os_display,
        "power_state": _normalize_power_state(arg_row.get("powerState", "")),
        "health_state": health["health_state"],
        "health_summary": health.get("summary"),
        "vm_type": arg_row.get("vmType", "Azure VM"),
        "ama_status": "unknown",
        "tags": arg_row.get("tags") or {},
        "active_incidents": active_incidents,
    }


@router.get("/{resource_id_base64}/metrics")
async def get_vm_metrics(
    resource_id_base64: str,
    metrics: str = Query(
        ",".join(DEFAULT_METRICS[:4]),
        description="Comma-separated metric names",
    ),
    timespan: str = Query("PT24H", description="ISO 8601 duration"),
    interval: str = Query("PT5M", description="ISO 8601 interval"),
    credential=Depends(get_credential),
    _user=Depends(verify_token),
) -> Dict[str, Any]:
    """Return time-series metric data for a VM."""
    start = time.monotonic()

    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        sub_id = _extract_subscription_id(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    logger.info(
        "vm_metrics: request | resource=%s metrics=%d timespan=%s",
        resource_id[-60:], len(metric_names), timespan,
    )

    try:
        from azure.mgmt.monitor import MonitorManagementClient

        client = MonitorManagementClient(credential, sub_id)
        response = client.metrics.list(
            resource_uri=resource_id,
            metricnames=",".join(metric_names),
            timespan=timespan,
            interval=interval,
            aggregation="Average,Maximum,Minimum",
        )

        metrics_out = []
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
            metrics_out.append({
                "name": metric.name.value if hasattr(metric.name, "value") else str(metric.name) if metric.name else None,
                "unit": metric.unit.value if hasattr(metric.unit, "value") else str(metric.unit) if metric.unit else None,
                "timeseries": timeseries,
            })

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "vm_metrics: complete | resource=%s metrics_count=%d duration_ms=%.0f",
            resource_id[-60:], len(metrics_out), duration_ms,
        )

        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "interval": interval,
            "metrics": metrics_out,
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "vm_metrics: failed | resource=%s error=%s duration_ms=%.0f",
            resource_id[-60:], exc, duration_ms, exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Metrics unavailable: {exc}")
