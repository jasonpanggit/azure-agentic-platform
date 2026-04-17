from __future__ import annotations
"""Tagging compliance API endpoints (Phase 75).

Routes:
  GET /api/v1/tagging/compliance        — full resource list with pagination
  GET /api/v1/tagging/remediation-script — bash script (text/plain)
  GET /api/v1/tagging/summary           — lightweight summary only
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse, JSONResponse

from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.tagging_service import (
    DEFAULT_REQUIRED_TAGS,
    compute_compliance_summary,
    generate_remediation_script,
    scan_tagging_compliance,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tagging", tags=["tagging"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result_to_dict(r: Any) -> dict[str, Any]:
    return {
        "resource_id": r.resource_id,
        "resource_name": r.resource_name,
        "resource_type": r.resource_type,
        "resource_group": r.resource_group,
        "location": r.location,
        "existing_tags": r.existing_tags,
        "missing_tags": r.missing_tags,
        "is_compliant": r.is_compliant,
        "compliance_pct": r.compliance_pct,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/compliance")
async def get_tagging_compliance(
    request: Request,
    subscription_id: str = Query(..., description="Azure subscription ID"),
    required_tags: Optional[str] = Query(None, description="Comma-separated tag names override"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    compliant_filter: str = Query("all", description="all | non_compliant | compliant"),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> JSONResponse:
    tags = [t.strip() for t in required_tags.split(",")] if required_tags else DEFAULT_REQUIRED_TAGS

    all_results = scan_tagging_compliance(
        credential=credential,
        subscription_ids=[subscription_id],
        required_tags=tags,
    )

    # Filter
    if compliant_filter == "non_compliant":
        filtered = [r for r in all_results if not r.is_compliant]
    elif compliant_filter == "compliant":
        filtered = [r for r in all_results if r.is_compliant]
    else:
        filtered = all_results

    total = len(filtered)
    page_results = filtered[offset : offset + limit]
    page_num = (offset // limit) + 1

    summary = compute_compliance_summary(all_results)

    return JSONResponse({
        "results": [_result_to_dict(r) for r in page_results],
        "summary": summary,
        "pagination": {
            "page": page_num,
            "page_size": limit,
            "total": total,
        },
        "required_tags": tags,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/remediation-script", response_class=PlainTextResponse)
async def get_remediation_script(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    required_tags: Optional[str] = Query(None),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> PlainTextResponse:
    tags = [t.strip() for t in required_tags.split(",")] if required_tags else DEFAULT_REQUIRED_TAGS

    all_results = scan_tagging_compliance(
        credential=credential,
        subscription_ids=[subscription_id],
        required_tags=tags,
    )

    non_compliant = [r for r in all_results if not r.is_compliant]
    script = generate_remediation_script(non_compliant)

    return PlainTextResponse(
        content=script,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=tagging-remediation.sh"},
    )


@router.get("/summary")
async def get_tagging_summary(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    required_tags: Optional[str] = Query(None),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> JSONResponse:
    tags = [t.strip() for t in required_tags.split(",")] if required_tags else DEFAULT_REQUIRED_TAGS

    all_results = scan_tagging_compliance(
        credential=credential,
        subscription_ids=[subscription_id],
        required_tags=tags,
    )

    summary = compute_compliance_summary(all_results)
    return JSONResponse({
        **summary,
        "required_tags": tags,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
