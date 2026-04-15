---
wave: 2
depends_on: [55-1]
files_modified:
  - services/api-gateway/sla_endpoints.py          # new — SLA CRUD + compliance router
  - services/api-gateway/main.py                    # register sla_router
  - services/api-gateway/tests/test_sla_endpoints.py  # new — 25+ tests
autonomous: true
---

## Goal

Implement the SLA definition CRUD API and the compliance calculation engine that
computes current-period availability attainment per SLA definition.

Routes delivered:
- `POST   /api/v1/admin/sla-definitions`        — create
- `GET    /api/v1/admin/sla-definitions`         — list all (active only by default)
- `GET    /api/v1/admin/sla-definitions/{id}`    — get single
- `PUT    /api/v1/admin/sla-definitions/{id}`    — update
- `DELETE /api/v1/admin/sla-definitions/{id}`    — soft-delete (set `is_active=false`)
- `GET    /api/v1/sla/compliance`               — current-period attainment per SLA

---

## Tasks

<task id="55-2-1">
### Write `services/api-gateway/sla_endpoints.py`

<read_first>
- `services/api-gateway/admin_endpoints.py` — DSN pattern, `_get_pg_connection()`,
  router prefix, `asyncpg.connect(dsn)`, `verify_token` dependency, error handling.
- `services/api-gateway/eol_endpoints.py` — `Optional[X]` type annotation style,
  Pydantic `BaseModel` pattern, graceful fallback on `ImportError`.
- `services/api-gateway/slo_tracker.py` — `resolve_postgres_dsn()` import pattern.
- `services/api-gateway/requirements.txt` — confirm `azure-mgmt-resourcehealth==1.0.0b6`
  is present (it is).
</read_first>

<action>
Create `services/api-gateway/sla_endpoints.py` with the following structure.
Follow these rules exactly:
- All `Optional[X]` annotations (not `X | None`) — Python 3.9 compat.
- Tool functions never raise — return structured error dicts on failure.
- `start_time = time.monotonic()` at entry of compliance calculation; record
  `duration_ms` in both `try` and `except` blocks.
- Guard all SDK imports with `try/except ImportError`.
- No mutation of input dicts — build new dicts for responses.

#### 1. Pydantic models

```python
class SLADefinitionCreate(BaseModel):
    name: str
    target_availability_pct: float          # validated: 0.0–100.0
    covered_resource_ids: list[str] = []
    measurement_period: str = "monthly"
    customer_name: Optional[str] = None
    report_recipients: list[str] = []

class SLADefinitionUpdate(BaseModel):
    name: Optional[str] = None
    target_availability_pct: Optional[float] = None
    covered_resource_ids: Optional[list[str]] = None
    measurement_period: Optional[str] = None
    customer_name: Optional[str] = None
    report_recipients: Optional[list[str]] = None
    is_active: Optional[bool] = None

class SLADefinitionResponse(BaseModel):
    id: str
    name: str
    target_availability_pct: float
    covered_resource_ids: list[str]
    measurement_period: str
    customer_name: Optional[str]
    report_recipients: list[str]
    is_active: bool
    created_at: str
    updated_at: str

class ResourceAttainment(BaseModel):
    resource_id: str
    availability_pct: Optional[float]
    downtime_minutes: Optional[float]
    data_source: str          # "resource_health" | "unavailable"

class SLAComplianceResult(BaseModel):
    sla_id: str
    sla_name: str
    target_availability_pct: float
    attained_availability_pct: Optional[float]
    is_compliant: Optional[bool]
    measurement_period: str
    period_start: str
    period_end: str
    resource_attainments: list[ResourceAttainment]
    data_source: str          # "resource_health" | "partial" | "unavailable"
    duration_ms: float

class SLAComplianceResponse(BaseModel):
    results: list[SLAComplianceResult]
    computed_at: str
```

#### 2. Two APIRouters

