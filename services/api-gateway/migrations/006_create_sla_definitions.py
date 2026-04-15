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
