# Plan 24-2: Wire Noise Reducer into Incident Ingestion + Stats Endpoint

**Phase:** 24 — Alert Intelligence and Noise Reduction
**Wave:** 2 (depends on 24-1 — noise_reducer.py and model fields must exist)
**Requirement:** INTEL-001 — Alert noise reduction ≥80%
**autonomous:** true

---

## Objective

Wire the three noise reduction functions from `noise_reducer.py` into the
`ingest_incident` handler in `main.py`, inserting them BEFORE the existing dedup
check. Add `GET /api/v1/incidents/stats` endpoint for noise reduction metrics.

---

## Pre-condition Check

Before starting Wave 2:
1. Confirm `services/api-gateway/noise_reducer.py` exists (created in 24-1).
2. Confirm `IncidentResponse` has `suppressed` and `parent_incident_id` fields.
3. Confirm `IncidentSummary` has `composite_severity`, `suppressed`, `parent_incident_id`.

---

## Files to Modify / Create

| Action | Path |
|--------|------|
| MODIFY | `services/api-gateway/main.py` |
| CREATE | `services/api-gateway/tests/test_noise_reducer_wiring.py` |

No new source files; `noise_reducer.py` is imported in-place.

---

## Step 1 — Read `main.py` before editing

Always read `services/api-gateway/main.py` in full before making any edits.
The current `ingest_incident` handler ends at line ~495. Confirm exact line numbers
of the dedup block (`check_dedup` call and early return) before inserting new code.

---

## Step 2 — Modify `ingest_incident` in `main.py`

### Insertion point

New noise-reduction block inserts BEFORE the existing dedup check (currently step 1
in the ingestion flow). The final order must be:

```
0a. get_blast_radius for primary resource (async, via run_in_executor)
0b. check_causal_suppression — if hit → store suppressed doc + return early
0c. check_temporal_topological_correlation — if hit → attach thread routing hint
0d. compute_composite_severity — attach to log / later Cosmos write
1.  check_dedup  ← existing code, unchanged
2.  create_foundry_thread ← existing code, unchanged
...
```

### Exact changes to `ingest_incident`

#### 2a. Resolve topology_client early (move up from later in the function)

Currently `topology_client = getattr(request.app.state, "topology_client", None)` is
fetched mid-function (around line 421). Move this assignment to be the FIRST line
inside `ingest_incident` after the opening log statement, so it is available for
the new noise-reduction block.

**Do not duplicate** this line — move it; ensure it only appears once.

#### 2b. Insert noise-reduction block (after topology_client assignment, before dedup call)

```python
# --- Phase 24: Noise reduction (INTEL-001) ---
# Runs before dedup check. Precedence: suppression > correlation > dedup > new.
from services.api_gateway.noise_reducer import (
    check_causal_suppression,
    check_temporal_topological_correlation,
    compute_composite_severity,
)

_primary_resource_id = (
    payload.affected_resources[0].resource_id if payload.affected_resources else ""
)

# 0a. Pre-fetch blast_radius for suppression + severity scoring.
_blast_radius_size = 0
_blast_radius_for_suppression: Optional[dict] = None
if topology_client is not None and _primary_resource_id:
    try:
        loop = asyncio.get_running_loop()
        _br = await loop.run_in_executor(
            None,
            topology_client.get_blast_radius,
            _primary_resource_id,
            3,
        )
        _blast_radius_size = _br.get("total_affected", 0)
        _blast_radius_for_suppression = _br
    except Exception as _br_exc:
        logger.warning(
            "noise_reducer: blast_radius prefetch failed (non-fatal) | "
            "incident=%s error=%s",
            payload.incident_id, _br_exc,
        )

# 0b. Causal suppression check.
_suppressed_by: Optional[str] = await check_causal_suppression(
    resource_id=_primary_resource_id,
    topology_client=topology_client,
    cosmos_client=cosmos,
)
if _suppressed_by is not None:
    # Store suppressed incident to Cosmos (status=suppressed_cascade).
    if cosmos is not None:
        try:
            _db = cosmos.get_database_client(
                os.environ.get("COSMOS_DB_NAME", "aap")
            )
            _cont = _db.get_container_client("incidents")
            _cont.upsert_item({
                "id": payload.incident_id,
                "incident_id": payload.incident_id,
                "resource_id": _primary_resource_id,
                "severity": payload.severity,
                "domain": payload.domain,
                "status": "suppressed_cascade",
                "parent_incident_id": _suppressed_by,
                "title": payload.title,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as _sup_exc:
            logger.warning(
                "noise_reducer: failed to persist suppressed incident | "
                "incident=%s error=%s",
                payload.incident_id, _sup_exc,
            )
    logger.info(
        "noise_reducer: suppressed | incident=%s parent=%s",
        payload.incident_id, _suppressed_by,
    )
    return IncidentResponse(
        thread_id="suppressed",
        incident_id=payload.incident_id,
        status="suppressed_cascade",
        suppressed=True,
        parent_incident_id=_suppressed_by,
    )

# 0c. Multi-dimensional correlation check.
_correlated_with: Optional[str] = await check_temporal_topological_correlation(
    resource_id=_primary_resource_id,
    domain=payload.domain,
    topology_client=topology_client,
    cosmos_client=cosmos,
)

# 0d. Composite severity scoring.
_composite_severity = compute_composite_severity(
    severity=payload.severity,
    blast_radius_size=_blast_radius_size,
    domain=payload.domain,
)
logger.info(
    "noise_reducer: composite_severity=%s blast_radius=%d | incident=%s",
    _composite_severity, _blast_radius_size, payload.incident_id,
)
# --- End Phase 24 noise reduction ---
```

