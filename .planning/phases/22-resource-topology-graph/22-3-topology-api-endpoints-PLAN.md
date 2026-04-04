---
wave: 2
depends_on: [22-1, 22-2]
requirements: [TOPO-001, TOPO-002, TOPO-003]
autonomous: true
files_modified:
  - services/api-gateway/topology_endpoints.py   # new — FastAPI router
  - services/api-gateway/main.py                 # add router + TopologyClient lifespan init
  - services/api-gateway/tests/test_topology_endpoints.py  # new — unit tests
---

# Plan 22-3: Topology API Endpoints

Expose the topology service via a FastAPI router. Register the router and initialize `TopologyClient` in the existing lifespan. Authenticate all write operations with `verify_token`. Read endpoints (blast-radius, path, snapshot) are also token-protected. Add a `POST /api/v1/topology/bootstrap` operator endpoint (auth required).

---

<task id="22-3-01">
<title>Create services/api-gateway/topology_endpoints.py — FastAPI router</title>

<read_first>
- `services/api-gateway/topology.py` — `TopologyClient`, `TopologyDocument`, `run_topology_sync_loop` (Plan 22-2)
- `services/api-gateway/vm_inventory.py` — router declaration, `APIRouter(prefix="/api/v1", tags=[...])`, `Depends(get_credential)`, `Depends(verify_token)` pattern
- `services/api-gateway/dependencies.py` — `get_credential`, `get_cosmos_client`, `get_optional_cosmos_client`
- `services/api-gateway/main.py` — `app.state` access pattern; `request.app.state.topology_client` will be set in lifespan (task 22-3-02)
- `.planning/phases/22-resource-topology-graph/22-CONTEXT.md` — API endpoint shapes and response structures
</read_first>

<action>
Create `services/api-gateway/topology_endpoints.py`:

```python
"""Topology graph API endpoints — blast-radius, path, snapshot, bootstrap.

Exposes the resource property graph (TOPO-001) via:
  GET  /api/v1/topology/blast-radius?resource_id=X&max_depth=3
  GET  /api/v1/topology/path?source=X&target=Y
  GET  /api/v1/topology/snapshot?resource_id=X
  POST /api/v1/topology/bootstrap  (operator use, auth required)

All endpoints require Entra ID Bearer token (verify_token).
TopologyClient is accessed via request.app.state.topology_client.
"""
from __future__ import annotations

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
```
</action>

<acceptance_criteria>
```bash
# Router is importable and has correct prefix
python -c "
from services.api_gateway.topology_endpoints import router
assert router.prefix == '/api/v1/topology', f'Wrong prefix: {router.prefix}'
print('router OK')
"

# All 4 routes registered
python -c "
from services.api_gateway.topology_endpoints import router
paths = [r.path for r in router.routes]
assert any('blast-radius' in p for p in paths), 'missing blast-radius'
assert any('path' in p for p in paths), 'missing path'
assert any('snapshot' in p for p in paths), 'missing snapshot'
assert any('bootstrap' in p for p in paths), 'missing bootstrap'
print('routes OK')
"

# Response models are importable
python -c "
from services.api_gateway.topology_endpoints import (
    BlastRadiusResponse, PathResponse, TopologySnapshotResponse, BootstrapResponse
)
print('models OK')
"
```
</acceptance_criteria>
</task>

---

<task id="22-3-02">
<title>Update services/api-gateway/main.py — register router, init TopologyClient in lifespan</title>

<read_first>
- `services/api-gateway/main.py` — FULL FILE: the lifespan function (lines 169–194), all existing `app.include_router()` calls (lines 211–215), and how `app.state.cosmos_client` is initialized — must mirror this pattern for `topology_client`
- `services/api-gateway/topology.py` — `TopologyClient.__init__(cosmos_client, credential, subscription_ids)` signature and `run_topology_sync_loop(topology_client)` coroutine
- `services/api-gateway/topology_endpoints.py` — `router` (just created in task 22-3-01)
</read_first>

<action>
Make three targeted edits to `services/api-gateway/main.py`:

**Edit 1 — Add import** at the top of the imports block (after the existing `from services.api_gateway.vm_chat import router as vm_chat_router` line):

```python
from services.api_gateway.topology_endpoints import router as topology_router
from services.api_gateway.topology import TopologyClient, run_topology_sync_loop
```

**Edit 2 — Initialize TopologyClient in lifespan** (inside the `lifespan` async context manager, after `app.state.cosmos_client` is set and before `await _run_startup_migrations()`):

