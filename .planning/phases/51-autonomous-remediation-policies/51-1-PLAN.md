# Plan 51-1: PostgreSQL Migration + Pydantic Models + CRUD API Router

---
wave: 1
depends_on: []
files_modified:
  - services/api-gateway/migrations/005_create_remediation_policies_table.py
  - services/api-gateway/models.py
  - services/api-gateway/admin_endpoints.py
  - services/api-gateway/main.py
  - services/api-gateway/requirements.txt
  - services/api-gateway/tests/test_admin_endpoints.py
autonomous: true
---

<threat_model>
## Threat Model

**Assets:** Remediation policy configuration data; API gateway admin endpoints

**Threat actors:**
- Unauthorized operators attempting to create permissive auto-approval policies
- Attackers exploiting unvalidated CRUD inputs (SQL injection, JSONB injection)

**Key risks and mitigations:**
1. **SQL injection via policy fields** — MITIGATED: asyncpg parameterized queries ($1, $2 placeholders), Pydantic validation on all inputs
2. **Unauthorized policy creation** — MITIGATED: All admin endpoints require `Depends(verify_token)` (Entra ID Bearer token)
3. **Overly permissive policies** — MITIGATED: `max_blast_radius` has hard ceiling of 50 (matches `_run_preflight()` limit), `max_daily_executions` capped at 100, `action_class` validated against SAFE_ARM_ACTIONS
4. **JSONB tag filter injection** — MITIGATED: `resource_tag_filter` is a Pydantic `dict[str, str]` — serialized to JSONB via asyncpg, no string interpolation
</threat_model>

## Goal

Create the PostgreSQL table for remediation policies, define all Pydantic models, and implement the full CRUD API router (`admin_endpoints.py`) mounted at `/api/v1/admin`.

## Tasks

<task id="51-1-01">
<title>Create PostgreSQL migration 005</title>
<read_first>
- services/api-gateway/migrations/003_create_sops_table.py
- services/api-gateway/main.py (lines 142-270 — _run_startup_migrations)
</read_first>
<action>
Create `services/api-gateway/migrations/005_create_remediation_policies_table.py` following the migration 003 pattern.

The file must contain:

```python
UP_SQL = """
CREATE TABLE IF NOT EXISTS remediation_policies (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL UNIQUE,
    description             TEXT,
    action_class            TEXT NOT NULL,
    resource_tag_filter     JSONB DEFAULT '{}',
    max_blast_radius        INT DEFAULT 10,
    max_daily_executions    INT DEFAULT 20,
    require_slo_healthy     BOOLEAN DEFAULT true,
    maintenance_window_exempt BOOLEAN DEFAULT false,
    enabled                 BOOLEAN DEFAULT true,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_remediation_policies_action_class
    ON remediation_policies (action_class, enabled);
"""
```

Include `DOWN_SQL` with `DROP TABLE IF EXISTS remediation_policies;`.

Include `async def up(conn)` and `async def down(conn)` functions.

Include `if __name__ == "__main__"` block for standalone execution using `asyncpg.connect(os.environ["DATABASE_URL"])`.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/migrations/005_create_remediation_policies_table.py`
- File contains `CREATE TABLE IF NOT EXISTS remediation_policies`
- File contains `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- File contains `action_class TEXT NOT NULL`
- File contains `resource_tag_filter JSONB DEFAULT '{}'`
- File contains `max_blast_radius INT DEFAULT 10`
- File contains `max_daily_executions INT DEFAULT 20`
- File contains `require_slo_healthy BOOLEAN DEFAULT true`
- File contains `enabled BOOLEAN DEFAULT true`
- File contains `CREATE INDEX IF NOT EXISTS idx_remediation_policies_action_class`
- File contains `async def up(conn)`
- File contains `async def down(conn)`
- `python -c "import ast; ast.parse(open('services/api-gateway/migrations/005_create_remediation_policies_table.py').read())"` exits 0
</acceptance_criteria>
</task>