**Note on `datetime` import:** `main.py` does not currently import `datetime` at the
top level (it uses a local import in the change correlator block). Add
`from datetime import datetime, timezone` to the top-level imports OR use the existing
local import pattern. Check `main.py` imports before deciding.

**Note on `IncidentResponse` fields:** The new fields `incident_id`, `suppressed`,
and `parent_incident_id` on `IncidentResponse` are added in Wave 1 (24-1).
When constructing the suppressed return, include `incident_id=payload.incident_id`
only if `IncidentResponse.incident_id` was added — check models.py. If not added,
omit it (the context spec only requires `suppressed` and `parent_incident_id`
on `IncidentResponse`).

#### 2c. Attach composite_severity and correlation hint to Cosmos write

The existing `dedup_integration.create_incident_record` call (inside `check_dedup`)
already writes the incident to Cosmos. To attach `composite_severity` and
`correlated_with` to that document, add a post-dedup Cosmos patch after `check_dedup`
returns `None` (i.e., no duplicate found, about to create a Foundry thread):

```python
# After dedup_result is None and before create_foundry_thread:
# Attach noise-reduction metadata to Cosmos incident doc (best-effort).
if cosmos is not None and _primary_resource_id:
    try:
        _db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        _cont = _db.get_container_client("incidents")
        _cont.patch_item(
            item=payload.incident_id,
            partition_key=payload.incident_id,
            patch_operations=[
                {"op": "add", "path": "/composite_severity", "value": _composite_severity},
                {"op": "add", "path": "/correlated_with", "value": _correlated_with},
            ],
        )
    except Exception as _patch_exc:
        logger.debug(
            "noise_reducer: composite_severity patch skipped | incident=%s reason=%s",
            payload.incident_id, _patch_exc,
        )
```

This is best-effort. If `patch_item` fails (e.g., doc not yet written by dedup
integration), log at DEBUG level and continue.

#### 2d. Attach to final IncidentResponse

In the final `return IncidentResponse(...)` statement at the end of `ingest_incident`,
add:

```python
composite_severity=_composite_severity,
```

`blast_radius_summary` is already populated in the existing code; keep it.

**Important:** `_composite_severity` is declared before the dedup block in 0d above.
If for any reason the noise-reduction block is skipped (e.g., empty affected_resources),
ensure `_composite_severity` has a fallback:
```python
_composite_severity: Optional[str] = None
```
Declare this right after the topology_client line, before entering the
noise-reduction block.

---

## Step 3 — Add `GET /api/v1/incidents/stats` endpoint to `main.py`

Add after the `list_incidents_endpoint` route (around line 826):

```python
@app.get("/api/v1/incidents/stats")
async def get_incident_stats(
    window_hours: int = 24,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> dict:
    """Noise reduction metrics for the INTEL-001 requirement.

    Queries the incidents container and returns counts for:
    - total: all incidents in the window
    - suppressed: status == 'suppressed_cascade'
    - correlated: status == 'correlated'
    - new: status not in (suppressed_cascade, correlated, closed, deduplicated)
    - noise_reduction_pct: (suppressed + correlated) / total * 100
    - window_hours: echo of input param

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Incident store not configured")

    import time as _time_mod
    cutoff_ts = int(_time_mod.time()) - (window_hours * 3600)

    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("incidents")

        query = (
            "SELECT c.status FROM c "
            "WHERE c._ts > @cutoff"
        )
        params = [{"name": "@cutoff", "value": cutoff_ts}]
        items = list(container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        ))

        total = len(items)
        suppressed = sum(1 for i in items if i.get("status") == "suppressed_cascade")
        correlated = sum(1 for i in items if i.get("status") == "correlated")
        noise_reduction_pct = (
            round((suppressed + correlated) / total * 100, 1) if total > 0 else 0.0
        )
        new_count = total - suppressed - correlated

        return {
            "total": total,
            "suppressed": suppressed,
            "correlated": correlated,
            "new": new_count,
            "noise_reduction_pct": noise_reduction_pct,
            "window_hours": window_hours,
        }
    except Exception as exc:
        logger.error("get_incident_stats: error | error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Stats query failed")
```

**Placement:** Insert this route AFTER `list_incidents_endpoint` and BEFORE
`get_incident_evidence`. Verify the final route order doesn't cause path conflicts
(FastAPI routes are matched in order; `/api/v1/incidents/stats` must appear before
`/api/v1/incidents/{incident_id}/evidence` to avoid `stats` being consumed as
an `incident_id` path segment).

