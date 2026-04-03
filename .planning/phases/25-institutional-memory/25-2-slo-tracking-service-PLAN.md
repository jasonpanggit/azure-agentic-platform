# Plan 25-2: SLO Tracking Service

**Phase:** 25 — Institutional Memory and SLO Tracking
**Wave:** 1 (independent — no dependency on 25-1)
**Requirement:** INTEL-004 (SLO breach prediction alerts fire before threshold is crossed)
**Autonomous:** true

---

## Goal

Create `services/api-gateway/slo_tracker.py` — SLODefinition CRUD, error budget computation, and burn-rate alert detection. Add `SLODefinition` and `SLOHealth` Pydantic models to `models.py`. No HTTP routes yet — that is Wave 2 (25-3).

---

## Files Changed

| File | Action |
|------|--------|
| `services/api-gateway/models.py` | Add `SLODefinition`, `SLOHealth`, `SLOCreateRequest` |
| `services/api-gateway/slo_tracker.py` | Create new module |
| `services/api-gateway/tests/test_slo_tracker.py` | Create unit tests |

---

## Step 1 — Add SLO models to `models.py`

Append after `AuditExportResponse` at the bottom of `models.py`:

### `SLODefinition`

```python
class SLODefinition(BaseModel):
    """A Service Level Objective definition with current health metrics (INTEL-004)."""

    id: str = Field(..., description="Unique SLO identifier (UUID)")
    name: str = Field(..., description="Human-readable SLO name, e.g. 'Compute API Availability'")
    domain: str = Field(..., description="Domain this SLO applies to (compute, network, etc.)")
    metric: str = Field(
        ..., description="Metric type: error_rate | latency_p99 | availability"
    )
    target_pct: float = Field(..., description="Target percentage, e.g. 99.9")
    window_hours: int = Field(..., description="Rolling evaluation window in hours")
    current_value: Optional[float] = Field(
        default=None, description="Last measured metric value"
    )
    error_budget_pct: Optional[float] = Field(
        default=None,
        description="Remaining error budget as percentage: (current_value / target_pct) * 100",
    )
    burn_rate_1h: Optional[float] = Field(
        default=None, description="Error budget consumption rate over last 1 hour"
    )
    burn_rate_15min: Optional[float] = Field(
        default=None, description="Error budget consumption rate over last 15 minutes"
    )
    status: str = Field(
        default="healthy",
        description="healthy | burn_rate_alert | budget_exhausted",
    )
    created_at: Optional[str] = Field(default=None, description="ISO 8601 creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="ISO 8601 last-updated timestamp")
```

### `SLOHealth`

```python
class SLOHealth(BaseModel):
    """SLO health snapshot returned by GET /api/v1/slos/{slo_id}/health (INTEL-004)."""

    slo_id: str
    status: str  # healthy | burn_rate_alert | budget_exhausted
    error_budget_pct: Optional[float] = None
    burn_rate_1h: Optional[float] = None
    burn_rate_15min: Optional[float] = None
    alert: bool = Field(
        ...,
        description="True when burn_rate_1h > 2.0 OR burn_rate_15min > 3.0",
    )
```

### `SLOCreateRequest`

```python
class SLOCreateRequest(BaseModel):
    """Request body for POST /api/v1/slos."""

    name: str = Field(..., min_length=1)
    domain: str = Field(..., description="compute | network | storage | security | arc | sre")
    metric: str = Field(..., description="error_rate | latency_p99 | availability")
    target_pct: float = Field(..., gt=0.0, le=100.0)
    window_hours: int = Field(..., gt=0)
```

---

## Step 2 — Create `services/api-gateway/slo_tracker.py`

### Module structure

```
slo_tracker.py
├── Constants / config
├── SLOTrackerUnavailableError
├── create_slo(name, domain, metric, target_pct, window_hours) -> dict
├── list_slos(domain=None) -> list[dict]
├── get_slo_health(slo_id) -> dict
├── update_slo_metrics(slo_id, current_value) -> dict
├── check_domain_burn_rate_alert(domain) -> bool
└── (private) _compute_status(burn_rate_1h, burn_rate_15min, error_budget_pct) -> str
```

### Error class

```python
class SLOTrackerUnavailableError(RuntimeError):
    """Raised when the SLO tracking database is unavailable."""
```

### Burn-rate alert thresholds (constants)

```python
BURN_RATE_1H_THRESHOLD = 2.0    # Google SRE book, Chapter 5
BURN_RATE_15MIN_THRESHOLD = 3.0
```

### `create_slo` signature

```python
async def create_slo(
    name: str,
    domain: str,
    metric: str,
    target_pct: float,
    window_hours: int,
) -> dict:
    """Insert a new SLO definition into the slo_definitions table.

    Returns:
        Full SLODefinition dict with generated UUID id and timestamps.

    Raises:
        SLOTrackerUnavailableError: if postgres is unreachable.
    """
```

