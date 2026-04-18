from __future__ import annotations
"""TLS / Certificate Expiry API endpoints — Phase 97.

Routes:
  GET  /api/v1/certs/expiry?subscription_id=&severity=&cert_type=
  GET  /api/v1/certs/summary?subscription_id=

Data is queried live from ARG on every request with a 1h in-process TTL cache.
No scan button — data is always fresh on page load. No Cosmos persistence.
"""
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/certs", tags=["cert-expiry"])

_TTL_SECONDS = 3600  # 1 hour — certificates change infrequently


@router.get("/expiry")
async def list_cert_expiry(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical|high|medium|low"),
    cert_type: Optional[str] = Query(None, description="Filter by type: keyvault|app_service"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return certificate expiry findings queried live from ARG (1h TTL cache)."""
    start_time = time.monotonic()
    from services.api_gateway.cert_expiry_service import scan_cert_expiry
    from services.api_gateway.arg_cache import get_cached

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = get_cached(
        key="cert_expiry",
        subscription_ids=subscription_ids,
        ttl_seconds=_TTL_SECONDS,
        fetch_fn=lambda: scan_cert_expiry(credential, subscription_ids),
    )

    if severity:
        findings = [f for f in findings if f.get("severity") == severity.lower()]
    if cert_type:
        findings = [f for f in findings if f.get("cert_type") == cert_type.lower()]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /certs/expiry → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.get("/summary")
async def cert_summary(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return aggregated certificate expiry summary queried live from ARG (1h TTL cache)."""
    start_time = time.monotonic()
    from services.api_gateway.cert_expiry_service import scan_cert_expiry
    from services.api_gateway.arg_cache import get_cached

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = get_cached(
        key="cert_expiry",
        subscription_ids=subscription_ids,
        ttl_seconds=_TTL_SECONDS,
        fetch_fn=lambda: scan_cert_expiry(credential, subscription_ids),
    )

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    low = sum(1 for f in findings if f.get("severity") == "low")

    soonest: Optional[str] = None
    min_days: Optional[int] = None
    for f in findings:
        d = f.get("days_until_expiry")
        if d is not None and (min_days is None or d < min_days):
            min_days = d
            soonest = f.get("expires_on")

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /certs/summary (%.0fms)", duration_ms)
    return {
        "total": len(findings),
        "critical_count": critical,
        "high_count": high,
        "medium_count": medium,
        "low_count": low,
        "soonest_expiry": soonest,
        "soonest_expiry_days": min_days,
    }