---

## Step 4 — Create `services/api-gateway/tests/test_noise_reducer_wiring.py`

### 10+ tests for wiring and stats endpoint

```python
"""Unit tests for Phase 24 noise reducer wiring in main.py and stats endpoint."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
```

#### Group 1: `ingest_incident` suppression path (4 tests)

| # | Test name | Description |
|---|-----------|-------------|
| 1 | `test_ingest_suppressed_returns_suppressed_status` | When `check_causal_suppression` returns a parent_id, response has `status="suppressed_cascade"`, `suppressed=True`, `parent_incident_id` set |
| 2 | `test_ingest_suppressed_skips_foundry_dispatch` | Suppressed incident must NOT call `create_foundry_thread` |
| 3 | `test_ingest_suppressed_persists_to_cosmos` | Cosmos `upsert_item` called once with `status="suppressed_cascade"` |
| 4 | `test_ingest_suppressed_no_cosmos_still_returns_suppressed` | cosmos=None but suppression hit → still returns suppressed response, no error |

#### Group 2: `ingest_incident` composite severity path (3 tests)

| # | Test name | Description |
|---|-----------|-------------|
| 5 | `test_ingest_attaches_composite_severity_to_response` | Not suppressed, not correlated → `IncidentResponse.composite_severity` is set |
| 6 | `test_ingest_composite_severity_no_topology` | topology_client=None → `compute_composite_severity` called with blast_radius_size=0, no error |
| 7 | `test_ingest_noise_reducer_failure_doesnt_block_dispatch` | If blast_radius prefetch raises → incident still dispatched to Foundry |

#### Group 3: `GET /api/v1/incidents/stats` (3 tests)

| # | Test name | Description |
|---|-----------|-------------|
| 8 | `test_stats_returns_correct_counts` | Cosmos returns 10 items (3 suppressed, 2 correlated, 5 new) → `noise_reduction_pct=50.0` |
| 9 | `test_stats_no_cosmos_returns_503` | cosmos=None → 503 |
| 10 | `test_stats_empty_window_returns_zeros` | Cosmos returns 0 items → `total=0, noise_reduction_pct=0.0`, no division-by-zero error |

### Test setup pattern

Use `TestClient` from `starlette.testclient` with `main.app`:

```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Override auth
def _mock_verify_token():
    return {"sub": "test-user", "aud": "aap-api"}

# Override Cosmos dependency
def _mock_cosmos():
    mock = MagicMock()
    mock.get_database_client.return_value.get_container_client.return_value = MagicMock()
    return mock
```

Use `app.dependency_overrides` to inject mocks for `verify_token`, `get_cosmos_client`,
`get_optional_cosmos_client`. Patch `noise_reducer` functions with `patch`.

---

## Acceptance Criteria

- [ ] `ingest_incident` noise-reduction block runs BEFORE dedup check
- [ ] Suppressed incident returns `{"status": "suppressed_cascade", "suppressed": true, "parent_incident_id": "..."}`
- [ ] Suppressed incident does NOT create a Foundry thread
- [ ] Suppressed incident is persisted to Cosmos with `status="suppressed_cascade"`
- [ ] Non-suppressed incident has `composite_severity` set in `IncidentResponse`
- [ ] `GET /api/v1/incidents/stats?window_hours=24` returns `{total, suppressed, correlated, new, noise_reduction_pct, window_hours}`
- [ ] Stats endpoint handles `cosmos=None` → 503
- [ ] Stats endpoint handles `total=0` → `noise_reduction_pct=0.0` (no ZeroDivisionError)
- [ ] `/api/v1/incidents/stats` route is ordered before `/api/v1/incidents/{incident_id}/evidence` in FastAPI
- [ ] All noise-reduction steps are non-blocking — any failure logs warning and proceeds
- [ ] 10+ unit tests pass
- [ ] `main.py` has no duplicate `topology_client` assignment (moved up, not duplicated)

---

## Notes

- The existing blast-radius prefetch block (TOPO-004, ~lines 461–489 in `main.py`)
  runs AFTER Foundry dispatch for the `IncidentResponse`. In Wave 2, we add a
  SEPARATE blast-radius call at step 0a for suppression/scoring — this is intentional.
  The TOPO-004 block remains for the response; the 0a block feeds suppression logic.
  Avoid merging these two calls as they serve different purposes and the 0a call must
  run before dedup.
- Import `noise_reducer` functions inside `ingest_incident` (local import, matching
  the dedup_integration pattern) to avoid circular imports at module load time.
- `_correlated_with` variable is available after step 0c; if a correlation hit is
  found, it is stored to Cosmos via the patch operation in step 2c. The correlation
  does NOT cause an early return — the incident is still dispatched to Foundry
  (but the `correlated_with` field links it to the existing thread for operators).
- The stats endpoint computes metrics on-the-fly (no pre-aggregated counter) —
  consistent with the context decision to avoid new Cosmos containers.
