# Phase 22-4 Summary: Domain Agent Topology Integration + Load Test

**Completed:** 2026-04-03
**Branch:** `gsd/phase-22-resource-topology-graph`
**Requirements satisfied:** TOPO-002, TOPO-004, TOPO-005

---

## What Was Built

### 22-4-01: `IncidentResponse.blast_radius_summary` field

**File:** `services/api-gateway/models.py`

Added `blast_radius_summary: Optional[dict] = Field(default=None, ...)` to `IncidentResponse`. Uses `Optional[dict]` (not a typed sub-model) so topology schema changes don't require model churn. Fully backward compatible — all existing `IncidentResponse(thread_id=..., status=...)` call sites continue to work unchanged.

### 22-4-02: Blast-radius pre-fetch in `ingest_incident` (TOPO-004)

**File:** `services/api-gateway/main.py`

Two changes:
1. Added `request: Request` parameter to `ingest_incident` (FastAPI auto-injects, no `Depends` needed).
2. After the background diagnostic pipeline is queued, pre-fetches `topology_client.get_blast_radius(primary_resource_id, max_depth=3)` via `loop.run_in_executor` (synchronous Cosmos BFS traversal offloaded to thread pool).

Graceful degradation (TOPO-004 requirement):
- If `topology_client` is `None` on `app.state` → `blast_radius_summary=None`, incident dispatched normally.
- If `get_blast_radius` raises any exception → logs `WARNING: blast_radius prefetch failed (non-fatal)`, `blast_radius_summary=None`, incident dispatched normally.

The `blast_radius_summary` dict shape:
```json
{
  "resource_id": "<ARM resource ID>",
  "total_affected": 5,
  "affected_resources": [...],
  "hop_counts": {"<resource_id>": <hop_depth>}
}
```

### 22-4-03: Load test script `scripts/ops/22-4-topology-load-test.sh`

**File:** `scripts/ops/22-4-topology-load-test.sh`

Self-contained bash load test that:

**Phase 1 — Seed:** Uses Python/azure-cosmos SDK to upsert `NODE_COUNT=10000` synthetic nodes into Cosmos DB topology container:
- 4999 VMs (`vm-loadtest-{i}`) each with outbound edges to a NIC and shared subnet
- 4999 NICs (`nic-loadtest-{i}`) each with outbound edge to shared subnet
- 1 shared subnet node + 1 shared VNet node
- Total: 10,002 nodes (>=10,000 satisfies TOPO-005)

**Phase 2 — Query timing:** Runs `QUERY_COUNT=10` blast-radius HTTP queries against `GET /api/v1/topology/blast-radius?resource_id=...&max_depth=3`, measuring each with `curl --time_total`.

**Phase 3 — Assessment:**
- `TOPO-002`: All 10 queries must complete in `<MAX_LATENCY_MS=2000ms`; reports p50/p95 statistics
- `TOPO-005`: Seeded node count must be `>=10,000`

**Exit codes:** `0` if both TOPO-002 and TOPO-005 pass; `1` on any failure.

**Environment variables:**
| Variable | Default | Required |
|---|---|---|
| `COSMOS_ENDPOINT` | — | Yes (unless `SKIP_SEED=true`) |
| `API_GATEWAY_URL` | `http://localhost:8000` | Yes |
| `API_GATEWAY_TOKEN` | — | Yes |
| `NODE_COUNT` | `10000` | No |
| `QUERY_COUNT` | `10` | No |
| `MAX_LATENCY_MS` | `2000` | No |
| `SKIP_SEED` | `false` | No |
| `ORIGIN_RESOURCE_ID` | auto-detected | Required if `SKIP_SEED=true` |

### 22-4-04: 3 unit tests for topology integration

**File:** `services/api-gateway/tests/test_incidents.py`

New class `TestIncidentHandlerTopologyIntegration` with 3 tests:

1. **`test_blast_radius_summary_populated_when_topology_available`** — Mocks `topology_client.get_blast_radius` returning 1 affected NIC; verifies `blast_radius_summary.total_affected == 1` in response.
2. **`test_blast_radius_summary_none_when_topology_unavailable`** — Sets `topology_client = None` on app state; verifies `blast_radius_summary` is absent from response.
3. **`test_incident_dispatched_even_if_topology_raises`** — Makes `get_blast_radius` raise `RuntimeError("Cosmos timeout")`; verifies incident still returns `202` with `blast_radius_summary=None` (graceful degradation).

Key mock decision: `check_dedup` is patched at `services.api_gateway.dedup_integration.check_dedup` (inline import path) rather than `services.api_gateway.main.check_dedup`.

---

## Files Created / Modified

| File | Change |
|---|---|
| `services/api-gateway/models.py` | Added `blast_radius_summary: Optional[dict]` to `IncidentResponse` |
| `services/api-gateway/main.py` | Added `request: Request` param + TOPO-004 blast-radius pre-fetch block |
| `scripts/ops/22-4-topology-load-test.sh` | **New** — 10K-node seed + TOPO-002/TOPO-005 load test |
| `services/api-gateway/tests/test_incidents.py` | Added `TestIncidentHandlerTopologyIntegration` (3 tests) |

---

## Test Results

```
388 passed, 2 skipped — services/api-gateway/tests/
```

All 6 pre-existing incident tests continue to pass. All 3 new topology integration tests pass.

---

## Design Decisions

1. **`run_in_executor` not `asyncio.to_thread`** — `asyncio.to_thread` was added in Python 3.9; project runs on Python 3.9 but using `run_in_executor(None, ...)` is equivalent and more explicit.
2. **Non-fatal design** — The blast-radius pre-fetch is a latency-bounded enrichment. Topology service unavailability must never block incident dispatch. Any exception is caught, logged as WARNING, and results in `None`.
3. **`Optional[dict]` not typed sub-model** — Topology data structure (`hop_counts`, `affected_resources`) may evolve through Phase 22-3. Using `dict` avoids model churn while TOPO shapes stabilize.
4. **Load test uses VM+NIC graph topology** — 5K VMs each connected to a shared subnet via a NIC creates a star topology. The blast-radius query from any VM traverses 3 nodes (VM → NIC → subnet) quickly, validating the BFS logic at scale without creating an artificially slow graph.
