"""Unit tests for Arc Data Services tools (AGENT-005, AGENT-006).

Tests cover:
  - SQL Managed Instance list pagination exhaustion
  - PostgreSQL list pagination exhaustion
  - total_count correctness
  - Serialisation of optional fields
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from arc_mcp_server.tools.arc_data import (
    arc_data_postgresql_list_impl,
    arc_data_sql_mi_get_impl,
    arc_data_sql_mi_list_impl,
)


def _make_sql_mi(index: int, subscription_id: str = "sub-test-001") -> MagicMock:
    """Create a mock SqlManagedInstance for testing."""
    mi = MagicMock()
    mi.name = f"arc-sqlmi-{index:04d}"
    mi.id = (
        f"/subscriptions/{subscription_id}/resourceGroups/rg-arc-data"
        f"/providers/Microsoft.AzureArcData/sqlManagedInstances/arc-sqlmi-{index:04d}"
    )
    mi.location = "eastus"
    props = MagicMock()
    props.state = "Ready"
    props.edition = "Developer"
    props.v_cores = 4
    props.provisioning_state = "Succeeded"
    mi.properties = props
    return mi


def _make_postgresql(index: int, subscription_id: str = "sub-test-001") -> MagicMock:
    """Create a mock PostgreSqlInstance for testing."""
    pg = MagicMock()
    pg.name = f"arc-pg-{index:04d}"
    pg.id = (
        f"/subscriptions/{subscription_id}/resourceGroups/rg-arc-data"
        f"/providers/Microsoft.AzureArcData/postgresInstances/arc-pg-{index:04d}"
    )
    pg.location = "eastus"
    props = MagicMock()
    props.state = "Ready"
    props.provisioning_state = "Succeeded"
    pg.properties = props
    return pg


# ---------------------------------------------------------------------------
# AGENT-006: SQL MI pagination
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_data_sql_mi_list_pagination():
    """AGENT-006: arc_data_sql_mi_list_impl returns all instances with total_count."""
    fake_instances = [_make_sql_mi(i) for i in range(15)]

    with patch(
        "arc_mcp_server.tools.arc_data._get_arcdata_client"
    ) as mock_client_factory:
        mock_client = MagicMock()
        mock_client.sql_managed_instances.list.return_value = iter(fake_instances)
        mock_client_factory.return_value = mock_client

        result = await arc_data_sql_mi_list_impl(subscription_id="sub-test-001")

    assert result.total_count == 15
    assert len(result.instances) == 15
    assert result.subscription_id == "sub-test-001"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_data_sql_mi_list_empty():
    """arc_data_sql_mi_list_impl handles zero results."""
    with patch(
        "arc_mcp_server.tools.arc_data._get_arcdata_client"
    ) as mock_client_factory:
        mock_client = MagicMock()
        mock_client.sql_managed_instances.list.return_value = iter([])
        mock_client_factory.return_value = mock_client

        result = await arc_data_sql_mi_list_impl(subscription_id="sub-empty")

    assert result.total_count == 0
    assert result.instances == []


# ---------------------------------------------------------------------------
# AGENT-006: PostgreSQL pagination
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_data_postgresql_list_pagination():
    """AGENT-006: arc_data_postgresql_list_impl returns all instances with total_count."""
    fake_pgs = [_make_postgresql(i) for i in range(20)]

    with patch(
        "arc_mcp_server.tools.arc_data._get_arcdata_client"
    ) as mock_client_factory:
        mock_client = MagicMock()
        mock_client.postgresql_instances.list.return_value = iter(fake_pgs)
        mock_client_factory.return_value = mock_client

        result = await arc_data_postgresql_list_impl(subscription_id="sub-test-001")

    assert result.total_count == 20
    assert len(result.instances) == 20


# ---------------------------------------------------------------------------
# arc_data_sql_mi_get_impl
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_data_sql_mi_get():
    """arc_data_sql_mi_get_impl returns single instance with correct fields."""
    single = _make_sql_mi(42)

    with patch(
        "arc_mcp_server.tools.arc_data._get_arcdata_client"
    ) as mock_client_factory:
        mock_client = MagicMock()
        mock_client.sql_managed_instances.get.return_value = single
        mock_client_factory.return_value = mock_client

        result = await arc_data_sql_mi_get_impl(
            subscription_id="sub-test-001",
            resource_group="rg-arc-data",
            instance_name="arc-sqlmi-0042",
        )

    assert result.name == "arc-sqlmi-0042"
    assert result.subscription_id == "sub-test-001"
    mock_client.sql_managed_instances.get.assert_called_once_with(
        "rg-arc-data", "arc-sqlmi-0042"
    )
