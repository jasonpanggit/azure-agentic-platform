---
wave: 1
status: complete
---

## Summary

Created `services/api-gateway/migrations/006_create_sla_definitions.py`.

**Table:** `sla_definitions` — customer-facing SLA contracts
- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `name TEXT NOT NULL UNIQUE`
- `target_availability_pct NUMERIC(6,3) NOT NULL` — supports 99.9 to 100.000 precision
- `covered_resource_ids TEXT[] NOT NULL DEFAULT '{}'`
- `measurement_period TEXT NOT NULL DEFAULT 'monthly'`
- `customer_name TEXT` (nullable)
- `report_recipients TEXT[] NOT NULL DEFAULT '{}'`
- `is_active BOOLEAN NOT NULL DEFAULT TRUE`
- `created_at / updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

**Index:** `idx_sla_definitions_active ON sla_definitions (is_active)`

Migration is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).
`__main__` block uses `resolve_postgres_dsn()` — consistent with rest of gateway.

**Verification:** All 9 checks passed (file, table name, NUMERIC(6,3), DOWN_SQL, up/down fns, DSN helper, index, py_compile).
