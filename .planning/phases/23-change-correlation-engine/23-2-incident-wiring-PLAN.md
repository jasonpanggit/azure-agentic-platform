---
wave: 2
depends_on:
  - 23-1-change-correlator-service-PLAN.md
autonomous: true
requirements:
  - INTEL-002
files_modified:
  - services/api-gateway/main.py
  - services/api-gateway/incidents_list.py
  - services/api-gateway/tests/test_change_correlator_wiring.py
---

# Plan 23-2: Wire Correlator into Incident Ingestion + Correlations Endpoint

## Goal

Wire `correlate_incident_changes` into `ingest_incident` as a second `BackgroundTask`
(parallel to the existing `run_diagnostic_pipeline`). Add the
`GET /api/v1/incidents/{incident_id}/correlations` endpoint that reads `top_changes` from
the Cosmos `incidents` container. Update `incidents_list.py` to include `top_changes` in
the SELECT projection so it flows through to `IncidentSummary`. Add targeted unit and
integration tests.

**Prerequisite:** Plan 23-1 must be complete. `change_correlator.py` and the updated
`models.py` must exist before these changes are applied.

---

<task id="23-2-A">
<title>Update ingest_incident in main.py to fire correlate_incident_changes as BackgroundTask</title>

<read_first>
- `services/api-gateway/main.py` lines 348–471 (the full `ingest_incident` handler —
  understand existing BackgroundTask usage at lines 417–430, topology_client access
  pattern at lines 437–465, how `request.app.state` is accessed)
- `services/api-gateway/change_correlator.py` (just written — the public function
  `correlate_incident_changes` and its parameter names)
- `services/api-gateway/diagnostic_pipeline.py` lines 328–360 (run_diagnostic_pipeline
  signature for comparison — use identical call-site pattern)
</read_first>

<action>
Make two targeted edits to `services/api-gateway/main.py`:

**Edit 1 — Add import at the top of the imports block (after `diagnostic_pipeline` import, line 66):**

```python
from services.api_gateway.change_correlator import correlate_incident_changes
```

Add it immediately after:
```python
from services.api_gateway.diagnostic_pipeline import run_diagnostic_pipeline
```

**Edit 2 — Add correlator BackgroundTask inside `ingest_incident`, after the existing diagnostic pipeline block.**

Locate this existing block (lines ~416–430):
```python
    # Queue diagnostic pipeline as background task (never blocks 202 response)
    if payload.affected_resources:
        primary_resource = payload.affected_resources[0].resource_id
        background_tasks.add_task(
            run_diagnostic_pipeline,
            incident_id=payload.incident_id,
            resource_id=primary_resource,
            domain=payload.domain,
            credential=credential,
            cosmos_client=cosmos,
        )
        logger.info(
            "pipeline: queued | incident_id=%s resource=%s",
            payload.incident_id, primary_resource,
        )
```

Immediately after the `logger.info(...)` call for the pipeline (still inside the `if payload.affected_resources:` block), add:

```python
        # Queue change correlator as background task (INTEL-002: within 30 seconds)
        # Runs in parallel with diagnostic_pipeline — both are independent BackgroundTasks.
        # incident_created_at is not yet in payload; use current UTC time as proxy
        # (Fabric Activator fires within seconds of the event, so skew is negligible).
        from datetime import datetime as _datetime, timezone as _timezone
        _incident_created_at = _datetime.now(_timezone.utc)
        background_tasks.add_task(
            correlate_incident_changes,
            incident_id=payload.incident_id,
            resource_id=primary_resource,
            incident_created_at=_incident_created_at,
            credential=credential,
            cosmos_client=cosmos,
            topology_client=topology_client,
        )
        logger.info(
            "correlator: queued | incident_id=%s resource=%s",
            payload.incident_id, primary_resource,
        )
```

Note: `topology_client` is already fetched above this block via
`topology_client = getattr(request.app.state, "topology_client", None)`.
If the topology block moves, ensure `topology_client` is resolved before this add_task call.

**What NOT to change:**
- Do not alter the `blast_radius_summary` TOPO-004 block.
- Do not alter the Foundry dispatch (`create_foundry_thread`) call.
- Do not alter the dedup check.
- Do not change the `return IncidentResponse(...)` line.
- Do not move the existing `run_diagnostic_pipeline` call.
</action>

