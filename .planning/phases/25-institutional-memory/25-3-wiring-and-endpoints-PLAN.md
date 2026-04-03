# Plan 25-3: Wiring and Endpoints

**Phase:** 25 — Institutional Memory and SLO Tracking
**Wave:** 2 (depends on 25-1 AND 25-2 both complete)
**Requirements:** INTEL-003 + INTEL-004 end-to-end
**Autonomous:** true

---

## Goal

Wire `incident_memory` and `slo_tracker` into the live incident path. Add startup DB migrations for both new tables. Add the resolve endpoint and SLO CRUD/health endpoints. The BackgroundTask for historical matching and the SLO escalation check are the two critical integration points.

---

## Files Changed

| File | Action |
|------|--------|
| `services/api-gateway/main.py` | Add migrations, BackgroundTask, SLO escalation, resolve endpoint, SLO routes |
| `services/api-gateway/tests/test_institutional_memory_wiring.py` | Create integration tests |

---

## Pre-condition check

Before starting this plan, verify:
- `services/api-gateway/incident_memory.py` exists and exports `store_incident_memory`, `search_incident_memory`
- `services/api-gateway/slo_tracker.py` exists and exports `create_slo`, `list_slos`, `get_slo_health`, `update_slo_metrics`, `check_domain_burn_rate_alert`
- `models.py` contains `HistoricalMatch`, `SLODefinition`, `SLOHealth`, `SLOCreateRequest`
- `IncidentSummary` has `historical_matches` and `slo_escalated` fields

---

## Step 1 — Startup Migration in `_run_startup_migrations`

### Location in `main.py`

Inside `_run_startup_migrations()`, after the existing `eol_cache` table migration and before the `logger.info("Startup migrations complete ...")` line.

### SQL to add

```python
# incident_memory table (Phase 25 — INTEL-003)
await conn.execute("""
    CREATE TABLE IF NOT EXISTS incident_memory (
        id TEXT PRIMARY KEY,
        domain TEXT NOT NULL,
        severity TEXT NOT NULL,
        resource_type TEXT,
        title TEXT,
        summary TEXT,
        transcript TEXT,
        resolution TEXT,
        resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        embedding VECTOR(1536)
    );
""")
await conn.execute(
    "CREATE INDEX IF NOT EXISTS incident_memory_embedding_idx "
    "ON incident_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);"
)

# slo_definitions table (Phase 25 — INTEL-004)
await conn.execute("""
    CREATE TABLE IF NOT EXISTS slo_definitions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        domain TEXT NOT NULL,
        metric TEXT NOT NULL,
        target_pct FLOAT NOT NULL,
        window_hours INT NOT NULL,
        current_value FLOAT,
        error_budget_pct FLOAT,
        burn_rate_1h FLOAT,
        burn_rate_15min FLOAT,
        status TEXT DEFAULT 'healthy',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
""")
await conn.execute(
    "CREATE INDEX IF NOT EXISTS slo_definitions_domain_status_idx "
    "ON slo_definitions (domain, status);"
)
```

### Updated logger line

Change:
```python
logger.info("Startup migrations complete (pgvector + runbooks table + eol_cache table)")
```
To:
```python
logger.info(
    "Startup migrations complete "
    "(pgvector + runbooks + eol_cache + incident_memory + slo_definitions)"
)
```

---

## Step 2 — New imports in `main.py`

Add to the existing import block (after the `runbook_rag` import line):

```python
from services.api_gateway.incident_memory import search_incident_memory, store_incident_memory
from services.api_gateway.slo_tracker import (
    check_domain_burn_rate_alert,
    create_slo,
    get_slo_health,
    list_slos,
)
from services.api_gateway.models import (
    # existing imports ...
    HistoricalMatch,
    SLOCreateRequest,
    SLODefinition,
    SLOHealth,
)
```

**Important:** Do not duplicate any existing model imports — add only the new ones to the existing `from services.api_gateway.models import (...)` block.

