"""Quota Usage API endpoints — Phase 95.

Routes:
  GET  /api/v1/quota/usage?subscription_id=&severity=&location=
  POST /api/v1/quota/scan
  GET  /api/v1/quota/summary?subscription_id=
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/quota", tags=["quota-usage"])

_COSMOS_DB = "aap"


@router.get("/usage")
async def list_quota_usage(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter: critical|high|medium|low"),
    location: Optional[str] = Query(None, description="Filter by Azure location"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return compute quota findings from the last scan."""
    start_time = time.monotonic()
    from services.api_gateway.quota_usage_service import get_quota_findings

    findings = (
        get_quota_findings(
            cosmos_client=cosmos_client,
            cosmos_db=_COSMOS_DB,
            subscription_id=subscription_id,
            severity=severity,
            location=location,
        )
        if cosmos_client
        else []
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /quota/usage → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.post("/scan")
async def scan_quota(
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a live scan of Compute quota usage across all subscriptions."""
    start_time = time.monotonic()
    from services.api_gateway.quota_usage_service import scan_quota_usage, persist_quota_findings
    from services.api_gateway.subscription_registry import get_managed_subscription_ids

    subscription_ids: List[str] = []
    try:
        subscription_ids = await get_managed_subscription_ids()
    except Exception as exc:
        logger.warning("quota_usage_endpoints: could not fetch subscription list: %s", exc)

    findings = scan_quota_usage(subscription_ids)
    if cosmos_client and findings:
        persist_quota_findings(findings, cosmos_client=cosmos_client, cosmos_db=_COSMOS_DB)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("POST /quota/scan → %d findings (%.0fms)", len(findings), duration_ms)
    return {
        "scanned": True,
        "findings_found": len(findings),
        "duration_ms": round(duration_ms),
    }


@router.get("/summary")
async def quota_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated quota utilisation summary."""
    start_time = time.monotonic()
    from services.api_gateway.quota_usage_service import get_quota_summary

    summary = (
        get_quota_summary(
            cosmos_client=cosmos_client,
            cosmos_db=_COSMOS_DB,
            subscription_id=subscription_id,
        )
        if cosmos_client
        else {
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "total_count": 0,
            "most_constrained": [],
        }
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /quota/summary (%.0fms)", duration_ms)
    return summary
