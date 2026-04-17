from __future__ import annotations
"""Migration 003 — Create sops metadata table (Phase 30).

The sops table is a lightweight metadata registry. SOP content lives
entirely in the Foundry vector store (aap-sops-v1). PostgreSQL only
stores the filename, domain, tags, and content hash for fast selection
and idempotent upload.

Run:
    python services/api-gateway/migrations/003_create_sops_table.py
"""
import os

UP_SQL = """
CREATE TABLE IF NOT EXISTS sops (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              TEXT NOT NULL,
    domain             TEXT NOT NULL,
    scenario_tags      TEXT[],
    foundry_filename   TEXT NOT NULL UNIQUE,
    foundry_file_id    TEXT,
    content_hash       TEXT,
    version            TEXT NOT NULL DEFAULT '1.0',
    description        TEXT,
    severity_threshold TEXT DEFAULT 'P2',
    resource_types     TEXT[],
    is_generic         BOOLEAN DEFAULT FALSE,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sops_domain_generic ON sops (domain, is_generic);
CREATE INDEX IF NOT EXISTS idx_sops_foundry_filename ON sops (foundry_filename);
"""

DOWN_SQL = """
DROP TABLE IF EXISTS sops;
"""


async def up(conn) -> None:
    """Apply migration 003 — create sops table."""
    await conn.execute(UP_SQL)


async def down(conn) -> None:
    """Roll back migration 003 — drop sops table."""
    await conn.execute(DOWN_SQL)


if __name__ == "__main__":
    import asyncio
    import os

    import asyncpg

    async def main() -> None:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            await up(conn)
            print("Migration 003 applied successfully.")
        finally:
            await conn.close()

    asyncio.run(main())
