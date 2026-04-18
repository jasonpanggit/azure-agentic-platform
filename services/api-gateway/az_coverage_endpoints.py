from __future__ import annotations
"""Availability Zone Coverage Audit API endpoints — Phase 102.

Routes:
  GET  /api/v1/compute/az-coverage?subscription_id=&has_zone_redundancy=&resource_type=
  GET  /api/v1/compute/az-coverage/summary?subscription_id=

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

router = APIRouter(prefix="/api/v1/compute/az-coverage", tags=["az-coverage"])

_TTL_SECONDS = 900  # 15 min — VM deployments change zone coverage


@router.get("")
async def list_az_findings(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    has_zone_redundancy: Optional[bool] = Query(None, description="Filter by zone redundancy"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type: vm or vmss"),
    token: Dict[str, Any] = Depends(verify_token),
) -> List[Dict[str, Any]]:
    """Return AZ coverage findings queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()
    from services.api_gateway.az_coverage_service import scan_az_coverage
    from services.api_gateway.arg_cache import get_cached

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = get_cached(
        key="az_coverage",
        subscription_ids=subscription_ids,
        ttl_seconds=_TTL_SECONDS,
        fetch_fn=lambda: scan_az_coverage(subscription_ids),
    )

    if has_zone_redundancy is not None:
        findings = [f for f in findings if f.get("has_zone_redundancy") == has_zone_redundancy]
    if resource_type:
        findings = [f for f in findings if f.get("resource_type") == resource_type.lower()]

    logger.info(
        "GET /compute/az-coverage → %d findings (%.0fms)",
        len(findings), (time.monotonic() - start_time) * 1000,
    )
    return findings


@router.get("/summary")
async def az_summary(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
) -> Dict[str, Any]:
    """Return aggregate AZ coverage summary queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()
    from services.api_gateway.az_coverage_service import scan_az_coverage
    from services.api_gateway.arg_cache import get_cached

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = get_cached(
        key="az_coverage",
        subscription_ids=subscription_ids,
        ttl_seconds=_TTL_SECONDS,
        fetch_fn=lambda: scan_az_coverage(subscription_ids),
    )

    total = len(findings)
    zone_redundant = sum(1 for f in findings if f.get("has_zone_redundancy"))
    non_redundant = total - zone_redundant
    coverage_pct = round((zone_redundant / total * 100) if total else 0.0, 1)

    logger.info(
        "GET /compute/az-coverage/summary total=%d coverage=%.1f%% (%.0fms)",
        total, coverage_pct, (time.monotonic() - start_time) * 1000,
    )
    return {
        "total": total,
        "zone_redundant": zone_redundant,
        "non_redundant": non_redundant,
        "coverage_pct": coverage_pct,
    }