```python
admin_sla_router = APIRouter(prefix="/api/v1/admin", tags=["admin-sla"])
sla_router       = APIRouter(prefix="/api/v1/sla",   tags=["sla"])
```

#### 3. Admin CRUD endpoints (`admin_sla_router`)

**POST `/sla-definitions`** — create
- Validate `target_availability_pct` in (0.0, 100.0]; raise HTTP 422 if outside.
- INSERT INTO sla_definitions returning all columns.
- Return `SLADefinitionResponse`.

**GET `/sla-definitions`** — list
- Query param `include_inactive: bool = False`.
- SELECT * WHERE `is_active = TRUE` (or all if `include_inactive=True`).
- Return `{"items": [...], "total": N}`.

**GET `/sla-definitions/{sla_id}`** — get single
- Validate UUID format; raise 422 if malformed.
- SELECT by id; raise HTTP 404 if not found.

**PUT `/sla-definitions/{sla_id}`** — update
- Build SET clause only for non-None fields in `SLADefinitionUpdate`.
- Always SET `updated_at = now()`.
- Raise 404 if not found.

**DELETE `/sla-definitions/{sla_id}`** — soft delete
- UPDATE sla_definitions SET is_active = false, updated_at = now() WHERE id = $1.
- Raise 404 if row not found.
- Return `{"deleted": true, "id": sla_id}`.

All admin endpoints: `Depends(verify_token)`.

#### 4. Compliance endpoint (`sla_router`)

**GET `/compliance`**
- No auth required (read-only operational data).
- Load all `is_active = TRUE` SLA definitions from Postgres.
- For each SLA, call `_calculate_compliance(sla_row)`.
- Return `SLAComplianceResponse`.

#### 5. Compliance calculation helper `_calculate_compliance(sla_row)`

```
Algorithm:
1. Determine period_start / period_end for current calendar month
   (UTC: first second of current month → now()).
2. For each resource_id in sla_row["covered_resource_ids"]:
   a. Call ResourceHealthClient.availability_statuses.list(resource_uri)
      using DefaultAzureCredential.
   b. Walk the paged results; for each status entry within the period:
      - "Available"     → no downtime
      - "Unavailable"   → add (occurrenceTime to next status or now) minutes
      - "Degraded"      → add half of that window as downtime (conservative)
      - "Unknown"       → skip (treat as available)
   c. availability_pct = (total_period_minutes - downtime_minutes)
                          / total_period_minutes * 100
   d. If ResourceHealthClient is unavailable or raises, set data_source =
      "unavailable", availability_pct = None.
3. Aggregate across resources: mean of per-resource availability_pct values
   (skip None values; if all None → attained = None, data_source = "unavailable").
4. is_compliant = (attained_availability_pct is not None and
                   attained_availability_pct >= sla_row["target_availability_pct"])
5. Record duration_ms.
```

Guard the entire ResourceHealth block with `try/except Exception` — compliance
calculation must NEVER raise; return partial/unavailable data instead.

Azure SDK guard at module top:
```python
try:
    from azure.mgmt.resourcehealth import ResourceHealthClient
    from azure.identity import DefaultAzureCredential as _DefaultAzureCredential
except ImportError:
    ResourceHealthClient = None       # type: ignore[assignment,misc]
    _DefaultAzureCredential = None    # type: ignore[assignment,misc]
```

#### 6. Helper `_row_to_response(row) -> dict`

Convert asyncpg Record to dict, converting UUID → str and datetime → ISO string.
Return a new dict (no mutation of `row`).
</action>

<acceptance_criteria>
1. `grep -n "admin_sla_router\|sla_router" services/api-gateway/sla_endpoints.py`
   shows both routers defined.
2. `grep -n "POST\|GET\|PUT\|DELETE" services/api-gateway/sla_endpoints.py`
   shows all 6 route decorators.
3. `grep -n "Depends(verify_token)" services/api-gateway/sla_endpoints.py`
   appears on all 5 admin routes (POST, GET list, GET single, PUT, DELETE).
