"""AKS Cluster Health Dashboard endpoints (Phase 83).

Router prefix: /api/v1/aks-health

GET  /api/v1/aks-health/clusters  — list clusters (filter: subscription_id, health_status)
GET  /api/v1/aks-health/summary   — aggregate summary
POST /api/v1/aks-health/scan      — trigger background scan
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_cosmos_client, get_credential
from services.api_gateway.federation import resolve_subscription_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/aks-health", tags=["aks-health"])


def _run_scan_background(credential: Any, subscription_ids: List[str], cosmos_client: Any) -> None:
    """Background task: scan and persist AKS cluster health."""
    import os
    from services.api_gateway.aks_health_service import persist_aks_data, scan_aks_clusters

    db_name = os.environ.get("COSMOS_DATABASE", "aap")
    try:
        clusters = scan_aks_clusters(credential, subscription_ids)
        if cosmos_client is not None:
            persist_aks_data(cosmos_client, db_name, clusters)
        logger.info("aks_health_endpoints.scan_background: scanned=%d", len(clusters))
    except Exception as exc:  # noqa: BLE001
        logger.error("aks_health_endpoints.scan_background: error=%s", exc)


@router.get("/clusters")
async def list_aks_health_clusters(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    health_status: Optional[str] = Query(None, description="Filter by health_status: healthy/degraded/stopped/provisioning"),
    _token: str = Depends(verify_token),
    cosmos_client: Any = Depends(get_cosmos_client),
    request: Request = None,
) -> Dict[str, Any]:
    """Return AKS cluster health records from Cosmos DB."""
    import os
    from services.api_gateway.aks_health_service import get_aks_clusters

    start_time = time.monotonic()
    db_name = os.environ.get("COSMOS_DATABASE", "aap")

    subscription_ids = None
    if subscription_id:
        subscription_ids = [subscription_id]

    clusters = get_aks_clusters(cosmos_client, db_name, subscription_ids, health_status)
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("aks_health_endpoints.clusters: total=%d duration_ms=%.1f", len(clusters), duration_ms)
    return {"clusters": clusters, "total": len(clusters)}


@router.get("/summary")
async def get_aks_health_summary(
    _token: str = Depends(verify_token),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregate AKS health summary from Cosmos DB."""
    import os
    from services.api_gateway.aks_health_service import get_aks_summary

    db_name = os.environ.get("COSMOS_DATABASE", "aap")
    return get_aks_summary(cosmos_client, db_name)


@router.post("/scan")
async def trigger_aks_health_scan(
    background_tasks: BackgroundTasks,
    _token: str = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_cosmos_client),
    request: Request = None,
) -> Dict[str, Any]:
    """Trigger a background AKS health scan across all registered subscriptions."""
    from services.api_gateway.subscription_registry import SubscriptionRegistry

    subscription_ids = SubscriptionRegistry.list_subscription_ids()
    if not subscription_ids:
        return {"status": "no_subscriptions", "message": "No subscriptions registered"}

    background_tasks.add_task(_run_scan_background, credential, subscription_ids, cosmos_client)
    logger.info("aks_health_endpoints.scan: triggered for %d subscriptions", len(subscription_ids))
    return {"status": "scanning", "subscription_count": len(subscription_ids)}
