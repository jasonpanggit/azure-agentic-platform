from __future__ import annotations
"""FastAPI router for Incident Report endpoints — Phase 82.

Prefix: /api/v1/incidents/{incident_id}/report

Endpoints:
- GET /api/v1/incidents/{incident_id}/report          — JSON report
- GET /api/v1/incidents/{incident_id}/report/markdown — Markdown download
"""
import os

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse

from services.api_gateway.dependencies import get_cosmos_client
from services.api_gateway.incident_report_service import (
    generate_incident_report,
    render_json,
    render_markdown,
)
import os

logger = logging.getLogger(__name__)

router = APIRouter(tags=["incident-reports"])

COSMOS_DB_NAME = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/api/v1/incidents/{incident_id}/report")
def get_incident_report_json(
    incident_id: str,
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Any:
    """Return a full incident report as JSON."""
    report = generate_incident_report(cosmos_client, COSMOS_DB_NAME, incident_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )
    return render_json(report)


@router.get(
    "/api/v1/incidents/{incident_id}/report/markdown",
    response_class=PlainTextResponse,
)
def get_incident_report_markdown(
    incident_id: str,
    cosmos_client: Any = Depends(get_cosmos_client),
) -> PlainTextResponse:
    """Return a full incident report as Markdown for download."""
    report = generate_incident_report(cosmos_client, COSMOS_DB_NAME, incident_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )
    md = render_markdown(report)
    return PlainTextResponse(
        content=md,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="incident-{incident_id}.md"'
        },
    )
