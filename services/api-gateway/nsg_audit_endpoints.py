from __future__ import annotations
"""NSG security audit API endpoints (Phase 77).

Provides:
  GET  /api/v1/nsg/findings         — list findings with optional filters
  GET  /api/v1/nsg/findings/summary — severity counts + top risky NSGs
  POST /api/v1/nsg/scan             — trigger on-demand background scan
"""
import os

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_cosmos_client, get_credential_for_subscriptions
from services.api_gateway.nsg_audit_service import (
    get_findings,
    get_summary,
    persist_findings,
    scan_nsg_compliance,
)

router = APIRouter(prefix="/api/v1/nsg", tags=["nsg-audit"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_subscription_ids() -> List[str]:
    """Read subscription IDs from SUBSCRIPTION_IDS env var."""
    raw = os.environ.get("SUBSCRIPTION_IDS", "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _get_db_name() -> str:
    return os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")


def _run_scan_background(credential: Any, subscription_ids: List[str], cosmos_client: Any, db_name: str) -> None:
    """Background task: scan NSGs and persist findings."""
    try:
        findings = scan_nsg_compliance(credential, subscription_ids)
        persist_findings(cosmos_client, db_name, findings)
        logger.info("Background NSG scan complete: %d findings", len(findings))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Background NSG scan failed: %s", exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/findings")
async def list_nsg_findings(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical | high | medium | info"),
    credential: Any = Depends(get_credential_for_subscriptions),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Dict[str, Any]:
    """Return NSG security findings with optional filters.

    Query params:
    - subscription_id: restrict to a single subscription
    - severity: one of critical, high, medium, info
    """
    db_name = _get_db_name()

    valid_severities = {"critical", "high", "medium", "info"}
    if severity and severity.lower() not in valid_severities:
        return JSONResponse(
            status_code=422,
            content={"error": f"severity must be one of: {sorted(valid_severities)}"},
        )

    sub_ids: Optional[List[str]] = [subscription_id] if subscription_id else None
    findings = get_findings(
        cosmos_client=cosmos_client,
        db_name=db_name,
        subscription_ids=sub_ids,
        severity=severity.lower() if severity else None,
    )

    return {
        "findings": [f.to_dict() for f in findings],
        "count": len(findings),
    }


@router.get("/findings/summary")
async def nsg_findings_summary(
    credential: Any = Depends(get_credential_for_subscriptions),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated NSG finding counts by severity and top 5 risky NSGs."""
    db_name = _get_db_name()
    summary = get_summary(cosmos_client=cosmos_client, db_name=db_name)
    return summary


@router.post("/scan")
async def trigger_nsg_scan(
    background_tasks: BackgroundTasks,
    credential: Any = Depends(get_credential_for_subscriptions),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Dict[str, Any]:
    """Trigger an on-demand NSG compliance scan across all configured subscriptions.

    The scan runs as a background task. Returns immediately with a scan_id.
    """
    subscription_ids = _get_subscription_ids()
    if not subscription_ids:
        return JSONResponse(
            status_code=422,
            content={"error": "SUBSCRIPTION_IDS environment variable is not configured"},
        )

    scan_id = str(uuid.uuid4())
    db_name = _get_db_name()

    background_tasks.add_task(
        _run_scan_background,
        credential,
        subscription_ids,
        cosmos_client,
        db_name,
    )

    logger.info("NSG scan queued: scan_id=%s subscriptions=%d", scan_id, len(subscription_ids))
    return {"scan_id": scan_id, "status": "queued", "subscription_count": len(subscription_ids)}
