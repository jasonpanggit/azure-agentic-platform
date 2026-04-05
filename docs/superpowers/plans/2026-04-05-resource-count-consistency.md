# Resource Count Consistency via ARG Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the resource count discrepancy between Topology tab and Resources tab by routing both through the API gateway using Azure Resource Graph (ARG), replacing direct ARM calls from the web UI.

**Architecture:** Two new API gateway endpoints (`GET /api/v1/resources/inventory` and `GET /api/v1/topology/tree`) query ARG via the shared `run_arg_query()` helper. The Next.js web UI routes these through new proxy routes (`/api/proxy/resources` and `/api/proxy/topology`). The old direct-ARM Next.js API routes (`/api/topology` and `/api/resources`) are deleted. Both tabs now see the same data source — same KQL, same count.

**Tech Stack:** Python/FastAPI (API gateway), `azure-mgmt-resourcegraph` (ARG SDK), TypeScript/Next.js (proxy routes), pytest (Python tests)

---

## Chunk 1: API Gateway — Resources Inventory Endpoint

### Task 1: Write failing tests for `resources_inventory.py`

**Files:**
- Create: `services/api-gateway/tests/test_resources_inventory.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for GET /api/v1/resources/inventory — flat resource listing.

Tests cover:
- list_resources route: success response shape with resources + resourceTypes
- ARG rows → response items mapping (id, name, type, location)
- resourceTypes derived from distinct type values sorted alphabetically
- Empty subscription list returns empty resources
- ARG failure returns 500
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


@pytest.fixture()
def client():
    from services.api_gateway.main import app
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None
    return TestClient(app)


def _arg_row(name: str, rtype: str, rg: str = "rg-prod", sub: str = "sub1", loc: str = "eastus") -> dict:
    return {
        "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{rtype}/{name}",
        "name": name,
        "type": rtype,
        "resourceGroup": rg,
        "subscriptionId": sub,
        "location": loc,
    }


def test_list_resources_success(client):
    rows = [
        _arg_row("vm-001", "microsoft.compute/virtualmachines"),
        _arg_row("kv-001", "microsoft.keyvault/vaults"),
        _arg_row("vm-002", "microsoft.compute/virtualmachines"),
    ]
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        return_value=rows,
    ):
        resp = client.get("/api/v1/resources/inventory?subscriptions=sub1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["resources"]) == 3
    assert data["total"] == 3


def test_list_resources_response_shape(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines")]
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        return_value=rows,
    ):
        resp = client.get("/api/v1/resources/inventory?subscriptions=sub1")
    item = resp.json()["resources"][0]
    assert "id" in item
    assert "name" in item
    assert "type" in item
    assert "location" in item


def test_list_resources_types_sorted(client):
    rows = [
        _arg_row("kv-001", "microsoft.keyvault/vaults"),
        _arg_row("vm-001", "microsoft.compute/virtualmachines"),
    ]
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        return_value=rows,
    ):
        resp = client.get("/api/v1/resources/inventory?subscriptions=sub1")
    types = resp.json()["resourceTypes"]
    assert types == sorted(types)
    assert "microsoft.compute/virtualmachines" in types
    assert "microsoft.keyvault/vaults" in types


def test_list_resources_empty_subscriptions(client):
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        return_value=[],
    ):
        resp = client.get("/api/v1/resources/inventory")
    assert resp.status_code == 200
    data = resp.json()
    assert data["resources"] == []
    assert data["total"] == 0
    assert data["resourceTypes"] == []


def test_list_resources_arg_failure_returns_500(client):
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        side_effect=Exception("ARG unavailable"),
    ):
        resp = client.get("/api/v1/resources/inventory?subscriptions=sub1")
    assert resp.status_code == 500
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_resources_inventory.py -v 2>&1 | head -30
```

Expected: `ERROR` or `ImportError` — `resources_inventory` module does not exist yet.

---

### Task 2: Implement `resources_inventory.py`

**Files:**
- Create: `services/api-gateway/resources_inventory.py`

- [ ] **Step 1: Create the module**

