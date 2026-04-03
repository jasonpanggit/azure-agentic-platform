# Plan 24-1: Noise Reducer Service

**Phase:** 24 — Alert Intelligence and Noise Reduction
**Wave:** 1 (foundation — no dependencies)
**Requirement:** INTEL-001 — Alert noise reduction ≥80%
**autonomous:** true

---

## Objective

Create `services/api-gateway/noise_reducer.py` — a self-contained module implementing
the three noise reduction mechanisms (causal suppression, multi-dimensional correlation,
composite severity scoring) and add the required fields to `models.py`.

This wave produces no wiring changes; `main.py` is untouched. Wave 2 wires these
functions in.

---

## Files to Create / Modify

| Action   | Path                                                          |
|----------|---------------------------------------------------------------|
| CREATE   | `services/api-gateway/noise_reducer.py`                       |
| MODIFY   | `services/api-gateway/models.py`                              |
| CREATE   | `services/api-gateway/tests/test_noise_reducer.py`            |

---

## Step 1 — Read existing files before any edits

Read each file that will be modified before touching it:

- `services/api-gateway/models.py` — understand current `IncidentResponse` and
  `IncidentSummary` field lists before adding new Optional fields.

The test file does not exist yet; no prior read needed.

---

## Step 2 — Create `services/api-gateway/noise_reducer.py`

### Module structure

```
noise_reducer.py
  ├── imports
  ├── constants (env-driven)
  ├── domain SLO risk weights dict
  ├── _base_severity_weight()        # private helper
  ├── _blast_radius_score()          # private helper
  ├── compute_composite_severity()   # public
  ├── check_causal_suppression()     # public, async
  └── check_temporal_topological_correlation()  # public, async
```

### Constants (read from environment with defaults)

```python
import os

SUPPRESSION_ENABLED: bool = os.environ.get("NOISE_SUPPRESSION_ENABLED", "true").lower() == "true"
SUPPRESSION_LOOKBACK_HOURS: int = int(os.environ.get("NOISE_SUPPRESSION_LOOKBACK_HOURS", "2"))
CORRELATION_WINDOW_MINUTES: int = int(os.environ.get("NOISE_CORRELATION_WINDOW_MINUTES", "10"))
```

### Domain SLO risk weights

```python
_DOMAIN_SLO_RISK: dict[str, float] = {
    "compute":  0.9,
    "network":  0.85,
    "storage":  0.8,
    "database": 0.8,
    "security": 1.0,
    "sre":      0.7,
    "arc":      0.6,
    "patch":    0.4,
}
_DOMAIN_SLO_RISK_DEFAULT: float = 0.5
```

### Private helper: `_base_severity_weight(severity: str) -> float`

```
Sev0 → 1.0
Sev1 → 0.8
Sev2 → 0.6
Sev3 → 0.4
unknown → 0.4
```

### Private helper: `_blast_radius_score(blast_radius_size: int) -> float`

```python
import math
return min(math.log10(blast_radius_size + 1) / math.log10(101), 1.0)
```

Rationale: log10 scaling so a blast radius of 0 → 0.0, 10 → ~0.52, 100 → 1.0.

### Public function: `compute_composite_severity`

```python
def compute_composite_severity(severity: str, blast_radius_size: int, domain: str) -> str:
    """Re-weight incident severity using blast radius and domain SLO risk.

    Formula:
        score = base_severity_weight(severity)
              + 0.3 * blast_radius_score(blast_radius_size)
              + 0.2 * slo_risk(domain)

    Thresholds:
        score >= 0.9  → "Sev0"
        score >= 0.7  → "Sev1"
        score >= 0.5  → "Sev2"
        else          → "Sev3"
    """
```

No I/O. Pure function. Never raises.

### Public function: `check_causal_suppression`

```python
async def check_causal_suppression(
    resource_id: str,
    topology_client: Any,
    cosmos_client: Any,
    lookback_hours: int = SUPPRESSION_LOOKBACK_HOURS,
) -> Optional[str]:
    """Check whether a new alert is a downstream cascade of an existing incident.

    Algorithm:
    1. If SUPPRESSION_ENABLED is False, return None immediately.
    2. If topology_client or cosmos_client is None, return None (graceful degrade).
    3. Compute cutoff = now(UTC) - lookback_hours.
    4. Query Cosmos `incidents` container for active incidents:
           SELECT c.incident_id, c.blast_radius_summary, c.status, c.created_at
           FROM c
           WHERE c.status NOT IN ('closed', 'suppressed_cascade')
           AND c._ts > @cutoff
    5. For each active incident I:
       a. If I.blast_radius_summary is None, skip.
       b. Check if resource_id (lowercased) is in
          I.blast_radius_summary.get('affected_resources', []).
          The affected_resources list contains ARM resource ID strings.
       c. If found → return I['incident_id'] (the parent).
    6. Return None (no suppression hit).

    Errors:
    - Cosmos query failure → log warning, return None (non-blocking).
    - topology_client is accepted as a parameter for future topology-assisted
      expansion but is not called in Wave 1 (topology blast_radius lookup
      happens in main.py before this function is called).
    """
```

