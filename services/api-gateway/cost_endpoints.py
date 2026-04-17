"""Cost anomaly API endpoints — /api/v1/cost/*

Exposes cost anomaly detection results and scan triggering.
Business logic lives in cost_service.py; this file is a thin router.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.cost_service import (
    COSMOS_DATABASE,
    get_anomalies,
    get_cost_snapshots,
    get_cost_summary,
    run_cost_scan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cost", tags=["cost"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_subscription_ids(request: Request) -> List[str]:
    """Return subscription IDs from app.state registry or SUBSCRIPTION_IDS env var."""
    registry = getattr(request.app.state, "subscription_registry", None)
    if registry is not None:
        ids = registry.get_all_ids()
        if ids:
            return ids
    raw = os.environ.get("SUBSCRIPTION_IDS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def _get_db_name() -> str:
    return os.environ.get("COSMOS_DATABASE", COSMOS_DATABASE)


# ---------------------------------------------------------------------------
# GET /api/v1/cost/anomalies
# ---------------------------------------------------------------------------


@router.get("/anomalies")
async def list_cost_anomalies(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: warning or critical"),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """List detected cost anomalies.

    Query params:
      - subscription_id (optional): filter to a single subscription
      - severity (optional): "warning" or "critical"

    Returns 200 with list of anomaly objects; empty list when none found.
    Returns 503 when Cosmos DB is not configured.
    """
    if cosmos is None:
        return JSONResponse({"anomalies": [], "total": 0, "note": "Cost store not configured"}, status_code=200)

    sub_ids = [subscription_id] if subscription_id else None
    anomalies = get_anomalies(
        cosmos_client=cosmos,
        db_name=_get_db_name(),
        subscription_ids=sub_ids,
        severity=severity,
    )

    return JSONResponse(
        {
            "anomalies": [
                {
                    "anomaly_id": a.anomaly_id,
                    "subscription_id": a.subscription_id,
                    "service_name": a.service_name,
                    "date": a.date,
                    "cost_usd": a.cost_usd,
                    "baseline_usd": a.baseline_usd,
                    "z_score": a.z_score,
                    "severity": a.severity,
                    "pct_change": a.pct_change,
                    "description": a.description,
                    "detected_at": a.detected_at,
                }
                for a in anomalies
            ],
            "total": len(anomalies),
        }
    )


# ---------------------------------------------------------------------------
# GET /api/v1/cost/summary
# ---------------------------------------------------------------------------


@router.get("/summary")
async def cost_summary(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return per-subscription cost anomaly summary + top spenders.

    Returns:
        {total_anomalies, critical_count, warning_count, top_spenders}
    """
    if cosmos is None:
        return JSONResponse(
            {
                "total_anomalies": 0,
                "critical_count": 0,
                "warning_count": 0,
                "top_spenders": [],
                "note": "Cost store not configured",
            }
        )

    sub_ids = [subscription_id] if subscription_id else None
    summary = get_cost_summary(
        cosmos_client=cosmos,
        db_name=_get_db_name(),
        subscription_ids=sub_ids,
    )
    return JSONResponse(summary)


# ---------------------------------------------------------------------------
# POST /api/v1/cost/scan
# ---------------------------------------------------------------------------


@router.post("/scan", status_code=202)
async def trigger_cost_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    credential: Any = Depends(get_credential),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Trigger an async cost anomaly scan for all configured subscriptions.

    Returns immediately with {scan_id, status: "queued"}.
    The scan runs as a BackgroundTask: fetch → detect → persist.
    """
    scan_id = str(uuid.uuid4())
    subscription_ids = _resolve_subscription_ids(request)
    db_name = _get_db_name()

    if not subscription_ids:
        logger.warning("cost_service: scan triggered but no subscription IDs configured")
        return JSONResponse(
            {"scan_id": scan_id, "status": "queued", "subscriptions": 0},
            status_code=202,
        )

    background_tasks.add_task(
        run_cost_scan,
        credential=credential,
        cosmos_client=cosmos,
        db_name=db_name,
        subscription_ids=subscription_ids,
    )
    logger.info(
        "cost_service: scan queued | scan_id=%s subs=%d",
        scan_id, len(subscription_ids),
    )
    return JSONResponse(
        {
            "scan_id": scan_id,
            "status": "queued",
            "subscriptions": len(subscription_ids),
        },
        status_code=202,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/cost/snapshots
# ---------------------------------------------------------------------------


@router.get("/snapshots")
async def list_cost_snapshots(
    request: Request,
    subscription_id: Optional[str] = Query(None),
    service_name: Optional[str] = Query(None),
    days: int = Query(14, ge=1, le=90),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return daily cost snapshots for sparkline/chart rendering.

    Query params:
      - subscription_id (optional)
      - service_name (optional)
      - days (default 14, max 90)

    Returns 200 with list of snapshots; empty list when none found.
    """
    if cosmos is None:
        return JSONResponse({"snapshots": [], "note": "Cost store not configured"})

    snapshots = get_cost_snapshots(
        cosmos_client=cosmos,
        db_name=_get_db_name(),
        subscription_id=subscription_id,
        service_name=service_name,
        days=days,
    )

    return JSONResponse(
        {
            "snapshots": [
                {
                    "snapshot_id": s.snapshot_id,
                    "subscription_id": s.subscription_id,
                    "date": s.date,
                    "service_name": s.service_name,
                    "cost_usd": s.cost_usd,
                    "currency": s.currency,
                    "captured_at": s.captured_at,
                }
                for s in snapshots
            ],
            "total": len(snapshots),
        }
    )