```python
"""Resources inventory endpoint — flat listing of all Azure resources via ARG.

GET /api/v1/resources/inventory
  ?subscriptions=sub1,sub2   (optional, comma-separated; all accessible if omitted)

Response: { resources: [...], total: int, resourceTypes: [...] }

Each resource item: { id, name, type, location }

Uses run_arg_query() from arg_helper so counts match topology/tree exactly
(same ARG data source, no ARM pagination caps).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api_gateway.arg_helper import run_arg_query
from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])

# KQL: project only the fields needed by the Resources tab.
# No filter, no cap — full inventory across all resource types.
_RESOURCES_KQL = """
Resources
| project
    id       = tolower(id),
    name,
    type     = tolower(type),
    location,
    resourceGroup,
    subscriptionId
| order by type asc, name asc
"""


@router.get("/inventory")
async def list_resources(
    subscriptions: str = Query(
        default="",
        description="Comma-separated subscription IDs. All accessible if omitted.",
    ),
    credential: Any = Depends(get_credential),
    _token: dict = Depends(verify_token),
) -> Dict[str, Any]:
    """Return all Azure resources across the specified subscriptions.

    Uses ARG for cross-subscription inventory — no per-page caps.
    Counts here will always match GET /api/v1/topology/tree.
    """
    start = time.monotonic()
    subscription_ids: List[str] = (
        [s.strip() for s in subscriptions.split(",") if s.strip()]
        if subscriptions
        else []
    )

    logger.info(
        "resources_inventory: request | subscriptions=%d",
        len(subscription_ids),
    )

    loop = asyncio.get_running_loop()
    try:
        rows: List[Dict[str, Any]] = await loop.run_in_executor(
            None,
            run_arg_query,
            credential,
            subscription_ids,
            _RESOURCES_KQL,
        )
    except Exception as exc:
        logger.error("resources_inventory: ARG query failed | error=%s", exc)
        raise HTTPException(status_code=500, detail=f"ARG query failed: {exc}") from exc

    resources = [
        {
            "id": row.get("id", ""),
            "name": row.get("name", ""),
            "type": row.get("type", ""),
            "location": row.get("location", ""),
        }
        for row in rows
    ]

    resource_types = sorted({r["type"] for r in resources if r["type"]})

    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "resources_inventory: complete | count=%d duration_ms=%.0f",
        len(resources),
        duration_ms,
    )

    return {
        "resources": resources,
        "total": len(resources),
        "resourceTypes": resource_types,
    }
```

- [ ] **Step 2: Register the router in `main.py`**

In `services/api-gateway/main.py`, add after the existing topology import (around line 100):

```python
from services.api_gateway.resources_inventory import router as resources_inventory_router
```

And after `app.include_router(forecast_router)` (around line 471):

```python
app.include_router(resources_inventory_router)
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_resources_inventory.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add services/api-gateway/resources_inventory.py \
        services/api-gateway/tests/test_resources_inventory.py \
        services/api-gateway/main.py
git commit -m "feat: add ARG-backed resources inventory endpoint"
```

---

## Chunk 2: API Gateway — Topology Tree Endpoint

### Task 3: Write failing tests for `topology_tree.py`