4. `grep -n "_calculate_compliance" services/api-gateway/sla_endpoints.py`
   shows the function is defined and called from `GET /compliance`.
5. `grep -n "start_time = time.monotonic" services/api-gateway/sla_endpoints.py`
   appears in `_calculate_compliance`.
6. `grep -n "try:" services/api-gateway/sla_endpoints.py | wc -l` ≥ 6
   (ResourceHealth guarded, each DB call guarded).
7. `grep -n "ResourceHealthClient = None" services/api-gateway/sla_endpoints.py`
   shows graceful SDK guard.
8. `python -m py_compile services/api-gateway/sla_endpoints.py && echo PASS`
</acceptance_criteria>
</task>

<task id="55-2-2">
### Register routers in `main.py`

<read_first>
- `services/api-gateway/main.py` lines 129–134 (existing router imports) and
  lines 569–586 (existing `app.include_router(...)` block).
</read_first>

<action>
1. Add two import lines after the `admin_router` import (line ~135):
   ```python
   from services.api_gateway.sla_endpoints import (
       admin_sla_router,
       sla_router as sla_compliance_router,
   )
   ```
2. Add two `app.include_router(...)` calls after `app.include_router(admin_router)`:
   ```python
   app.include_router(admin_sla_router)
   app.include_router(sla_compliance_router)
   ```
   No other lines in `main.py` should be changed.
</action>

<acceptance_criteria>
1. `grep -n "admin_sla_router\|sla_compliance_router" services/api-gateway/main.py`
   shows both the import and the `include_router` call.
2. `python -m py_compile services/api-gateway/main.py && echo PASS`
</acceptance_criteria>
</task>

<task id="55-2-3">
### Write tests `test_sla_endpoints.py` (25+ tests)

<read_first>
- `services/api-gateway/tests/test_admin_endpoints.py` — `_FakeRecord`, fixture
  pattern (`@pytest.fixture`), `TestClient`, `AsyncMock` / `MagicMock`,
  `patch("services.api_gateway.admin_endpoints._get_pg_connection", ...)`.
- `services/api-gateway/tests/conftest.py` — shared fixtures if any.
</read_first>

<action>
Create `services/api-gateway/tests/test_sla_endpoints.py` covering the following
test groups.  All tests must be independent (no shared mutable state) and use
`unittest.mock.patch` / `AsyncMock` so they run without a live database or Azure
subscription.

**Group A — Admin CRUD (15 tests)**

| # | Test name | What it asserts |
|---|-----------|-----------------|
| 1 | `test_create_sla_definition_success` | POST returns 200 with `id` field |
| 2 | `test_create_sla_duplicate_name_422` | DB unique violation → 409 Conflict |
| 3 | `test_create_sla_invalid_target_pct_over_100` | 422 Unprocessable |
| 4 | `test_create_sla_invalid_target_pct_zero` | 422 Unprocessable |
| 5 | `test_list_sla_definitions_default_active_only` | Returns only `is_active=True` rows |
| 6 | `test_list_sla_definitions_include_inactive` | `?include_inactive=true` returns all |
| 7 | `test_list_sla_empty_db` | Returns `{"items": [], "total": 0}` |
| 8 | `test_get_sla_definition_success` | 200 with full row |
| 9 | `test_get_sla_definition_not_found` | 404 |
| 10 | `test_get_sla_definition_invalid_uuid` | 422 |
| 11 | `test_update_sla_name_only` | Only `name` + `updated_at` changed |
| 12 | `test_update_sla_target_pct` | `target_availability_pct` updated |
| 13 | `test_update_sla_not_found` | 404 |
| 14 | `test_delete_sla_soft_delete` | Returns `{"deleted": true}` |
| 15 | `test_delete_sla_not_found` | 404 |

**Group B — Compliance calculation (8 tests)**