<acceptance_criteria>
# Import is present
grep -n "from services.api_gateway.change_correlator import correlate_incident_changes" services/api-gateway/main.py

# BackgroundTask wiring is present
grep -n "correlate_incident_changes" services/api-gateway/main.py

# Log line is present
grep -n "correlator: queued" services/api-gateway/main.py

# Both pipeline and correlator background tasks exist in the same if-block
python -c "
src = open('services/api-gateway/main.py').read()
assert 'run_diagnostic_pipeline' in src
assert 'correlate_incident_changes' in src
# Both should appear inside ingest_incident (roughly in the second half of the file)
pipeline_pos = src.index('run_diagnostic_pipeline,')
correlator_pos = src.index('correlate_incident_changes,')
assert correlator_pos > pipeline_pos, 'correlator task must come after pipeline task'
print('wiring order ok')
"

# No syntax errors
python -m py_compile services/api-gateway/main.py && echo "compiles ok"

# App still starts (import check — does not require Azure credentials)
python -c "
import os; os.environ.setdefault('COSMOS_ENDPOINT', '')
# Just check that main module imports without crashing
import importlib.util
spec = importlib.util.spec_from_file_location('main', 'services/api-gateway/main.py')
" 2>&1 | grep -v "Warning\|warning" | head -10
</acceptance_criteria>
</task>

---

<task id="23-2-B">
<title>Update incidents_list.py SELECT projection to include top_changes</title>

<read_first>
- `services/api-gateway/incidents_list.py` (full file — the `list_incidents` function,
  particularly the `query` string built at lines 112–118, and the `enriched_doc` dict
  at lines 142–152)
</read_first>

<action>
Make two targeted edits to `services/api-gateway/incidents_list.py`:

**Edit 1 — Add `top_changes` to the SELECT projection in the Cosmos query string.**

Locate:
```python
    query = (
        f"SELECT c.id, c.incident_id, c.severity, c.domain, c.status, "
        f"c.created_at, c.title, c.resource_id, c.subscription_id, "
        f"c.affected_resources, c.investigation_status, c.evidence_collected_at "
        f"FROM c WHERE {where_clause} "
        f"ORDER BY c.created_at DESC "
        f"OFFSET 0 LIMIT @limit"
    )
```

Change to:
```python
    query = (
        f"SELECT c.id, c.incident_id, c.severity, c.domain, c.status, "
        f"c.created_at, c.title, c.resource_id, c.subscription_id, "
        f"c.affected_resources, c.investigation_status, c.evidence_collected_at, "
        f"c.top_changes "
        f"FROM c WHERE {where_clause} "
        f"ORDER BY c.created_at DESC "
        f"OFFSET 0 LIMIT @limit"
    )
```

**Edit 2 — Pass `top_changes` through in the `enriched_doc` dict.**

Locate the `enriched_doc` assignment:
```python
        enriched_doc = {
            **doc,
            "resource_id": resource_id,
            "resource_name": parsed["resource_name"],
            "resource_group": parsed["resource_group"],
            "resource_type": parsed["resource_type"],
            "subscription_id": parsed["subscription_id"] or doc.get("subscription_id"),
            "investigation_status": doc.get("investigation_status", "pending"),
            "evidence_collected_at": doc.get("evidence_collected_at"),
        }
```

Add `top_changes` to the explicit fields (the `**doc` spread already includes it if
the SELECT projection includes it, but explicit passthrough makes the contract clear):

```python
        enriched_doc = {
            **doc,
            "resource_id": resource_id,
            "resource_name": parsed["resource_name"],
            "resource_group": parsed["resource_group"],
            "resource_type": parsed["resource_type"],
            "subscription_id": parsed["subscription_id"] or doc.get("subscription_id"),
            "investigation_status": doc.get("investigation_status", "pending"),
            "evidence_collected_at": doc.get("evidence_collected_at"),
            "top_changes": doc.get("top_changes"),
        }
```

**What NOT to change:** Do not alter query filters, subscription client-side filter,
`_parse_resource_id`, `_get_incidents_container`, or any other existing logic.
</action>

<acceptance_criteria>
# top_changes in SELECT projection
grep -n "c\.top_changes" services/api-gateway/incidents_list.py

