"""Security posture API endpoints — composite score, trend, and top findings (Phase 59)."""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.security_posture import SecurityPostureClient

router = APIRouter(prefix="/api/v1/security", tags=["security-posture"])
logger = logging.getLogger(__name__)


@router.get("/posture")
async def get_security_posture(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return composite security posture score + sub-scores + 30-day trend.

    Composite = 50% Defender Secure Score + 30% Policy Compliance + 20% Custom Controls.
    Score is cached in Cosmos with 1-hour TTL.
    """
    start_time = time.monotonic()
    try:
        client = SecurityPostureClient(cosmos_client, credential, subscription_id)
        score = client.get_composite_score()
        trend = client.get_posture_trend(days=30)

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "security_posture: subscription=%s composite=%.1f duration_ms=%s",
            subscription_id, score.get("composite_score", 0), duration_ms,
        )
        return {
            **score,
            "trend": trend.get("trend", []),
        }
    except Exception as exc:
        logger.warning("security_posture: posture endpoint error | subscription=%s error=%s", subscription_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/findings")
async def get_security_findings(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    limit: int = Query(default=25, ge=1, le=100, description="Maximum findings to return"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return top-N high/critical security findings with recommendations.

    Findings are sourced from Defender for Cloud tasks/recommendations,
    sorted by severity (Critical → High → Medium → Low).
    """
    start_time = time.monotonic()
    try:
        client = SecurityPostureClient(cosmos_client, credential, subscription_id)
        result = client.get_top_findings(limit=limit)

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "security_findings: subscription=%s findings=%d duration_ms=%s",
            subscription_id, result.get("total", 0), duration_ms,
        )
        return result
    except Exception as exc:
        logger.warning("security_findings: findings endpoint error | subscription=%s error=%s", subscription_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)