```python
    # Initialize TopologyClient and run bootstrap if Cosmos is configured (TOPO-001)
    _topology_sync_task = None
    subscription_ids_raw = os.environ.get("SUBSCRIPTION_IDS", "")
    _subscription_ids = [s.strip() for s in subscription_ids_raw.split(",") if s.strip()]
    if app.state.cosmos_client is not None and _subscription_ids:
        app.state.topology_client = TopologyClient(
            cosmos_client=app.state.cosmos_client,
            credential=app.state.credential,
            subscription_ids=_subscription_ids,
        )
        # Bootstrap synchronously in startup (blocks until complete — acceptable for
        # Container App startup; large estates may take 30–60s but remain within
        # Container Apps' 240s startup grace period)
        loop = asyncio.get_running_loop()
        try:
            bootstrap_result = await loop.run_in_executor(
                None, app.state.topology_client.bootstrap
            )
            logger.info(
                "startup: topology bootstrap complete | upserted=%d errors=%d",
                bootstrap_result.get("upserted", 0),
                bootstrap_result.get("errors", 0),
            )
        except Exception as exc:
            logger.warning("startup: topology bootstrap failed (non-fatal) | error=%s", exc)
        # Launch background sync loop (TOPO-003: <15 min freshness lag)
        _topology_sync_task = asyncio.create_task(
            run_topology_sync_loop(app.state.topology_client)
        )
        logger.info("startup: topology sync loop started | interval=900s")
    else:
        app.state.topology_client = None
        logger.warning(
            "startup: topology_client not initialized "
            "(COSMOS_ENDPOINT=%s, SUBSCRIPTION_IDS=%s)",
            "set" if app.state.cosmos_client else "not_set",
            "set" if _subscription_ids else "not_set",
        )
```

Add teardown of the sync task in the lifespan `yield` → shutdown section. After `if app.state.cosmos_client is not None: app.state.cosmos_client.close()`, add:

```python
    # Cancel topology sync loop on shutdown
    if _topology_sync_task is not None and not _topology_sync_task.done():
        _topology_sync_task.cancel()
        try:
            await _topology_sync_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown: topology sync loop cancelled")
```

**Edit 3 — Include topology router** after the existing `app.include_router(vm_chat_router)` line:

```python
app.include_router(topology_router)
```

IMPORTANT: `asyncio` is already imported in `main.py`. Do NOT add a duplicate import. Verify before editing.
</action>

<acceptance_criteria>
```bash
# main.py imports topology_router and TopologyClient
grep 'topology_router\|TopologyClient\|run_topology_sync_loop' services/api-gateway/main.py | wc -l | awk '$1 >= 3 {print "imports OK"}'

# topology_router is included
grep 'include_router(topology_router)' services/api-gateway/main.py

# TopologyClient initialized in lifespan
grep 'topology_client = TopologyClient' services/api-gateway/main.py

# Background sync task started
grep 'run_topology_sync_loop' services/api-gateway/main.py

# No duplicate asyncio import
grep '^import asyncio' services/api-gateway/main.py | wc -l | awk '$1 == 1 {print "no duplicate import"}'

# FastAPI app starts without import errors
python -c "
import sys; sys.path.insert(0, '.')
# Patch env to skip real Azure/Cosmos init
import os; os.environ.setdefault('COSMOS_ENDPOINT', ''); os.environ.setdefault('SUBSCRIPTION_IDS', '')
from services.api_gateway.topology_endpoints import router
print('main.py topology import OK')
"
```
</acceptance_criteria>
</task>

---

<task id="22-3-03">
<title>Unit tests for topology API endpoints</title>

<read_first>
- `services/api-gateway/tests/test_vm_detail.py` or `test_incidents.py` — test pattern for FastAPI TestClient with mocked `app.state` and `verify_token` bypass
- `services/api-gateway/tests/conftest.py` — check for shared `client` fixture and `mock_verify_token` fixture
- `services/api-gateway/topology_endpoints.py` — the router just created
- `services/api-gateway/topology.py` — `TopologyClient` method signatures for mock setup
</read_first>

<action>
Create `services/api-gateway/tests/test_topology_endpoints.py`:

