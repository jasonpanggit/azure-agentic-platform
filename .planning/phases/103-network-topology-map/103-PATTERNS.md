# Phase 103: Network Topology Map — Patterns

**Generated:** 2026-04-18
**Status:** Complete

---

## Files to Create/Modify

| # | File | Role | Action |
|---|------|------|--------|
| 1 | `services/api-gateway/network_topology_service.py` | Backend service | **Create** |
| 2 | `services/api-gateway/network_topology_endpoints.py` | Backend endpoints | **Create** |
| 3 | `services/web-ui/components/NetworkTopologyTab.tsx` | Frontend component | **Create** |
| 4 | `services/web-ui/app/api/proxy/network/topology/route.ts` | Proxy route (GET) | **Create** |
| 5 | `services/web-ui/app/api/proxy/network/topology/path-check/route.ts` | Proxy route (POST) | **Create** |
| 6 | `services/api-gateway/tests/test_network_topology_service.py` | Backend tests | **Create** |
| 7 | `services/web-ui/components/NetworkTab.tsx` (or equivalent) | Tab router | **Modify** — replace TopologyTab with NetworkTopologyTab |
| 8 | `services/api-gateway/main.py` | App entrypoint | **Modify** — register `network_topology_endpoints.router` |
| 9 | `services/web-ui/package.json` | Dependencies | **Modify** — add `@xyflow/react`, `elkjs` |

---

## 1. `network_topology_service.py` — Backend Service

**Role:** Data access + business logic. Runs 7 ARG queries, assembles graph, computes NSG health badges, evaluates path checks.

**Analog:** `services/api-gateway/vnet_peering_service.py` (Phase 99)

### Structural Pattern (from `vnet_peering_service.py`)

```python
from __future__ import annotations
"""Network Topology Service — Phase 103.

ARG-backed network topology graph assembly with NSG health scoring
and interactive path-check evaluation.
Never raises from public functions.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
```

### ARG Query Constants (one per domain)

Follow the module-level `_ARG_QUERY` pattern from `vnet_peering_service.py`:

```python
_VNET_SUBNET_QUERY = """
Resources
| where type =~ "microsoft.network/virtualnetworks"
| extend addressSpace = tostring(properties.addressSpace.addressPrefixes)
| mv-expand subnet = properties.subnets
...
"""

_NSG_RULES_QUERY = """
Resources
| where type =~ "microsoft.network/networksecuritygroups"
...
"""

_LB_QUERY = """..."""
_PE_QUERY = """..."""
_GATEWAY_QUERY = """..."""
_PUBLIC_IP_QUERY = """..."""
_NIC_NSG_QUERY = """..."""
```

All 7 queries are defined in RESEARCH.md §3.

### Import Pattern (lazy import, from `vnet_peering_service.py` L101-103)

```python
try:
    from services.api_gateway.arg_helper import run_arg_query
except ImportError:
    logger.warning("network_topology_service: arg_helper not available")
    run_arg_query = None  # type: ignore[assignment]
```

### Classification/Scoring Helpers

Analog: `_compute_severity()` in `vnet_peering_service.py` L39-45, `_classify()` in `lb_health_service.py` L48-79.

```python
def _score_nsg_health(nsg_rules: List[Dict[str, Any]]) -> str:
    """Return 'green', 'yellow', or 'red' for an NSG based on its rules."""
    # Red: asymmetric block detected (checked separately)
    # Yellow: overly permissive (priority < 1000, source *, dest port *, Allow)
    # Green: no issues
    ...

def _detect_asymmetries(
    nsg_map: Dict[str, List[Dict[str, Any]]],
    subnet_nsg_map: Dict[str, str],
    vnet_subnets: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    """Return list of asymmetry issues (source allows, dest denies) for common ports."""
    ...
```

### Public Scan Function

Analog: `scan_vnet_peerings()` in `vnet_peering_service.py` L85-133.