<task id="51-1-02">
<title>Add remediation_policies table to startup migrations</title>
<read_first>
- services/api-gateway/main.py (lines 142-270 — _run_startup_migrations)
</read_first>
<action>
Add the `remediation_policies` table creation to `_run_startup_migrations()` in `services/api-gateway/main.py`, after the existing `slo_definitions` table creation (around line 258).

Add the following SQL block:

```python
# remediation_policies table (Phase 51 — Autonomous Remediation)
await conn.execute("""
    CREATE TABLE IF NOT EXISTS remediation_policies (
        id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name                    TEXT NOT NULL UNIQUE,
        description             TEXT,
        action_class            TEXT NOT NULL,
        resource_tag_filter     JSONB DEFAULT '{}',
        max_blast_radius        INT DEFAULT 10,
        max_daily_executions    INT DEFAULT 20,
        require_slo_healthy     BOOLEAN DEFAULT true,
        maintenance_window_exempt BOOLEAN DEFAULT false,
        enabled                 BOOLEAN DEFAULT true,
        created_at              TIMESTAMPTZ DEFAULT now(),
        updated_at              TIMESTAMPTZ DEFAULT now()
    );
""")
await conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_remediation_policies_action_class "
    "ON remediation_policies (action_class, enabled);"
)
```

Update the final `logger.info()` message to include `remediation_policies`:
```python
logger.info(
    "Startup migrations complete "
    "(pgvector + runbooks + eol_cache + incident_memory + slo_definitions + remediation_policies)"
)
```
</action>
<acceptance_criteria>
- `services/api-gateway/main.py` contains `CREATE TABLE IF NOT EXISTS remediation_policies`
- `services/api-gateway/main.py` contains `idx_remediation_policies_action_class`
- `services/api-gateway/main.py` contains string `remediation_policies)` in the startup log message
</acceptance_criteria>
</task>

<task id="51-1-03">
<title>Add Pydantic models for remediation policies</title>
<read_first>
- services/api-gateway/models.py
</read_first>
<action>
Add the following Pydantic models to `services/api-gateway/models.py` after the `BusinessTiersResponse` class:

```python
class AutoRemediationPolicy(BaseModel):
    """An auto-approval policy for known-safe remediation actions (Phase 51)."""

    id: str = Field(..., description="Policy UUID")
    name: str = Field(..., description="Human-readable policy name")
    description: Optional[str] = Field(default=None, description="Policy description")
    action_class: str = Field(..., description="Remediation action class, e.g. 'restart_vm', 'restart_container_app'")
    resource_tag_filter: dict = Field(default_factory=dict, description="Resource tags that must be present for auto-approval, e.g. {'tier': 'dev'}")
    max_blast_radius: int = Field(default=10, description="Max blast-radius size; auto-approval blocked if exceeded", ge=1, le=50)
    max_daily_executions: int = Field(default=20, description="Max auto-executions per day for this policy", ge=1, le=100)
    require_slo_healthy: bool = Field(default=True, description="Block auto-approval if resource health != Available")
    maintenance_window_exempt: bool = Field(default=False, description="Allow auto-execution outside maintenance windows")
    enabled: bool = Field(default=True, description="Whether the policy is active")
    created_at: Optional[str] = Field(default=None, description="ISO 8601 creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="ISO 8601 last-updated timestamp")
    execution_count_today: int = Field(default=0, description="Number of auto-executions today (computed)")
    success_rate: Optional[float] = Field(default=None, description="Success rate of auto-executions (computed)")


class AutoRemediationPolicyCreate(BaseModel):
    """Request body for POST /api/v1/admin/remediation-policies."""

    name: str = Field(..., min_length=1, max_length=200, description="Policy name (must be unique)")
    description: Optional[str] = Field(default=None, max_length=1000)
    action_class: str = Field(..., min_length=1, description="Must match a key in SAFE_ARM_ACTIONS")
    resource_tag_filter: dict = Field(default_factory=dict)
    max_blast_radius: int = Field(default=10, ge=1, le=50)
    max_daily_executions: int = Field(default=20, ge=1, le=100)
    require_slo_healthy: bool = Field(default=True)
    maintenance_window_exempt: bool = Field(default=False)
    enabled: bool = Field(default=True)


class AutoRemediationPolicyUpdate(BaseModel):
    """Request body for PUT /api/v1/admin/remediation-policies/{id}."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    action_class: Optional[str] = Field(default=None, min_length=1)
    resource_tag_filter: Optional[dict] = None
    max_blast_radius: Optional[int] = Field(default=None, ge=1, le=50)
    max_daily_executions: Optional[int] = Field(default=None, ge=1, le=100)
    require_slo_healthy: Optional[bool] = None
    maintenance_window_exempt: Optional[bool] = None
    enabled: Optional[bool] = None


class PolicyExecution(BaseModel):
    """A single auto-execution record for a policy (computed from remediation_audit)."""

    execution_id: str
    resource_id: str
    proposed_action: str
    status: str
    verification_result: Optional[str] = None
    executed_at: str
    duration_ms: Optional[float] = None


class PolicySuggestion(BaseModel):
    """A learning-engine suggestion to create an auto-approval policy (Phase 51)."""

    id: str = Field(..., description="Suggestion UUID")
    action_class: str = Field(..., description="Remediation action class observed")
    resource_pattern: dict = Field(default_factory=dict, description="Common resource tag pattern observed")
    approval_count: int = Field(..., description="Number of HITL approvals observed")
    rollback_count: int = Field(default=0, description="Number of rollbacks observed (should be 0)")
    suggested_at: str = Field(..., description="ISO 8601 timestamp of suggestion creation")
    dismissed: bool = Field(default=False, description="Whether operator dismissed this suggestion")
    converted_to_policy_id: Optional[str] = Field(default=None, description="Policy ID if operator converted this suggestion")
    message: str = Field(..., description="Human-readable suggestion message")
```
</action>
<acceptance_criteria>
- `services/api-gateway/models.py` contains `class AutoRemediationPolicy(BaseModel):`
- `services/api-gateway/models.py` contains `class AutoRemediationPolicyCreate(BaseModel):`
- `services/api-gateway/models.py` contains `class AutoRemediationPolicyUpdate(BaseModel):`
- `services/api-gateway/models.py` contains `class PolicyExecution(BaseModel):`
- `services/api-gateway/models.py` contains `class PolicySuggestion(BaseModel):`
- `services/api-gateway/models.py` contains `max_blast_radius: int = Field(default=10`
- `services/api-gateway/models.py` contains `max_daily_executions: int = Field(default=20`
- `services/api-gateway/models.py` contains `ge=1, le=50` (blast radius ceiling)
- `services/api-gateway/models.py` contains `ge=1, le=100` (daily cap ceiling)
</acceptance_criteria>
</task>

<task id="51-1-04">
<title>Create admin_endpoints.py CRUD router</title>
<read_first>
- services/api-gateway/models.py (AutoRemediationPolicy* models from task 51-1-03)
- services/api-gateway/approvals.py (pattern for Cosmos queries + FastAPI endpoints)
- services/api-gateway/runbook_rag.py (resolve_postgres_dsn function)
- services/api-gateway/remediation_executor.py (SAFE_ARM_ACTIONS dict, lines 31-36)
- services/api-gateway/auth.py (verify_token dependency)
</read_first>
<action>
Create `services/api-gateway/admin_endpoints.py` with a FastAPI `APIRouter` at prefix `/api/v1/admin` with tag `admin`.

The router must include these endpoints:

1. **`GET /api/v1/admin/remediation-policies`** — List all policies from PostgreSQL. For each policy, compute `execution_count_today` by querying Cosmos `remediation_audit` container for records where `auto_approved_by_policy = policy.id` and `executed_at >= today 00:00 UTC`. Return `list[AutoRemediationPolicy]`.

