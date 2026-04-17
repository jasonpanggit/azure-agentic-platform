from __future__ import annotations
"""Migration 005 — Create remediation_policies table (Phase 51).

Auto-approval policies for known-safe remediation actions. Each policy
defines an action class, resource tag filter, blast-radius ceiling,
and daily execution cap. The admin CRUD router validates action_class
against SAFE_ARM_ACTIONS before insert.

Run:
    python services/api-gateway/migrations/005_create_remediation_policies_table.py
"""
import os

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

DOWN_SQL = """
DROP TABLE IF EXISTS remediation_policies;
"""


async def up(conn) -> None:
    """Apply migration 005 — create remediation_policies table."""
    await conn.execute(UP_SQL)


async def down(conn) -> None:
    """Roll back migration 005 — drop remediation_policies table."""
    await conn.execute(DOWN_SQL)


if __name__ == "__main__":
    import asyncio
    import os

    import asyncpg

    async def main() -> None:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            await up(conn)
            print("Migration 005 applied successfully.")
        finally:
            await conn.close()

    asyncio.run(main())
