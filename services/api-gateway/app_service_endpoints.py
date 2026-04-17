"""App Service / Function App health endpoints.

GET  /api/v1/app-services          — list apps (filters: subscription_id, health_status, app_type)
GET  /api/v1/app-services/summary  — aggregate summary counts
POST /api/v1/app-services/scan     — trigger ARG scan and persist results
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

router = APIRouter(prefix="/api/v1/app-services", tags=["app-services"])

COSMOS_DB = "aap"


class ScanResponse(BaseModel):
    scanned: int
    duration_ms: float


@router.get("")
async def list_app_services(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    health_status: Optional[str] = Query(None, description="healthy|stopped|misconfigured"),
    app_type: Optional[str] = Query(None, description="web_app|function_app|logic_app|app_service_plan"),
    _token: str = Depends(verify_token),
    request: Request = None,
) -> Dict[str, Any]:
    """List App Service apps from Cosmos DB cache."""
    start_time = time.monotonic()
    cosmos_client = get_cosmos_client(request)
    if cosmos_client is None:
        return {"apps": [], "total": 0}

    from services.api_gateway.app_service_health_service import get_app_services

    sub_list = [subscription_id] if subscription_id else None
    items = get_app_services(cosmos_client, COSMOS_DB, sub_list, health_status, app_type)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("app_services_list: total=%d duration_ms=%.1f", len(items), duration_ms)
    return {"apps": items, "total": len(items)}


@router.get("/summary")
async def get_summary(
    _token: str = Depends(verify_token),
    request: Request = None,
) -> Dict[str, Any]:
    """Return aggregate App Service health counts."""
    cosmos_client = get_cosmos_client(request)
    if cosmos_client is None:
        return {
            "total": 0,
            "healthy": 0,
            "stopped": 0,
            "misconfigured": 0,
            "https_only_violations": 0,
            "tls_violations": 0,
            "free_tier_count": 0,
        }

    from services.api_gateway.app_service_health_service import get_app_service_summary
    return get_app_service_summary(cosmos_client, COSMOS_DB)


@router.post("/scan")
async def trigger_scan(
    _token: str = Depends(verify_token),
    credential: Any = Depends(get_credential),
    request: Request = None,
) -> ScanResponse:
    """Scan all App Service resources via ARG and persist to Cosmos DB."""
    start_time = time.monotonic()
    cosmos_client = get_cosmos_client(request)

    # Resolve subscription IDs from registry
    subscription_ids: List[str] = []
    try:
        registry = getattr(request.app.state, "subscription_registry", None)
        if registry:
            subscription_ids = registry.get_all_ids()
    except Exception as exc:
        logger.warning("app_services_scan: subscription_registry unavailable error=%s", exc)

    from services.api_gateway.app_service_health_service import scan_app_services, persist_app_services

    apps = scan_app_services(credential, subscription_ids)

    if cosmos_client is not None:
        persist_app_services(cosmos_client, COSMOS_DB, apps)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("app_services_scan: scanned=%d duration_ms=%.1f", len(apps), duration_ms)
    return ScanResponse(scanned=len(apps), duration_ms=round(duration_ms, 1))