# top_changes in enriched_doc
grep -n '"top_changes"' services/api-gateway/incidents_list.py

# No syntax errors
python -m py_compile services/api-gateway/incidents_list.py && echo "compiles ok"

# Existing incidents_list tests still pass (no regressions)
python -m pytest services/api-gateway/tests/test_incidents_list.py -v 2>&1 | tail -10
</acceptance_criteria>
</task>

---

<task id="23-2-C">
<title>Add GET /api/v1/incidents/{incident_id}/correlations endpoint to main.py</title>

<read_first>
- `services/api-gateway/main.py` lines 474–507 (`get_incident_evidence` endpoint —
  use this as the pattern for the new correlations endpoint: same 404/503 guards,
  same Cosmos read pattern, same auth dependency)
- `services/api-gateway/models.py` (`ChangeCorrelation` model — used as response type)
- `services/api-gateway/change_correlator.py` (`correlate_incident_changes` signature —
  used for the optional on-demand re-run, but only if `force=true` query param is set)
</read_first>

<action>
Add a new endpoint to `services/api-gateway/main.py` immediately after the
`get_incident_evidence` endpoint (after line ~507, before the `search_runbooks_endpoint`).

**Also add `ChangeCorrelation` to the existing models import block** (the `from services.api_gateway.models import (` block starting at line 43). Add `ChangeCorrelation,` to the list.

**New endpoint:**

```python
@app.get(
    "/api/v1/incidents/{incident_id}/correlations",
    response_model=list[ChangeCorrelation],
)
async def get_incident_correlations(
    incident_id: str,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> list[ChangeCorrelation]:
    """Get change correlations for an incident (INTEL-002).

    Returns the top-3 ChangeCorrelation objects stored on the incident document.
    These are populated within 30 seconds of incident ingestion by the
    change_correlator BackgroundTask.

    Returns 200 with empty list if correlations have not yet been computed.
    Returns 404 if the incident itself does not exist.
    Returns 503 if Cosmos DB is not configured.

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Incident store not configured")
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("incidents")
        doc = container.read_item(incident_id, partition_key=incident_id)
        raw_changes = doc.get("top_changes") or []
        return [ChangeCorrelation(**c) for c in raw_changes]
    except Exception as exc:
        if "404" in str(exc) or "NotFound" in type(exc).__name__:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        logger.error(
            "get_incident_correlations: error | incident_id=%s error=%s",
            incident_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Correlations retrieval failed")
```

**Placement:** After `get_incident_evidence` (ends ~line 507), before the
`search_runbooks_endpoint` (starts with `@app.get("/api/v1/runbooks/search", ...)`).

**What NOT to change:**
- Do not alter `get_incident_evidence`.
- Do not add a `force` query parameter (deferred complexity — out of Phase 23 scope).
- Do not alter any existing endpoint.
</action>

<acceptance_criteria>
# Endpoint route is registered
grep -n '"/api/v1/incidents/{incident_id}/correlations"' services/api-gateway/main.py

# Function name
grep -n "async def get_incident_correlations" services/api-gateway/main.py

# ChangeCorrelation in models import
grep -n "ChangeCorrelation" services/api-gateway/main.py | head -5

# Response model annotation
grep -n "response_model=list\[ChangeCorrelation\]" services/api-gateway/main.py

# 404 guard present
grep -A3 "get_incident_correlations" services/api-gateway/main.py | grep -q "404" && echo "404 guard ok"

# 503 guard present
grep -n "Incident store not configured" services/api-gateway/main.py

# No syntax errors
python -m py_compile services/api-gateway/main.py && echo "compiles ok"

# Endpoint appears after get_incident_evidence and before search_runbooks_endpoint
python -c "
src = open('services/api-gateway/main.py').read()
evidence_pos = src.index('get_incident_evidence')
correlations_pos = src.index('get_incident_correlations')
runbooks_pos = src.index('search_runbooks_endpoint')
assert evidence_pos < correlations_pos < runbooks_pos, 'endpoint order wrong'
print('endpoint position ok')
"
</acceptance_criteria>
</task>

---

<task id="23-2-D">
<title>Write unit and integration tests: test_change_correlator_wiring.py</title>

<read_first>
- `services/api-gateway/main.py` (full — the updated ingest_incident and new correlations
  endpoint)
