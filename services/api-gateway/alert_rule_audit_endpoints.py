"""Alert Rule Coverage Audit endpoints (Phase 90).

Routes:
  GET  /api/v1/alert-coverage/gaps     — list coverage gaps
  GET  /api/v1/alert-coverage/summary  — aggregate summary
  POST /api/v1/alert-coverage/scan     — trigger live scan
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_cosmos_client, get_credential
from services.api_gateway.alert_rule_audit_service import (
    get_alert_coverage_summary,
    get_gaps,
    persist_gaps,
    scan_alert_coverage,
)

router = APIRouter(prefix="/api/v1/alert-coverage", tags=["alert-coverage"])
logger = logging.getLogger(__name__)

_DB_NAME = "aap"


@router.get("/gaps")
async def list_alert_coverage_gaps(
    subscription_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Return alert coverage gaps, optionally filtered."""
    subs = [subscription_id] if subscription_id else None
    gaps = get_gaps(cosmos_client, _DB_NAME, subscription_ids=subs, severity=severity)
    return JSONResponse({"gaps": gaps, "total": len(gaps)})


@router.get("/summary")
async def alert_coverage_summary(
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Return aggregate alert coverage summary."""
    summary = get_alert_coverage_summary(cosmos_client, _DB_NAME)
    return JSONResponse(summary)


@router.post("/scan")
async def trigger_alert_coverage_scan(
    subscription_id: Optional[str] = Query(None),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Trigger a live alert coverage scan and persist results."""
    try:
        from services.api_gateway.subscription_registry import SubscriptionRegistry
        registry = SubscriptionRegistry()
        all_subs = await registry.list_subscription_ids()
    except Exception:  # noqa: BLE001
        all_subs = [subscription_id] if subscription_id else []

    if subscription_id:
        all_subs = [subscription_id]

    gaps = scan_alert_coverage(credential, all_subs)
    persist_gaps(cosmos_client, _DB_NAME, gaps)

    logger.info("alert_coverage_endpoints: scan complete | gaps=%d", len(gaps))
    return JSONResponse({
        "status": "ok",
        "gaps_found": len(gaps),
        "subscriptions_scanned": len(all_subs),
    })
