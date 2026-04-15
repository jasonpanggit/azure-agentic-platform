---
wave: 1
depends_on: []
files_modified:
  - services/api-gateway/migrations/006_create_sla_definitions.py
autonomous: true
---

## Goal

Create the PostgreSQL migration that introduces the `sla_definitions` table — the
authoritative store for customer-facing SLA contracts.  The migration must be
idempotent (`IF NOT EXISTS`) and follow the exact pattern of
`005_create_remediation_policies_table.py`.

---

## Tasks

<task id="55-1-1">
### Write migration file `006_create_sla_definitions.py`

<read_first>
- `services/api-gateway/migrations/005_create_remediation_policies_table.py`
  — copy the module header, UP_SQL / DOWN_SQL pattern, `up()` / `down()` async
    functions, and the `__main__` block that reads `DATABASE_URL`.
- `services/api-gateway/runbook_rag.py` (lines 1–40) — note `resolve_postgres_dsn()`
  is the canonical DSN helper; the migration `__main__` block should also
  honour `PGVECTOR_CONNECTION_STRING` / `POSTGRES_DSN` as fallbacks by
  calling `resolve_postgres_dsn()` instead of reading `DATABASE_URL` directly,
  consistent with the rest of the gateway.
</read_first>

<action>
Create `services/api-gateway/migrations/006_create_sla_definitions.py` with the
following exact content (do not deviate from naming, column order, or type
precision):

```python
"""Migration 006 — Create sla_definitions table (Phase 55).

Customer-facing SLA contracts.  Each row defines an SLA with target
availability, the Azure resource IDs covered, measurement period, customer
name, and the e-mail addresses to receive monthly reports.

Run:
    python services/api-gateway/migrations/006_create_sla_definitions.py
"""
from __future__ import annotations

UP_SQL = """
CREATE TABLE IF NOT EXISTS sla_definitions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL UNIQUE,
    target_availability_pct NUMERIC(6,3) NOT NULL,
    covered_resource_ids    TEXT[]          NOT NULL DEFAULT '{}',
    measurement_period      TEXT            NOT NULL DEFAULT 'monthly',
    customer_name           TEXT,
    report_recipients       TEXT[]          NOT NULL DEFAULT '{}',
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sla_definitions_active
    ON sla_definitions (is_active);
"""

DOWN_SQL = """
DROP TABLE IF EXISTS sla_definitions;
"""


async def up(conn) -> None:
    """Apply migration 006 — create sla_definitions table."""
    await conn.execute(UP_SQL)


async def down(conn) -> None:
    """Roll back migration 006 — drop sla_definitions table."""
    await conn.execute(DOWN_SQL)


if __name__ == "__main__":
    import asyncio
    import os
    import sys

    # Allow running from repo root: python services/api-gateway/migrations/006_...
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    async def main() -> None:
        import asyncpg
        from services.api_gateway.runbook_rag import resolve_postgres_dsn

        dsn = resolve_postgres_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            await up(conn)
            print("Migration 006 applied successfully.")
        finally:
            await conn.close()

    asyncio.run(main())
```

Exact column spec (must match):
| Column | Type | Constraint |
|---|---|---|
| `id` | `UUID` | PK, `gen_random_uuid()` |
| `name` | `TEXT` | `NOT NULL UNIQUE` |
| `target_availability_pct` | `NUMERIC(6,3)` | `NOT NULL` (allows 99.9 to 100.000) |
| `covered_resource_ids` | `TEXT[]` | `NOT NULL DEFAULT '{}'` |
| `measurement_period` | `TEXT` | `NOT NULL DEFAULT 'monthly'` |
| `customer_name` | `TEXT` | nullable |
| `report_recipients` | `TEXT[]` | `NOT NULL DEFAULT '{}'` |
| `is_active` | `BOOLEAN` | `NOT NULL DEFAULT TRUE` |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT now()` |

Index: `idx_sla_definitions_active ON sla_definitions (is_active)`.
</action>

<acceptance_criteria>
1. File exists at the expected path.
2. `UP_SQL` contains `CREATE TABLE IF NOT EXISTS sla_definitions`.
3. `target_availability_pct NUMERIC(6,3)` appears verbatim.
4. `DOWN_SQL` contains `DROP TABLE IF EXISTS sla_definitions`.
5. `async def up(conn)` and `async def down(conn)` are both present.
6. `__main__` block calls `resolve_postgres_dsn()` (not a hard-coded env var).
7. `idx_sla_definitions_active` index is created in `UP_SQL`.
</acceptance_criteria>
</task>

---

## Verification

```bash
# 1. File exists
test -f services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: file exists"

# 2. Table name in UP_SQL
grep -q "CREATE TABLE IF NOT EXISTS sla_definitions" \
  services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: table name"

# 3. NUMERIC(6,3) precision
grep -q "NUMERIC(6,3)" \
  services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: numeric precision"

# 4. DOWN_SQL
grep -q "DROP TABLE IF EXISTS sla_definitions" \
  services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: down sql"

# 5. async functions
grep -q "async def up" services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: up fn"
grep -q "async def down" services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: down fn"

# 6. DSN helper
grep -q "resolve_postgres_dsn" services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: dsn helper"

# 7. Index
grep -q "idx_sla_definitions_active" services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: index"

# 8. Python syntax check
python -m py_compile services/api-gateway/migrations/006_create_sla_definitions.py && echo "PASS: syntax ok"
```

---

## must_haves

- [ ] Migration is idempotent — `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`
- [ ] `target_availability_pct` uses `NUMERIC(6,3)` (not FLOAT — precision required for ±0.01% success metric)
- [ ] `DOWN_SQL` fully reverses `UP_SQL`
- [ ] `__main__` uses `resolve_postgres_dsn()` — consistent with rest of gateway
- [ ] No hardcoded DSN strings anywhere in the file
- [ ] Python syntax is valid (`py_compile` passes)
