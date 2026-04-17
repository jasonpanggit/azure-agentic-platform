from __future__ import annotations
"""Load Balancer Health API endpoints.

GET  /api/v1/network/lb              — list LB findings (live ARG query)
GET  /api/v1/network/lb/summary      — aggregate summary (live ARG query)

Data is queried live from Azure Resource Graph on every request.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.lb_health_service import scan_lb_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/network/lb", tags=["lb-health"])


@router.get("")
async def list_lb_findings(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical, high, medium, info"),
    _token: str = Depends(verify_token),
) -> List[Dict[str, Any]]:
    """Return LB health findings queried live from ARG."""
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)
    results = scan_lb_health(subscription_ids)
    if severity:
        results = [r for r in results if r.get("severity") == severity]
    logger.info(
        "lb_findings: count=%d subscription_id=%s severity=%s duration_ms=%.0f",
        len(results), subscription_id, severity, (time.monotonic() - start_time) * 1000,
    )
    return results


@router.get("/summary")
async def lb_summary(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Return aggregate summary of LB health findings queried live from ARG."""
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings = scan_lb_health(subscription_ids)

    total = len(findings)
    by_severity: Dict[str, int] = {}
    basic_sku_count = 0
    for f in findings:
        sev = f.get("severity", "info")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if str(f.get("sku", "")).lower() == "basic":
            basic_sku_count += 1

    summary = {"total": total, "by_severity": by_severity, "basic_sku_count": basic_sku_count}
    logger.info(
        "lb_summary: total=%d duration_ms=%.0f",
        total, (time.monotonic() - start_time) * 1000,
    )
    return summary
