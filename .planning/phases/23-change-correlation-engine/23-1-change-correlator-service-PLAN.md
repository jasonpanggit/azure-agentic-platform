---
wave: 1
depends_on: []
autonomous: true
requirements:
  - INTEL-002
files_modified:
  - services/api-gateway/models.py
  - services/api-gateway/change_correlator.py
  - services/api-gateway/tests/test_change_correlator.py
---

# Plan 23-1: ChangeCorrelation Model + change_correlator Service

## Goal

Add `ChangeCorrelation` Pydantic model to `models.py`, extend `IncidentSummary` with
`top_changes`, and implement `services/api-gateway/change_correlator.py` — the async
function that queries the Activity Log, scores change events, and returns the top-3
correlations. No wiring into the API yet (that is Wave 2).

---

<task id="23-1-A">
<title>Add ChangeCorrelation model and extend IncidentSummary in models.py</title>

<read_first>
- `services/api-gateway/models.py` (full file — understand existing Pydantic patterns,
  field naming, Optional usage, and the current IncidentSummary definition at line 183)
</read_first>

<action>
Open `services/api-gateway/models.py` and make two additions:

**1. Insert `ChangeCorrelation` model immediately before `IncidentSummary` (after `ApprovalRecord`):**

```python
class ChangeCorrelation(BaseModel):
    """A single Azure resource change correlated with an incident (INTEL-002)."""

    change_id: str = Field(
        ...,
        description="Activity Log event ID (correlationId or eventDataId)",
    )
    operation_name: str = Field(
        ...,
        description="ARM operation name, e.g. 'Microsoft.Compute/virtualMachines/write'",
    )
    resource_id: str = Field(
        ...,
        description="Full ARM resource ID of the changed resource",
    )
    resource_name: str = Field(
        ...,
        description="Last path segment of resource_id (human-readable name)",
    )
    caller: Optional[str] = Field(
        default=None,
        description="UPN or object ID of the principal who made the change",
    )
    changed_at: str = Field(
        ...,
        description="ISO 8601 timestamp when the change occurred",
    )
    delta_minutes: float = Field(
        ...,
        description="Minutes before the incident was created (positive = before incident)",
    )
    topology_distance: int = Field(
        ...,
        description="BFS hop count from incident resource: 0 = same resource, 1 = direct neighbor, etc.",
    )
    change_type_score: float = Field(
        ...,
        description="Score 0.0–1.0 based on the operation type",
    )
    correlation_score: float = Field(
        ...,
        description="Overall weighted score 0.0–1.0: w_temporal*temporal + w_topology*topology + w_change_type*change_type",
    )
    status: str = Field(
        ...,
        description="Activity Log event status: 'Succeeded' | 'Failed' | 'Started'",
    )
```

**2. Extend `IncidentSummary` — add `top_changes` field after `evidence_collected_at`:**

```python
    top_changes: Optional[list["ChangeCorrelation"]] = Field(
        default=None,
        description=(
            "Top-3 Azure resource changes correlated with this incident. "
            "Populated by the change_correlator BackgroundTask within 30 seconds "
            "of incident ingestion (INTEL-002)."
        ),
    )
```

Ordering note: `ChangeCorrelation` must be defined before `IncidentSummary` in the file
so the forward reference resolves. Insert it above `IncidentSummary` — after
`ApprovalRecord` ends at the blank line before `class IncidentSummary`.
</action>

<acceptance_criteria>
# ChangeCorrelation class exists in models.py
grep -n "class ChangeCorrelation" services/api-gateway/models.py

# All 11 required fields are present
grep -c "    [a-z_]*:" services/api-gateway/models.py | head -1  # sanity, not precise
grep -n "change_id\|operation_name\|resource_id\|resource_name\|caller\|changed_at\|delta_minutes\|topology_distance\|change_type_score\|correlation_score\|status" services/api-gateway/models.py | grep -A1 "ChangeCorrelation" | head -20

# top_changes field on IncidentSummary
grep -n "top_changes" services/api-gateway/models.py

# Pydantic import unchanged (Optional already imported)
grep "from typing import Optional" services/api-gateway/models.py

