---
phase: 51-autonomous-remediation-policies
plan: 1
subsystem: api
tags: [postgresql, pydantic, fastapi, asyncpg, crud, remediation, admin]

requires:
  - phase: 27-closed-loop-remediation
    provides: SAFE_ARM_ACTIONS dict, remediation_executor.py, Cosmos remediation_audit container
  - phase: 28-platform-intelligence
    provides: BusinessTiersResponse model (insertion point for new models)
provides:
  - PostgreSQL remediation_policies table with 12-column schema
  - 5 Pydantic models for auto-remediation policy CRUD
  - Admin CRUD router at /api/v1/admin with 6 endpoints
  - action_class validation against SAFE_ARM_ACTIONS
  - Cosmos remediation_audit integration for execution counts
affects: [51-2-safe-actions, 51-3-learning-engine, 51-4-ui-policy-management]

tech-stack:
  added: [azure-mgmt-appcontainers>=4.0.0]
  patterns: [asyncpg parameterized queries, dynamic SET clause builder, JSONB serialization]

key-files:
  created:
    - services/api-gateway/migrations/005_create_remediation_policies_table.py
    - services/api-gateway/admin_endpoints.py
    - services/api-gateway/tests/test_admin_endpoints.py
  modified:
    - services/api-gateway/main.py
    - services/api-gateway/models.py
    - services/api-gateway/requirements.txt

key-decisions:
  - "Dynamic SET clause for partial updates — build parameterized query from non-None fields only"
  - "Cosmos execution_count_today is computed per request, not cached — acceptable for admin endpoint traffic"
  - "JSONB resource_tag_filter stored via json.dumps + $N::jsonb cast — no string interpolation"

patterns-established:
  - "Admin router pattern: prefix=/api/v1/admin, all endpoints guarded by Depends(verify_token)"
  - "PostgreSQL CRUD with asyncpg: _get_pg_connection() + try/finally conn.close()"
  - "_row_to_policy() converter from asyncpg Record to Pydantic model"

requirements-completed: []

duration: 18min
completed: 2026-04-14
---

# Plan 51-1: PostgreSQL Migration + Pydantic Models + CRUD API Router Summary

**Remediation policy CRUD system with PostgreSQL storage, asyncpg parameterized queries, 6 admin endpoints, and 14 unit tests**

## Performance

- **Duration:** 18 min
- **Tasks:** 7
- **Files created:** 3
- **Files modified:** 3

## Accomplishments
- PostgreSQL `remediation_policies` table with 12 columns (UUID PK, JSONB tag filter, blast-radius/daily caps, composite index)
- 5 Pydantic models: AutoRemediationPolicy, AutoRemediationPolicyCreate (with ge/le validation), AutoRemediationPolicyUpdate (partial), PolicyExecution, PolicySuggestion
- Full CRUD router at `/api/v1/admin` with action_class validation against SAFE_ARM_ACTIONS
- 14 unit tests covering all 6 endpoints (list, create, get, update, delete, executions) — all passing

## Task Commits

Each task was committed atomically:

1. **Task 51-1-01: Create PostgreSQL migration 005** - `848aca5` (feat)
2. **Task 51-1-02: Add remediation_policies table to startup migrations** - `d5903b6` (feat)
3. **Task 51-1-03: Add Pydantic models for remediation policies** - `fc4f987` (feat)
4. **Task 51-1-04: Create admin_endpoints.py CRUD router** - `69e85a3` (feat)
5. **Task 51-1-05: Mount admin_router in main.py** - `abbc135` (feat)
6. **Task 51-1-06: Add azure-mgmt-appcontainers to requirements.txt** - `79e870c` (chore)
7. **Task 51-1-07: Write unit tests for admin CRUD endpoints** - `0076b5d` (test)

## Files Created/Modified
- `services/api-gateway/migrations/005_create_remediation_policies_table.py` - Standalone migration with UP/DOWN SQL, async up/down functions
- `services/api-gateway/admin_endpoints.py` - 6-endpoint CRUD router with asyncpg + Cosmos integration
- `services/api-gateway/tests/test_admin_endpoints.py` - 14 unit tests with mocked asyncpg and TestClient
- `services/api-gateway/main.py` - Startup migration for remediation_policies, admin_router mount, model imports
- `services/api-gateway/models.py` - 5 new Pydantic models after BusinessTiersResponse
- `services/api-gateway/requirements.txt` - azure-mgmt-appcontainers>=4.0.0

## Decisions Made
- Dynamic SET clause builder for partial updates avoids N separate update functions
- Cosmos execution_count_today computed per-request (not cached) — admin endpoints are low-traffic
- JSONB resource_tag_filter uses json.dumps + asyncpg $N::jsonb cast — no string interpolation (SQL injection safe)
- asyncpg UniqueViolationError maps to HTTP 409; asyncpg "DELETE 0" result maps to HTTP 404

## Deviations from Plan
None - plan executed exactly as written

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CRUD endpoints ready for Plan 51-2 (safe actions expansion with restart_container_app)
- PolicySuggestion model ready for Plan 51-3 (learning engine)
- Admin endpoints ready for Plan 51-4 (UI policy management tab)

---
*Phase: 51-autonomous-remediation-policies*
*Completed: 2026-04-14*
