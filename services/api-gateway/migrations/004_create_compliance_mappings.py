"""Migration 004 -- Create compliance_mappings table (Phase 54).

Maps Defender assessments, Azure Policy definitions, and Advisor
recommendations to CIS v8, NIST 800-53 Rev 5, and ASB v3 controls.
Each row links a specific finding to its corresponding compliance
framework control IDs for cross-framework posture reporting.

Run:
    python services/api-gateway/migrations/004_create_compliance_mappings.py
"""
from __future__ import annotations

UP_SQL = """
CREATE TABLE IF NOT EXISTS compliance_mappings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_type        TEXT NOT NULL,
    defender_rule_id    TEXT,
    display_name        TEXT NOT NULL,
    description         TEXT,
    cis_control_id      TEXT,
    cis_title           TEXT,
    nist_control_id     TEXT,
    nist_title          TEXT,
    asb_control_id      TEXT,
    asb_title           TEXT,
    severity            TEXT NOT NULL DEFAULT 'Medium',
    remediation_sop_id  UUID,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_mappings_defender_rule_id ON compliance_mappings (defender_rule_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_asb ON compliance_mappings (asb_control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_nist ON compliance_mappings (nist_control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_cis ON compliance_mappings (cis_control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_finding_type ON compliance_mappings (finding_type);

CREATE UNIQUE INDEX IF NOT EXISTS idx_compliance_mappings_unique_finding
    ON compliance_mappings (finding_type, COALESCE(defender_rule_id, display_name));
"""

DOWN_SQL = """
DROP TABLE IF EXISTS compliance_mappings;
"""


async def up(conn) -> None:
    """Apply migration 004 -- create compliance_mappings table."""
    await conn.execute(UP_SQL)


async def down(conn) -> None:
    """Roll back migration 004 -- drop compliance_mappings table."""
    await conn.execute(DOWN_SQL)


if __name__ == "__main__":
    import asyncio
    import os

    import asyncpg

    async def main() -> None:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            await up(conn)
            print("Migration 004 applied successfully.")
        finally:
            await conn.close()

    asyncio.run(main())
