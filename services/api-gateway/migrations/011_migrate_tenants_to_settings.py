from __future__ import annotations
"""Migration 011: Move tenant data to platform_settings, then drop tenants table.

This migration:
1. Creates platform_settings table if it doesn't exist
2. Copies compliance_frameworks + operator_group_id from tenants → platform_settings
3. DROPs the tenants table

Run UP_SQL first in a transaction. Verify with down() (which is a no-op because
DROP TABLE is irreversible — re-create tenants from a backup if rollback needed).

Idempotent: safe to re-run if interrupted before DROP TABLE.
"""
import logging

logger = logging.getLogger(__name__)

UP_SQL = """
-- Step 1: Create platform_settings if not exists
CREATE TABLE IF NOT EXISTS platform_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Step 2: Copy compliance_frameworks from first (and typically only) tenant record
INSERT INTO platform_settings (key, value, updated_at)
SELECT 'compliance_frameworks', compliance_frameworks, NOW()
FROM tenants
WHERE compliance_frameworks IS NOT NULL
ORDER BY created_at ASC
LIMIT 1
ON CONFLICT (key) DO UPDATE
  SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;

-- Step 3: Copy operator_group_id from first tenant record
INSERT INTO platform_settings (key, value, updated_at)
SELECT 'operator_group_id', operator_group_id, NOW()
FROM tenants
WHERE operator_group_id IS NOT NULL
ORDER BY created_at ASC
LIMIT 1
ON CONFLICT (key) DO UPDATE
  SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;

-- Step 4: Drop tenants table (data is now in platform_settings)
DROP TABLE IF EXISTS tenants;
"""

DOWN_SQL = """
-- down() intentionally empty — DROP TABLE is irreversible.
-- If rollback is needed, restore the tenants table from a database backup.
SELECT 'migration 011 down: no-op - restore tenants from backup if required';
"""

DESCRIPTION = "Migrate tenant data to platform_settings and drop tenants table"


async def up(conn) -> None:  # noqa: ANN001
    """Run the migration. Idempotent."""
    logger.info("migration 011: reading tenants table...")
    rows = await conn.fetch("SELECT compliance_frameworks, operator_group_id FROM tenants LIMIT 1")
    if rows:
        row = rows[0]
        logger.info(
            "migration 011: found tenant data — compliance_frameworks=%s operator_group_id=%s",
            row.get("compliance_frameworks"),
            row.get("operator_group_id"),
        )
    await conn.execute(UP_SQL)
    logger.info("migration 011: tenants → platform_settings migration complete, tenants table dropped")


async def down(conn) -> None:  # noqa: ANN001
    """No-op — DROP TABLE is irreversible."""
    logger.warning(
        "migration 011 down: DROP TABLE is irreversible. "
        "Restore tenants table from a database backup if rollback is needed."
    )
    await conn.execute(DOWN_SQL)
