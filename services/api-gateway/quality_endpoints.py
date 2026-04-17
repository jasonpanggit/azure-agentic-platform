from __future__ import annotations
"""Quality Flywheel endpoints — eval regression metrics and SOP effectiveness."""

import logging
import time
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.api_gateway.feedback_capture import FeedbackRecord, FeedbackCaptureService

router = APIRouter(prefix="/api/v1/quality", tags=["quality"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependency: FeedbackCaptureService (singleton via app state)
# ---------------------------------------------------------------------------

async def _get_feedback_service(request: Request) -> FeedbackCaptureService:
    """Return FeedbackCaptureService from app state, or create a fresh one."""
    svc = getattr(request.app.state, "feedback_service", None)
    if svc is None:
        svc = await FeedbackCaptureService.create()
        request.app.state.feedback_service = svc
    return svc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/metrics")
async def get_quality_metrics(request: Request) -> Any:
    """Return platform-level quality metrics: MTTR, auto-remediation rate, noise ratio."""
    start_time = time.monotonic()
    try:
        svc = await _get_feedback_service(request)
        metrics = await svc.get_quality_metrics()
        metrics["generated_at"] = datetime.now(timezone.utc).isoformat()
        metrics.setdefault("duration_ms", round((time.monotonic() - start_time) * 1000, 1))
        return metrics
    except Exception as exc:
        logger.warning("quality_metrics: error | error=%s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/sop-effectiveness")
async def get_sop_effectiveness(
    request: Request,
    days: int = 30,
) -> Any:
    """Return SOP effectiveness scores sorted by score ASC (worst SOPs first)."""
    start_time = time.monotonic()
    try:
        svc = await _get_feedback_service(request)
        items = await svc.list_sop_effectiveness(days=days)
        return {
            "sop_effectiveness": items,
            "window_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
        }
    except Exception as exc:
        logger.warning("quality_sop_effectiveness: error | error=%s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/feedback")
async def get_recent_feedback(
    request: Request,
    limit: int = 50,
) -> Any:
    """Return the most recent feedback records."""
    start_time = time.monotonic()
    try:
        svc = await _get_feedback_service(request)
        records = await svc.list_recent_feedback(limit=limit)
        # Serialize datetimes
        serialised = []
        for r in records:
            row: dict = {}
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
                else:
                    row[k] = v
            serialised.append(row)
        return {
            "feedback": serialised,
            "count": len(serialised),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
        }
    except Exception as exc:
        logger.warning("quality_feedback: error | error=%s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/feedback")
async def post_feedback(
    request: Request,
    payload: FeedbackRecord,
) -> Any:
    """Record operator feedback for an incident decision."""
    start_time = time.monotonic()
    try:
        svc = await _get_feedback_service(request)
        await svc.record_feedback(payload)
        return {
            "status": "ok",
            "feedback_id": payload.feedback_id,
            "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
        }
    except Exception as exc:
        logger.warning("quality_feedback_post: error | error=%s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)
