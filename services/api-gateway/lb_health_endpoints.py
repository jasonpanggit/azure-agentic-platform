from __future__ import annotations
"""Load Balancer Health API endpoints — Phase 101.

GET  /api/v1/network/lb              — list LB findings (filterable)
POST /api/v1/network/lb/scan         — trigger on-demand ARG scan
GET  /api/v1/network/lb/summary      — aggregate summary
"""

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.lb_health_service import (
    get_lb_findings,
    get_lb_summary,
    persist_lb_findings,
    scan_lb_health,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/network/lb", tags=["lb-health"])


@router.get("")
async def list_lb_findings(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical, high, medium, info"),
    _token: str = Depends(verify_token),
) -> List[Dict[str, Any]]:
    """Return persisted LB health findings, optionally filtered."""
    start_time = time.monotonic()
    results = get_lb_findings(subscription_id=subscription_id, severity=severity)
    logger.info(
        "lb_findings: count=%d subscription_id=%s severity=%s duration_ms=%.0f",
        len(results), subscription_id, severity, (time.monotonic() - start_time) * 1000,
    )
    return results


@router.post("/scan")
async def trigger_lb_scan(
    request: Request,
    subscriptions: Optional[str] = Query(
        None,
        description="Comma-separated subscription IDs. Omit to scan all discovered subscriptions.",
    ),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Trigger an on-demand ARG scan for all load balancers and persist results."""
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscriptions, request)

    findings = scan_lb_health(subscription_ids)
    persist_lb_findings(findings)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "lb_scan: scanned=%d persisted duration_ms=%.0f",
        len(findings), duration_ms,
    )
    return {
        "scanned": len(findings),
        "status": "complete",
        "duration_ms": round(duration_ms),
    }


@router.get("/summary")
async def lb_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Return aggregate summary of LB health findings."""
    start_time = time.monotonic()
    summary = get_lb_summary(subscription_id=subscription_id)
    logger.info(
        "lb_summary: total=%d duration_ms=%.0f",
        summary.get("total", 0), (time.monotonic() - start_time) * 1000,
    )
    return summary
