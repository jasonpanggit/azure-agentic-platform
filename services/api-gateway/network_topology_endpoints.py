from __future__ import annotations
"""Network Topology API endpoints — Phase 103.

Routes:
  GET  /api/v1/network-topology
  POST /api/v1/network-topology/path-check

Data is queried live from Azure Resource Graph (15m TTL cache).
"""

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.network_topology_service import (
    evaluate_path_check,
    fetch_network_topology,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/network-topology", tags=["network-topology"])


class PathCheckRequest(BaseModel):
    """Request body for NSG path check evaluation."""

    source_resource_id: str
    destination_resource_id: str
    port: int = Field(ge=1, le=65535)
    protocol: str = "TCP"


@router.get("")
async def get_topology(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return network topology graph queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    result = fetch_network_topology(subscription_ids, credential=credential)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /network-topology → nodes=%d edges=%d issues=%d (%.0fms)",
        len(result.get("nodes", [])),
        len(result.get("edges", [])),
        len(result.get("issues", [])),
        duration_ms,
    )
    return result


@router.post("/path-check")
async def path_check(
    body: PathCheckRequest,
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Evaluate NSG rule chain for source->destination traffic. On-demand, not cached."""
    start_time = time.monotonic()

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    result = evaluate_path_check(
        source_resource_id=body.source_resource_id,
        destination_resource_id=body.destination_resource_id,
        port=body.port,
        protocol=body.protocol,
        subscription_ids=subscription_ids,
        credential=credential,
    )

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "POST /network-topology/path-check → verdict=%s (%.0fms)",
        result.get("verdict", "unknown"),
        duration_ms,
    )
    return result
