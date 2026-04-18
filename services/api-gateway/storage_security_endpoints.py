from __future__ import annotations
"""Storage Account Security API endpoints — Phase 98.

Routes:
  GET  /api/v1/storage/security?subscription_id=&severity=
  GET  /api/v1/storage/security/summary?subscription_id=

Data is queried live from ARG on every request with a 1h in-process TTL cache.
No scan button — data is always fresh on page load. No Cosmos persistence.
"""
import logging
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/storage", tags=["storage-security"])

_TTL_SECONDS = 3600  # 1 hour — storage config changes infrequently


@router.get("/security")
async def list_storage_findings(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical|high|medium|low"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return storage account security findings queried live from ARG (1h TTL cache)."""
    start_time = time.monotonic()
    from services.api_gateway.storage_security_service import scan_storage_security
    from services.api_gateway.arg_cache import get_cached

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = get_cached(
        key="storage_security",
        subscription_ids=subscription_ids,
        ttl_seconds=_TTL_SECONDS,
        fetch_fn=lambda: scan_storage_security(credential, subscription_ids),
    )

    if severity:
        findings = [f for f in findings if f.get("severity") == severity.lower()]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /storage/security → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.get("/security/summary")
async def storage_summary(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return aggregated storage security summary queried live from ARG (1h TTL cache)."""
    start_time = time.monotonic()
    from services.api_gateway.storage_security_service import scan_storage_security
    from services.api_gateway.arg_cache import get_cached

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings: List[Dict[str, Any]] = get_cached(
        key="storage_security",
        subscription_ids=subscription_ids,
        ttl_seconds=_TTL_SECONDS,
        fetch_fn=lambda: scan_storage_security(credential, subscription_ids),
    )

    sev_counts: Counter[str] = Counter(f.get("severity", "low") for f in findings)
    all_risks: List[str] = [risk for f in findings for risk in f.get("findings", [])]
    top_risks = [
        {"description": desc, "count": cnt}
        for desc, cnt in Counter(all_risks).most_common(5)
    ]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /storage/security/summary (%.0fms)", duration_ms)
    return {
        "total_accounts": len(findings),
        "critical_count": sev_counts.get("critical", 0),
        "high_count": sev_counts.get("high", 0),
        "medium_count": sev_counts.get("medium", 0),
        "low_count": sev_counts.get("low", 0),
        "top_risks": top_risks,
    }