2. **`POST /api/v1/admin/remediation-policies`** — Create a policy. Validate `action_class` against `SAFE_ARM_ACTIONS` keys from `remediation_executor.py`. Insert into PostgreSQL `remediation_policies` table using asyncpg with parameterized query. Return 201 with the created `AutoRemediationPolicy`.

3. **`GET /api/v1/admin/remediation-policies/{policy_id}`** — Get single policy by UUID. Return 404 if not found.

4. **`PUT /api/v1/admin/remediation-policies/{policy_id}`** — Update policy. Only update fields that are not None in `AutoRemediationPolicyUpdate`. Set `updated_at = now()`. Return 404 if not found.

5. **`DELETE /api/v1/admin/remediation-policies/{policy_id}`** — Delete policy. Return 204. Return 404 if not found.

6. **`GET /api/v1/admin/remediation-policies/{policy_id}/executions`** — Return last 10 auto-executions for this policy from Cosmos `remediation_audit` container. Query: `SELECT TOP 10 * FROM c WHERE c.auto_approved_by_policy = @policy_id ORDER BY c.executed_at DESC`. Return `list[PolicyExecution]`.

All endpoints require `Depends(verify_token)`.

PostgreSQL access pattern: use `asyncpg.connect(dsn)` where dsn comes from `resolve_postgres_dsn()` imported from `services.api_gateway.runbook_rag`. Use `try/finally` to close connection.

Cosmos access pattern: use `request.app.state.cosmos_client` for Cosmos queries (same as existing endpoint patterns). Gracefully handle `cosmos_client is None` by returning `execution_count_today=0`.

Import `SAFE_ARM_ACTIONS` from `services.api_gateway.remediation_executor` for action_class validation.

