from __future__ import annotations
"""VNet Peering Health Audit API endpoints.

Routes:
  GET  /api/v1/network/peerings?subscription_id=&is_healthy=
  GET  /api/v1/network/peerings/summary?subscription_id=

Data is queried live from Azure Resource Graph on every request — no
scan-then-read cycle required.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.vnet_peering_service import scan_vnet_peerings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/network/peerings", tags=["vnet-peering"])


@router.get("")
async def list_peerings(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    is_healthy: Optional[bool] = Query(None, description="Filter by health status"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return VNet peering findings queried live from ARG."""
    start_time = time.monotonic()

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = scan_vnet_peerings(subscription_ids, credential=credential)

    if is_healthy is not None:
        findings = [f for f in findings if f.get("is_healthy") == is_healthy]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /network/peerings → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.get("/summary")
async def peering_summary(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return aggregated VNet peering health summary queried live from ARG."""
    start_time = time.monotonic()

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings = scan_vnet_peerings(subscription_ids, credential=credential)

    total = len(findings)
    healthy = sum(1 for f in findings if f.get("is_healthy"))
    unhealthy = total - healthy
    disconnected = sum(
        1 for f in findings if f.get("peering_state", "").lower() == "disconnected"
    )

    summary = {
        "total": total,
        "healthy": healthy,
        "unhealthy": unhealthy,
        "disconnected": disconnected,
    }
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /network/peerings/summary (%.0fms)", duration_ms)
    return summary
