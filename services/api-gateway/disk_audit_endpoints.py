from __future__ import annotations
"""Orphaned Disk & Snapshot Audit API endpoints — Phase 100.

Routes:
  GET  /api/v1/compute/disks/orphaned?subscription_id=&resource_type=
  GET  /api/v1/compute/disks/summary?subscription_id=

Data is queried live from ARG on every request with a 15-min in-process TTL
cache. No scan button — data is always fresh on page load. No Cosmos persistence.
"""
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.federation import resolve_subscription_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/compute/disks", tags=["disk-audit"])

_TTL_SECONDS = 900  # 15 min — disks are created/deleted throughout the day


@router.get("/orphaned")
async def list_orphaned_disks(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    resource_type: Optional[str] = Query(None, description="Filter by type: disk or snapshot"),
    token: Dict[str, Any] = Depends(verify_token),
) -> Dict[str, Any]:
    """Return orphaned disk and snapshot findings queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()
    from services.api_gateway.disk_audit_service import scan_orphaned_disks
    from services.api_gateway.arg_cache import get_cached

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = get_cached(
        key="disk_audit",
        subscription_ids=subscription_ids,
        ttl_seconds=_TTL_SECONDS,
        fetch_fn=lambda: scan_orphaned_disks(subscription_ids),
    )

    if resource_type:
        findings = [f for f in findings if f.get("resource_type") == resource_type.lower()]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /compute/disks/orphaned → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.get("/summary")
async def disk_summary(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
) -> Dict[str, Any]:
    """Return aggregated disk waste summary queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()
    from services.api_gateway.disk_audit_service import scan_orphaned_disks
    from services.api_gateway.arg_cache import get_cached

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = get_cached(
        key="disk_audit",
        subscription_ids=subscription_ids,
        ttl_seconds=_TTL_SECONDS,
        fetch_fn=lambda: scan_orphaned_disks(subscription_ids),
    )

    orphaned_disks = sum(1 for f in findings if f.get("resource_type") == "disk")
    old_snapshots = sum(1 for f in findings if f.get("resource_type") == "snapshot")
    total_gb = sum(f.get("size_gb", 0) for f in findings)
    total_cost = sum(f.get("estimated_monthly_cost_usd", 0.0) for f in findings)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /compute/disks/summary (%.0fms)", duration_ms)
    return {
        "orphaned_disks": orphaned_disks,
        "old_snapshots": old_snapshots,
        "total_wasted_gb": total_gb,
        "estimated_monthly_cost_usd": round(total_cost, 2),
    }