```python
"""Unit tests for topology API endpoints (topology_endpoints.py).

Tests cover all four endpoints with mocked TopologyClient:
- GET /api/v1/topology/blast-radius
- GET /api/v1/topology/path
- GET /api/v1/topology/snapshot
- POST /api/v1/topology/bootstrap

Uses FastAPI TestClient with app.state.topology_client overridden to a mock.
verify_token is patched to return a dummy claims dict.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.topology_endpoints import router


# ---------------------------------------------------------------------------
# Test app fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_topology_client():
    """Create a minimal FastAPI app with the topology router and a mock TopologyClient."""
    test_app = FastAPI()
    test_app.include_router(router)

    mock_client = MagicMock()
    test_app.state.topology_client = mock_client

    return test_app, mock_client


@pytest.fixture()
def client_with_mock(app_with_topology_client):
    test_app, mock_topology_client = app_with_topology_client
    with patch("services.api_gateway.topology_endpoints.verify_token", return_value={"sub": "test-user"}):
        with TestClient(test_app) as c:
            yield c, mock_topology_client


@pytest.fixture()
def client_no_topology():
    """TestClient with topology_client=None to test 503 responses."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.topology_client = None
    with patch("services.api_gateway.topology_endpoints.verify_token", return_value={"sub": "test-user"}):
        with TestClient(test_app) as c:
            yield c


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_ORIGIN_ID = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"
_NIC_ID = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"

_BLAST_RADIUS_RESULT = {
    "resource_id": _ORIGIN_ID,
    "affected_resources": [
        {
            "resource_id": _NIC_ID,
            "resource_type": "microsoft.network/networkinterfaces",
            "resource_group": "rg1",
            "subscription_id": "s1",
            "name": "nic1",
            "hop_count": 1,
        }
    ],
    "hop_counts": {_NIC_ID: 1},
    "total_affected": 1,
}

_PATH_RESULT = {
    "source": _ORIGIN_ID,
    "target": _NIC_ID,
    "path": [_ORIGIN_ID, _NIC_ID],
    "hops": 1,
    "found": True,
}

_SNAPSHOT_DOC = {
    "id": _ORIGIN_ID,
    "resource_id": _ORIGIN_ID,
    "resource_type": "microsoft.compute/virtualmachines",
    "resource_group": "rg1",
    "subscription_id": "s1",
    "name": "vm1",
    "tags": {"env": "prod"},
    "relationships": [
        {"target_id": _NIC_ID, "rel_type": "nic_of", "direction": "outbound"}
    ],
    "last_synced_at": "2026-04-03T10:00:00+00:00",
}


# ---------------------------------------------------------------------------
# GET /blast-radius tests
# ---------------------------------------------------------------------------


class TestBlastRadiusEndpoint:
    def test_returns_200_with_affected_resources(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_blast_radius.return_value = _BLAST_RADIUS_RESULT

        resp = http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID, "max_depth": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resource_id"] == _ORIGIN_ID
        assert data["total_affected"] == 1
        assert len(data["affected_resources"]) == 1
        assert data["affected_resources"][0]["resource_id"] == _NIC_ID
        assert "query_duration_ms" in data

    def test_passes_max_depth_to_client(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_blast_radius.return_value = {
            "resource_id": _ORIGIN_ID,
            "affected_resources": [],
            "hop_counts": {},
            "total_affected": 0,
        }

        http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID, "max_depth": 2},
        )
        call_args = mock_topology_client.get_blast_radius.call_args
        assert call_args[0][1] == 2  # max_depth positional arg

    def test_missing_resource_id_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get("/api/v1/topology/blast-radius")
        assert resp.status_code == 422

    def test_max_depth_above_6_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID, "max_depth": 10},
        )
        assert resp.status_code == 422

    def test_returns_503_when_client_unavailable(self, client_no_topology):
        resp = client_no_topology.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 503

    def test_returns_500_when_client_raises(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_blast_radius.side_effect = RuntimeError("Cosmos timeout")

        resp = http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /path tests
# ---------------------------------------------------------------------------


class TestPathEndpoint:
    def test_returns_200_with_path(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_path.return_value = _PATH_RESULT

        resp = http_client.get(
            "/api/v1/topology/path",
            params={"source": _ORIGIN_ID, "target": _NIC_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["hops"] == 1
        assert len(data["path"]) == 2
        assert "query_duration_ms" in data

    def test_returns_found_false_when_no_path(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_path.return_value = {
            "source": _ORIGIN_ID,
            "target": "/subscriptions/s1/resourcegroups/rg2/providers/microsoft.compute/virtualmachines/vm99",
            "path": [],
            "hops": -1,
            "found": False,
        }

        resp = http_client.get(
            "/api/v1/topology/path",
            params={"source": _ORIGIN_ID, "target": "/subscriptions/s1/resourcegroups/rg2/providers/microsoft.compute/virtualmachines/vm99"},
        )
        assert resp.status_code == 200
        assert resp.json()["found"] is False
        assert resp.json()["hops"] == -1

    def test_missing_source_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get("/api/v1/topology/path", params={"target": _NIC_ID})
        assert resp.status_code == 422

    def test_missing_target_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get("/api/v1/topology/path", params={"source": _ORIGIN_ID})
        assert resp.status_code == 422

    def test_returns_503_when_client_unavailable(self, client_no_topology):
        resp = client_no_topology.get(
            "/api/v1/topology/path",
            params={"source": _ORIGIN_ID, "target": _NIC_ID},
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /snapshot tests
# ---------------------------------------------------------------------------


class TestSnapshotEndpoint:
    def test_returns_200_with_document(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_snapshot.return_value = _SNAPSHOT_DOC

        resp = http_client.get(
            "/api/v1/topology/snapshot",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resource_id"] == _ORIGIN_ID
        assert data["resource_type"] == "microsoft.compute/virtualmachines"
        assert data["name"] == "vm1"
        assert len(data["relationships"]) == 1

    def test_returns_404_when_not_found(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_snapshot.return_value = None

        resp = http_client.get(
            "/api/v1/topology/snapshot",
            params={"resource_id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/missing"},
        )
        assert resp.status_code == 404

    def test_missing_resource_id_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get("/api/v1/topology/snapshot")
        assert resp.status_code == 422

    def test_returns_503_when_client_unavailable(self, client_no_topology):
        resp = client_no_topology.get(
            "/api/v1/topology/snapshot",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /bootstrap tests
# ---------------------------------------------------------------------------


class TestBootstrapEndpoint:
    def test_returns_202_and_starts_background(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock

        with patch("services.api_gateway.topology_endpoints.asyncio.create_task") as mock_task:
            resp = http_client.post("/api/v1/topology/bootstrap")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "started"
        assert "background" in data["message"].lower()

    def test_returns_unavailable_when_no_client(self, client_no_topology):
        resp = client_no_topology.post("/api/v1/topology/bootstrap")
        # 202 is returned but with status=unavailable
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "unavailable"
```
</action>