**Files:**
- Create: `services/api-gateway/tests/test_topology_tree.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for GET /api/v1/topology/tree — hierarchical resource tree.

Tests cover:
- tree response shape: nodes list + edges list
- subscription/resourceGroup/resource node kinds
- parentId linking (sub → rg → resource)
- resourceCount on resourceGroup nodes equals actual child count
- ARG failure returns 500
- Empty subscriptions returns empty nodes/edges
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


@pytest.fixture()
def client():
    from services.api_gateway.main import app
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None
    return TestClient(app)


def _arg_row(
    name: str,
    rtype: str,
    rg: str,
    sub: str,
    loc: str = "eastus",
) -> dict:
    return {
        "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{rtype}/{name}",
        "name": name,
        "type": rtype,
        "resourceGroup": rg,
        "subscriptionId": sub,
        "location": loc,
    }


def _sub_row(sub_id: str, display_name: str) -> dict:
    return {"subscriptionId": sub_id, "displayName": display_name}


def test_tree_response_has_nodes_and_edges(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data


def test_tree_has_subscription_node(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    nodes = resp.json()["nodes"]
    sub_nodes = [n for n in nodes if n["kind"] == "subscription"]
    assert len(sub_nodes) == 1
    assert sub_nodes[0]["label"] == "My Sub"
    assert sub_nodes[0]["parentId"] is None


def test_tree_has_resource_group_node(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    nodes = resp.json()["nodes"]
    rg_nodes = [n for n in nodes if n["kind"] == "resourceGroup"]
    assert len(rg_nodes) == 1
    assert rg_nodes[0]["label"] == "rg-prod"
    assert rg_nodes[0]["resourceCount"] == 1


def test_tree_has_resource_node(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    nodes = resp.json()["nodes"]
    res_nodes = [n for n in nodes if n["kind"] == "resource"]
    assert len(res_nodes) == 1
    assert res_nodes[0]["label"] == "vm-001"
    assert res_nodes[0]["type"] == "microsoft.compute/virtualmachines"


def test_tree_edges_link_sub_to_rg_to_resource(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    data = resp.json()
    edges = data["edges"]
    sub_node = next(n for n in data["nodes"] if n["kind"] == "subscription")
    rg_node = next(n for n in data["nodes"] if n["kind"] == "resourceGroup")
    res_node = next(n for n in data["nodes"] if n["kind"] == "resource")
    assert {"source": sub_node["id"], "target": rg_node["id"]} in edges
    assert {"source": rg_node["id"], "target": res_node["id"]} in edges


def test_tree_resource_count_matches_children(client):
    rows = [
        _arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1"),
        _arg_row("vm-002", "microsoft.compute/virtualmachines", "rg-prod", "sub1"),
        _arg_row("kv-001", "microsoft.keyvault/vaults", "rg-prod", "sub1"),
    ]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    nodes = resp.json()["nodes"]
    rg_node = next(n for n in nodes if n["kind"] == "resourceGroup")
    resource_nodes = [n for n in nodes if n["kind"] == "resource"]
    assert rg_node["resourceCount"] == len(resource_nodes)


def test_tree_arg_failure_returns_500(client):
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch(
        "services.api_gateway.topology_tree.run_arg_query",
        side_effect=[sub_rows, Exception("ARG down")],
    ):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    assert resp.status_code == 500


def test_tree_empty_subscriptions_returns_empty(client):
    with patch(
        "services.api_gateway.topology_tree.run_arg_query",
        side_effect=[[], []],
    ):
        resp = client.get("/api/v1/topology/tree")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
    assert data["edges"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_topology_tree.py -v 2>&1 | head -30
```

Expected: `ERROR` or `ImportError` — `topology_tree` module does not exist yet.

---

### Task 4: Implement `topology_tree.py`

**Files:**
- Create: `services/api-gateway/topology_tree.py`

- [ ] **Step 1: Create the module**

