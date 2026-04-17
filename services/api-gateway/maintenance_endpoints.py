from __future__ import annotations
"""Maintenance Window Intelligence API endpoints — Phase 94.

Routes:
  GET  /api/v1/maintenance/events  — list events (optional ?subscription_id=, ?event_type=, ?status=)
  GET  /api/v1/maintenance/summary — summary counts
  POST /api/v1/maintenance/scan    — trigger live ARG scan
"""
import os
import os

import logging
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_cosmos_client, get_credential, get_optional_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])

_COSMOS_DB = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")


@router.get("/events")
async def list_maintenance_events(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    event_type: Optional[str] = Query(None, description="Filter: planned_maintenance|health_advisory|resource_degraded"),
    status: Optional[str] = Query(None, description="Filter: Active|Resolved|InProgress"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return maintenance events from the last scan."""
    start_time = time.monotonic()
    from services.api_gateway.maintenance_service import get_events

    sub_ids = [subscription_id] if subscription_id else None
    events = get_events(cosmos_client, _COSMOS_DB, subscription_ids=sub_ids, event_type=event_type, status=status) if cosmos_client else []
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /maintenance/events → %d events (%.0fms)", len(events), duration_ms)
    return {"events": [asdict(e) for e in events], "total": len(events)}


@router.get("/summary")
async def maintenance_summary(
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated maintenance event summary."""
    start_time = time.monotonic()
    from services.api_gateway.maintenance_service import get_maintenance_summary

    summary = get_maintenance_summary(cosmos_client, _COSMOS_DB) if cosmos_client else {
        "active_events": 0,
        "planned_upcoming": 0,
        "health_advisories": 0,
        "affected_subscriptions": 0,
        "critical_count": 0,
    }
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /maintenance/summary (%.0fms)", duration_ms)
    return summary


@router.post("/scan")
async def scan_maintenance(
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a live ARG scan for maintenance events across all managed subscriptions."""
    start_time = time.monotonic()
    from services.api_gateway.maintenance_service import scan_maintenance_events, persist_events

    # Resolve managed subscription IDs
    subscription_ids: List[str] = []
    try:
        from services.api_gateway.subscription_registry import SubscriptionRegistry
        registry = SubscriptionRegistry(cosmos_client, _COSMOS_DB) if cosmos_client else None
        if registry:
            subs = await registry.list_subscriptions()
            subscription_ids = [s.subscription_id for s in subs if s.subscription_id]
    except Exception as exc:
        logger.warning("maintenance/scan: could not resolve subscriptions: %s", exc)

    if not subscription_ids:
        subscription_ids = []

    events = scan_maintenance_events(credential, subscription_ids)
    if cosmos_client and events:
        persist_events(cosmos_client, _COSMOS_DB, events)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("POST /maintenance/scan → %d events (%.0fms)", len(events), duration_ms)
    return {"scanned": True, "events_found": len(events), "duration_ms": round(duration_ms)}
