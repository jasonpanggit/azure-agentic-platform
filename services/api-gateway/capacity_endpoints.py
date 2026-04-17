from __future__ import annotations
"""Capacity planning endpoints — quota headroom, IP space, AKS node headroom."""

import logging
import time
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.capacity_planner import (
    CapacityPlannerClient,
    CAPACITY_DEFAULT_LOCATION,
)
from services.api_gateway.models import (
    CapacityHeadroomResponse,
    CapacityQuotaItem,
    IPSpaceHeadroomResponse,
    SubnetHeadroomItem,
    AKSHeadroomResponse,
    AKSNodePoolHeadroomItem,
)

router = APIRouter(prefix="/api/v1/capacity", tags=["capacity"])
logger = logging.getLogger(__name__)


def _to_quota_item(q: dict) -> CapacityQuotaItem:
    """Convert a raw quota dict from CapacityPlannerClient to a CapacityQuotaItem."""
    return CapacityQuotaItem(
        resource_category=q.get("category", "unknown"),
        name=q.get("display_name", q.get("quota_name", "")),
        quota_name=q.get("quota_name", ""),
        current_value=int(q.get("current_value", 0)),
        limit=int(q.get("limit", 0)),
        usage_pct=float(q.get("usage_pct", 0.0)),
        available=int(q.get("available", 0)),
        days_to_exhaustion=q.get("days_to_exhaustion"),
        confidence=q.get("confidence"),
        traffic_light=q.get("traffic_light", "green"),
        growth_rate_per_day=q.get("growth_rate_per_day"),
        confidence_interval_upper_pct=q.get("confidence_interval_upper_pct"),
        confidence_interval_lower_pct=q.get("confidence_interval_lower_pct"),
    )


@router.get("/headroom", response_model=CapacityHeadroomResponse)
async def get_capacity_headroom(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    location: str = Query(default=CAPACITY_DEFAULT_LOCATION, description="Azure region"),
    days_threshold: int = Query(default=30, description="Days-to-exhaustion threshold for filtering"),
    include_categories: str = Query(default="compute,network,storage,aks"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return top-10 most constrained resources sorted by days_to_exhaustion ASC (nulls last)."""
    start_time = time.monotonic()
    try:
        planner = CapacityPlannerClient(cosmos_client, credential, subscription_id, location)
        result = planner.get_subscription_quota_headroom(location)
        quotas = result.get("quotas", [])
        snapshot_count = len(quotas)

        # Filter: include items that are near exhaustion or heavily used
        filtered = [
            q for q in quotas
            if (q.get("days_to_exhaustion") is not None and q["days_to_exhaustion"] <= days_threshold)
            or q.get("usage_pct", 0) >= 90
        ]

        # Sort: days_to_exhaustion ASC (None → infinity), then usage_pct DESC
        def sort_key(q: dict) -> tuple:
            dte = q.get("days_to_exhaustion")
            return (dte if dte is not None else float("inf"), -q.get("usage_pct", 0))

        filtered.sort(key=sort_key)
        top10 = filtered[:10]

        items = [_to_quota_item(q) for q in top10]
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "capacity_headroom: subscription=%s location=%s items=%d duration_ms=%s",
            subscription_id, location, len(items), duration_ms,
        )
        return CapacityHeadroomResponse(
            subscription_id=subscription_id,
            location=location,
            top_constrained=items,
            generated_at=datetime.now(timezone.utc).isoformat(),
            snapshot_count=snapshot_count,
        )
    except Exception as exc:
        logger.warning("capacity_headroom: error | subscription=%s error=%s", subscription_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/quotas")
async def get_capacity_quotas(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    location: str = Query(default=CAPACITY_DEFAULT_LOCATION, description="Azure region"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return all quotas sorted by usage_pct DESC."""
    start_time = time.monotonic()
    try:
        planner = CapacityPlannerClient(cosmos_client, credential, subscription_id, location)
        result = planner.get_subscription_quota_headroom(location)
        quotas = result.get("quotas", [])

        # Filter zero-limit quotas
        quotas = [q for q in quotas if q.get("limit", 0) > 0]
        quotas.sort(key=lambda q: q.get("usage_pct", 0), reverse=True)

        items = [_to_quota_item(q) for q in quotas]
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "capacity_quotas: subscription=%s location=%s items=%d duration_ms=%s",
            subscription_id, location, len(items), duration_ms,
        )
        return {
            "subscription_id": subscription_id,
            "location": location,
            "quotas": [i.model_dump() for i in items],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int(duration_ms),
        }
    except Exception as exc:
        logger.warning("capacity_quotas: error | subscription=%s error=%s", subscription_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/ip-space", response_model=IPSpaceHeadroomResponse)
async def get_ip_space_headroom(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return IP address space headroom per subnet."""
    start_time = time.monotonic()
    try:
        planner = CapacityPlannerClient(cosmos_client, credential, subscription_id)
        result = planner.get_ip_address_space_headroom()
        subnets_raw = result.get("subnets", [])

        subnets = [
            SubnetHeadroomItem(
                vnet_name=s.get("vnet_name", ""),
                resource_group=s.get("resource_group", ""),
                subnet_name=s.get("subnet_name", ""),
                address_prefix=s.get("address_prefix", ""),
                total_ips=s.get("total_ips", 0),
                reserved_ips=s.get("reserved_ips", 5),
                ip_config_count=s.get("ip_config_count", 0),
                available_ips=s.get("available", 0),
                usage_pct=s.get("usage_pct", 0.0),
                traffic_light=s.get("traffic_light", "green"),
            )
            for s in subnets_raw
        ]
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "capacity_ip_space: subscription=%s subnets=%d duration_ms=%s",
            subscription_id, len(subnets), duration_ms,
        )
        return IPSpaceHeadroomResponse(
            subscription_id=subscription_id,
            subnets=subnets,
            generated_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int(duration_ms),
            note=result.get("note"),
        )
    except Exception as exc:
        logger.warning("capacity_ip_space: error | subscription=%s error=%s", subscription_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/aks", response_model=AKSHeadroomResponse)
async def get_aks_headroom(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return AKS node pool headroom per cluster pool."""
    start_time = time.monotonic()
    try:
        planner = CapacityPlannerClient(cosmos_client, credential, subscription_id)
        result = planner.get_aks_node_quota_headroom()
        clusters_raw = result.get("clusters", [])

        clusters = [
            AKSNodePoolHeadroomItem(
                cluster_name=c.get("cluster_name", ""),
                resource_group=c.get("resource_group", ""),
                location=c.get("location", ""),
                pool_name=c.get("pool_name", ""),
                vm_size=c.get("vm_size", ""),
                quota_family=c.get("quota_family", "unknown"),
                current_nodes=c.get("current_nodes", 0),
                max_nodes=c.get("max_nodes", 0),
                available_nodes=c.get("available_nodes", 0),
                usage_pct=c.get("usage_pct", 0.0),
                traffic_light=c.get("traffic_light", "green"),
            )
            for c in clusters_raw
        ]
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "capacity_aks: subscription=%s clusters=%d duration_ms=%s",
            subscription_id, len(clusters), duration_ms,
        )
        return AKSHeadroomResponse(
            subscription_id=subscription_id,
            clusters=clusters,
            generated_at=result.get("generated_at", datetime.now(timezone.utc).isoformat()),
            duration_ms=int(duration_ms),
        )
    except Exception as exc:
        logger.warning("capacity_aks: error | subscription=%s error=%s", subscription_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)