```python
def fetch_network_topology(
    subscription_ids: List[str],
    credential: Any = None,
) -> Dict[str, Any]:
    """Fetch full network topology graph from ARG.

    Returns {"nodes": [...], "edges": [...], "issues": [...]} dict.
    Never raises — returns empty graph on error.
    """
    start_time = time.monotonic()

    if not subscription_ids:
        logger.warning("network_topology_service: empty subscription list")
        return {"nodes": [], "edges": [], "issues": []}

    if credential is None or run_arg_query is None:
        logger.warning("network_topology_service: no credential/arg_helper — skipped")
        return {"nodes": [], "edges": [], "issues": []}

    try:
        # Run all 7 ARG queries (sequentially for now; asyncio.gather in async context)
        vnets = run_arg_query(credential, subscription_ids, _VNET_SUBNET_QUERY)
        nsgs = run_arg_query(credential, subscription_ids, _NSG_RULES_QUERY)
        lbs = run_arg_query(credential, subscription_ids, _LB_QUERY)
        pes = run_arg_query(credential, subscription_ids, _PE_QUERY)
        gateways = run_arg_query(credential, subscription_ids, _GATEWAY_QUERY)
        public_ips = run_arg_query(credential, subscription_ids, _PUBLIC_IP_QUERY)
        nics = run_arg_query(credential, subscription_ids, _NIC_NSG_QUERY)

        nodes, edges = _assemble_graph(vnets, nsgs, lbs, pes, gateways, public_ips, nics)
        issues = _detect_asymmetries(...)

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("network_topology: fetched | nodes=%d edges=%d issues=%d (%.0fms)",
                     len(nodes), len(edges), len(issues), duration_ms)
        return {"nodes": nodes, "edges": edges, "issues": issues}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning("network_topology: failed | error=%s (%.0fms)", exc, duration_ms)
        return {"nodes": [], "edges": [], "issues": []}
```

### Path Check Function

New function (no direct analog — unique to Phase 103). Follows same never-raise + duration logging pattern:

```python
def evaluate_path_check(
    source_resource_id: str,
    destination_resource_id: str,
    port: int,
    protocol: str,
    subscription_ids: List[str],
    credential: Any = None,
) -> Dict[str, Any]:
    """Evaluate NSG rule chain for source→destination traffic.

    Returns {"verdict": "allowed"|"blocked", "steps": [...], "blocking_nsg_id": ...}.
    Never raises.
    """
    start_time = time.monotonic()
    try:
        ...
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning("path_check: failed | error=%s (%.0fms)", exc, duration_ms)
        return {"verdict": "error", "steps": [], "blocking_nsg_id": None, "error": str(exc)}
```

### In-Memory TTL Cache

Since `arg_cache.py` does not exist, implement simple TTL cache inline (RESEARCH §4 decision):

```python
import threading

_cache: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_TOPOLOGY_TTL_SECONDS = 900  # 15 min — resource inventory tier

def _get_cached_or_fetch(
    key: str,
    ttl: int,
    fetch_fn: Any,
) -> Any:
    with _cache_lock:
        if key in _cache:
            ts, data = _cache[key]
            if time.monotonic() - ts < ttl:
                return data
    result = fetch_fn()
    with _cache_lock:
        _cache[key] = (time.monotonic(), result)
    return result
```

---

## 2. `network_topology_endpoints.py` — Backend Endpoints

**Role:** FastAPI router. Thin layer — delegates to service.

**Analog:** `services/api-gateway/vnet_peering_endpoints.py` (Phase 99)

### Full Pattern (from `vnet_peering_endpoints.py`)

```python
from __future__ import annotations
"""Network Topology API endpoints — Phase 103.

GET  /api/v1/network-topology              — full graph (nodes, edges, issues)
POST /api/v1/network-topology/path-check   — interactive NSG path check
"""

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.network_topology_service import (
    fetch_network_topology,
    evaluate_path_check,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/network-topology", tags=["network-topology"])


class PathCheckRequest(BaseModel):
    source_resource_id: str
    destination_resource_id: str
    port: int
    protocol: str = "TCP"


@router.get("")
async def get_topology(
    request: Request,
    subscription_id: Optional[str] = Query(None),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return network topology graph queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)
    result = fetch_network_topology(subscription_ids, credential=credential)
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /network-topology → nodes=%d edges=%d (%.0fms)",
                len(result.get("nodes", [])), len(result.get("edges", [])), duration_ms)
    return result


@router.post("/path-check")
async def path_check(
    body: PathCheckRequest,
    request: Request,
    subscription_id: Optional[str] = Query(None),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Evaluate NSG rule chain for source→destination traffic. On-demand, not cached."""
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
    logger.info("POST /network-topology/path-check → %s (%.0fms)", result.get("verdict"), duration_ms)
    return result
```

### Key Differences from Analog

| Aspect | `vnet_peering_endpoints.py` | `network_topology_endpoints.py` |
|--------|---------------------------|-------------------------------|
| Routes | GET + GET /summary | GET + POST /path-check |
| Request body | None (query params only) | `PathCheckRequest` Pydantic model for POST |
| Response | `{"findings": [...], "total": N}` | `{"nodes": [...], "edges": [...], "issues": [...]}` |
| Credential | `Depends(get_credential_for_subscriptions)` | Same |

