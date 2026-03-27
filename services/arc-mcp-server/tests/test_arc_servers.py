"""Unit tests for Arc Servers tools (AGENT-005, MONITOR-004, MONITOR-005).

Tests cover:
  - Connectivity status and prolonged_disconnection flag (MONITOR-004)
  - Extension health field mapping (MONITOR-005)
  - Pydantic model serialisation
  - Subscription ID preservation in output
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from arc_mcp_server.tools.arc_servers import (
    _is_prolonged_disconnect,
    _serialize_extension,
    _serialize_machine,
    arc_extensions_list_impl,
    arc_servers_get_impl,
    arc_servers_list_impl,
)


# ---------------------------------------------------------------------------
# MONITOR-004: Prolonged disconnection detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_connected_server_not_flagged():
    """MONITOR-004: Connected servers must never have prolonged_disconnection=True."""
    machine = MagicMock()
    machine.status = "Connected"
    machine.last_status_change = datetime.now(timezone.utc) - timedelta(hours=5)
    assert _is_prolonged_disconnect(machine) is False


@pytest.mark.unit
def test_recent_disconnect_not_flagged():
    """MONITOR-004: Disconnected < 1h ago is NOT prolonged."""
    machine = MagicMock()
    machine.status = "Disconnected"
    # Disconnected 30 minutes ago — below 1h threshold
    machine.last_status_change = datetime.now(timezone.utc) - timedelta(minutes=30)
    assert _is_prolonged_disconnect(machine) is False


@pytest.mark.unit
def test_prolonged_disconnect_flagged():
    """MONITOR-004: Disconnected > 1h must be flagged as prolonged."""
    machine = MagicMock()
    machine.status = "Disconnected"
    # Disconnected 2 hours ago — exceeds 1h default threshold
    machine.last_status_change = datetime.now(timezone.utc) - timedelta(hours=2)
    assert _is_prolonged_disconnect(machine) is True


@pytest.mark.unit
def test_unknown_last_status_change_flagged():
    """MONITOR-004: Disconnected with unknown last_status_change is fail-safe flagged."""
    machine = MagicMock()
    machine.status = "Disconnected"
    machine.last_status_change = None
    assert _is_prolonged_disconnect(machine) is True


@pytest.mark.unit
def test_error_status_not_flagged_by_disconnect_logic():
    """MONITOR-004: Error status (not Disconnected) is not flagged by this function."""
    machine = MagicMock()
    machine.status = "Error"
    machine.last_status_change = datetime.now(timezone.utc) - timedelta(hours=5)
    assert _is_prolonged_disconnect(machine) is False


# ---------------------------------------------------------------------------
# Model serialisation: _serialize_machine
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_serialize_machine_extracts_resource_group():
    """_serialize_machine must extract resource group from ARM ID."""
    machine = MagicMock()
    machine.id = "/subscriptions/sub1/resourceGroups/rg-prod/providers/Microsoft.HybridCompute/machines/vm-01"
    machine.name = "vm-01"
    machine.status = "Connected"
    machine.last_status_change = datetime(2026, 3, 1, tzinfo=timezone.utc)
    machine.agent_version = "1.37.0"
    machine.os_name = "Ubuntu 22.04"
    machine.os_type = "linux"
    machine.os_version = "22.04"
    machine.kind = None
    machine.provisioning_state = "Succeeded"
    machine.location = "eastus"

    summary = _serialize_machine(machine, "sub1")

    assert summary.resource_group == "rg-prod"
    assert summary.subscription_id == "sub1"
    assert summary.name == "vm-01"
    assert summary.status == "Connected"
    assert summary.prolonged_disconnection is False


@pytest.mark.unit
def test_serialize_machine_handles_none_fields():
    """_serialize_machine must not raise when optional SDK fields are None."""
    machine = MagicMock()
    machine.id = "/subscriptions/sub1/resourceGroups/rg-test/providers/Microsoft.HybridCompute/machines/vm-02"
    machine.name = "vm-02"
    machine.status = "Disconnected"
    machine.last_status_change = datetime.now(timezone.utc) - timedelta(hours=3)
    machine.agent_version = None
    machine.os_name = None
    machine.os_type = None
    machine.os_version = None
    machine.kind = None
    machine.provisioning_state = None
    machine.location = None

    # Should not raise ValidationError
    summary = _serialize_machine(machine, "sub1")
    assert summary.prolonged_disconnection is True
    assert summary.agent_version is None


# ---------------------------------------------------------------------------
# MONITOR-005: Extension health mapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_serialize_extension_ama_succeeded():
    """MONITOR-005: AMA extension with Succeeded state is correctly serialised."""
    ext = MagicMock()
    ext.name = "AzureMonitorLinuxAgent"
    props = MagicMock()
    props.publisher = "Microsoft.Azure.Monitor"
    props.type = "AzureMonitorLinuxAgent"
    props.provisioning_state = "Succeeded"
    props.type_handler_version = "1.21.0"
    props.enable_automatic_upgrade = True
    instance_view = MagicMock()
    status = MagicMock()
    status.code = "ProvisioningState/succeeded"
    status.level = "Info"
    status.display_status = "Provisioning succeeded"
    status.message = ""
    instance_view.status = status
    props.instance_view = instance_view
    ext.properties = props

    health = _serialize_extension(ext)

    assert health.name == "AzureMonitorLinuxAgent"
    assert health.publisher == "Microsoft.Azure.Monitor"
    assert health.provisioning_state == "Succeeded"
    assert health.status_level == "Info"
    assert health.auto_upgrade_enabled is True


@pytest.mark.unit
def test_serialize_extension_change_tracking_failed():
    """MONITOR-005: Failed Change Tracking extension surfaces Error status."""
    ext = MagicMock()
    ext.name = "ChangeTracking-Linux"
    props = MagicMock()
    props.publisher = "Microsoft.Azure.ChangeTrackingAndInventory"
    props.type = "ChangeTracking-Linux"
    props.provisioning_state = "Failed"
    props.type_handler_version = "2.0.0"
    props.enable_automatic_upgrade = False
    instance_view = MagicMock()
    status = MagicMock()
    status.code = "ProvisioningState/failed"
    status.level = "Error"
    status.display_status = "Provisioning failed"
    status.message = "Extension installation failed: timeout"
    instance_view.status = status
    props.instance_view = instance_view
    ext.properties = props

    health = _serialize_extension(ext)

    assert health.provisioning_state == "Failed"
    assert health.status_level == "Error"
    assert "timeout" in (health.status_message or "")


# ---------------------------------------------------------------------------
# arc_servers_list_impl — pagination and subscription ID
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_servers_list_subscription_scope(sample_machines_120):
    """arc_servers_list_impl returns all 120 machines with correct subscription_id."""
    with patch(
        "arc_mcp_server.tools.arc_servers._get_hybridcompute_client"
    ) as mock_client_factory:
        mock_client = MagicMock()
        mock_client.machines.list_by_subscription.return_value = iter(sample_machines_120)
        mock_client_factory.return_value = mock_client

        result = await arc_servers_list_impl(subscription_id="sub-test-001")

    assert result.total_count == 120
    assert len(result.servers) == 120
    assert result.subscription_id == "sub-test-001"
    assert result.resource_group is None  # No RG filter


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_servers_list_rg_scope(sample_machines_120):
    """arc_servers_list_impl uses list_by_resource_group when resource_group is given."""
    subset = sample_machines_120[:15]
    with patch(
        "arc_mcp_server.tools.arc_servers._get_hybridcompute_client"
    ) as mock_client_factory:
        mock_client = MagicMock()
        mock_client.machines.list_by_resource_group.return_value = iter(subset)
        mock_client_factory.return_value = mock_client

        result = await arc_servers_list_impl(
            subscription_id="sub-test-001",
            resource_group="rg-arc-test",
        )

    assert result.total_count == 15
    assert len(result.servers) == 15
    assert result.resource_group == "rg-arc-test"
    mock_client.machines.list_by_resource_group.assert_called_once_with("rg-arc-test")
    mock_client.machines.list_by_subscription.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_servers_list_empty_subscription():
    """arc_servers_list_impl handles zero results without error."""
    with patch(
        "arc_mcp_server.tools.arc_servers._get_hybridcompute_client"
    ) as mock_client_factory:
        mock_client = MagicMock()
        mock_client.machines.list_by_subscription.return_value = iter([])
        mock_client_factory.return_value = mock_client

        result = await arc_servers_list_impl(subscription_id="sub-empty")

    assert result.total_count == 0
    assert result.servers == []


# ---------------------------------------------------------------------------
# arc_extensions_list_impl
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_extensions_list_returns_all_extensions():
    """arc_extensions_list_impl returns all extensions with correct total_count."""
    ext_ama = MagicMock()
    ext_ama.name = "AzureMonitorLinuxAgent"
    props_ama = MagicMock()
    props_ama.publisher = "Microsoft.Azure.Monitor"
    props_ama.type = "AzureMonitorLinuxAgent"
    props_ama.provisioning_state = "Succeeded"
    props_ama.type_handler_version = "1.21.0"
    props_ama.enable_automatic_upgrade = True
    iv_ama = MagicMock()
    st_ama = MagicMock()
    st_ama.code = "ProvisioningState/succeeded"
    st_ama.level = "Info"
    st_ama.display_status = "Provisioning succeeded"
    st_ama.message = ""
    iv_ama.status = st_ama
    props_ama.instance_view = iv_ama
    ext_ama.properties = props_ama

    ext_ct = MagicMock()
    ext_ct.name = "ChangeTracking-Linux"
    props_ct = MagicMock()
    props_ct.publisher = "Microsoft.Azure.ChangeTrackingAndInventory"
    props_ct.type = "ChangeTracking-Linux"
    props_ct.provisioning_state = "Failed"
    props_ct.type_handler_version = "2.0.0"
    props_ct.enable_automatic_upgrade = False
    iv_ct = MagicMock()
    st_ct = MagicMock()
    st_ct.code = "ProvisioningState/failed"
    st_ct.level = "Error"
    st_ct.display_status = "Provisioning failed"
    st_ct.message = "Timeout"
    iv_ct.status = st_ct
    props_ct.instance_view = iv_ct
    ext_ct.properties = props_ct

    with patch(
        "arc_mcp_server.tools.arc_servers._get_hybridcompute_client"
    ) as mock_client_factory:
        mock_client = MagicMock()
        mock_client.machine_extensions.list.return_value = iter([ext_ama, ext_ct])
        mock_client_factory.return_value = mock_client

        result = await arc_extensions_list_impl(
            subscription_id="sub-test-001",
            resource_group="rg-arc-test",
            machine_name="arc-server-0001",
        )

    assert result.total_count == 2
    assert len(result.extensions) == 2
    names = {e.name for e in result.extensions}
    assert "AzureMonitorLinuxAgent" in names
    assert "ChangeTracking-Linux" in names
    # Verify failed extension is present with Error level
    ct = next(e for e in result.extensions if e.name == "ChangeTracking-Linux")
    assert ct.provisioning_state == "Failed"
    assert ct.status_level == "Error"
