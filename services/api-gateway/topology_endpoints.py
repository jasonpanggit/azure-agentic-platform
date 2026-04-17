from __future__ import annotations
"""Topology graph API endpoints — blast-radius, path, snapshot, bootstrap.

Exposes the resource property graph (TOPO-001) via:
  GET  /api/v1/topology/blast-radius?resource_id=X&max_depth=3
  GET  /api/v1/topology/path?source=X&target=Y
  GET  /api/v1/topology/snapshot?resource_id=X
  POST /api/v1/topology/bootstrap  (operator use, auth required)

All endpoints require Entra ID Bearer token (verify_token).
TopologyClient is accessed via request.app.state.topology_client.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from services.api_gateway.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/topology", tags=["topology"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class AffectedResource(BaseModel):
    """A resource reachable within blast-radius from the origin."""

    resource_id: str
    resource_type: str
    resource_group: str
    subscription_id: str
    name: str
    hop_count: int


class BlastRadiusResponse(BaseModel):
    """Response for GET /api/v1/topology/blast-radius."""

    resource_id: str = Field(..., description="The queried origin resource ID")
    affected_resources: List[AffectedResource] = Field(
        ..., description="All resources reachable within max_depth hops"
    )
    hop_counts: Dict[str, int] = Field(
        ..., description="Map of resource_id → hop distance from origin"
    )
    total_affected: int = Field(..., description="Count of affected resources")
    query_duration_ms: float = Field(..., description="BFS query latency in milliseconds")


class PathResponse(BaseModel):
    """Response for GET /api/v1/topology/path."""

    source: str
    target: str
    path: List[str] = Field(..., description="Ordered resource IDs from source to target")
    hops: int = Field(..., description="Number of edges (len(path) - 1); -1 if not found")
    found: bool
    query_duration_ms: float


class TopologySnapshotResponse(BaseModel):
    """Response for GET /api/v1/topology/snapshot — full topology document."""

    id: str
    resource_id: str
    resource_type: str
    resource_group: str
    subscription_id: str
    name: str
    tags: Dict[str, str] = Field(default_factory=dict)
    relationships: List[Dict[str, str]] = Field(default_factory=list)
    last_synced_at: str


class BootstrapResponse(BaseModel):
    """Response for POST /api/v1/topology/bootstrap."""

    status: str  # "started" | "unavailable"
    message: str


# ---------------------------------------------------------------------------
# Dependency: get TopologyClient from app.state
# ---------------------------------------------------------------------------


def _get_topology_client(request: Request) -> Any:
    """Return the TopologyClient singleton from app.state.

    Raises HTTP 503 if TopologyClient was not initialized at startup
    (e.g., COSMOS_ENDPOINT not set).
    """
    client = getattr(request.app.state, "topology_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Topology service not available (COSMOS_ENDPOINT not set or bootstrap not run)",
        )
    return client


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/blast-radius", response_model=BlastRadiusResponse)
async def get_blast_radius(
    resource_id: str = Query(
        ...,
        description="Full ARM resource ID of the origin resource",
        min_length=1,
    ),
    max_depth: int = Query(
        3,
        ge=1,
        le=6,
        description="Maximum BFS hop depth (1–6, default 3)",
    ),
    topology_client: Any = Depends(_get_topology_client),
    _token: dict = Depends(verify_token),
) -> BlastRadiusResponse:
    """Return all resources within max_depth hops of the given resource (TOPO-002).

    BFS traverses the adjacency-list graph stored in Cosmos DB.
    Target: <2 seconds at ≥10,000 nodes (TOPO-005).

    Authentication: Entra ID Bearer token required.
    """
    start = time.monotonic()
    logger.info(
        "topology: blast_radius request | resource_id=%s max_depth=%d",
        resource_id[:80],
        max_depth,
    )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            topology_client.get_blast_radius,
            resource_id,
            max_depth,
        )
    except Exception as exc:
        logger.error("topology: blast_radius failed | error=%s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Blast-radius query failed: {exc}",
        ) from exc

    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "topology: blast_radius complete | origin=%s affected=%d duration_ms=%.0f",
        resource_id[:80],
        result.get("total_affected", 0),
        duration_ms,
    )

    affected = [AffectedResource(**r) for r in result.get("affected_resources", [])]
    return BlastRadiusResponse(
        resource_id=result["resource_id"],
        affected_resources=affected,
        hop_counts=result.get("hop_counts", {}),
        total_affected=result.get("total_affected", 0),
        query_duration_ms=round(duration_ms, 2),
    )


@router.get("/path", response_model=PathResponse)
async def get_path(
    source: str = Query(
        ...,
        description="ARM resource ID of the source node",
        min_length=1,
    ),
    target: str = Query(
        ...,
        description="ARM resource ID of the target node",
        min_length=1,
    ),
    topology_client: Any = Depends(_get_topology_client),
    _token: dict = Depends(verify_token),
) -> PathResponse:
    """Find the shortest path between two resources in the topology graph.

    Uses bidirectional BFS capped at depth 6. Returns found=False if no
    path exists within the search depth.

    Authentication: Entra ID Bearer token required.
    """
    start = time.monotonic()
    logger.info(
        "topology: path request | source=%s target=%s",
        source[:80],
        target[:80],
    )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            topology_client.get_path,
            source,
            target,
        )
    except Exception as exc:
        logger.error("topology: path query failed | error=%s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Path query failed: {exc}",
        ) from exc

    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "topology: path complete | found=%s hops=%d duration_ms=%.0f",
        result.get("found"),
        result.get("hops", -1),
        duration_ms,
    )

    return PathResponse(
        source=result["source"],
        target=result["target"],
        path=result.get("path", []),
        hops=result.get("hops", -1),
        found=result.get("found", False),
        query_duration_ms=round(duration_ms, 2),
    )


@router.get("/snapshot", response_model=TopologySnapshotResponse)
async def get_snapshot(
    resource_id: str = Query(
        ...,
        description="ARM resource ID to fetch the topology document for",
        min_length=1,
    ),
    topology_client: Any = Depends(_get_topology_client),
    _token: dict = Depends(verify_token),
) -> TopologySnapshotResponse:
    """Fetch the full topology document for a single resource.

    Returns the adjacency-list document exactly as stored in Cosmos DB
    (without internal Cosmos fields).

    Returns 404 if the resource is not in the topology graph.

    Authentication: Entra ID Bearer token required.
    """
    loop = asyncio.get_running_loop()
    try:
        doc = await loop.run_in_executor(
            None,
            topology_client.get_snapshot,
            resource_id,
        )
    except Exception as exc:
        logger.error("topology: snapshot failed | error=%s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Snapshot query failed: {exc}",
        ) from exc

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Resource not found in topology graph: {resource_id}",
        )

    return TopologySnapshotResponse(**doc)


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_bootstrap(
    request: Request,
    _token: dict = Depends(verify_token),
) -> BootstrapResponse:
    """Trigger a full ARG re-bootstrap of the topology graph (operator use).

    Runs bootstrap in a background asyncio task so the endpoint returns
    202 immediately. Monitor progress via application logs.

    Use this to recover from topology drift or after a large-scale
    infrastructure change.

    Authentication: Entra ID Bearer token required.
    """
    topology_client = getattr(request.app.state, "topology_client", None)
    if topology_client is None:
        return BootstrapResponse(
            status="unavailable",
            message="Topology service not initialized — COSMOS_ENDPOINT not set",
        )

    async def _run_bootstrap():
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, topology_client.bootstrap)
            logger.info(
                "topology: manual bootstrap complete | upserted=%d errors=%d",
                result.get("upserted", 0),
                result.get("errors", 0),
            )
        except Exception as exc:
            logger.error("topology: manual bootstrap failed | error=%s", exc, exc_info=True)

    asyncio.create_task(_run_bootstrap())
    logger.info("topology: manual bootstrap triggered by operator")

    return BootstrapResponse(
        status="started",
        message="Bootstrap started in background. Check application logs for progress.",
    )