---

## Step 3 — SLO escalation in `ingest_incident`

### Location

Immediately after the `# 0d. Composite severity scoring.` block (after `_composite_severity` is computed) and before the dedup check. Insert after line:

```python
logger.info(
    "noise_reducer: composite_severity=%s blast_radius=%d | incident=%s",
    ...
)
# --- End Phase 24 noise reduction ---
```

### Code to insert

```python
# --- Phase 25: SLO-aware escalation (INTEL-004) ---
_slo_escalated: bool = False
if _composite_severity != "Sev0":
    try:
        _domain_in_alert = await check_domain_burn_rate_alert(payload.domain)
        if _domain_in_alert:
            _composite_severity = "Sev0"
            _slo_escalated = True
            logger.info(
                "slo_escalation: escalated to Sev0 | incident=%s domain=%s",
                payload.incident_id,
                payload.domain,
            )
    except Exception as _slo_exc:
        # Non-fatal: SLO check failure must not block incident ingestion
        logger.warning(
            "slo_escalation: check failed (non-fatal) | incident=%s error=%s",
            payload.incident_id,
            _slo_exc,
        )
# --- End Phase 25 SLO escalation ---
```

### Patch Cosmos incident doc with SLO escalation flag

In the existing `patch_item` call (after the dedup check, where `composite_severity` is patched), add `slo_escalated` to the patch operations:

```python
patch_operations=[
    {"op": "add", "path": "/composite_severity", "value": _composite_severity},
    {"op": "add", "path": "/correlated_with", "value": _correlated_with},
    {"op": "add", "path": "/slo_escalated", "value": _slo_escalated},  # Phase 25
],
```

---

## Step 4 — BackgroundTask: historical memory search

### Location

In `ingest_incident`, after the existing `correlate_incident_changes` BackgroundTask enqueue block and before the topology blast-radius prefetch. Insert:

```python
# Queue historical incident memory search (INTEL-003: surface past patterns within 10s)
background_tasks.add_task(
    _attach_historical_matches,
    incident_id=payload.incident_id,
    title=payload.title,
    domain=payload.domain,
    resource_type=(
        payload.affected_resources[0].resource_type
        if payload.affected_resources else None
    ),
    cosmos_client=cosmos,
)
logger.info(
    "memory: queued | incident_id=%s",
    payload.incident_id,
)
```

### Define `_attach_historical_matches` function

Add as a module-level async function in `main.py`, near the other background task helpers. Place it above `ingest_incident`:

```python
async def _attach_historical_matches(
    incident_id: str,
    title: Optional[str],
    domain: Optional[str],
    resource_type: Optional[str],
    cosmos_client: Any,
) -> None:
    """BackgroundTask: search incident_memory and attach top-3 matches to Cosmos doc.

    Non-fatal — logs warning and returns on any error. Must complete within 10s
    to satisfy INTEL-003 (historical match available before first agent triage response).
    """
    try:
        matches = await search_incident_memory(
            title=title,
            domain=domain,
            resource_type=resource_type,
            limit=3,
        )
        if not matches or cosmos_client is None:
            return

        db = cosmos_client.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("incidents")
        container.patch_item(
            item=incident_id,
            partition_key=incident_id,
            patch_operations=[
                {"op": "add", "path": "/historical_matches", "value": matches},
            ],
        )
        logger.info(
            "memory: attached %d historical match(es) | incident=%s",
            len(matches),
            incident_id,
        )
    except Exception as exc:
        logger.warning(
            "memory: attach failed (non-fatal) | incident=%s error=%s",
            incident_id,
            exc,
        )
```

---

## Step 5 — `POST /api/v1/incidents/{incident_id}/resolve` endpoint

Add to `main.py` after `get_incident_correlations`:

```python
class ResolveIncidentRequest(BaseModel):
    """Request body for POST /api/v1/incidents/{incident_id}/resolve."""

    summary: str = Field(..., min_length=1, description="Operator-provided investigation summary")
    resolution: str = Field(..., min_length=1, description="What fixed the incident")


@app.post("/api/v1/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    payload: ResolveIncidentRequest,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> dict:
    """Mark an incident as resolved and store its embedding in incident_memory (INTEL-003).

    Reads the incident from Cosmos DB to retrieve domain, severity, resource_type,
    and title. Generates an embedding for the summary+resolution text and upserts
    into incident_memory. Updates Cosmos status to 'resolved'.

    Returns:
        { incident_id, memory_id, resolved_at }

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Incident store not configured")

    # Read incident from Cosmos
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("incidents")
        doc = container.read_item(incident_id, partition_key=incident_id)
    except Exception as exc:
        if "404" in str(exc) or "NotFound" in type(exc).__name__:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        logger.error("resolve_incident: read failed | incident=%s error=%s", incident_id, exc)
        raise HTTPException(status_code=500, detail="Failed to read incident")

    domain = doc.get("domain", "")
    severity = doc.get("severity", "")
    resource_type = doc.get("resource_type")
    title = doc.get("title")

    # Store in incident_memory (embed + upsert)
    from services.api_gateway.incident_memory import IncidentMemoryUnavailableError

    try:
        memory_id = await store_incident_memory(
            incident_id=incident_id,
            domain=domain,
            severity=severity,
            resource_type=resource_type,
            title=title,
            summary=payload.summary,
            resolution=payload.resolution,
        )
    except IncidentMemoryUnavailableError as exc:
        logger.error(
            "resolve_incident: memory store unavailable | incident=%s error=%s",
            incident_id, exc,
        )
        raise HTTPException(status_code=503, detail="Incident memory store unavailable")

    # Update Cosmos status to 'resolved'
    from datetime import datetime as _datetime, timezone as _timezone
    _resolved_at = _datetime.now(_timezone.utc).isoformat()
    try:
        container.patch_item(
            item=incident_id,
            partition_key=incident_id,
            patch_operations=[
                {"op": "add", "path": "/status", "value": "resolved"},
                {"op": "add", "path": "/resolved_at", "value": _resolved_at},
                {"op": "add", "path": "/resolution", "value": payload.resolution},
                {"op": "add", "path": "/summary", "value": payload.summary},
            ],
        )
    except Exception as exc:
        # Memory was already stored — log but don't fail the request
        logger.warning(
            "resolve_incident: Cosmos status update failed (non-fatal) | "
            "incident=%s error=%s",
            incident_id, exc,
        )

    logger.info(
        "resolve_incident: complete | incident=%s memory_id=%s",
        incident_id, memory_id,
    )
    return {"incident_id": incident_id, "memory_id": memory_id, "resolved_at": _resolved_at}
```

**Note:** `ResolveIncidentRequest` is a local model inline to `main.py` — it is small and endpoint-specific. Do not add to `models.py`.

---

## Step 6 — SLO API routes

Add to `main.py` after the `resolve_incident` endpoint:

```python
@app.post("/api/v1/slos", response_model=SLODefinition, status_code=status.HTTP_201_CREATED)
async def create_slo_endpoint(
    payload: SLOCreateRequest,
    token: dict[str, Any] = Depends(verify_token),
) -> SLODefinition:
    """Create a new SLO definition (INTEL-004).

    Authentication: Entra ID Bearer token required.
    """
    from services.api_gateway.slo_tracker import SLOTrackerUnavailableError

    try:
        result = await create_slo(
            name=payload.name,
            domain=payload.domain,
            metric=payload.metric,
            target_pct=payload.target_pct,
            window_hours=payload.window_hours,
        )
    except SLOTrackerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return SLODefinition(**result)


@app.get("/api/v1/slos", response_model=list[SLODefinition])
async def list_slos_endpoint(
    domain: Optional[str] = None,
    token: dict[str, Any] = Depends(verify_token),
) -> list[SLODefinition]:
    """List SLO definitions, optionally filtered by domain (INTEL-004).

    Authentication: Entra ID Bearer token required.
    """
    results = await list_slos(domain=domain)
    return [SLODefinition(**r) for r in results]


@app.get("/api/v1/slos/{slo_id}/health", response_model=SLOHealth)
async def get_slo_health_endpoint(
    slo_id: str,
    token: dict[str, Any] = Depends(verify_token),
) -> SLOHealth:
    """Get the current health snapshot for a single SLO (INTEL-004).

    Authentication: Entra ID Bearer token required.
    """
    from services.api_gateway.slo_tracker import SLOTrackerUnavailableError

    try:
        result = await get_slo_health(slo_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"SLO {slo_id} not found")
    except SLOTrackerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return SLOHealth(**result)
```

