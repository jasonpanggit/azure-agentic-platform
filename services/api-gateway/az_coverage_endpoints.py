"""Availability Zone Coverage Audit API endpoints — Phase 102.

GET  /api/v1/compute/az-coverage              — list AZ findings (filterable)
POST /api/v1/compute/az-coverage/scan         — trigger on-demand ARG scan
GET  /api/v1/compute/az-coverage/summary      — aggregate summary
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.az_coverage_service import (
    get_az_findings,
    get_az_summary,
    persist_az_findings,
    scan_az_coverage,
)
from services.api_gateway.federation import resolve_subscription_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/compute/az-coverage", tags=["az-coverage"])


@router.get("")
async def list_az_findings(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    has_zone_redundancy: Optional[bool] = Query(None, description="Filter by zone redundancy"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type: vm or vmss"),
    _token: str = Depends(verify_token),
) -> List[Dict[str, Any]]:
    """Return persisted AZ coverage findings, optionally filtered."""
    start_time = time.monotonic()
    results = get_az_findings(
        subscription_id=subscription_id,
        has_zone_redundancy=has_zone_redundancy,
        resource_type=resource_type,
    )
    logger.info(
        "az_findings: count=%d subscription_id=%s duration_ms=%.0f",
        len(results), subscription_id, (time.monotonic() - start_time) * 1000,
    )
    return results


@router.post("/scan")
async def trigger_az_scan(
    request: Request,
    subscriptions: Optional[str] = Query(
        None,
        description="Comma-separated subscription IDs. Omit to scan all discovered subscriptions.",
    ),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Trigger an on-demand ARG scan for VM/VMSS AZ coverage and persist results."""
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscriptions, request)

    findings = scan_az_coverage(subscription_ids)
    persist_az_findings(findings)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "az_scan: scanned=%d persisted duration_ms=%.0f",
        len(findings), duration_ms,
    )
    return {
        "scanned": len(findings),
        "status": "complete",
        "duration_ms": round(duration_ms),
    }


@router.get("/summary")
async def az_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Return aggregate AZ coverage summary."""
    start_time = time.monotonic()
    summary = get_az_summary(subscription_id=subscription_id)
    logger.info(
        "az_summary: total=%d coverage_pct=%.1f duration_ms=%.0f",
        summary.get("total", 0),
        summary.get("coverage_pct", 0.0),
        (time.monotonic() - start_time) * 1000,
    )
    return summary
