from __future__ import annotations
"""CVE Fleet View endpoint — fleet-level CVE exposure summary.

GET /api/v1/cve/fleet
  Query params:
    subscriptions (Optional[str]) — comma-separated subscription IDs; omit for all registered
  Returns:
    { vms: [...], total_vms: int, vms_with_data: int, query_time_ms: float }

Strategy:
  1. Enumerate VMs from ARG (arg_cache, 900 s TTL) — fast, no MSRC calls.
  2. For each VM, read pg cve_cache (read-only, no upserts).
  3. VMs absent from cve_cache surface as rows with null counts and status "NO_DATA".
  Never triggers live CVE fetches — fleet query is a pure read of cached state.
"""

import json as _json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from services.api_gateway.arg_cache import get_cached
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cve", tags=["cve-fleet"])

# ARG VM inventory — 15-minute TTL (resource inventory volatility)
_FLEET_CACHE_TTL_SECONDS = 900

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]
except ImportError:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]


def _log_sdk_availability() -> None:
    if ResourceGraphClient is None:
        logger.debug("cve_fleet: azure-mgmt-resourcegraph not installed — ARG enumeration disabled")


_log_sdk_availability()


def _enumerate_vms_arg(
    credential: Any, subscription_ids: List[str]
) -> List[Dict[str, Any]]:
    """Enumerate all VMs and Arc machines from ARG with OS metadata.

    Returns list of dicts: {vm_name, resource_group, subscription_id, os_type, os_version, vm_type}
    """
    if ResourceGraphClient is None or QueryRequest is None:
        logger.warning("cve_fleet: azure-mgmt-resourcegraph not installed")
        return []

    kql = (
        "resources\n"
        '| where type =~ "microsoft.compute/virtualmachines"\n'
        '    or type =~ "microsoft.hybridcompute/machines"\n'
        "| extend osType = tostring(properties.osType),\n"
        "         osVersion = coalesce(\n"
        "             tostring(properties.osSku),\n"
        "             tostring(properties.extended.instanceView.osName),\n"
        "             iff(\n"
        "                 isnotempty(tostring(properties.storageProfile.imageReference.offer)),\n"
        '                 strcat(tostring(properties.storageProfile.imageReference.offer), " ",\n'
        "                        tostring(properties.storageProfile.imageReference.sku)),\n"
        '                 ""\n'
        "             ),\n"
        "             tostring(properties.osType)\n"
        "         ),\n"
        '         vmType = iff(type =~ "microsoft.hybridcompute/machines", "Arc VM", "Azure VM")\n'
        "| project name, resourceGroup, subscriptionId, osType, osVersion, vmType, id"
    )

    start_time = time.monotonic()
    duration_ms = 0.0
    try:
        client = ResourceGraphClient(credential)
        request = QueryRequest(subscriptions=subscription_ids, query=kql)
        response = client.resources(request)
        rows = list(response.data)
        duration_ms = (time.monotonic() - start_time) * 1000
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning("cve_fleet: ARG VM enumeration failed (%.0fms): %s", duration_ms, exc)
        return []

    logger.debug("cve_fleet: ARG enumerated %d VMs (%.0fms)", len(rows), duration_ms)
    return [
        {
            "vm_name": row.get("name", ""),
            "resource_group": row.get("resourceGroup", ""),
            "subscription_id": row.get("subscriptionId", ""),
            "os_type": row.get("osType", ""),
            "os_version": row.get("osVersion", ""),
            "vm_type": row.get("vmType", "Azure VM"),
            "resource_id": row.get("id", ""),
        }
        for row in rows
        if row.get("name")
    ]


