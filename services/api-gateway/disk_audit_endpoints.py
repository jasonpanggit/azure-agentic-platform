"""Orphaned Disk & Snapshot Audit API endpoints — Phase 100.

Routes:
  GET  /api/v1/compute/disks/orphaned?subscription_id=&resource_type=
  POST /api/v1/compute/disks/scan
  GET  /api/v1/compute/disks/summary?subscription_id=
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/compute/disks", tags=["disk-audit"])

_COSMOS_DB = "aap"


@router.get("/orphaned")
async def list_orphaned_disks(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    resource_type: Optional[str] = Query(
        None, description="Filter by type: disk or snapshot"
    ),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return orphaned disk and snapshot findings from the last scan."""
    start_time = time.monotonic()
    from services.api_gateway.disk_audit_service import get_disk_findings

    findings = (
        get_disk_findings(
            cosmos_client=cosmos_client,
            cosmos_db=_COSMOS_DB,
            subscription_id=subscription_id,
            resource_type=resource_type,
        )
        if cosmos_client
        else []
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /compute/disks/orphaned → %d findings (%.0fms)", len(findings), duration_ms
    )
    return {"findings": findings, "total": len(findings)}


@router.post("/scan")
async def scan_disks(
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a live ARG scan for orphaned disks and old snapshots."""
    start_time = time.monotonic()
    from services.api_gateway.disk_audit_service import (
        scan_orphaned_disks,
        persist_disk_findings,
    )
    from services.api_gateway.subscription_registry import get_managed_subscription_ids

    subscription_ids: List[str] = []
    try:
        subscription_ids = await get_managed_subscription_ids()
    except Exception as exc:
        logger.warning("disk_audit_endpoints: could not fetch subscription list: %s", exc)

    findings = scan_orphaned_disks(subscription_ids)
    if cosmos_client and findings:
        persist_disk_findings(findings, cosmos_client=cosmos_client, cosmos_db=_COSMOS_DB)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "POST /compute/disks/scan → %d findings (%.0fms)", len(findings), duration_ms
    )
    return {
        "scanned": True,
        "findings_found": len(findings),
        "duration_ms": round(duration_ms),
    }


@router.get("/summary")
async def disk_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated disk waste summary."""
    start_time = time.monotonic()
    from services.api_gateway.disk_audit_service import get_disk_summary

    summary = (
        get_disk_summary(
            cosmos_client=cosmos_client,
            cosmos_db=_COSMOS_DB,
            subscription_id=subscription_id,
        )
        if cosmos_client
        else {
            "orphaned_disks": 0,
            "old_snapshots": 0,
            "total_wasted_gb": 0,
            "estimated_monthly_cost_usd": 0.0,
        }
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /compute/disks/summary (%.0fms)", duration_ms)
    return summary
