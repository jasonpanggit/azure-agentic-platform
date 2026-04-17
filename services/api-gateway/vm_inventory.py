from __future__ import annotations
"""VM inventory endpoint — fleet-level VM listing with health and alert enrichment.

Covers both Azure VMs (microsoft.compute/virtualmachines) and Arc-enabled
servers (microsoft.hybridcompute/machines) to match the Patch tab scope.

GET /api/v1/vms
  ?subscriptions=sub1,sub2   (required, comma-separated)
  ?status=all|running|stopped|deallocated  (default: all)
  ?search=<text>             (optional VM name contains-filter)
  ?limit=100                 (default 100, max 500)
  ?offset=0

Response: { vms: [...], total: int, has_more: bool }

Each VM record contains:
  id, name, resource_group, subscription_id, location, size,
  os_type, os_name, power_state, vm_type, health_state, ama_status,
  active_alert_count, tags

vm_type: "Azure VM" for microsoft.compute/virtualmachines,
         "Arc VM" for microsoft.hybridcompute/machines
"""
import os

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.os_normalizer import normalize_os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["vms"])


# ---------------------------------------------------------------------------
# ARG query helper (same pattern as patch_endpoints.py)
# ---------------------------------------------------------------------------


def _run_arg_query(
    credential: Any,
    subscription_ids: List[str],
    kql: str,
) -> List[Dict[str, Any]]:
    """Execute an Azure Resource Graph query with pagination.

    Args:
        credential: Azure credential (DefaultAzureCredential).
        subscription_ids: Subscriptions to scope the query.
        kql: KQL query string.

    Returns:
        List of result rows from ARG.
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    client = ResourceGraphClient(credential)
    all_rows: List[Dict[str, Any]] = []
    skip_token: Optional[str] = None

    while True:
        options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
        request = QueryRequest(
            subscriptions=subscription_ids,
            query=kql,
            options=options,
        )
        response = client.resources(request)
        all_rows.extend(response.data)

        skip_token = response.skip_token
        if not skip_token:
            break

    return all_rows


def _build_vm_kql(status_filter: str, search: Optional[str], limit: int = 100, offset: int = 0) -> str:
    """Build ARG KQL query for VM inventory.

    Includes both Azure VMs (microsoft.compute/virtualmachines) and
    Arc-enabled servers (microsoft.hybridcompute/machines) so the count
    matches the Patch tab which covers both resource types.

    Arc machines use different property paths:
      - osType:  properties.osType (same for both)
      - osName:  properties.osSku (Arc) vs strcat(offer, " ", sku) (Azure) + normalize_os()
      - vmSize:  no hardware profile on Arc — returns empty string
      - vmType:  "Arc VM" vs "Azure VM" label for the UI
      - power state: properties.status ("Connected"/"Disconnected") for Arc
                     vs properties.extended.instanceView.powerState.displayStatus for Azure

    Args:
        status_filter: "all", "running", "stopped", or "deallocated".
        search: Optional name substring filter.

    Returns:
        KQL query string ready to submit to ARG.
    """
    kql = """Resources
| where type =~ 'microsoft.compute/virtualmachines'
    or type =~ 'microsoft.hybridcompute/machines'
| extend vmType = iff(type =~ 'microsoft.hybridcompute/machines', 'Arc VM', 'Azure VM')
| extend powerState = iff(
    type =~ 'microsoft.hybridcompute/machines',
    tostring(properties.status),
    tostring(properties.extended.instanceView.powerState.displayStatus)
  )
| extend osType = tostring(properties.osType)
| extend osName = iff(
    isnotempty(tostring(properties.osSku)),
    tostring(properties.osSku),
    iff(
        isnotempty(tostring(properties.extended.instanceView.osName)),
        tostring(properties.extended.instanceView.osName),
        iff(
            isnotempty(tostring(properties.storageProfile.imageReference.offer)),
            strcat(
                tostring(properties.storageProfile.imageReference.offer),
                " ",
                tostring(properties.storageProfile.imageReference.sku)
            ),
            tostring(properties.osType)
        )
    )
  )
| extend vmSize = tostring(properties.hardwareProfile.vmSize)
| join kind=leftouter (
    Resources
    | where type =~ 'microsoft.compute/virtualmachines/extensions'
    | where name in~ ('AzureMonitorWindowsAgent', 'AzureMonitorLinuxAgent', 'MicrosoftMonitoringAgent')
    | extend vmId = tolower(strcat_array(array_slice(split(id, '/'), 0, 9), '/'))
    | project vmId, amaExtName = name
) on $left.id == $right.vmId
| extend amaStatus = iff(
    vmType =~ 'Arc VM',
    'unknown',
    iff(isnotempty(amaExtName), 'installed', 'not_installed')
  )
| project
    id,
    name,
    resourceGroup,
    subscriptionId,
    location,
    vmSize,
    osType,
    osName,
    powerState,
    vmType,
    amaStatus,
    tags