---

## Step 7 — Integration Tests: `services/api-gateway/tests/test_institutional_memory_wiring.py`

**Minimum:** 12 tests. Target: 15.

### Test file preamble

```python
"""Integration tests for Phase 25 wiring in main.py.

Tests:
- POST /api/v1/incidents queues _attach_historical_matches BackgroundTask
- SLO escalation: composite_severity elevated to Sev0 when domain has burn-rate alert
- POST /api/v1/incidents/{id}/resolve → stores memory, updates Cosmos
- GET /api/v1/slos → list SLOs
- POST /api/v1/slos → create SLO
- GET /api/v1/slos/{slo_id}/health → health snapshot
"""
```

### Fixtures

Follow the exact same fixture pattern as `test_change_correlator_wiring.py`:

```python
@pytest.fixture()
def mock_cosmos():
    cosmos = MagicMock(name="CosmosClient")
    db = MagicMock(name="DatabaseProxy")
    container = MagicMock(name="ContainerProxy")
    container.read_item.return_value = {
        "id": "inc-001",
        "incident_id": "inc-001",
        "domain": "compute",
        "severity": "Sev1",
        "title": "High CPU on vm-01",
    }
    db.get_container_client.return_value = container
    cosmos.get_database_client.return_value = db
    return cosmos

@pytest.fixture()
def client(mock_cosmos):
    app.state.credential = MagicMock()
    app.state.cosmos_client = mock_cosmos
    app.state.topology_client = None
    return TestClient(app)
```

### Test list

| # | Class / test name | What it verifies |
|---|-------------------|-----------------|
| 1 | `TestHistoricalMemoryWiring::test_ingest_queues_attach_historical_matches` | `_attach_historical_matches` is in `BackgroundTasks.add_task` calls after POST /incidents |
| 2 | `TestHistoricalMemoryWiring::test_attach_historical_matches_not_queued_without_affected_resources` | Pydantic rejects empty list → 422, no BackgroundTask queued |
| 3 | `TestSLOEscalation::test_no_escalation_when_no_slo_alert` | `check_domain_burn_rate_alert` returns False → composite_severity unchanged (not Sev0) |
| 4 | `TestSLOEscalation::test_escalates_to_sev0_when_domain_in_burn_rate_alert` | `check_domain_burn_rate_alert` returns True → response includes `composite_severity: "Sev0"` |
| 5 | `TestSLOEscalation::test_no_double_escalation_when_already_sev0` | `_composite_severity` already Sev0 → `check_domain_burn_rate_alert` not called |
| 6 | `TestSLOEscalation::test_slo_check_failure_does_not_block_ingestion` | `check_domain_burn_rate_alert` raises exception → incident still dispatched (202) |
| 7 | `TestResolveEndpoint::test_resolve_returns_200_with_memory_id` | `POST /api/v1/incidents/inc-001/resolve` → 200, body has `incident_id`, `memory_id`, `resolved_at` |
| 8 | `TestResolveEndpoint::test_resolve_404_for_unknown_incident` | Cosmos `read_item` raises "404 Not Found" → HTTP 404 |
| 9 | `TestResolveEndpoint::test_resolve_503_when_cosmos_not_configured` | `cosmos=None` → HTTP 503 |
| 10 | `TestResolveEndpoint::test_resolve_503_when_memory_store_unavailable` | `store_incident_memory` raises `IncidentMemoryUnavailableError` → HTTP 503 |
| 11 | `TestSLORoutes::test_create_slo_returns_201` | `POST /api/v1/slos` with valid body → 201, body has `id`, `name`, `domain` |
| 12 | `TestSLORoutes::test_list_slos_returns_200` | `GET /api/v1/slos` → 200, list (may be empty) |
| 13 | `TestSLORoutes::test_list_slos_domain_filter_passed_through` | `GET /api/v1/slos?domain=compute` → `list_slos(domain="compute")` called |
| 14 | `TestSLORoutes::test_get_slo_health_returns_200` | `GET /api/v1/slos/{slo_id}/health` → 200 with SLOHealth body |
| 15 | `TestSLORoutes::test_get_slo_health_404_for_unknown` | `get_slo_health` raises `KeyError` → HTTP 404 |