| # | Test name | What it asserts |
|---|-----------|-----------------|
| 16 | `test_compliance_empty_sla_list` | Returns `{"results": [], "computed_at": ...}` |
| 17 | `test_compliance_all_available_resource` | `attained_availability_pct` = 100.0, `is_compliant=True` |
| 18 | `test_compliance_fully_unavailable_resource` | `attained_availability_pct` < `target`, `is_compliant=False` |
| 19 | `test_compliance_partial_downtime` | Correct pro-rata minutes calculation |
| 20 | `test_compliance_resource_health_sdk_unavailable` | `data_source="unavailable"`, no exception raised |
| 21 | `test_compliance_resource_health_exception` | Exception inside SDK call caught; `data_source="unavailable"` |
| 22 | `test_compliance_multiple_slas` | Returns one result per SLA |
| 23 | `test_compliance_duration_ms_recorded` | `duration_ms` > 0 in each result |

**Group C — Edge / integration (4 tests)**

| # | Test name | What it asserts |
|---|-----------|-----------------|
| 24 | `test_create_then_list_roundtrip` | Item created appears in list |
| 25 | `test_create_then_delete_then_list` | Deleted item absent from active list |
| 26 | `test_compliance_db_unavailable_returns_503` | Postgres down → HTTP 503 with `detail` key |
| 27 | `test_compliance_no_covered_resources` | SLA with empty `covered_resource_ids` → `attained=None`, no crash |

Minimum: **25 tests** passing.  Tests must NOT import from `main.py` directly;
use `from services.api_gateway.sla_endpoints import admin_sla_router, sla_router`
and mount on a fresh `FastAPI()` app in each fixture.
</action>

<acceptance_criteria>
1. File exists at `services/api-gateway/tests/test_sla_endpoints.py`.
2. `grep -c "^def test_\|^async def test_" services/api-gateway/tests/test_sla_endpoints.py`
   outputs ≥ 25.
3. `python -m pytest services/api-gateway/tests/test_sla_endpoints.py -v --tb=short 2>&1 | tail -5`
   shows 0 failures, 0 errors.
4. No test imports from `main` — verified by:
   `grep "from.*main" services/api-gateway/tests/test_sla_endpoints.py` returns nothing.
</acceptance_criteria>
</task>

---

## Verification

```bash
# 1. Both routers present in sla_endpoints.py
grep -n "admin_sla_router\|sla_router" services/api-gateway/sla_endpoints.py

# 2. All 6 routes present
grep -n "@admin_sla_router\|@sla_router" services/api-gateway/sla_endpoints.py

# 3. Routers registered in main.py
grep -n "admin_sla_router\|sla_compliance_router" services/api-gateway/main.py

# 4. Syntax OK
python -m py_compile services/api-gateway/sla_endpoints.py && echo "sla_endpoints OK"
python -m py_compile services/api-gateway/main.py && echo "main OK"

# 5. Test count
grep -c "^def test_\|^async def test_" services/api-gateway/tests/test_sla_endpoints.py

# 6. Full test run
python -m pytest services/api-gateway/tests/test_sla_endpoints.py -v --tb=short

# 7. Verify no regression in existing admin tests
python -m pytest services/api-gateway/tests/test_admin_endpoints.py -v --tb=short
```

---

## must_haves

- [ ] `target_availability_pct` validated: must be > 0.0 and ≤ 100.0 (HTTP 422 otherwise)
- [ ] All 5 admin routes protected by `Depends(verify_token)`
- [ ] `GET /compliance` returns HTTP 503 (not 500) when Postgres is down — so the UI can show a graceful empty state
- [ ] Compliance calculation never raises — all SDK / DB exceptions caught, `data_source="unavailable"` returned
- [ ] `duration_ms` field populated on every `SLAComplianceResult`
- [ ] `_row_to_response()` creates a new dict — no mutation of asyncpg `Record`
- [ ] 25+ tests, all passing
- [ ] `python -m py_compile` passes on both `sla_endpoints.py` and `main.py`