"""
    if status_filter != "all":
        power_map = {
            "running": "VM running",
            "stopped": "VM stopped",
            "deallocated": "VM deallocated",
        }
        display = power_map.get(status_filter)
        if display:
            kql += f"| where powerState =~ '{display}'\n"

    if search:
        # Escape single quotes to prevent KQL injection
        safe = search.replace("'", "''")
        kql += f"| where name contains '{safe}'\n"

    kql += "| order by name asc"
    kql += f"\n| limit {limit + offset}"
    return kql.strip()


# ---------------------------------------------------------------------------
# Resource Health join (sync SDK wrapped in executor)
# ---------------------------------------------------------------------------


def _get_health_states_sync(
    credential: Any,
    resource_ids: List[str],
) -> Dict[str, str]:
    """Fetch availability health state for a list of VM resource IDs.

    Uses the sync azure-mgmt-resourcehealth SDK. Runs in a thread-pool
    executor from the async route handler.

    Args:
        credential: Azure credential.
        resource_ids: List of ARM VM resource IDs.

    Returns:
        Dict mapping resource_id → availability_state string.
        Unknown on any failure.
    """
    results: Dict[str, str] = {}

    try:
        from azure.mgmt.resourcehealth import ResourceHealthMgmtClient as _RHClient
    except ImportError:
        from azure.mgmt.resourcehealth import MicrosoftResourceHealth as _RHClient  # type: ignore[no-redef]

    def _fetch_one(rid: str) -> tuple:
        parts = rid.split("/")
        try:
            idx = [p.lower() for p in parts].index("subscriptions")
            sub_id = parts[idx + 1]
        except (ValueError, IndexError):
            return rid, "Unknown"
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
            return rid, state
        except Exception as exc:
            logger.debug("health_state: failed | resource=%s error=%s", rid[:80], exc)
            return rid, "Unknown"

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_fetch_one, rid): rid for rid in resource_ids}
        done, _ = concurrent.futures.wait(futures.keys(), timeout=8)
        for f in done:
            rid, state = f.result()
            results[rid] = state
        # VMs not resolved within 8s get "Unknown" default
        for f in futures:
            if f not in done:
                results[futures[f]] = "Unknown"

    return results


# ---------------------------------------------------------------------------
# Cosmos alert count join
# ---------------------------------------------------------------------------


def _get_alert_counts(
    cosmos_client: Any,
    resource_ids: List[str],
) -> Dict[str, int]:
    """Count active incidents per resource_id from Cosmos incidents container.

    Args:
        cosmos_client: Initialized CosmosClient.
        resource_ids: List of ARM resource IDs to look up.

    Returns:
        Dict mapping resource_id_lower → active incident count.
        Defaults to 0 for any resource not found. Returns empty dict on error.
    """
    db_name = os.environ.get("COSMOS_DATABASE", "aap")
    container = cosmos_client.get_database_client(db_name).get_container_client(
        "incidents"
    )

    counts: Dict[str, int] = {rid.lower(): 0 for rid in resource_ids}

    try:
        query = """
            SELECT c.resource_id, COUNT(1) as cnt
            FROM c
            WHERE c.status IN ('open', 'dispatched', 'investigating')
            AND c.investigation_status != 'resolved'
            GROUP BY c.resource_id
        """
        for item in container.query_items(
            query=query, enable_cross_partition_query=True
        ):
            rid = (item.get("resource_id") or "").lower()
            if rid in counts:
                counts[rid] = item.get("cnt", 0)
    except Exception as exc:
        logger.warning("alert_count_join: failed | error=%s", exc)

    return counts


# ---------------------------------------------------------------------------
# Power state normalizer
# ---------------------------------------------------------------------------


def _normalize_power_state(raw: str) -> str:
    """Normalize ARG power state display string to a short canonical form.

    Args:
        raw: Raw display string from ARG, e.g. "VM running".

    Returns:
        One of: "running", "deallocated", "stopped", "starting",
        "deallocating", or "unknown".
    """
    raw_lower = raw.lower()
    if "running" in raw_lower:
        return "running"
    if "deallocated" in raw_lower:
        return "deallocated"
    if "stopped" in raw_lower:
        return "stopped"
    if "starting" in raw_lower:
        return "starting"
    if "deallocating" in raw_lower:
        return "deallocating"
    return "unknown"


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.get("/vms")
async def list_vms(
    subscriptions: Optional[str] = Query(
        None,
        description="Comma-separated subscription IDs. Omit to query all registered subscriptions.",
    ),
    status: str = Query(
        "all",
        description="Power state filter: all|running|stopped|deallocated",
    ),
    search: Optional[str] = Query(None, description="Filter by VM name (contains)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
    _user: Any = Depends(verify_token),
    request: Request = None,
) -> Dict[str, Any]:
    """Return VM fleet inventory with power state, health, and active alert count.

    Joins three data sources:
    1. Azure Resource Graph — base VM list with power state
    2. Resource Health API — availability_state per VM
    3. Cosmos incidents container — active alert count per VM

    Resource Health and Cosmos joins are gracefully degraded: if either
    fails, VMs are still returned with "Unknown" / 0 defaults.
    """
    start = time.monotonic()

    sub_list = resolve_subscription_ids(subscriptions, request)
    if not sub_list:
        logger.info("vm_inventory: no subscriptions resolved — returning empty")
        return {"vms": [], "total": 0, "has_more": False}

    logger.info(
        "vm_inventory: request | subscriptions=%d status=%s search=%s limit=%d offset=%d",
        len(sub_list),
        status,
        search or "",
        limit,
        offset,
    )

    # Step 1: ARG query for VM list
    arg_start = time.monotonic()
    try:
        kql = _build_vm_kql(status, search, limit=limit, offset=offset)
        loop = asyncio.get_running_loop()
        rows: List[Dict[str, Any]] = await loop.run_in_executor(
            None, _run_arg_query, credential, sub_list, kql
        )
    except Exception as exc:
        logger.error(
            "vm_inventory: arg_query failed | error=%s", exc, exc_info=True
        )
        rows = []

    arg_ms = (time.monotonic() - arg_start) * 1000
    logger.info(
        "vm_inventory: arg_query complete | total=%d duration_ms=%.0f",
        len(rows),
        arg_ms,
    )

    total = len(rows)
    page_rows = rows[offset : offset + limit]

    if not page_rows:
        return {"vms": [], "total": total, "has_more": total > offset + limit}

    resource_ids = [row.get("id", "") for row in page_rows if row.get("id")]

    # Step 2: Resource Health join (sync SDK in thread pool)
    health_start = time.monotonic()
    try:
        loop = asyncio.get_running_loop()
        health_map: Dict[str, str] = await loop.run_in_executor(
            None, _get_health_states_sync, credential, resource_ids
        )
    except Exception as exc:
        logger.warning(
            "vm_inventory: resource_health_join failed (degraded) | error=%s", exc
        )
        health_map = {}

    health_ms = (time.monotonic() - health_start) * 1000
    logger.info(
        "vm_inventory: resource_health_join | vms_checked=%d duration_ms=%.0f",
        len(resource_ids),
        health_ms,
    )

    # Step 3: Cosmos alert count join (optional — skip if Cosmos not configured)
    alert_map: Dict[str, int] = {}
    if cosmos_client is not None:
        cosmos_start = time.monotonic()
        try:
            loop = asyncio.get_running_loop()
            alert_map = await loop.run_in_executor(
                None, _get_alert_counts, cosmos_client, resource_ids
            )
        except Exception as exc:
            logger.warning(
                "vm_inventory: cosmos_alert_join failed (degraded) | error=%s", exc
            )
        cosmos_ms = (time.monotonic() - cosmos_start) * 1000
        logger.info(
            "vm_inventory: cosmos_alert_join | vms_enriched=%d duration_ms=%.0f",
            len(resource_ids),
            cosmos_ms,
        )

    # Step 4: Build response
    vms: List[Dict[str, Any]] = []
    for row in page_rows:
        rid = row.get("id", "")
        power_raw = row.get("powerState", "")
        vm_type = row.get("vmType", "Azure VM")
        if vm_type == "Arc VM":
            raw_lower = power_raw.lower()
            if "connected" in raw_lower and "disconnected" not in raw_lower:
                power_state = "connected"
            elif "disconnected" in raw_lower:
                power_state = "disconnected"
            else:
                power_state = "unknown"
        else:
            power_state = _normalize_power_state(power_raw)
        health_state = health_map.get(rid, "Unknown")
        alert_count = alert_map.get(rid.lower(), 0)

        os_raw = row.get("osName", "")
        os_type = row.get("osType", "")
        os_display = normalize_os(os_raw, os_type)

        vms.append(
            {
                "id": rid,
                "name": row.get("name", ""),
                "resource_group": row.get("resourceGroup", ""),
                "subscription_id": row.get("subscriptionId", ""),
                "location": row.get("location", ""),
                "size": row.get("vmSize", ""),
                "os_type": os_type,
                "os_name": os_display,
                "power_state": power_state,
                "vm_type": vm_type,  # "Azure VM" or "Arc VM"
                "health_state": health_state,
                "ama_status": row.get("amaStatus", "unknown"),
                "active_alert_count": alert_count,
                "tags": row.get("tags") or {},
            }
        )

    total_ms = (time.monotonic() - start) * 1000
    logger.info(
        "vm_inventory: response | total=%d returned=%d duration_ms=%.0f",
        total,
        len(vms),
        total_ms,
    )

    return {"vms": vms, "total": total, "has_more": total > offset + limit}