**Cosmos query detail:**

```python
import time as _time

cutoff_ts = int(_time.time()) - (lookback_hours * 3600)
query = (
    "SELECT c.incident_id, c.blast_radius_summary, c.status "
    "FROM c "
    "WHERE c.status NOT IN ('closed', 'suppressed_cascade') "
    "AND c._ts > @cutoff"
)
params = [{"name": "@cutoff", "value": cutoff_ts}]
```

Use `cosmos_client.get_database_client(COSMOS_DB_NAME).get_container_client("incidents")`
where `COSMOS_DB_NAME = os.environ.get("COSMOS_DB_NAME", "aap")`.

Iterate results with a synchronous `for item in container.query_items(...)` call
(azure-cosmos SDK is synchronous; wrap in `asyncio.get_running_loop().run_in_executor`
for async callers, matching the pattern used in `topology.py` and `change_correlator.py`).

**resource_id matching:**
```python
resource_id_lower = resource_id.lower()
affected = blast_summary.get("affected_resources", [])
# affected_resources is a list of ARM resource ID strings (lowercased by topology)
if resource_id_lower in [r.lower() for r in affected]:
    return incident["incident_id"]
```

### Public function: `check_temporal_topological_correlation`

```python
async def check_temporal_topological_correlation(
    resource_id: str,
    domain: str,
    topology_client: Any,
    cosmos_client: Any,
    window_minutes: int = CORRELATION_WINDOW_MINUTES,
) -> Optional[str]:
    """Check whether a new alert should be correlated to an existing incident thread.

    This runs AFTER check_causal_suppression returns None (not suppressed).
    If an existing active incident in the same domain fired within window_minutes
    AND shares at least one topology neighbor with resource_id, route the new
    alert to that existing incident thread rather than creating a new Foundry thread.

    Algorithm:
    1. If SUPPRESSION_ENABLED is False, return None.
    2. If topology_client or cosmos_client is None, return None.
    3. Fetch topology neighbors of resource_id using topology_client:
           node = topology_client._get_topology_node(resource_id)
           neighbors = {rel['target_id'] for rel in node.get('relationships', [])}
           neighbors.add(resource_id.lower())
    4. Compute window_cutoff = now(UTC) - window_minutes.
       Convert to Unix timestamp for Cosmos _ts comparison.
    5. Query Cosmos for recent active incidents in same domain within window:
           SELECT c.incident_id, c.resource_id, c.thread_id, c.blast_radius_summary, c._ts
           FROM c
           WHERE c.status NOT IN ('closed', 'suppressed_cascade')
           AND c.domain = @domain
           AND c._ts > @window_cutoff
    6. For each candidate incident C:
       a. If C.resource_id.lower() in neighbors → correlation hit.
       b. If C.blast_radius_summary exists: check if resource_id.lower() in
          C.blast_radius_summary.get('affected_resources', []) → correlation hit.
       c. If hit → return C['incident_id'].
    7. Return None (no correlation).

    Errors: log warning, return None (non-blocking).
    """
```

**Topology node fetch** — use private method that already exists in TopologyClient:
```python
loop = asyncio.get_running_loop()
node_doc = await loop.run_in_executor(
    None,
    topology_client._get_topology_node,
    resource_id.lower(),
)
```
If `_get_topology_node` raises or returns None → neighbors set contains only
`{resource_id.lower()}` (single-node fallback, still enables same-resource correlation).

---

## Step 3 — Modify `services/api-gateway/models.py`

### `IncidentResponse` — add two fields

After `blast_radius_summary`, add:

```python
suppressed: Optional[bool] = Field(
    default=None,
    description="True when this incident was suppressed as a downstream cascade (INTEL-001).",
)
parent_incident_id: Optional[str] = Field(
    default=None,
    description="incident_id of the parent incident that caused suppression.",
)
```

### `IncidentSummary` — add three fields

After `top_changes`, add:

```python
composite_severity: Optional[str] = Field(
    default=None,
    description=(
        "Re-weighted severity combining base severity, blast radius size, "
        "and domain SLO risk (INTEL-001). One of: Sev0, Sev1, Sev2, Sev3."
    ),
)
suppressed: Optional[bool] = Field(
    default=None,
    description="True when this incident was suppressed as a downstream cascade.",
)
parent_incident_id: Optional[str] = Field(
    default=None,
    description="incident_id of the parent incident that caused suppression.",
)
```

Both sets of new fields are `Optional` with `default=None` — fully backward-compatible,
no migration required.

---

## Step 4 — Create `services/api-gateway/tests/test_noise_reducer.py`

### Test file structure — 15 tests minimum

All external dependencies mocked with `unittest.mock.MagicMock` / `AsyncMock`.
No real Cosmos, no real topology client. Import pattern matches
`test_change_correlator.py`.

