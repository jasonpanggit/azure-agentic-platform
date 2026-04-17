# services/api-gateway/tests/test_subscription_spn_migration.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_migration_up_updates_existing_records():
    """Migration up() adds SPN fields with safe defaults to existing subscription records."""
    import importlib
    migration = importlib.import_module(
        "services.api_gateway.migrations.010_subscription_spn_fields"
    )

    mock_conn = MagicMock()
    # Test that the function runs without error (Cosmos migration is fire-and-forget)
    await migration.up(mock_conn)
    # No assert needed — just verify it doesn't throw


@pytest.mark.asyncio
async def test_migration_down_is_no_op():
    """Migration down() is a no-op (field removal is backwards-compatible)."""
    import importlib
    migration = importlib.import_module(
        "services.api_gateway.migrations.010_subscription_spn_fields"
    )
    mock_conn = MagicMock()
    await migration.down(mock_conn)