- `services/api-gateway/tests/test_incidents.py` (existing test patterns for FastAPI
  TestClient, auth mocking, Cosmos mocking — replicate the pattern exactly)
- `services/api-gateway/tests/test_diagnostic_pipeline.py` (BackgroundTask test pattern)
- `services/api-gateway/change_correlator.py` (the function being wired)
</read_first>

<action>
Create `services/api-gateway/tests/test_change_correlator_wiring.py`.

**Test file header:**
```python
"""Tests for change correlator wiring in main.py — BackgroundTask + correlations endpoint.

Tests:
- POST /api/v1/incidents queues correlate_incident_changes as a BackgroundTask
- GET /api/v1/incidents/{incident_id}/correlations returns stored top_changes
- GET correlations returns 404 for unknown incident
- GET correlations returns 503 when cosmos not configured
- GET correlations returns empty list when top_changes not yet populated
- POST /api/v1/incidents without affected_resources does NOT queue correlator
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
```

**Required test functions:**

1. **`test_ingest_incident_queues_correlator(client, mock_cosmos)`**
   - POST `/api/v1/incidents` with a valid IncidentPayload (severity=Sev1, domain=compute, one affected resource).
   - Mock `create_foundry_thread` to return `{"thread_id": "th-001"}`.
   - Mock `background_tasks.add_task` via `patch("fastapi.BackgroundTasks.add_task")`.
   - Assert `add_task` was called with `correlate_incident_changes` as first arg in at least one call.
   - Assert response is 202.

2. **`test_ingest_incident_correlator_queued_after_pipeline(client, mock_cosmos)`**
   - Same setup as above.
   - Assert `add_task` call with `run_diagnostic_pipeline` precedes call with `correlate_incident_changes` in `add_task.call_args_list`.

3. **`test_ingest_incident_no_resources_skips_correlator(client, mock_cosmos)`**
   - Cannot send zero `affected_resources` (model validation prevents it — min_length=1).
   - Instead: mock `payload.affected_resources` to be empty list via patching the route.
   - OR: test the guard logic directly by calling the BackgroundTask block logic with `affected_resources=[]`.
   - Assert `correlate_incident_changes` is not in `add_task` calls.

4. **`test_get_correlations_returns_top_changes(client, mock_cosmos)`**
   - Mock Cosmos to return an incident doc with `top_changes = [{"change_id": "evt-001", "operation_name": "Microsoft.Compute/virtualMachines/write", "resource_id": "/subscriptions/sub-123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-01", "resource_name": "vm-01", "caller": "user@example.com", "changed_at": "2026-04-03T12:00:00Z", "delta_minutes": 15.0, "topology_distance": 0, "change_type_score": 0.9, "correlation_score": 0.83, "status": "Succeeded"}]`.
   - GET `/api/v1/incidents/inc-001/correlations`.
   - Assert 200, response is a list of length 1.
   - Assert `response.json()[0]["change_id"] == "evt-001"`.
   - Assert `response.json()[0]["correlation_score"] == 0.83`.

5. **`test_get_correlations_returns_empty_list_when_not_populated(client, mock_cosmos)`**
   - Mock Cosmos to return incident doc without `top_changes` field (key absent).
   - GET `/api/v1/incidents/inc-001/correlations`.
   - Assert 200, response `== []`.

6. **`test_get_correlations_404_for_unknown_incident(client, mock_cosmos)`**
   - Mock Cosmos `read_item` to raise an exception containing "404" in the message.
   - GET `/api/v1/incidents/unknown-inc/correlations`.
   - Assert 404 status code.

7. **`test_get_correlations_503_when_cosmos_not_configured(client_no_cosmos)`**
   - Use a TestClient where `cosmos` dependency returns None.
   - GET `/api/v1/incidents/inc-001/correlations`.
   - Assert 503 status code.

**Fixture guidance** (replicate patterns from `test_incidents.py`):
- `client` fixture: use `TestClient(app)` with overridden `get_optional_cosmos_client`
  and `verify_token` dependencies.
- `mock_cosmos` fixture: MagicMock with `get_database_client().get_container_client().read_item()` chain.
- `client_no_cosmos` fixture: same but `get_optional_cosmos_client` returns `None`.
- Auth: override `verify_token` to return `{"sub": "test-user"}` (no real JWT needed).
</action>