### Key mock patterns

**For BackgroundTask queuing tests (tests 1, 2):**
```python
@patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
@patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
@patch("services.api_gateway.main.check_domain_burn_rate_alert", new_callable=AsyncMock, return_value=False)
def test_ingest_queues_attach_historical_matches(self, _mock_br, _mock_dedup, mock_foundry, client):
    from services.api_gateway.main import _attach_historical_matches
    mock_foundry.return_value = {"thread_id": "th-001"}

    with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
        response = client.post("/api/v1/incidents", json=VALID_INCIDENT_PAYLOAD)

    assert response.status_code == 202
    called_funcs = [call.args[0] for call in mock_add_task.call_args_list]
    assert _attach_historical_matches in called_funcs
```

**For SLO escalation tests (tests 3–6):**
```python
@patch("services.api_gateway.main.check_domain_burn_rate_alert", new_callable=AsyncMock, return_value=True)
@patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
@patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
def test_escalates_to_sev0(self, _mock_dedup, mock_foundry, _mock_br, client):
    mock_foundry.return_value = {"thread_id": "th-002"}
    response = client.post("/api/v1/incidents", json=VALID_INCIDENT_PAYLOAD)
    assert response.status_code == 202
    # composite_severity in response body is "Sev0"
    data = response.json()
    assert data["composite_severity"] == "Sev0"
```

**For resolve endpoint tests (tests 7–10):**
```python
@patch("services.api_gateway.main.store_incident_memory", new_callable=AsyncMock, return_value="inc-001")
def test_resolve_returns_200(self, mock_store, client):
    response = client.post(
        "/api/v1/incidents/inc-001/resolve",
        json={"summary": "CPU spike caused by runaway process", "resolution": "Restarted service X"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["incident_id"] == "inc-001"
    assert data["memory_id"] == "inc-001"
    assert "resolved_at" in data
```

**For SLO routes (tests 11–15):**
```python
@patch("services.api_gateway.main.create_slo", new_callable=AsyncMock)
def test_create_slo_returns_201(self, mock_create, client):
    mock_create.return_value = {
        "id": "slo-uuid-1",
        "name": "Compute API Availability",
        "domain": "compute",
        "metric": "availability",
        "target_pct": 99.9,
        "window_hours": 24,
        "status": "healthy",
        "current_value": None,
        "error_budget_pct": None,
        "burn_rate_1h": None,
        "burn_rate_15min": None,
        "created_at": "2026-04-03T00:00:00Z",
        "updated_at": "2026-04-03T00:00:00Z",
    }
    response = client.post("/api/v1/slos", json={
        "name": "Compute API Availability",
        "domain": "compute",
        "metric": "availability",
        "target_pct": 99.9,
        "window_hours": 24,
    })
    assert response.status_code == 201
    assert response.json()["id"] == "slo-uuid-1"
```