# Model is importable (no syntax errors)
python -c "from services.api_gateway.models import ChangeCorrelation, IncidentSummary; print('ok')"

# ChangeCorrelation appears BEFORE IncidentSummary in the file
python -c "
import ast, sys
src = open('services/api-gateway/models.py').read()
tree = ast.parse(src)
classes = {n.name: n.lineno for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
assert classes['ChangeCorrelation'] < classes['IncidentSummary'], 'ChangeCorrelation must precede IncidentSummary'
print('order ok')
"
</acceptance_criteria>
</task>

---

<task id="23-1-B">
<title>Implement change_correlator.py</title>

<read_first>
- `services/api-gateway/diagnostic_pipeline.py` (full file — the `_collect_activity_log`
  helper at line 52, `_extract_subscription_id` at line 42, BackgroundTask guard pattern,
  env var pattern at lines 27-29, asyncio executor pattern at line 71)
- `services/api-gateway/topology.py` lines 430–510 (get_blast_radius signature and return
  shape: `{resource_id, affected_resources: [{resource_id, hop_count, ...}], hop_counts: dict}`)
- `services/api-gateway/models.py` (ChangeCorrelation fields — just confirmed in 23-1-A)
- `.planning/phases/23-change-correlation-engine/23-CONTEXT.md` (scoring formula,
  weights, change_type_score table, function signature spec)
</read_first>

<action>
Create `services/api-gateway/change_correlator.py` with the following exact structure:

```
"""Change Correlation Engine — correlates incidents with recent Azure resource changes.

Runs as a FastAPI BackgroundTask after POST /api/v1/incidents. Queries the Azure
Activity Log for the incident's primary resource and all topology neighbors within
blast_radius, then scores each change event by temporal proximity, topological
distance, and change type. Stores the top-3 ChangeCorrelation objects on the
incident document in Cosmos DB (field: top_changes).

Satisfies INTEL-002: change correlation surfaces correct cause within 30 seconds
of incident creation.

All steps run with individual error handling. Correlator never raises — all
failures are logged. Partial results are better than no results.
"""
```

**Module-level constants (from env):**

```python
CORRELATOR_ENABLED: bool = os.environ.get("CHANGE_CORRELATOR_ENABLED", "true").lower() == "true"
CORRELATOR_TIMEOUT: int = int(os.environ.get("CHANGE_CORRELATOR_TIMEOUT_SECONDS", "25"))
CORRELATOR_WINDOW_MINUTES: int = int(os.environ.get("CORRELATOR_WINDOW_MINUTES", "30"))
CORRELATOR_MAX_RESULTS: int = int(os.environ.get("CORRELATOR_MAX_RESULTS", "3"))

# Scoring weights (must sum to 1.0)
W_TEMPORAL: float = 0.5
W_TOPOLOGY: float = 0.3
W_CHANGE_TYPE: float = 0.2

# Change-type score table (operation_name prefix → score)
_CHANGE_TYPE_SCORES: dict[str, float] = {
    "microsoft.compute/virtualmachines/write": 0.9,
    "microsoft.sql/servers/databases/write": 0.8,
    "microsoft.network/networksecuritygroups/write": 0.8,
    "microsoft.resources/deployments/write": 0.7,
    "microsoft.authorization/roleassignments/write": 0.6,
}
_CHANGE_TYPE_DEFAULT: float = 0.4
```

**Private helpers:**

```python
def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from ARM resource ID.
    Identical logic to diagnostic_pipeline._extract_subscription_id — duplicated to
    avoid a cross-module dependency on a private helper.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return resource_id.split("/")[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(f"Cannot extract subscription_id from resource_id: {resource_id}")


def _resource_name(resource_id: str) -> str:
    """Return the last non-empty path segment of an ARM resource ID."""
    parts = [p for p in resource_id.split("/") if p]
    return parts[-1] if parts else resource_id


def _change_type_score(operation_name: str) -> float:
    """Look up a change-type score for the given ARM operation name.

    Matches on normalized (lowercase) operation_name prefix.
    Returns _CHANGE_TYPE_DEFAULT for unknown operations.
    """
    normalized = (operation_name or "").lower()
    for prefix, score in _CHANGE_TYPE_SCORES.items():
        if normalized.startswith(prefix):
            return score
    return _CHANGE_TYPE_DEFAULT


def _score_event(
    delta_minutes: float,
    topology_distance: int,
    operation_name: str,
    window_minutes: int,
) -> tuple[float, float]:
    """Compute (change_type_score, correlation_score) for one Activity Log event.

    Scoring formula:
        temporal_score    = 1.0 - (delta_minutes / window_minutes)   # clamp [0, 1]
        topology_score    = 1.0 / (topology_distance + 1)            # 1.0, 0.5, 0.33, …
        change_type_score = _change_type_score(operation_name)

        correlation_score = W_TEMPORAL * temporal_score
                          + W_TOPOLOGY * topology_score
                          + W_CHANGE_TYPE * change_type_score
    """
    temporal_score = max(0.0, min(1.0, 1.0 - (delta_minutes / window_minutes)))
    topology_score = 1.0 / (topology_distance + 1)
    ct_score = _change_type_score(operation_name)
    correlation = W_TEMPORAL * temporal_score + W_TOPOLOGY * topology_score + W_CHANGE_TYPE * ct_score
    return ct_score, round(correlation, 4)
```

**Activity Log query helper:**

```python
async def _query_activity_log_for_resource(
    credential: Any,
    resource_id: str,
    window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """Query Activity Log for write/action events on one resource in the given window.

    Returns a list of raw event dicts with keys:
        event_id, operation_name, caller, status, event_timestamp
    Returns [] on any error (logged but not raised).
    """
    try:
        from azure.mgmt.monitor import MonitorManagementClient

        sub_id = _extract_subscription_id(resource_id)
        filter_str = (
            f"eventTimestamp ge '{window_start.isoformat()}' "
            f"and eventTimestamp le '{window_end.isoformat()}' "
            f"and resourceId eq '{resource_id}'"
        )
        client = MonitorManagementClient(credential, sub_id)
        events = await asyncio.get_event_loop().run_in_executor(
            None, lambda: list(client.activity_logs.list(filter=filter_str))
        )
        results = []
        for event in events:
            op = event.operation_name.value if event.operation_name else ""
            # Only correlate write/action operations — skip reads and diagnostics
            if not (op.lower().endswith("/write") or op.lower().endswith("/action")):
                continue
            results.append({
                "event_id": getattr(event, "event_data_id", None) or getattr(event, "correlation_id", None) or "",
                "operation_name": op,
                "caller": event.caller,
                "status": event.status.value if event.status else "Unknown",
                "event_timestamp": event.event_timestamp,
            })
        logger.debug(
            "correlator: activity_log query | resource=%s events=%d write_events=%d",
            resource_id[:80], len(events), len(results),
        )
        return results
    except Exception as exc:
        logger.warning(
            "correlator: activity_log query failed | resource=%s error=%s",
            resource_id[:80], exc,
        )
        return []
```

**Main public function:**

```python
async def correlate_incident_changes(
    incident_id: str,
    resource_id: str,
    incident_created_at: datetime,
    credential: Any,
    cosmos_client: Any,
    topology_client: Optional[Any] = None,
    window_minutes: int = CORRELATOR_WINDOW_MINUTES,
    max_correlations: int = CORRELATOR_MAX_RESULTS,
    cosmos_db_name: str = "aap",
) -> None:
    """Correlate an incident with recent Azure resource changes.

    Called as a BackgroundTask from ingest_incident. Queries the Activity Log
    for the incident's primary resource and all topology neighbors, scores each
    change event, and writes the top-N results to the incident document in Cosmos.

    Args:
        incident_id: Unique incident identifier (Cosmos document ID).
        resource_id: Primary affected resource ARM ID.
        incident_created_at: UTC datetime when the incident was created.
        credential: Azure DefaultAzureCredential instance.
        cosmos_client: CosmosClient instance (may be None in dev/test mode).
        topology_client: Optional TopologyClient for blast-radius expansion.
        window_minutes: How far back to look for changes (default: CORRELATOR_WINDOW_MINUTES).
        max_correlations: Maximum ChangeCorrelation objects to store (default: CORRELATOR_MAX_RESULTS).
        cosmos_db_name: Cosmos DB database name.
    """
```

Implementation body inside `correlate_incident_changes`:

1. Guard on `CORRELATOR_ENABLED`; log and return if disabled.
2. Wrap entire function body in `try/except Exception` — never raise.
3. Record `correlator_start = time.monotonic()`.
4. Compute `window_start = incident_created_at - timedelta(minutes=window_minutes)`.
5. Build `resources_to_query: list[tuple[str, int]]` — list of `(resource_id, topology_distance)`:
   - Start with `[(resource_id, 0)]`.
   - If `topology_client is not None`, call (in executor):
     ```python
     blast = await asyncio.get_event_loop().run_in_executor(
         None, topology_client.get_blast_radius, resource_id, 3
     )
     ```
     For each entry in `blast.get("affected_resources", [])`:
     - Append `(entry["resource_id"], entry["hop_count"])`.
   - Log warning on topology error, continue without expansion.
6. Query Activity Log for each resource in parallel:
   ```python
   query_tasks = [
       asyncio.create_task(
           asyncio.wait_for(
               _query_activity_log_for_resource(credential, rid, window_start, incident_created_at),
               timeout=CORRELATOR_TIMEOUT,
           )
       )
       for rid, _ in resources_to_query
   ]
   query_results = await asyncio.gather(*query_tasks, return_exceptions=True)
   ```
7. Score all events — build `candidates: list[ChangeCorrelation]`:
   - Iterate `zip(resources_to_query, query_results)`.
   - Skip if result is an Exception (log it).
   - For each event dict in result:
     - Compute `delta_minutes = (incident_created_at - event["event_timestamp"].replace(tzinfo=timezone.utc)).total_seconds() / 60`.
     - Skip if `delta_minutes < 0` (event after incident) or `delta_minutes > window_minutes`.
     - Call `ct_score, score = _score_event(delta_minutes, distance, op, window_minutes)`.
     - Build `ChangeCorrelation(...)` — use `event["event_id"] or f"{rid}:{op}:{ts}"` as `change_id`.
     - Append to `candidates`.
8. Sort `candidates` by `correlation_score` descending; take `[:max_correlations]`.
9. Log summary: `correlator: scored | incident_id=... candidates=N top_score=X.XX`.
10. If `cosmos_client is None`: log warning, return.
11. Persist: read incident doc from Cosmos `incidents` container, set `top_changes` field
    (serialize as list of dicts via `.model_dump()`), call `replace_item`. Log success.
12. Log total duration.
</action>

<acceptance_criteria>
# File exists
test -f services/api-gateway/change_correlator.py && echo "exists"

# Public function signature is importable with correct parameter names
python -c "
import inspect
from services.api_gateway.change_correlator import correlate_incident_changes
sig = inspect.signature(correlate_incident_changes)
params = list(sig.parameters)
expected = ['incident_id', 'resource_id', 'incident_created_at', 'credential',
            'cosmos_client', 'topology_client', 'window_minutes', 'max_correlations',
            'cosmos_db_name']
assert params == expected, f'got {params}'
print('signature ok')
"

# Scoring constants present
grep -n "W_TEMPORAL\s*=\s*0\.5" services/api-gateway/change_correlator.py
grep -n "W_TOPOLOGY\s*=\s*0\.3" services/api-gateway/change_correlator.py
grep -n "W_CHANGE_TYPE\s*=\s*0\.2" services/api-gateway/change_correlator.py

# Change-type score table has all required entries
grep -n "microsoft.compute/virtualmachines/write.*0\.9" services/api-gateway/change_correlator.py
grep -n "microsoft.sql/servers/databases/write.*0\.8" services/api-gateway/change_correlator.py
grep -n "microsoft.network/networksecuritygroups/write.*0\.8" services/api-gateway/change_correlator.py
grep -n "microsoft.resources/deployments/write.*0\.7" services/api-gateway/change_correlator.py
grep -n "microsoft.authorization/roleassignments/write.*0\.6" services/api-gateway/change_correlator.py

# Timeout constant is 25s (INTEL-002 = 30s; 5s headroom)
grep -n "CHANGE_CORRELATOR_TIMEOUT_SECONDS.*25" services/api-gateway/change_correlator.py

# File is < 400 lines (style rule)
wc -l services/api-gateway/change_correlator.py

# No syntax errors
python -m py_compile services/api-gateway/change_correlator.py && echo "compiles ok"
</acceptance_criteria>
</task>

---

<task id="23-1-C">
<title>Write unit tests: test_change_correlator.py</title>

<read_first>
- `services/api-gateway/change_correlator.py` (just written — test what is there)
- `services/api-gateway/tests/test_diagnostic_pipeline.py` (test patterns: patch.dict
  sys.modules for azure SDK mocks, AsyncMock usage, run_in_executor patterns)
- `services/api-gateway/tests/conftest.py` (shared fixtures if any)
</read_first>

<action>
Create `services/api-gateway/tests/test_change_correlator.py`.

**Test file structure:**

```python
"""Unit tests for change_correlator.py.

Tests cover:
- Scoring math (_score_event, _change_type_score)
- Activity Log query helper (_query_activity_log_for_resource)
- Full correlate_incident_changes: happy path with topology expansion
- Full correlate_incident_changes: topology unavailable (graceful degradation)
- Full correlate_incident_changes: cosmos_client=None (no persistence)
- Full correlate_incident_changes: activity log returns no write events
- Full correlate_incident_changes: all events outside window
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
import asyncio
from datetime import datetime, timezone, timedelta

RESOURCE_ID = "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-001"
INCIDENT_CREATED_AT = datetime(2026, 4, 3, 12, 30, 0, tzinfo=timezone.utc)
```

**Required test functions (write all of these):**

1. **`test_extract_subscription_id()`** — calls `_extract_subscription_id(RESOURCE_ID)`, asserts `"sub-123"`.

2. **`test_resource_name()`** — calls `_resource_name(RESOURCE_ID)`, asserts `"vm-prod-001"`.

3. **`test_change_type_score_known_operations()`** — parametrize with:
   - `("Microsoft.Compute/virtualMachines/write", 0.9)`
   - `("Microsoft.Sql/servers/databases/write", 0.8)`
   - `("Microsoft.Network/networkSecurityGroups/write", 0.8)`
   - `("Microsoft.Resources/deployments/write", 0.7)`
   - `("Microsoft.Authorization/roleAssignments/write", 0.6)`
   - `("Microsoft.Storage/storageAccounts/write", 0.4)` (default)
   - `("Microsoft.Compute/virtualMachines/read", 0.4)` (read op → default)

4. **`test_score_event_same_resource_immediate()`** — delta=1min, distance=0, op="Microsoft.Compute/virtualMachines/write", window=30.
   - Assert `ct_score == 0.9`.
   - Assert `correlation_score` ≈ `0.5*(1-1/30) + 0.3*1.0 + 0.2*0.9` (±0.001).

5. **`test_score_event_distant_old_change()`** — delta=29min (near end of window), distance=3, op="Microsoft.Storage/storageAccounts/write", window=30.
   - Assert `temporal_score` is close to `1/30` ≈ 0.033.
   - Assert `correlation_score` < 0.4 (low score for distant + old + low change type).

6. **`test_score_event_temporal_clamped_to_zero()`** — delta=31min (outside window), distance=0, op="...write". Assert temporal_score component would be 0.0 (clamped). Check `correlation_score == W_TOPOLOGY * 1.0 + W_CHANGE_TYPE * ct_score`.

7. **`test_query_activity_log_filters_non_write_events()`** — mock `MonitorManagementClient` to return 3 events: one `/write`, one `/read`, one `/action`. Assert only 2 events returned (write + action).

8. **`test_query_activity_log_returns_empty_on_error()`** — mock `MonitorManagementClient` to raise `Exception("Auth failed")`. Assert returns `[]` (no raise).

9. **`test_correlate_incident_changes_happy_path()`** — end-to-end async test:
   - Mock topology_client: `get_blast_radius` returns `{"affected_resources": [{"resource_id": "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-01", "hop_count": 1}]}`.
   - Mock `_query_activity_log_for_resource` (patch on module) to return 1 event for the primary resource (delta=5min, write) and 1 event for the NIC (delta=10min, write).
   - Mock `cosmos_client`: `get_database_client().get_container_client().read_item()` returns `{"id": "inc-001", "incident_id": "inc-001"}`.
   - Call `correlate_incident_changes(incident_id="inc-001", resource_id=RESOURCE_ID, incident_created_at=INCIDENT_CREATED_AT, ...)`.
   - Assert `replace_item` was called once with a doc containing `"top_changes"` key.
   - Assert `len(doc["top_changes"]) <= 3`.
   - Assert the first item has `topology_distance == 0` (primary resource scores higher).

10. **`test_correlate_incident_changes_no_topology()`** — topology_client=None. Assert only primary resource is queried (1 Activity Log call, not 2).

11. **`test_correlate_incident_changes_cosmos_none()`** — cosmos_client=None. Assert function returns without raising. Assert `replace_item` is never called.

12. **`test_correlate_incident_changes_no_write_events()`** — mock Activity Log returns events with only `/read` operations. Assert `top_changes` written to Cosmos is an empty list `[]`.

13. **`test_correlate_incident_changes_all_events_outside_window()`** — mock events with `event_timestamp` = `INCIDENT_CREATED_AT - timedelta(minutes=45)` (outside 30-min window). Assert `top_changes == []`.

14. **`test_correlator_disabled_env()`** — set `CHANGE_CORRELATOR_ENABLED=false`, call `correlate_incident_changes(...)`, assert Activity Log is never queried.

All async tests decorated with `@pytest.mark.asyncio`.
Use `patch.dict("sys.modules", {"azure.mgmt.monitor": mock_module})` when mocking the Azure SDK import (consistent with `test_diagnostic_pipeline.py` pattern).
</action>

<acceptance_criteria>
# Test file exists
test -f services/api-gateway/tests/test_change_correlator.py && echo "exists"

# All 14 test functions present
grep -c "^def test_\|^async def test_" services/api-gateway/tests/test_change_correlator.py

# All tests pass
cd /path/to/repo && python -m pytest services/api-gateway/tests/test_change_correlator.py -v 2>&1 | tail -20

# No tests are skipped or xfailed unexpectedly
python -m pytest services/api-gateway/tests/test_change_correlator.py -v 2>&1 | grep -E "PASSED|FAILED|ERROR" | wc -l

# Scoring math test names are present
grep -n "test_score_event_same_resource_immediate\|test_score_event_distant_old_change\|test_score_event_temporal_clamped" services/api-gateway/tests/test_change_correlator.py

# Integration guards: disabled env test present
grep -n "test_correlator_disabled_env" services/api-gateway/tests/test_change_correlator.py
</acceptance_criteria>
</task>

---

## must_haves

- [ ] `ChangeCorrelation` Pydantic model is in `models.py` with all 11 fields matching the spec
- [ ] `IncidentSummary.top_changes: Optional[list[ChangeCorrelation]] = None` is added
- [ ] `ChangeCorrelation` is defined *before* `IncidentSummary` in `models.py` (no forward-ref issues)
- [ ] `change_correlator.py` exists and passes `python -m py_compile`
- [ ] `correlate_incident_changes` has the exact signature from the CONTEXT (8 parameters + cosmos_db_name)
- [ ] Weights are exactly: `W_TEMPORAL=0.5, W_TOPOLOGY=0.3, W_CHANGE_TYPE=0.2`
- [ ] Timeout constant is `25` seconds (INTEL-002 = 30s; 5s headroom)
- [ ] Change-type score table has all 5 named operations with correct values + default of `0.4`
- [ ] Only `/write` and `/action` operations are correlated (reads filtered out in `_query_activity_log_for_resource`)
- [ ] Function never raises — all failures logged and swallowed
- [ ] cosmos_client=None is handled gracefully (log + return, no crash)
- [ ] topology_client=None is handled gracefully (single-resource query, no crash)
- [ ] `_extract_subscription_id` is a module-private copy (not imported from `diagnostic_pipeline`)
- [ ] All 14 unit tests exist and pass
- [ ] File length < 400 lines (style rule: `wc -l services/api-gateway/change_correlator.py`)