Use `import json` for JSONB serialization of `resource_tag_filter`.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/admin_endpoints.py`
- File contains `APIRouter(prefix="/api/v1/admin", tags=["admin"])`
- File contains `@router.get("/remediation-policies"` (list endpoint)
- File contains `@router.post("/remediation-policies"` (create endpoint)
- File contains `@router.get("/remediation-policies/{policy_id}"` (get single)
- File contains `@router.put("/remediation-policies/{policy_id}"` (update)
- File contains `@router.delete("/remediation-policies/{policy_id}"` (delete)
- File contains `@router.get("/remediation-policies/{policy_id}/executions"` (execution history)
- File contains `Depends(verify_token)` in at least 6 endpoint signatures
- File contains `from services.api_gateway.remediation_executor import SAFE_ARM_ACTIONS`
- File contains `resolve_postgres_dsn` import
- File contains `auto_approved_by_policy` (Cosmos query field)
- `python -c "import ast; ast.parse(open('services/api-gateway/admin_endpoints.py').read())"` exits 0
</acceptance_criteria>
</task>

<task id="51-1-05">
<title>Mount admin_router in main.py</title>
<read_first>
- services/api-gateway/main.py (lines 496-520 — app creation and router mounting)
</read_first>
<action>
In `services/api-gateway/main.py`:

1. Add import at the top (near line 123, after the `subscription_registry` import):
```python
from services.api_gateway.admin_endpoints import router as admin_router
```

2. Mount the router after the existing `app.include_router(aks_router)` line (around line 518):
```python
app.include_router(admin_router)
```

3. Add the new model imports to the existing `from services.api_gateway.models import (...)` block:
```python
AutoRemediationPolicy,
AutoRemediationPolicyCreate,
AutoRemediationPolicyUpdate,
PolicyExecution,
PolicySuggestion,
```
</action>
<acceptance_criteria>
- `services/api-gateway/main.py` contains `from services.api_gateway.admin_endpoints import router as admin_router`
- `services/api-gateway/main.py` contains `app.include_router(admin_router)`
</acceptance_criteria>
</task>

<task id="51-1-06">
<title>Add azure-mgmt-appcontainers to requirements.txt</title>
<read_first>
- services/api-gateway/requirements.txt
</read_first>
<action>
Add the following line to `services/api-gateway/requirements.txt` in the Azure SDK section (after the `azure-mgmt-compute` line):

```
azure-mgmt-appcontainers>=4.0.0
```

This is needed for Plan 51-2 (`restart_container_app` action) but should be in requirements now to avoid import failures when admin_endpoints validates action_class against SAFE_ARM_ACTIONS (which will include `restart_container_app` after 51-2).
</action>
<acceptance_criteria>
- `services/api-gateway/requirements.txt` contains `azure-mgmt-appcontainers>=4.0.0`
</acceptance_criteria>
</task>

<task id="51-1-07">
<title>Write unit tests for admin CRUD endpoints</title>
<read_first>
- services/api-gateway/admin_endpoints.py (from task 51-1-04)
- services/api-gateway/tests/test_remediation_executor.py (test pattern reference)
</read_first>
<action>
Create `services/api-gateway/tests/test_admin_endpoints.py` with at least 10 unit tests:

1. `test_list_policies_empty` — GET /api/v1/admin/remediation-policies returns empty list when no policies exist
2. `test_create_policy_success` — POST with valid `AutoRemediationPolicyCreate` returns 201 + correct fields
3. `test_create_policy_invalid_action_class` — POST with `action_class="nonexistent"` returns 400
4. `test_create_policy_duplicate_name` — POST with duplicate name returns 409
5. `test_get_policy_success` — GET /{policy_id} returns correct policy
6. `test_get_policy_not_found` — GET /{policy_id} with nonexistent UUID returns 404
7. `test_update_policy_success` — PUT /{policy_id} with partial update returns 200 + updated fields
8. `test_update_policy_not_found` — PUT /{policy_id} with nonexistent UUID returns 404
9. `test_delete_policy_success` — DELETE /{policy_id} returns 204
10. `test_delete_policy_not_found` — DELETE /{policy_id} with nonexistent UUID returns 404
11. `test_get_policy_executions_empty` — GET /{policy_id}/executions returns empty list

Use `unittest.mock.patch` to mock:
- `asyncpg.connect` — return a `MagicMock` with `fetch`, `fetchrow`, `execute` methods
- `resolve_postgres_dsn` — return `"postgresql://test:test@localhost/test"`
- `verify_token` — return `{"sub": "test-user"}`
- `request.app.state.cosmos_client` — `MagicMock` or `None`

Use `from fastapi.testclient import TestClient` with the FastAPI app for synchronous testing.

All tests must be async (use `@pytest.mark.asyncio` or test directly via TestClient).
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/tests/test_admin_endpoints.py`
- File contains at least 10 test functions matching `def test_`
- File contains `test_list_policies_empty`
- File contains `test_create_policy_success`
- File contains `test_create_policy_invalid_action_class`
- File contains `test_get_policy_not_found`
- File contains `test_update_policy_success`
- File contains `test_delete_policy_success`
- File contains `test_get_policy_executions_empty`
- `python -m pytest services/api-gateway/tests/test_admin_endpoints.py --tb=short` exits 0
</acceptance_criteria>
</task>

## Verification

After all tasks complete:
- `python -c "import ast; ast.parse(open('services/api-gateway/admin_endpoints.py').read())"` — syntax check
- `python -c "import ast; ast.parse(open('services/api-gateway/migrations/005_create_remediation_policies_table.py').read())"` — migration syntax
- `python -m pytest services/api-gateway/tests/test_admin_endpoints.py -v` — all tests pass
- `grep -c "remediation-policies" services/api-gateway/admin_endpoints.py` — returns ≥6 (one per endpoint)

## must_haves
- [ ] PostgreSQL `remediation_policies` table schema defined with all 12 columns
- [ ] Startup migration creates the table idempotently
- [ ] All 5 Pydantic models added to `models.py`
- [ ] CRUD router mounted at `/api/v1/admin` with 6 endpoints
- [ ] `action_class` validated against `SAFE_ARM_ACTIONS`
- [ ] All endpoints require Entra ID auth (`Depends(verify_token)`)
- [ ] `azure-mgmt-appcontainers>=4.0.0` in requirements.txt
- [ ] ≥10 unit tests passing