---

## 3. `NetworkTopologyTab.tsx` — Frontend Component

**Role:** React Flow canvas with custom nodes, ELK auto-layout, path checker side panel.

**Analog:** `services/web-ui/components/VNetPeeringTab.tsx`

### Data Loading Pattern (from `VNetPeeringTab.tsx` L116-162)

```tsx
'use client'

import { useEffect, useState, useCallback } from 'react'

const REFRESH_INTERVAL_MS = 10 * 60 * 1000

export default function NetworkTopologyTab() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/proxy/network/topology')
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d?.error ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      // Transform data into React Flow nodes/edges
      ...
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])
```

### CSS Semantic Token Pattern (from `VNetPeeringTab.tsx` throughout)

```tsx
// Badge backgrounds — NEVER hardcoded Tailwind colors
style={{
  background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
  color: 'var(--accent-green)',
  border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
}}

// Canvas/text colors
style={{ background: 'var(--bg-canvas)' }}
style={{ color: 'var(--text-primary)' }}
style={{ color: 'var(--text-secondary)' }}
style={{ borderColor: 'var(--border)' }}
```

### Error Banner Pattern (from `VNetPeeringTab.tsx` L196-208)

```tsx
{error && (
  <div
    className="flex items-center gap-2 rounded border px-3 py-2 text-sm"
    style={{
      background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
      borderColor: 'color-mix(in srgb, var(--accent-red) 30%, transparent)',
      color: 'var(--accent-red)',
    }}
  >
    <AlertTriangle size={14} />
    {error}
  </div>
)}
```

### React Flow Custom Node Pattern (from RESEARCH §1)

```tsx
import { ReactFlow, Handle, Position, type Node, type Edge, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

interface NsgNodeData {
  label: string
  healthStatus: 'green' | 'yellow' | 'red'
  ruleCount: number
}

function NsgNode({ data }: NodeProps<NsgNodeData>) {
  return (
    <div className="rounded-lg border p-3" style={{ background: 'var(--bg-canvas)' }}>
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
          {data.label}
        </span>
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{ background: `var(--accent-${data.healthStatus})` }}
        />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = { nsgNode: NsgNode, vnetNode: VNetNode, subnetNode: SubnetNode, lbNode: LBNode, peNode: PENode, gatewayNode: GatewayNode }
```

### ELK Layout Pattern (from RESEARCH §1)

```tsx
import ELK from 'elkjs/lib/elk.bundled.js'

const elk = new ELK()

async function layoutGraph(nodes: Node[], edges: Edge[]): Promise<{ nodes: Node[]; edges: Edge[] }> {
  const graph = {
    id: 'root',
    layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT' },
    children: nodes.map(n => ({ id: n.id, width: n.measured?.width ?? 200, height: n.measured?.height ?? 80 })),
    edges: edges.map(e => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  }
  const layout = await elk.layout(graph)
  // Map layout positions back to React Flow nodes
  ...
}
```

### Path Checker Side Panel (shadcn Sheet)

```tsx
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'

<Sheet>
  <SheetTrigger asChild>
    <Button variant="outline" size="sm">Path Checker</Button>
  </SheetTrigger>
  <SheetContent>
    <SheetHeader>
      <SheetTitle>NSG Path Check</SheetTitle>
    </SheetHeader>
    {/* Source/dest selectors, port, protocol, submit button, results */}
  </SheetContent>
</Sheet>
```

---

## 4. `app/api/proxy/network/topology/route.ts` — GET Proxy

**Analog:** `services/web-ui/app/api/proxy/network/peerings/route.ts`

### Exact Pattern (from `peerings/route.ts`)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/network/topology' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = request.nextUrl;
    const qs = searchParams.toString();

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/network-topology${qs ? `?${qs}` : ''}`,
      {
        method: 'GET',
        headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.info('topology fetched', { nodes: data?.nodes?.length });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
```

---

## 5. `app/api/proxy/network/topology/path-check/route.ts` — POST Proxy