<acceptance_criteria>
# Test file exists
test -f services/api-gateway/tests/test_change_correlator_wiring.py && echo "exists"

# All 7 test functions present
grep -c "^def test_\|^async def test_" services/api-gateway/tests/test_change_correlator_wiring.py

# All tests pass
python -m pytest services/api-gateway/tests/test_change_correlator_wiring.py -v 2>&1 | tail -15

# No FAILed or ERRORed tests
python -m pytest services/api-gateway/tests/test_change_correlator_wiring.py 2>&1 | grep -E "FAILED|ERROR" | wc -l

# Correlator queuing test exists
grep -n "test_ingest_incident_queues_correlator" services/api-gateway/tests/test_change_correlator_wiring.py

# Endpoint 404 test exists
grep -n "test_get_correlations_404" services/api-gateway/tests/test_change_correlator_wiring.py
</acceptance_criteria>
</task>

---

<task id="23-2-E">
<title>Verify full test suite — no regressions from Phase 23 changes</title>

<read_first>
- No files need to be read. This is a verification-only task.
- Run after all prior 23-2 tasks are complete.
</read_first>

<action>
Run the complete api-gateway test suite and confirm no pre-existing tests regress.

```bash
python -m pytest services/api-gateway/tests/ -v --tb=short 2>&1 | tail -40
```

If any pre-existing test fails (i.e., a test that was passing before Phase 23):
1. Identify the test file and assertion.
2. Check if the failure is caused by:
   a. The new `top_changes` field in `IncidentSummary` (most likely culprit — existing tests
      that assert exact field lists on IncidentSummary may need `top_changes=None` added to expected dicts).
   b. The `ChangeCorrelation` import added to `main.py`.
   c. The `c.top_changes` added to the Cosmos SELECT projection in `incidents_list.py`.
3. Fix the regression minimally — do not rewrite tests, only add the missing field assertion
   or update expected dict to include `top_changes: None`.

**Do NOT fail silently** — if there are still failures after fixes, report them explicitly.
</action>

<acceptance_criteria>
# Full suite passes (0 failures)
python -m pytest services/api-gateway/tests/ --tb=short 2>&1 | grep -E "passed|failed|error" | tail -3

# Specifically: test_incidents.py and test_incidents_list.py pass (most likely regression targets)
python -m pytest services/api-gateway/tests/test_incidents.py services/api-gateway/tests/test_incidents_list.py -v 2>&1 | tail -10

# New tests from Phase 23 also pass
python -m pytest services/api-gateway/tests/test_change_correlator.py services/api-gateway/tests/test_change_correlator_wiring.py -v 2>&1 | tail -10

# Total test count increased by at least 14+7=21 tests from Phase 22 baseline
python -m pytest services/api-gateway/tests/ --co -q 2>&1 | tail -5
</acceptance_criteria>
</task>

---

## must_haves

- [ ] `from services.api_gateway.change_correlator import correlate_incident_changes` added to `main.py`
- [ ] `background_tasks.add_task(correlate_incident_changes, ...)` fires inside `if payload.affected_resources:` block in `ingest_incident`
- [ ] Correlator `add_task` call appears AFTER the `run_diagnostic_pipeline` `add_task` call (not before)
- [ ] `topology_client` is passed to `correlate_incident_changes` (from `request.app.state`)
- [ ] `GET /api/v1/incidents/{incident_id}/correlations` endpoint exists, returns `list[ChangeCorrelation]`
- [ ] Correlations endpoint returns 200 + empty list (not 404) when `top_changes` absent on doc
- [ ] Correlations endpoint returns 404 when incident doc itself does not exist in Cosmos
- [ ] Correlations endpoint returns 503 when `cosmos_client` is None
- [ ] `ChangeCorrelation` imported in `main.py` models import block
- [ ] `c.top_changes` added to SELECT projection in `incidents_list.py`
- [ ] `top_changes` passed through in `enriched_doc` in `incidents_list.py`
- [ ] All 7 wiring tests in `test_change_correlator_wiring.py` pass
- [ ] Zero regressions in pre-existing test suite
- [ ] `python -m py_compile services/api-gateway/main.py` passes
- [ ] `python -m py_compile services/api-gateway/incidents_list.py` passes
