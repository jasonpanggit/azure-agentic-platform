"""VNet Peering Health Audit API endpoints — Phase 99.

Routes:
  GET  /api/v1/network/peerings?subscription_id=&is_healthy=
  POST /api/v1/network/peerings/scan
  GET  /api/v1/network/peerings/summary?subscription_id=
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/network/peerings", tags=["vnet-peering"])

_COSMOS_DB = "aap"


@router.get("")
async def list_peerings(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    is_healthy: Optional[bool] = Query(None, description="Filter by health status"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return VNet peering findings from the last scan."""
    start_time = time.monotonic()
    from services.api_gateway.vnet_peering_service import get_peering_findings

    findings = (
        get_peering_findings(
            cosmos_client=cosmos_client,
            cosmos_db=_COSMOS_DB,
            subscription_id=subscription_id,
            is_healthy=is_healthy,
        )
        if cosmos_client
        else []
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /network/peerings → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.post("/scan")
async def scan_peerings(
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a live ARG scan of VNet peerings."""
    start_time = time.monotonic()
    from services.api_gateway.vnet_peering_service import (
        scan_vnet_peerings,
        persist_peering_findings,
    )
    from services.api_gateway.subscription_registry import get_managed_subscription_ids

    subscription_ids: List[str] = []
    try:
        subscription_ids = await get_managed_subscription_ids()
    except Exception as exc:
        logger.warning("vnet_peering_endpoints: could not fetch subscription list: %s", exc)

    findings = scan_vnet_peerings(subscription_ids)
    if cosmos_client and findings:
        persist_peering_findings(findings, cosmos_client=cosmos_client, cosmos_db=_COSMOS_DB)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "POST /network/peerings/scan → %d findings (%.0fms)", len(findings), duration_ms
    )
    return {
        "scanned": True,
        "findings_found": len(findings),
        "duration_ms": round(duration_ms),
    }


@router.get("/summary")
async def peering_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated VNet peering health summary."""
    start_time = time.monotonic()
    from services.api_gateway.vnet_peering_service import get_peering_summary

    summary = (
        get_peering_summary(
            cosmos_client=cosmos_client,
            cosmos_db=_COSMOS_DB,
            subscription_id=subscription_id,
        )
        if cosmos_client
        else {"total": 0, "healthy": 0, "unhealthy": 0, "disconnected": 0}
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /network/peerings/summary (%.0fms)", duration_ms)
    return summary