```python
"""Unit tests for noise_reducer.py."""
import pytest
import asyncio
import math
from unittest.mock import MagicMock, patch
```

#### Group 1: `compute_composite_severity` — scoring math (5 tests)

| # | Test name | Description |
|---|-----------|-------------|
| 1 | `test_composite_severity_sev0_security_large_blast` | security domain + Sev1 + blast_radius=50 → expect Sev0 (score ≥ 0.9) |
| 2 | `test_composite_severity_sev3_small_blast_patch` | patch domain + Sev3 + blast_radius=0 → expect Sev3 (score < 0.5) |
| 3 | `test_composite_severity_no_blast_radius` | blast_radius=0 → blast_radius_score = 0.0 |
| 4 | `test_composite_severity_exact_threshold_sev1` | craft inputs so score lands in [0.7, 0.9) → Sev1 |
| 5 | `test_composite_severity_unknown_domain_uses_default` | domain="unknown" → uses _DOMAIN_SLO_RISK_DEFAULT=0.5, doesn't raise |

Verify by computing the expected score with the formula from the context doc and
asserting the returned string matches.

#### Group 2: `check_causal_suppression` — suppression logic (5 tests)

| # | Test name | Description |
|---|-----------|-------------|
| 6 | `test_suppression_disabled_returns_none` | NOISE_SUPPRESSION_ENABLED=false → None immediately, no Cosmos call |
| 7 | `test_suppression_no_cosmos_returns_none` | cosmos_client=None → None without error |
| 8 | `test_suppression_hit_resource_in_blast_radius` | active incident with blast_radius_summary containing resource_id → returns parent incident_id |
| 9 | `test_suppression_miss_resource_not_in_blast_radius` | active incident exists but resource_id NOT in blast_radius → returns None |
| 10 | `test_suppression_cosmos_error_returns_none` | Cosmos query raises Exception → logs warning, returns None |

For tests 8–9: mock `cosmos_client.get_database_client().get_container_client().query_items()`
to return a list with one mock incident document.

#### Group 3: `check_temporal_topological_correlation` — correlation logic (5 tests)

| # | Test name | Description |
|---|-----------|-------------|
| 11 | `test_correlation_disabled_returns_none` | NOISE_SUPPRESSION_ENABLED=false → None |
| 12 | `test_correlation_no_topology_client_returns_none` | topology_client=None → None |
| 13 | `test_correlation_hit_neighbor_resource` | topology returns neighbor that matches existing incident resource_id → returns incident_id |
| 14 | `test_correlation_miss_no_overlap` | topology neighbors don't overlap with any active incident → None |
| 15 | `test_correlation_topology_fetch_error_falls_back_to_single_node` | topology._get_topology_node raises → graceful fallback, still checks resource_id itself |

For topology_client mock in tests 13–15: mock `_get_topology_node` to return a dict
with `relationships` list containing one neighbor.

### Test execution contract

All async tests must be wrapped:
```python
def test_something():
    asyncio.run(async_test_something())
```
or use `pytest-asyncio` with `@pytest.mark.asyncio` if already configured in the
project (check `pytest.ini` or `pyproject.toml`).

---

## Acceptance Criteria

- [ ] `noise_reducer.py` exists with all three public functions and correct signatures
- [ ] `compute_composite_severity` returns one of: "Sev0", "Sev1", "Sev2", "Sev3"
- [ ] `check_causal_suppression` returns `Optional[str]` — parent incident_id or None
- [ ] `check_temporal_topological_correlation` returns `Optional[str]` — existing incident_id or None
- [ ] Both check functions degrade gracefully (return None) when Cosmos or topology unavailable
- [ ] `SUPPRESSION_ENABLED=false` feature flag bypasses all I/O in both check functions
- [ ] `models.py` gains `suppressed`, `parent_incident_id` on `IncidentResponse`
- [ ] `models.py` gains `composite_severity`, `suppressed`, `parent_incident_id` on `IncidentSummary`
- [ ] All new fields are `Optional` with `default=None` (backward-compatible)
- [ ] 15+ unit tests pass with `pytest services/api-gateway/tests/test_noise_reducer.py`
- [ ] No mutations of input dicts or objects — return new values only

---

## Notes

- Do NOT wire `noise_reducer.py` into `main.py` in this wave — that is Wave 2 (24-2).
- Do NOT import from `noise_reducer` in any existing module yet.
- The `topology_client` parameter is accepted by both check functions but
  `_get_topology_node` access is via the existing internal method; do not add new
  public methods to `TopologyClient`.
- Match the constant naming pattern from `change_correlator.py`:
  `SUPPRESSION_ENABLED`, `SUPPRESSION_LOOKBACK_HOURS`, `CORRELATION_WINDOW_MINUTES`.
- Use `from __future__ import annotations` at top of file.
- All functions must have type annotations on every parameter and return type.
