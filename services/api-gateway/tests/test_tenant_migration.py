from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_migration_up_copies_tenant_data():
    """Migration copies compliance_frameworks and operator_group_id to platform_settings."""
    import importlib
    migration = importlib.import_module(
        "services.api_gateway.migrations.011_migrate_tenants_to_settings"
    )

    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {"compliance_frameworks": '["ISO27001"]', "operator_group_id": "grp-abc"}
    ])
    mock_conn.execute = AsyncMock()

    await migration.up(mock_conn)

    # Should have called SELECT on tenants and INSERT/UPSERT to platform_settings
    mock_conn.fetch.assert_called_once()
    assert mock_conn.execute.call_count >= 1  # At minimum: upsert + drop


@pytest.mark.asyncio
async def test_migration_down_is_no_op():
    """down() is a no-op — DROP TABLE is irreversible; down documents this."""
    import importlib
    migration = importlib.import_module(
        "services.api_gateway.migrations.011_migrate_tenants_to_settings"
    )
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    await migration.down(mock_conn)
    # down is intentionally a no-op
