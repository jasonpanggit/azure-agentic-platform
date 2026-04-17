from __future__ import annotations
"""Advisory endpoints — pre-incident anomaly advisories (Phase 73).

Routes:
  GET  /api/v1/advisories                       list active advisories
  GET  /api/v1/advisories/summary               aggregate counts
  PATCH /api/v1/advisories/{advisory_id}/dismiss dismiss an advisory
"""
import os

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.advisory_service import (
    dismiss_advisory,
    get_advisories,
)
from services.api_gateway.dependencies import get_optional_cosmos_client

logger = logging.getLogger(__name__)

COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")

router = APIRouter(tags=["advisories"])


@router.get("/api/v1/advisories")
async def list_advisories(
    subscription_id: Optional[str] = Query(None),
    status: str = Query("active"),
    limit: int = Query(50, ge=1, le=200),
    cosmos_client=Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """List pre-incident advisories."""
    try:
        advisories = await get_advisories(
            cosmos_client,
            COSMOS_DATABASE,
            subscription_id=subscription_id,
            status=status,
            limit=limit,
        )
        return JSONResponse(
            {
                "advisories": advisories,
                "total": len(advisories),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("list_advisories error: %s", exc)
        return JSONResponse(
            {
                "advisories": [],
                "total": 0,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            },
            status_code=500,
        )


@router.get("/api/v1/advisories/summary")
async def advisories_summary(
    subscription_id: Optional[str] = Query(None),
    cosmos_client=Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return aggregate counts for active advisories."""
    try:
        advisories = await get_advisories(
            cosmos_client,
            COSMOS_DATABASE,
            subscription_id=subscription_id,
            status="active",
            limit=200,
        )
        critical = sum(1 for a in advisories if a.get("severity") == "critical")
        warning = sum(1 for a in advisories if a.get("severity") == "warning")
        return JSONResponse(
            {
                "total_active": len(advisories),
                "critical": critical,
                "warning": warning,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("advisories_summary error: %s", exc)
        return JSONResponse(
            {
                "total_active": 0,
                "critical": 0,
                "warning": 0,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            },
            status_code=500,
        )


@router.patch("/api/v1/advisories/{advisory_id}/dismiss")
async def dismiss_advisory_endpoint(
    advisory_id: str,
    cosmos_client=Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Dismiss an advisory by ID."""
    try:
        found = await dismiss_advisory(cosmos_client, COSMOS_DATABASE, advisory_id)
        if not found:
            return JSONResponse(
                {"success": False, "error": "Advisory not found"},
                status_code=404,
            )
        return JSONResponse({"success": True, "advisory_id": advisory_id})
    except Exception as exc:  # noqa: BLE001
        logger.error("dismiss_advisory error: %s", exc)
        return JSONResponse(
            {"success": False, "error": str(exc)},
            status_code=500,
        )