```python
"""Topology tree endpoint — hierarchical subscription → RG → resource view via ARG.

GET /api/v1/topology/tree
  ?subscriptions=sub1,sub2   (optional, comma-separated; all accessible if omitted)

Response: { nodes: [...], edges: [...] }

Node shapes:
  subscription: { id, label, kind="subscription", parentId=null }
  resourceGroup: { id, label, kind="resourceGroup", location, parentId, resourceCount }
  resource:      { id, label, kind="resource", type, location, parentId }

Uses run_arg_query() so counts are identical to /api/v1/resources/inventory.
No per-RG cap, no global resource cap.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api_gateway.arg_helper import run_arg_query
from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/topology", tags=["topology"])

# KQL: subscription display names
_SUBSCRIPTIONS_KQL = """
ResourceContainers
| where type =~ 'microsoft.resources/subscriptions'
| project subscriptionId, displayName = name
"""

# KQL: all resources with group + location. No type filter — full inventory.
_TREE_RESOURCES_KQL = """
Resources
| project
    id            = tolower(id),
    name,
    type          = tolower(type),
    resourceGroup,
    subscriptionId,
    location
"""


@router.get("/tree")
async def get_topology_tree(
    subscriptions: str = Query(
        default="",
        description="Comma-separated subscription IDs. All accessible if omitted.",
    ),
    credential: Any = Depends(get_credential),
    _token: dict = Depends(verify_token),
) -> Dict[str, Any]:
    """Return a three-tier resource tree: subscriptions → resource groups → resources.

    Counts are accurate — backed by ARG with full pagination, no caps.
    Matches counts from GET /api/v1/resources/inventory exactly.
    """
    start = time.monotonic()
    subscription_ids: List[str] = (
        [s.strip() for s in subscriptions.split(",") if s.strip()]
        if subscriptions
        else []
    )

    logger.info(
        "topology_tree: request | subscriptions=%d",
        len(subscription_ids),
    )

    loop = asyncio.get_running_loop()

    # Step 1: resolve subscription display names
    try:
        sub_rows: List[Dict[str, Any]] = await loop.run_in_executor(
            None,
            run_arg_query,
            credential,
            subscription_ids,
            _SUBSCRIPTIONS_KQL,
        )
    except Exception as exc:
        logger.warning("topology_tree: subscription name query failed | error=%s", exc)
        sub_rows = []

    sub_names: Dict[str, str] = {
        row["subscriptionId"]: row.get("displayName", row["subscriptionId"])
        for row in sub_rows
        if row.get("subscriptionId")
    }

    # Step 2: fetch all resources
    try:
        resource_rows: List[Dict[str, Any]] = await loop.run_in_executor(
            None,
            run_arg_query,
            credential,
            subscription_ids,
            _TREE_RESOURCES_KQL,
        )
    except Exception as exc:
        logger.error("topology_tree: ARG resource query failed | error=%s", exc)
        raise HTTPException(status_code=500, detail=f"ARG query failed: {exc}") from exc

    # Step 3: group resources by subscription → resource group
    # rg_resources[sub_id][rg_name_lower] = list of resource rows
    rg_resources: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    rg_locations: Dict[str, Dict[str, str]] = defaultdict(dict)

    for row in resource_rows:
        sub_id: str = row.get("subscriptionId", "")
        rg_name: str = (row.get("resourceGroup") or "").lower()
        loc: str = row.get("location", "")
        if sub_id and rg_name:
            rg_resources[sub_id][rg_name].append(row)
            if rg_name not in rg_locations[sub_id]:
                rg_locations[sub_id][rg_name] = loc

    # Step 4: build node + edge lists
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []

    # Collect unique subscription IDs from results + explicit filter
    all_sub_ids = set(subscription_ids) | set(rg_resources.keys())

    for sub_id in sorted(all_sub_ids):
        sub_node_id = f"sub:{sub_id}"
        nodes.append({
            "id": sub_node_id,
            "label": sub_names.get(sub_id, sub_id),
            "kind": "subscription",
            "parentId": None,
        })

        for rg_name, resources in sorted(rg_resources[sub_id].items()):
            rg_node_id = f"rg:{sub_id}:{rg_name}"
            rg_loc = rg_locations[sub_id].get(rg_name, "")
            nodes.append({
                "id": rg_node_id,
                "label": rg_name,
                "kind": "resourceGroup",
                "location": rg_loc,
                "parentId": sub_node_id,
                "resourceCount": len(resources),
            })
            edges.append({"source": sub_node_id, "target": rg_node_id})

            for resource in resources:
                res_node_id = f"res:{resource['id']}"
                nodes.append({
                    "id": res_node_id,
                    "label": resource.get("name", ""),
                    "kind": "resource",
                    "type": resource.get("type", ""),
                    "location": resource.get("location", ""),
                    "parentId": rg_node_id,
                })
                edges.append({"source": rg_node_id, "target": res_node_id})

    duration_ms = (time.monotonic() - start) * 1000
    resource_count = sum(1 for n in nodes if n["kind"] == "resource")
    logger.info(
        "topology_tree: complete | nodes=%d resources=%d duration_ms=%.0f",
        len(nodes),
        resource_count,
        duration_ms,
    )

    return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 2: Register the router in `main.py`**

In `services/api-gateway/main.py`, add after the `resources_inventory_router` import:

```python
from services.api_gateway.topology_tree import router as topology_tree_router
```

And after `app.include_router(resources_inventory_router)`:

```python
app.include_router(topology_tree_router)
```

**Note:** The new `topology_tree_router` uses the same prefix `"/api/v1/topology"` as the existing `topology_router` but adds a distinct `/tree` path — no conflict.

- [ ] **Step 3: Run tests to verify they pass**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_topology_tree.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add services/api-gateway/topology_tree.py \
        services/api-gateway/tests/test_topology_tree.py \
        services/api-gateway/main.py
git commit -m "feat: add ARG-backed topology tree endpoint"
```

---

## Chunk 3: Next.js Proxy Routes

### Task 5: Create `/api/proxy/resources` proxy route

**Files:**
- Create: `services/web-ui/app/api/proxy/resources/route.ts`

- [ ] **Step 1: Create the proxy route**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/resources' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/resources
 *
 * Proxies resource inventory requests to the API gateway ARG endpoint.
 * Replaces the old direct-ARM /api/resources route.
 *
 * Query params forwarded: subscriptions
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptions = searchParams.get('subscriptions') ?? '';

  log.info('proxy request', { method: 'GET', subscriptions });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/resources/inventory`);
    if (subscriptions) url.searchParams.set('subscriptions', subscriptions);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      log.warn('upstream error', { status: res.status });
      return NextResponse.json(
        { error: `Upstream error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('resources response', { total: data?.total });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('proxy error', { error: message });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
