"""FastAPI router for Change Intelligence endpoints — Phase 81.

Prefix: /api/v1/changes

Endpoints:
- GET  /api/v1/changes         — filtered change list
- GET  /api/v1/changes/summary — aggregate stats
- POST /api/v1/changes/scan    — trigger background scan
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from services.api_gateway.dependencies import get_cosmos_client, get_credential
from services.api_gateway.change_intelligence_service import (
    get_change_summary,
    get_changes,
    persist_changes,
    scan_recent_changes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/changes", tags=["change-intelligence"])

COSMOS_DB_NAME = os.environ.get("COSMOS_DB_NAME", "aap-db")


def _default_subscription_ids() -> List[str]:
    raw = os.environ.get("AZURE_SUBSCRIPTION_IDS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


# ──────────────────────────────────────────────────────────────────────────────
# Background scan worker
# ──────────────────────────────────────────────────────────────────────────────


def _run_scan_background(
    credential: Any,
    cosmos_client: Any,
    subscription_ids: List[str],
) -> None:
    records = scan_recent_changes(credential, subscription_ids, hours=24)
    if records:
        persist_changes(cosmos_client, COSMOS_DB_NAME, records)
    logger.info("change_intelligence: background scan done | records=%d", len(records))


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.get("")
def list_changes(
    subscription_id: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    min_impact: float = Query(0.0, ge=0.0, le=1.0),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Any:
    """Return change records, optionally filtered."""
    sub_ids = [subscription_id] if subscription_id else None
    records = get_changes(
        cosmos_client,
        COSMOS_DB_NAME,
        subscription_ids=sub_ids,
        min_impact=min_impact,
        change_type=change_type,
    )
    return {
        "changes": [
            {
                "change_id": r.change_id,
                "subscription_id": r.subscription_id,
                "resource_id": r.resource_id,
                "resource_name": r.resource_name,
                "resource_type": r.resource_type,
                "change_type": r.change_type,
                "changed_by": r.changed_by,
                "timestamp": r.timestamp,
                "resource_group": r.resource_group,
                "impact_score": r.impact_score,
                "impact_reason": r.impact_reason,
                "captured_at": r.captured_at,
            }
            for r in records
        ],
        "total": len(records),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/summary")
def get_summary(
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Any:
    """Return aggregate change intelligence statistics."""
    return get_change_summary(cosmos_client, COSMOS_DB_NAME)


@router.post("/scan")
def trigger_scan(
    background_tasks: BackgroundTasks,
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Any:
    """Queue a change scan in the background."""
    scan_id = str(uuid.uuid4())
    subscription_ids = _default_subscription_ids()
    background_tasks.add_task(
        _run_scan_background,
        credential,
        cosmos_client,
        subscription_ids,
    )
    logger.info(
        "change_intelligence: scan queued | scan_id=%s subscriptions=%d",
        scan_id,
        len(subscription_ids),
    )
    return {
        "scan_id": scan_id,
        "status": "queued",
        "subscription_count": len(subscription_ids),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
