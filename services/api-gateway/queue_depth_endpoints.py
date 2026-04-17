"""Queue depth (Service Bus / Event Hub) endpoints.

GET  /api/v1/queues          — list namespaces (filters: subscription_id, health_status, namespace_type)
GET  /api/v1/queues/summary  — aggregate counts
POST /api/v1/queues/scan     — trigger ARG + metrics scan and persist
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_cosmos_client, get_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/queues", tags=["queues"])

COSMOS_DB = "aap"


class ScanResponse(BaseModel):
    scanned: int
    duration_ms: float


@router.get("")
async def list_queue_namespaces(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    health_status: Optional[str] = Query(None, description="healthy|warning|critical|unknown"),
    namespace_type: Optional[str] = Query(None, description="service_bus|event_hub"),
    _token: str = Depends(verify_token),
    request: Request = None,
) -> Dict[str, Any]:
    """List queue namespaces from Cosmos DB cache."""
    start_time = time.monotonic()
    cosmos_client = get_cosmos_client(request)
    if cosmos_client is None:
        return {"namespaces": [], "total": 0}

    from services.api_gateway.queue_depth_service import get_namespaces

    sub_list = [subscription_id] if subscription_id else None
    items = get_namespaces(cosmos_client, COSMOS_DB, sub_list, health_status, namespace_type)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("queue_list: total=%d duration_ms=%.1f", len(items), duration_ms)
    return {"namespaces": items, "total": len(items)}


@router.get("/summary")
async def get_summary(
    _token: str = Depends(verify_token),
    request: Request = None,
) -> Dict[str, Any]:
    """Return aggregate queue depth health counts."""
    cosmos_client = get_cosmos_client(request)
    if cosmos_client is None:
        return {
            "total": 0,
            "critical": 0,
            "warning": 0,
            "healthy": 0,
            "total_dead_letter": 0,
            "total_active_messages": 0,
        }

    from services.api_gateway.queue_depth_service import get_queue_summary
    return get_queue_summary(cosmos_client, COSMOS_DB)


@router.post("/scan")
async def trigger_scan(
    _token: str = Depends(verify_token),
    credential: Any = Depends(get_credential),
    request: Request = None,
) -> ScanResponse:
    """Scan all Service Bus / Event Hub namespaces and persist to Cosmos DB."""
    start_time = time.monotonic()
    cosmos_client = get_cosmos_client(request)

    subscription_ids: List[str] = []
    try:
        registry = getattr(request.app.state, "subscription_registry", None)
        if registry:
            subscription_ids = registry.get_all_ids()
    except Exception as exc:
        logger.warning("queue_scan: subscription_registry unavailable error=%s", exc)

    from services.api_gateway.queue_depth_service import scan_queue_namespaces, persist_namespaces

    namespaces = scan_queue_namespaces(credential, subscription_ids)

    if cosmos_client is not None:
        persist_namespaces(cosmos_client, COSMOS_DB, namespaces)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("queue_scan: scanned=%d duration_ms=%.1f", len(namespaces), duration_ms)
    return ScanResponse(scanned=len(namespaces), duration_ms=round(duration_ms, 1))