<acceptance_criteria>
```bash
# Tests pass
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_topology_endpoints.py -v 2>&1 | tail -25

# Test count (≥15 tests)
python -m pytest services/api-gateway/tests/test_topology_endpoints.py --collect-only -q 2>&1 | grep 'test session starts' -A 100 | grep '::test_' | wc -l
```
</acceptance_criteria>
</task>

---

## must_haves

- [ ] `services/api-gateway/topology_endpoints.py` created with `APIRouter(prefix="/api/v1/topology", tags=["topology"])`
- [ ] `GET /api/v1/topology/blast-radius` accepts `resource_id` (required) and `max_depth` (1–6, default 3); returns `BlastRadiusResponse` with `query_duration_ms`
- [ ] `GET /api/v1/topology/path` accepts `source` and `target` (both required); returns `PathResponse` with `found` bool and `hops=-1` when no path
- [ ] `GET /api/v1/topology/snapshot` accepts `resource_id`; returns `TopologySnapshotResponse` (200) or 404 when not found
- [ ] `POST /api/v1/topology/bootstrap` returns 202 immediately; bootstrap runs in background via `asyncio.create_task`
- [ ] All endpoints return 503 when `app.state.topology_client is None`
- [ ] All endpoints protected by `Depends(verify_token)`
- [ ] Topology-heavy operations (BFS, bootstrap) run in `loop.run_in_executor(None, ...)` — never block the event loop
- [ ] `main.py` updated: imports `topology_router` + `TopologyClient` + `run_topology_sync_loop`; calls `app.include_router(topology_router)`; initializes `TopologyClient` in lifespan (conditional on `COSMOS_ENDPOINT` + `SUBSCRIPTION_IDS` both set); cancels sync task on shutdown
- [ ] Bootstrap in lifespan is non-fatal — `except Exception` catches failures and logs a warning; app continues to start even if bootstrap fails
- [ ] `services/api-gateway/tests/test_topology_endpoints.py` created with ≥15 tests; all pass with mocked TopologyClient
