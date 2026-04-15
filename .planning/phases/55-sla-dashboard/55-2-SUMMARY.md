---
wave: 2
status: complete
---

## Summary

Created `services/api-gateway/sla_endpoints.py` and `tests/test_sla_endpoints.py`. Updated `main.py`.

### sla_endpoints.py
**Pydantic models:** `SLADefinitionCreate`, `SLADefinitionUpdate`, `SLADefinitionResponse`, `ResourceAttainment`, `SLAComplianceResult`, `SLAComplianceResponse`

**admin_sla_router** (`/api/v1/admin`), all `Depends(verify_token)`:
- `POST /sla-definitions` — validates `target_availability_pct` in (0.0, 100.0]; 409 on duplicate name
- `GET /sla-definitions` — list active (default) or all (`?include_inactive=true`)
- `GET /sla-definitions/{sla_id}` — get single; 404 if not found; 422 on bad UUID
- `PUT /sla-definitions/{sla_id}` — partial update (only non-None fields); always sets `updated_at`
- `DELETE /sla-definitions/{sla_id}` — soft delete (`is_active=false`); 404 if not found

**sla_router** (`/api/v1/sla`):
- `GET /compliance` — no auth; loads active SLAs, calls `_calculate_compliance()` per SLA; HTTP 503 on Postgres down

**_calculate_compliance:** ResourceHealthClient with `try/except ImportError` guard; Available/Unavailable/Degraded/Unknown parsing; pro-rata minute aggregation; `start_time = time.monotonic()`; `duration_ms` recorded; never raises.

**_row_to_response:** New dict (UUID→str, datetime→ISO); no mutation of asyncpg Record.

### main.py
Added imports and `app.include_router()` calls for both routers.

### Tests
27 tests: 27 passed, 0 failed, 0 errors.
Groups: A (15 CRUD), B (8 compliance), C (4 edge). All mount fresh `FastAPI()` — no `main.py` dependency.