---

## Acceptance Criteria

### Migrations
- [ ] `incident_memory` table migration in `_run_startup_migrations` (idempotent `CREATE TABLE IF NOT EXISTS`)
- [ ] `slo_definitions` table migration in `_run_startup_migrations` (idempotent)
- [ ] Both include their respective index creation
- [ ] Startup log message updated to mention both new tables

### Imports
- [ ] `search_incident_memory`, `store_incident_memory` imported from `incident_memory`
- [ ] `check_domain_burn_rate_alert`, `create_slo`, `list_slos`, `get_slo_health` imported from `slo_tracker`
- [ ] New models imported from `models`: `HistoricalMatch`, `SLOCreateRequest`, `SLODefinition`, `SLOHealth`

### SLO escalation
- [ ] `check_domain_burn_rate_alert(payload.domain)` called in `ingest_incident` when `_composite_severity != "Sev0"`
- [ ] On alert: `_composite_severity = "Sev0"`, `_slo_escalated = True`
- [ ] SLO check failure is non-fatal (try/except → log warning → continue)
- [ ] `slo_escalated` patched onto Cosmos incident doc alongside `composite_severity`

### BackgroundTask
- [ ] `_attach_historical_matches` defined as module-level async function in `main.py`
- [ ] `background_tasks.add_task(_attach_historical_matches, ...)` called in `ingest_incident`
- [ ] `_attach_historical_matches` patches `historical_matches` onto Cosmos incident doc
- [ ] Failure in `_attach_historical_matches` is non-fatal (try/except → log warning)

### Resolve endpoint
- [ ] `POST /api/v1/incidents/{incident_id}/resolve` exists and returns `{ incident_id, memory_id, resolved_at }`
- [ ] Returns 404 when incident not found in Cosmos
- [ ] Returns 503 when Cosmos not configured
- [ ] Returns 503 when `IncidentMemoryUnavailableError` raised by `store_incident_memory`
- [ ] Cosmos `status` patched to `"resolved"` after successful memory storage
- [ ] Cosmos `patch_item` failure for status update is logged as warning but does NOT fail the request

### SLO routes
- [ ] `POST /api/v1/slos` → 201, returns `SLODefinition`
- [ ] `GET /api/v1/slos` → 200, returns `list[SLODefinition]` (with optional `?domain=` filter)
- [ ] `GET /api/v1/slos/{slo_id}/health` → 200, returns `SLOHealth`; 404 on `KeyError`; 503 on `SLOTrackerUnavailableError`

### Tests
- [ ] 15 integration tests, all passing
- [ ] Tests follow the exact fixture + mock pattern from `test_change_correlator_wiring.py`
- [ ] No real DB connections in tests — all `asyncpg` / Cosmos calls mocked

---

## Incident Status Flow Update (documentation)

After this plan, the incident status lifecycle is:

```
new → evidence_ready → investigating → resolved  (operator-triggered via POST .../resolve)
                                      → closed   (system-triggered)
                    → suppressed_cascade         (noise reducer)
                    → correlated                 (noise reducer)
```

`resolved` differs from `closed`:
- `resolved`: operator confirmed root cause and resolution; embedding stored in `incident_memory`
- `closed`: system-triggered (e.g. alert auto-resolved in Azure Monitor)

---

## Reminders

- Read `main.py` before any edits — it is ~1084 lines, respect all existing patterns
- Add `_slo_escalated: bool = False` before the SLO check block so it is always defined, even if the `if` branch is skipped
- The `check_domain_burn_rate_alert` import goes at the top of `main.py` (module-level), not inside `ingest_incident`
- `_attach_historical_matches` must be defined BEFORE `ingest_incident` in the file (Python requires functions to be defined before reference in async contexts)
- All new endpoints require `Depends(verify_token)` — no unauthenticated routes
- Do not introduce new environment variables; use `COSMOS_DB_NAME` (already used) for the Cosmos DB name