**Analog:** Same as above but POST method, forwards JSON body.

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/network/topology/path-check' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/network-topology/path-check`,
      {
        method: 'POST',
        headers: {
          ...buildUpstreamHeaders(request.headers.get('Authorization'), false),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.info('path-check complete', { verdict: data?.verdict });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
```

---

## 6. `tests/test_network_topology_service.py` — Backend Tests

**Analog:** `services/api-gateway/tests/test_vnet_peering_service.py`

### Test Structure Pattern (from `test_vnet_peering_service.py`)

```python
from __future__ import annotations
"""Tests for network_topology_service.py — Phase 103."""

from unittest.mock import MagicMock, patch
import pytest

from services.api_gateway.network_topology_service import (
    _score_nsg_health,
    _detect_asymmetries,
    fetch_network_topology,
    evaluate_path_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vnet_row(...) -> Dict[str, Any]:
    """Factory for ARG VNet+subnet row."""
    return { "subscriptionId": ..., "vnetName": ..., ... }

def _make_nsg_row(...) -> Dict[str, Any]:
    """Factory for ARG NSG+rule row."""
    return { ... }


# ---------------------------------------------------------------------------
# _score_nsg_health
# ---------------------------------------------------------------------------

def test_score_nsg_health_green_no_issues(): ...
def test_score_nsg_health_yellow_overly_permissive(): ...
def test_score_nsg_health_red_asymmetry(): ...


# ---------------------------------------------------------------------------
# fetch_network_topology
# ---------------------------------------------------------------------------

def test_fetch_topology_empty_subscriptions():
    result = fetch_network_topology([])
    assert result == {"nodes": [], "edges": [], "issues": []}

def test_fetch_topology_no_credential():
    result = fetch_network_topology(["sub-1"], credential=None)
    assert result == {"nodes": [], "edges": [], "issues": []}

def test_fetch_topology_arg_error_returns_empty():
    """ARG failure returns empty graph, never raises."""
    ...

def test_fetch_topology_assembles_nodes_and_edges():
    """Mock 7 ARG queries and verify graph assembly."""
    ...


# ---------------------------------------------------------------------------
# evaluate_path_check
# ---------------------------------------------------------------------------

def test_path_check_allowed(): ...
def test_path_check_blocked_by_dest_nsg(): ...
def test_path_check_error_returns_error_verdict(): ...


# ---------------------------------------------------------------------------
# NSG rule matching
# ---------------------------------------------------------------------------

def test_rule_matches_exact_port(): ...
def test_rule_matches_port_range(): ...
def test_rule_matches_wildcard_protocol(): ...
def test_rule_priority_ordering(): ...
```

### Key Testing Patterns from Analog

1. **Row factories** (`_make_row()`) — create realistic ARG result dicts
2. **Never-raise verification** — every public function tested with error inputs returning safe defaults
3. **Stable ID testing** — if deterministic IDs used, verify idempotency
4. **Patch pattern:** `patch("services.api_gateway.network_topology_service.run_arg_query", return_value=mock_rows)`

---

## Import/Dependency Map

```
network_topology_endpoints.py
  ├── services.api_gateway.auth.verify_token
  ├── services.api_gateway.dependencies.get_credential_for_subscriptions
  ├── services.api_gateway.federation.resolve_subscription_ids
  └── services.api_gateway.network_topology_service
        └── services.api_gateway.arg_helper.run_arg_query

NetworkTopologyTab.tsx
  ├── @xyflow/react (ReactFlow, Handle, Position, etc.)
  ├── elkjs/lib/elk.bundled.js
  ├── @/components/ui/button, sheet, etc.
  └── /api/proxy/network/topology (GET)
      /api/proxy/network/topology/path-check (POST)
        └── @/lib/api-gateway (getApiGatewayUrl, buildUpstreamHeaders)
```

---

## Checklist Compliance (from CLAUDE.md)

### Dashboard Tab Rules
- [x] No `scanning` state variable
- [x] No `handleScan` function
- [x] No `POST` to a `/scan` proxy route
- [x] No "Run a scan" in empty state messages
- [x] `useEffect` fires `fetchData()` immediately on mount
- [x] Empty state says "No network resources found" not "Run a scan"

### Backend Rules
- [x] `GET` endpoint calls service directly
- [x] Service uses TTL cache (900s in-memory, since `arg_cache.py` doesn't exist)
- [x] No `POST /scan` route
- [x] No Cosmos intermediary for topology data
- [x] `POST /path-check` is on-demand (not cached) — justified by D-05

### Frontend Rules
- [x] CSS semantic tokens only — no hardcoded Tailwind colors
- [x] Dark-mode badge pattern: `color-mix(in srgb, var(--accent-*) 15%, transparent)`
- [x] Proxy routes use `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout(15000)`

---

*Patterns extracted. Ready for PLAN.md generation.*