Key implementation details:
- Generate `id = str(uuid.uuid4())`
- Import `resolve_postgres_dsn` from `services.api_gateway.runbook_rag` (shared DSN resolution)
- `asyncpg` imported lazily inside the function body
- SQL: `INSERT INTO slo_definitions (id, name, domain, metric, target_pct, window_hours, status) VALUES ($1, $2, $3, $4, $5, $6, 'healthy') RETURNING *`
- Use `conn.fetchrow(...)` and convert to dict via `dict(row)`
- `created_at` and `updated_at` come from `RETURNING *` (the DEFAULT NOW() in the table)
- Return the full row as dict (timestamps as `.isoformat()` strings)

### `list_slos` signature

```python
async def list_slos(domain: Optional[str] = None) -> list[dict]:
    """List all SLO definitions, optionally filtered by domain.

    Returns:
        List of SLODefinition dicts.

    Returns [] when postgres is not configured (non-fatal).
    """
```

Key implementation details:
- If `domain` provided: `SELECT * FROM slo_definitions WHERE domain = $1 ORDER BY name`
- Else: `SELECT * FROM slo_definitions ORDER BY domain, name`
- Each row converted to dict; `created_at` / `updated_at` → `.isoformat()`
- Catch `SLOTrackerUnavailableError` → log warning → return `[]`

### `get_slo_health` signature

```python
async def get_slo_health(slo_id: str) -> dict:
    """Get the current health snapshot for a single SLO.

    Returns:
        SLOHealth dict: slo_id, status, error_budget_pct, burn_rate_1h,
        burn_rate_15min, alert (bool)

    Raises:
        KeyError: if slo_id does not exist.
        SLOTrackerUnavailableError: if postgres is unreachable.
    """
```

Key implementation details:
- `SELECT * FROM slo_definitions WHERE id = $1`
- Raises `KeyError(slo_id)` when `fetchrow` returns `None`
- `alert = (burn_rate_1h or 0) > BURN_RATE_1H_THRESHOLD or (burn_rate_15min or 0) > BURN_RATE_15MIN_THRESHOLD`

### `update_slo_metrics` signature

```python
async def update_slo_metrics(
    slo_id: str,
    current_value: float,
    burn_rate_1h: Optional[float] = None,
    burn_rate_15min: Optional[float] = None,
) -> dict:
    """Update the current metric value and recompute error budget + status.

    Error budget formula:
        error_budget_pct = (current_value / target_pct) * 100

    Status logic (applied in order):
        1. error_budget_pct <= 0.0 → 'budget_exhausted'
        2. burn_rate_1h > 2.0 OR burn_rate_15min > 3.0 → 'burn_rate_alert'
        3. else → 'healthy'

    Returns:
        Updated SLODefinition dict.

    Raises:
        KeyError: if slo_id does not exist.
        SLOTrackerUnavailableError: if postgres is unreachable.
    """
```

Key implementation details:
- First `SELECT target_pct FROM slo_definitions WHERE id = $1` to get target
- Raises `KeyError(slo_id)` if not found
- Compute `error_budget_pct = (current_value / target_pct) * 100` — pure arithmetic, no side effects
- Compute `status = _compute_status(burn_rate_1h, burn_rate_15min, error_budget_pct)`
- `UPDATE slo_definitions SET current_value=$2, error_budget_pct=$3, burn_rate_1h=$4, burn_rate_15min=$5, status=$6, updated_at=NOW() WHERE id=$1 RETURNING *`
- Return full updated row as dict

### `check_domain_burn_rate_alert` signature

```python
async def check_domain_burn_rate_alert(domain: str) -> bool:
    """Return True if ANY SLO for the given domain is in burn_rate_alert or budget_exhausted state.

    Used by ingest_incident to decide whether to escalate to Sev0 (INTEL-004).

    Returns:
        True → domain has an active SLO burn-rate or budget alert.
        False → all SLOs healthy, or no SLOs defined, or postgres unavailable.

    Never raises — always returns bool (non-fatal for incident ingestion).
    """
```

Key implementation details:
- `SELECT COUNT(*) FROM slo_definitions WHERE domain = $1 AND status IN ('burn_rate_alert', 'budget_exhausted')`
- If count > 0 → return `True`
- Catch all exceptions → log warning → return `False` (must never block incident ingestion)

### `_compute_status` (private)

```python
def _compute_status(
    burn_rate_1h: Optional[float],
    burn_rate_15min: Optional[float],
    error_budget_pct: Optional[float],
) -> str:
    """Compute SLO status string from metric values. Pure function, no DB."""
    if error_budget_pct is not None and error_budget_pct <= 0.0:
        return "budget_exhausted"
    if (burn_rate_1h or 0.0) > BURN_RATE_1H_THRESHOLD:
        return "burn_rate_alert"
    if (burn_rate_15min or 0.0) > BURN_RATE_15MIN_THRESHOLD:
        return "burn_rate_alert"
    return "healthy"
```

This is a pure function — test it directly without any DB mocking.

---

## Step 3 — Unit Tests: `services/api-gateway/tests/test_slo_tracker.py`

**Minimum:** 10 tests. Target: 14.

### Mock pattern for DB connection