```

- [ ] **Step 2: Verify the file was created correctly**

```bash
cat services/web-ui/app/api/proxy/resources/route.ts
```

---

### Task 6: Create `/api/proxy/topology` proxy route

**Files:**
- Create: `services/web-ui/app/api/proxy/topology/route.ts`

- [ ] **Step 1: Create the proxy route**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/topology' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/topology
 *
 * Proxies topology tree requests to the API gateway ARG endpoint.
 * Replaces the old direct-ARM /api/topology route.
 *
 * Query params forwarded: subscriptions
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptions = searchParams.get('subscriptions') ?? '';

  log.info('proxy request', { method: 'GET', subscriptions });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/topology/tree`);
    if (subscriptions) url.searchParams.set('subscriptions', subscriptions);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      log.warn('upstream error', { status: res.status });
      return NextResponse.json(
        { error: `Upstream error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('topology response', { node_count: data?.nodes?.length });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('proxy error', { error: message });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
```

- [ ] **Step 2: Commit proxy routes**

```bash
git add services/web-ui/app/api/proxy/resources/route.ts \
        services/web-ui/app/api/proxy/topology/route.ts
git commit -m "feat: add proxy routes for resources and topology via API gateway"
```

---

## Chunk 4: Update Frontend Components + Delete Old Routes

### Task 7: Update `ResourcesTab.tsx` to use new proxy URL

**Files:**
- Modify: `services/web-ui/components/ResourcesTab.tsx:94`

- [ ] **Step 1: Change the fetch URL**

In `services/web-ui/components/ResourcesTab.tsx`, change line 94:

```typescript
// Before
const res = await fetch(`/api/resources?${params.toString()}`);

// After
const res = await fetch(`/api/proxy/resources?${params.toString()}`);
```

- [ ] **Step 2: Verify the change**

```bash
grep "fetch.*api/" services/web-ui/components/ResourcesTab.tsx
```

Expected output: `/api/proxy/resources`

---

### Task 8: Update `TopologyTab.tsx` to use new proxy URL

**Files:**
- Modify: `services/web-ui/components/TopologyTab.tsx:183`

- [ ] **Step 1: Change the fetch URL**

In `services/web-ui/components/TopologyTab.tsx`, change line 183:

```typescript
// Before
const res = await fetch(`/api/topology?${params.toString()}`);

// After
const res = await fetch(`/api/proxy/topology?${params.toString()}`);
```

- [ ] **Step 2: Verify the change**

```bash
grep "fetch.*api/" services/web-ui/components/TopologyTab.tsx
```

Expected output: `/api/proxy/topology`

---

### Task 9: Delete old direct-ARM Next.js API routes

**Files:**
- Delete: `services/web-ui/app/api/topology/route.ts`
- Delete: `services/web-ui/app/api/resources/route.ts`

- [ ] **Step 1: Delete the old routes**

```bash
rm services/web-ui/app/api/topology/route.ts
rm services/web-ui/app/api/resources/route.ts
```

- [ ] **Step 2: Verify no remaining references to the old routes**

```bash
grep -r '"/api/topology"' services/web-ui/ --include="*.ts" --include="*.tsx"
grep -r '"/api/resources"' services/web-ui/ --include="*.ts" --include="*.tsx"
grep -r "api/topology" services/web-ui/ --include="*.ts" --include="*.tsx" | grep -v "proxy/topology"
grep -r "api/resources" services/web-ui/ --include="*.ts" --include="*.tsx" | grep -v "proxy/resources"
```

Expected: No output (no remaining references to old routes).

- [ ] **Step 3: Confirm directory structure**

```bash
ls services/web-ui/app/api/proxy/
```

Expected: `approvals/  audit/  chat/  incidents/  patch/  resources/  topology/  vms/`

- [ ] **Step 4: Commit**

```bash
git add -A services/web-ui/
git commit -m "feat: update Topology and Resources tabs to use ARG-backed proxy routes, remove direct-ARM routes"
```

---

## Chunk 5: Smoke Test

### Task 10: Verify counts match between both tabs

- [ ] **Step 1: Run the full Python test suite for the new modules**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_resources_inventory.py \
                 services/api-gateway/tests/test_topology_tree.py -v
```

Expected: All tests PASS.

- [ ] **Step 2: TypeScript build check**

```bash
cd services/web-ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git status
```

If clean, no commit needed. Otherwise:

```bash
git add -A && git commit -m "chore: cleanup after ARG resource count consistency fix"
```
