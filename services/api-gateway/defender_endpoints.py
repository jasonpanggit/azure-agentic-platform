from __future__ import annotations
"""Defender for Cloud API endpoints.

Routes:
- GET  /api/v1/defender/alerts          — paginated alert list
- GET  /api/v1/defender/recommendations — recommendation list
- GET  /api/v1/defender/summary         — combined counts
- POST /api/v1/defender/scan            — trigger background scan
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from fastapi.responses import JSONResponse

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_cosmos_client, get_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/defender", tags=["defender"])

COSMOS_DATABASE = "aap"


# ---------------------------------------------------------------------------
# Background scan task
# ---------------------------------------------------------------------------

def _run_scan(credential: Any, cosmos_client: Any, subscription_ids: List[str]) -> None:
    """Background task: scan Defender data and persist to Cosmos."""
    try:
        from services.api_gateway.defender_service import (
            scan_defender_alerts,
            scan_defender_recommendations,
            persist_defender_data,
        )
        from services.api_gateway.subscription_registry import SubscriptionRegistry

        if not subscription_ids:
            try:
                registry = SubscriptionRegistry(cosmos_client, COSMOS_DATABASE)
                subscription_ids = registry.list_subscription_ids()
            except Exception:
                subscription_ids = []

        if not subscription_ids:
            logger.warning("defender_endpoints: _run_scan — no subscription_ids resolved")
            return

        alerts = scan_defender_alerts(credential, subscription_ids)
        recs = scan_defender_recommendations(credential, subscription_ids)
        persist_defender_data(cosmos_client, COSMOS_DATABASE, alerts, recs)
        logger.info(
            "defender_endpoints: scan complete | alerts=%d recommendations=%d",
            len(alerts), len(recs),
        )
    except Exception as exc:
        logger.warning("defender_endpoints: _run_scan failed | error=%s", exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/alerts")
async def get_alerts(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: High/Medium/Low/Informational"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Return Defender security alerts.

    Query params:
        subscription_id: Filter to a single subscription (optional).
        severity: Filter by severity level (optional).
        limit: Maximum number of alerts to return (default 50).

    Returns:
        { alerts: [...], total: int, duration_ms: float }
    """
    start_time = time.monotonic()
    try:
        from services.api_gateway.defender_service import get_alerts as svc_get_alerts
        from dataclasses import asdict

        sub_ids = [subscription_id] if subscription_id else None
        alerts = svc_get_alerts(cosmos_client, COSMOS_DATABASE, sub_ids, severity, limit)
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info("GET /api/v1/defender/alerts → %d results (%.0fms)", len(alerts), duration_ms)
        return JSONResponse({"alerts": [asdict(a) for a in alerts], "total": len(alerts), "duration_ms": duration_ms})
    except Exception as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.warning("defender_endpoints: get_alerts error | error=%s", exc)
        return JSONResponse({"alerts": [], "total": 0, "duration_ms": duration_ms, "error": str(exc)})


@router.get("/recommendations")
async def get_recommendations(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    category: Optional[str] = Query(None, description="Filter by category"),
    severity: Optional[str] = Query(None, description="Filter by severity: High/Medium/Low"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Return Defender recommendations (unhealthy assessments).

    Query params:
        subscription_id: Filter to a single subscription (optional).
        category: Filter by category, e.g. Compute/Networking (optional).
        severity: Filter by severity (optional).

    Returns:
        { recommendations: [...], total: int, duration_ms: float }
    """
    start_time = time.monotonic()
    try:
        from services.api_gateway.defender_service import get_recommendations as svc_get_recs
        from dataclasses import asdict

        sub_ids = [subscription_id] if subscription_id else None
        recs = svc_get_recs(cosmos_client, COSMOS_DATABASE, sub_ids, category, severity)
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info("GET /api/v1/defender/recommendations → %d results (%.0fms)", len(recs), duration_ms)
        return JSONResponse({"recommendations": [asdict(r) for r in recs], "total": len(recs), "duration_ms": duration_ms})
    except Exception as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.warning("defender_endpoints: get_recommendations error | error=%s", exc)
        return JSONResponse({"recommendations": [], "total": 0, "duration_ms": duration_ms, "error": str(exc)})


@router.get("/summary")
async def get_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Return combined Defender alert + recommendation counts.

    Query params:
        subscription_id: Filter to a single subscription (optional).

    Returns:
        {
          alert_counts_by_severity,
          recommendation_counts_by_severity,
          secure_score_estimate,
          top_affected_resources,
          total_alerts,
          total_recommendations,
          duration_ms
        }
    """
    start_time = time.monotonic()
    try:
        from services.api_gateway.defender_service import get_defender_summary

        sub_ids = [subscription_id] if subscription_id else None
        summary = get_defender_summary(cosmos_client, COSMOS_DATABASE, sub_ids)
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info("GET /api/v1/defender/summary (%.0fms)", duration_ms)
        return JSONResponse({**summary, "duration_ms": duration_ms})
    except Exception as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.warning("defender_endpoints: get_summary error | error=%s", exc)
        return JSONResponse({"error": str(exc), "duration_ms": duration_ms}, status_code=500)


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scan(
    background_tasks: BackgroundTasks,
    subscription_id: Optional[str] = Query(None, description="Scope scan to a single subscription"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Trigger a background Defender data scan.

    Runs scan_defender_alerts + scan_defender_recommendations and persists
    results to Cosmos. Returns immediately with a scan_id.

    Returns:
        { scan_id: str, status: "queued" }
    """
    scan_id = str(uuid.uuid4())
    sub_ids = [subscription_id] if subscription_id else []
    background_tasks.add_task(_run_scan, credential, cosmos_client, sub_ids)
    logger.info("defender_endpoints: scan queued | scan_id=%s", scan_id)
    return JSONResponse({"scan_id": scan_id, "status": "queued"}, status_code=status.HTTP_202_ACCEPTED)