```python
@pytest.fixture()
def mock_conn():
    conn = AsyncMock()
    conn.close = AsyncMock()
    return conn

@pytest.fixture(autouse=True)
def patch_asyncpg(mock_conn, monkeypatch):
    asyncpg_mod = types.ModuleType("asyncpg")
    asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
    sys.modules["asyncpg"] = asyncpg_mod
    yield asyncpg_mod
```

### Test list

| # | Test name | What it verifies |
|---|-----------|-----------------|
| 1 | `test_compute_status_healthy` | `burn_rate_1h=1.0, burn_rate_15min=1.0, error_budget_pct=50.0` → `"healthy"` |
| 2 | `test_compute_status_burn_rate_1h_alert` | `burn_rate_1h=2.1` → `"burn_rate_alert"` |
| 3 | `test_compute_status_burn_rate_15min_alert` | `burn_rate_15min=3.1` → `"burn_rate_alert"` |
| 4 | `test_compute_status_budget_exhausted` | `error_budget_pct=-5.0` → `"budget_exhausted"` |
| 5 | `test_compute_status_budget_exhausted_takes_priority` | `error_budget_pct=-1.0, burn_rate_1h=5.0` → `"budget_exhausted"` (budget_exhausted has priority) |
| 6 | `test_create_slo_returns_dict_with_id` | `create_slo(...)` returns dict containing `id`, `name`, `domain`, `status="healthy"` |
| 7 | `test_create_slo_executes_insert_sql` | `conn.fetchrow` called with SQL containing `INSERT INTO slo_definitions` |
| 8 | `test_update_slo_metrics_computes_error_budget` | `current_value=99.95, target_pct=99.9` → `error_budget_pct ≈ 100.05` |
| 9 | `test_update_slo_metrics_sets_burn_rate_alert_status` | `burn_rate_1h=2.5` → status in returned dict is `"burn_rate_alert"` |
| 10 | `test_check_domain_burn_rate_alert_returns_true` | `fetchrow` returns `{"count": 1}` → `check_domain_burn_rate_alert("compute")` returns `True` |
| 11 | `test_check_domain_burn_rate_alert_returns_false_on_zero` | `fetchrow` returns `{"count": 0}` → returns `False` |
| 12 | `test_check_domain_burn_rate_alert_returns_false_on_db_error` | DB raises exception → returns `False` (non-fatal) |
| 13 | `test_list_slos_returns_empty_when_unavailable` | `resolve_postgres_dsn` raises `RunbookSearchUnavailableError` → returns `[]` |
| 14 | `test_get_slo_health_raises_keyerror_for_unknown_id` | `fetchrow` returns `None` → raises `KeyError` |

### Notes on test 8 (error budget math)

```python
# current_value=99.95, target_pct=99.9
# error_budget_pct = (99.95 / 99.9) * 100 = 100.05 (above target = healthy)
assert abs(result["error_budget_pct"] - 100.05) < 0.01
```

### Notes on test 5 (priority ordering)

`budget_exhausted` must have higher priority than `burn_rate_alert`. The `_compute_status` function checks budget first:

```python
result = _compute_status(burn_rate_1h=5.0, burn_rate_15min=5.0, error_budget_pct=-1.0)
assert result == "budget_exhausted"
```

---

## Acceptance Criteria

- [ ] `SLODefinition`, `SLOHealth`, `SLOCreateRequest` models in `models.py`
- [ ] `slo_tracker.py` exports: `create_slo`, `list_slos`, `get_slo_health`, `update_slo_metrics`, `check_domain_burn_rate_alert`
- [ ] `_compute_status` is pure (no side effects, no DB calls)
- [ ] `resolve_postgres_dsn` imported from `runbook_rag` — not reimplemented
- [ ] Burn-rate thresholds: `BURN_RATE_1H_THRESHOLD = 2.0`, `BURN_RATE_15MIN_THRESHOLD = 3.0`
- [ ] `check_domain_burn_rate_alert` NEVER raises — always returns bool
- [ ] `list_slos` returns `[]` (non-fatal) when postgres unavailable
- [ ] Error budget formula: `error_budget_pct = (current_value / target_pct) * 100`
- [ ] Status priority: `budget_exhausted` > `burn_rate_alert` > `healthy`
- [ ] 14 unit tests, all passing
- [ ] File is < 250 lines (focused, high cohesion)

---

## Migration SQL (reference for 25-3)

The startup migration for the `slo_definitions` table will be added in Plan 25-3. This plan does NOT modify `main.py`.

```sql
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
CREATE INDEX IF NOT EXISTS slo_definitions_domain_status_idx
  ON slo_definitions (domain, status);
```

---

## Reminders

- `from __future__ import annotations` at top of new file
- All function signatures include type annotations
- Use `logging.getLogger(__name__)` — no `print()` statements
- `asyncpg` is a lazy import inside function bodies so the module can be imported in tests without the package
- Immutability: build new dicts for results; never mutate asyncpg `Record` objects
- `uuid` is in stdlib — no new dependencies needed
