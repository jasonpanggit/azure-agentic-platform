"""Shift Handover Report endpoints — Phase 74.

POST /api/v1/reports/shift-handover       — generate a new handover report
GET  /api/v1/reports/shift-handover/latest — fetch most recent (or generate on-demand)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field

from services.api_gateway.dependencies import get_optional_cosmos_client
from services.api_gateway.handover_report import generate_handover_report

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
logger = logging.getLogger(__name__)

import os

COSMOS_DATABASE_NAME = os.environ.get("COSMOS_DATABASE_NAME", "aap")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class HandoverRequest(BaseModel):
    shift_hours: int = Field(default=8, ge=1, le=24, description="Shift window in hours")
    format: str = Field(default="json", description="'json' or 'markdown'")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/shift-handover")
async def post_shift_handover(
    body: HandoverRequest,
    cosmos_client=Depends(get_optional_cosmos_client),
):
    """Generate a new shift handover report on demand."""
    report = await generate_handover_report(
        cosmos_client=cosmos_client,
        cosmos_database_name=COSMOS_DATABASE_NAME,
        shift_hours=body.shift_hours,
    )
    if body.format == "markdown":
        return PlainTextResponse(content=report.markdown, media_type="text/plain")
    return JSONResponse(content=_report_to_dict(report))


@router.get("/shift-handover/latest")
async def get_latest_handover(
    cosmos_client=Depends(get_optional_cosmos_client),
):
    """Return the most recently generated handover report, or generate one on-demand."""
    # Try to fetch from Cosmos
    if cosmos_client is not None:
        try:
            db = cosmos_client.get_database_client(COSMOS_DATABASE_NAME)
            container = db.get_container_client("handover_reports")
            items = list(container.query_items(
                query="SELECT TOP 1 * FROM c ORDER BY c._ts DESC",
                enable_cross_partition_query=True,
            ))
            if items:
                return JSONResponse(content=items[0])
        except Exception as exc:
            logger.warning("Could not fetch latest handover from Cosmos: %s", exc)

    # Fallback: generate on-demand
    report = await generate_handover_report(
        cosmos_client=cosmos_client,
        cosmos_database_name=COSMOS_DATABASE_NAME,
    )
    return JSONResponse(content=_report_to_dict(report))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _report_to_dict(report) -> dict:
    return {
        "report_id": report.report_id,
        "shift_start": report.shift_start,
        "shift_end": report.shift_end,
        "generated_at": report.generated_at,
        "open_incidents": report.open_incidents,
        "resolved_this_shift": report.resolved_this_shift,
        "new_this_shift": report.new_this_shift,
        "sev0_open": report.sev0_open,
        "sev1_open": report.sev1_open,
        "top_open_incidents": report.top_open_incidents,
        "slo_status": report.slo_status,
        "slo_burn_rate": report.slo_burn_rate,
        "top_patterns": report.top_patterns,
        "pending_approvals": report.pending_approvals,
        "urgent_approvals": report.urgent_approvals,
        "recommended_focus": report.recommended_focus,
        "markdown": report.markdown,
    }
