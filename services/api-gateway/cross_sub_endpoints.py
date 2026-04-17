from __future__ import annotations
"""Cross-subscription correlation endpoints — Phase 86.

Router prefix: /api/v1/correlations
"""
import os

import logging
import os
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_optional_cosmos_client
from services.api_gateway.cross_sub_correlator import (
    detect_correlation_groups,
    get_active_groups,
    get_correlation_summary,
    persist_groups,
)

router = APIRouter(prefix="/api/v1/correlations", tags=["correlations"])
logger = logging.getLogger(__name__)

COSMOS_DATABASE_NAME = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")


def _group_to_dict(g: Any) -> dict:
    return asdict(g)


# ---------------------------------------------------------------------------
# GET /api/v1/correlations/groups
# ---------------------------------------------------------------------------


@router.get("/groups")
async def list_correlation_groups(
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return active correlation groups persisted in Cosmos."""
    groups = get_active_groups(cosmos_client=cosmos_client, db_name=COSMOS_DATABASE_NAME)
    return JSONResponse({
        "groups": [_group_to_dict(g) for g in groups],
        "total": len(groups),
    })


# ---------------------------------------------------------------------------
# GET /api/v1/correlations/summary
# ---------------------------------------------------------------------------


@router.get("/summary")
async def correlation_summary(
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return high-level correlation summary."""
    summary = get_correlation_summary(
        cosmos_client=cosmos_client,
        db_name=COSMOS_DATABASE_NAME,
    )
    return JSONResponse(summary)


# ---------------------------------------------------------------------------
# POST /api/v1/correlations/analyze
# ---------------------------------------------------------------------------


def _run_analysis(cosmos_client: Any, db_name: str) -> None:
    """Background task: detect groups and persist them."""
    groups = detect_correlation_groups(cosmos_client=cosmos_client, db_name=db_name)
    persist_groups(cosmos_client=cosmos_client, db_name=db_name, groups=groups)
    logger.info("Background correlation analysis complete: %d groups", len(groups))


@router.post("/analyze")
async def trigger_analysis(
    background_tasks: BackgroundTasks,
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Trigger a background correlation analysis."""
    background_tasks.add_task(_run_analysis, cosmos_client, COSMOS_DATABASE_NAME)
    return JSONResponse({"status": "analysis_started"})