async def _load_fleet_cve_cache(
    vm_entries: List[Dict[str, Any]],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Read pg cve_cache for all VMs in one batch query.

    Returns dict keyed by normalised vm_resource_id -> summary dict or None.
    Uses the same vm_resource_id format as cve_service.py:
      /subscriptions/{sub}/resourcegroups/{rg}/vm/{vm_name}  (lower-cased)
    """
    try:
        from services.api_gateway.cve_service import _get_pg_connection
    except ImportError:
        return {}

    # Build cache key map: normalised_id -> vm_entry
    id_map: Dict[str, Dict[str, Any]] = {}
    for vm in vm_entries:
        cache_key = (
            f"/subscriptions/{vm['subscription_id']}"
            f"/resourcegroups/{vm['resource_group']}"
            f"/vm/{vm['vm_name']}"
        ).lower()
        id_map[cache_key] = vm

    if not id_map:
        return {}

    conn = await _get_pg_connection()
    if conn is None:
        return {}

    result: Dict[str, Optional[Dict[str, Any]]] = {}
    start_time = time.monotonic()
    duration_ms = 0.0
    try:
        placeholders = ", ".join(f"${i+1}" for i in range(len(id_map)))
        rows = await conn.fetch(
            f"SELECT vm_resource_id, cve_data FROM cve_cache WHERE vm_resource_id IN ({placeholders})",
            *list(id_map.keys()),
        )
        duration_ms = (time.monotonic() - start_time) * 1000
        for row in rows:
            raw = row["cve_data"]
            cve_list = _json.loads(raw) if isinstance(raw, str) else raw
            result[row["vm_resource_id"]] = _summarise_cve_list(cve_list)
        logger.debug(
            "cve_fleet: pg batch read %d/%d VMs with cache data (%.0fms)",
            len(result),
            len(id_map),
            duration_ms,
        )
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.debug("cve_fleet: pg batch read failed (%.0fms): %s", duration_ms, exc)
    finally:
        await conn.close()

    return result


def _summarise_cve_list(cve_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate a list of CVERecord dicts into a fleet-row summary."""
    critical = sum(1 for c in cve_list if c.get("severity") == "CRITICAL" and c.get("status") != "PATCHED")
    high = sum(1 for c in cve_list if c.get("severity") == "HIGH" and c.get("status") != "PATCHED")
    medium = sum(1 for c in cve_list if c.get("severity") == "MEDIUM" and c.get("status") != "PATCHED")
    low = sum(1 for c in cve_list if c.get("severity") == "LOW" and c.get("status") != "PATCHED")
    total_unpatched = critical + high + medium + low

    # Top CVEs: CRITICAL first, then HIGH, capped at 3, UNPATCHED/PENDING only
    unpatched = [c for c in cve_list if c.get("status") in ("UNPATCHED", "PENDING_PATCH")]
    unpatched.sort(
        key=lambda c: (
            0 if c.get("severity") == "CRITICAL" else
            1 if c.get("severity") == "HIGH" else
            2
        )
    )
    top_cves = [c["cve_id"] for c in unpatched[:3]]

    # Patch status: worst unpatched severity
    if critical > 0:
        patch_status = "CRITICAL"
    elif high > 0:
        patch_status = "HIGH"
    elif medium > 0 or low > 0:
        patch_status = "MEDIUM_LOW"
    elif total_unpatched == 0 and len(cve_list) > 0:
        patch_status = "CLEAN"
    else:
        patch_status = "UNKNOWN"

    return {
        "critical": critical,
        "high": high,
        "medium": medium,
        "low": low,
        "total_unpatched": total_unpatched,
        "top_cves": top_cves,
        "patch_status": patch_status,
    }


@router.get("/fleet")
async def get_cve_fleet(
    request: Request,
    subscriptions: Optional[str] = Query(
        None,
        description="Comma-separated subscription IDs. Omit to query all registered subscriptions.",
    ),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> JSONResponse:
    """Return fleet-level CVE exposure summary.

    Queries live from ARG (15 min TTL cache) for VM inventory.
    CVE counts sourced from pg cve_cache (read-only, 24 h TTL).
    VMs absent from cve_cache are returned with status=NO_DATA.

    Returns:
        { vms: [...], total_vms: int, vms_with_data: int, query_time_ms: float }
    """
    start_time = time.monotonic()
    duration_ms = 0.0

    subscription_ids = resolve_subscription_ids(subscriptions, request)
    if not subscription_ids:
        return JSONResponse({"error": "No subscriptions configured"}, status_code=400)

    vm_entries: List[Dict[str, Any]] = get_cached(
        key="cve_fleet_vms",
        subscription_ids=subscription_ids,
        ttl_seconds=_FLEET_CACHE_TTL_SECONDS,
        fetch_fn=lambda: _enumerate_vms_arg(credential, subscription_ids),
    )

    # Batch read pg cve_cache for all VMs
    cve_cache_map = await _load_fleet_cve_cache(vm_entries)

    rows: List[Dict[str, Any]] = []
    for vm in vm_entries:
        cache_key = (
            f"/subscriptions/{vm['subscription_id']}"
            f"/resourcegroups/{vm['resource_group']}"
            f"/vm/{vm['vm_name']}"
        ).lower()
        summary = cve_cache_map.get(cache_key)

        if summary is not None:
            row: Dict[str, Any] = {
                "vm_name": vm["vm_name"],
                "subscription_id": vm["subscription_id"],
                "resource_group": vm["resource_group"],
                "os_type": vm["os_type"],
                "os_version": vm["os_version"],
                "vm_type": vm["vm_type"],
                "critical_count": summary["critical"],
                "high_count": summary["high"],
                "medium_count": summary["medium"],
                "low_count": summary["low"],
                "total_unpatched": summary["total_unpatched"],
                "top_cves": summary["top_cves"],
                "patch_status": summary["patch_status"],
                "has_data": True,
            }
        else:
            row = {
                "vm_name": vm["vm_name"],
                "subscription_id": vm["subscription_id"],
                "resource_group": vm["resource_group"],
                "os_type": vm["os_type"],
                "os_version": vm["os_version"],
                "vm_type": vm["vm_type"],
                "critical_count": None,
                "high_count": None,
                "medium_count": None,
                "low_count": None,
                "total_unpatched": None,
                "top_cves": [],
                "patch_status": "NO_DATA",
                "has_data": False,
            }
        rows.append(row)

    # Sort: CRITICAL first, then HIGH, MEDIUM_LOW, CLEAN, NO_DATA, UNKNOWN
    _status_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM_LOW": 2, "CLEAN": 3, "NO_DATA": 4, "UNKNOWN": 5}
    rows.sort(key=lambda r: (_status_order.get(r["patch_status"], 9), -(r["critical_count"] or 0)))

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /cve/fleet -> %d VMs, %d with data (%.0fms)",
        len(rows),
        sum(1 for r in rows if r["has_data"]),
        duration_ms,
    )

    return JSONResponse({
        "vms": rows,
        "total_vms": len(rows),
        "vms_with_data": sum(1 for r in rows if r["has_data"]),
        "query_time_ms": round(duration_ms),
    })
