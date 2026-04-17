"""Budget Alert API endpoints — Phase 96.

Routes:
  GET  /api/v1/budgets?subscription_id=&status=
  POST /api/v1/budgets/scan
  GET  /api/v1/budgets/summary?subscription_id=
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/budgets", tags=["budget-alerts"])

_COSMOS_DB = "aap"


@router.get("")
async def list_budgets(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    status: Optional[str] = Query(None, description="Filter: no_budget|on_track|warning|exceeded"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return budget findings from the last scan."""
    start_time = time.monotonic()
    from services.api_gateway.budget_alert_service import get_budget_findings

    findings = (
        get_budget_findings(
            cosmos_client=cosmos_client,
            cosmos_db=_COSMOS_DB,
            subscription_id=subscription_id,
            status=status,
        )
        if cosmos_client
        else []
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /budgets → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.post("/scan")
async def scan_budgets(
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a live scan of subscription budgets and spending."""
    start_time = time.monotonic()
    from services.api_gateway.budget_alert_service import scan_budget_status, persist_budget_findings
    from services.api_gateway.subscription_registry import get_managed_subscription_ids

    subscription_ids: List[str] = []
    try:
        subscription_ids = await get_managed_subscription_ids()
    except Exception as exc:
        logger.warning("budget_alert_endpoints: could not fetch subscription list: %s", exc)

    findings = scan_budget_status(subscription_ids)
    if cosmos_client and findings:
        persist_budget_findings(findings, cosmos_client=cosmos_client, cosmos_db=_COSMOS_DB)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("POST /budgets/scan → %d findings (%.0fms)", len(findings), duration_ms)
    return {
        "scanned": True,
        "findings_found": len(findings),
        "duration_ms": round(duration_ms),
    }


@router.get("/summary")
async def budget_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated budget status summary."""
    start_time = time.monotonic()
    from services.api_gateway.budget_alert_service import get_budget_summary

    summary = (
        get_budget_summary(
            cosmos_client=cosmos_client,
            cosmos_db=_COSMOS_DB,
            subscription_id=subscription_id,
        )
        if cosmos_client
        else {
            "total_budgets": 0,
            "exceeded_count": 0,
            "warning_count": 0,
            "on_track_count": 0,
            "no_budget_count": 0,
        }
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /budgets/summary (%.0fms)", duration_ms)
    return summary
