"""Tests for new Azure VM tools (Phase 32): extensions, boot diagnostics, disk health, SKU options, propose_*."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest


def _instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryVmExtensions:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_extensions_list(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        ext = MagicMock()
        ext.name = "MicrosoftMonitoringAgent"
        ext.properties.provisioning_state = "Succeeded"
        ext.properties.type_handler_version = "1.0"
        ext.properties.auto_upgrade_minor_version = True
        ext.type = "Microsoft.Compute/virtualMachines/extensions"
        mock_result = MagicMock()
        mock_result.value = [ext]
        mock_compute.virtual_machine_extensions.list.return_value = mock_result

        from agents.compute.tools import query_vm_extensions

        result = query_vm_extensions(
            resource_group="rg1",
            vm_name="vm1",
            subscription_id="sub",
            thread_id="thread-1",
        )

        assert "extensions" in result
        assert len(result["extensions"]) == 1

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_vm_extensions

        result = query_vm_extensions("rg1", "vm1", "sub", "thread-1")
        assert "error" in result


class TestQueryBootDiagnostics:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_screenshot_uri(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        diag_result = MagicMock()
        diag_result.console_screenshot_blob_uri = "https://storage/screenshot.png"
        diag_result.serial_console_log_blob_uri = "https://storage/serial.txt"
        mock_compute.virtual_machines.retrieve_boot_diagnostics_data.return_value = diag_result

        from agents.compute.tools import query_boot_diagnostics

        result = query_boot_diagnostics("rg1", "vm1", "sub", "thread-1")
        assert "screenshot_uri" in result
        assert result["screenshot_uri"] == "https://storage/screenshot.png"


class TestQueryVmSkuOptions:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_sku_list(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        sku = MagicMock()
        sku.name = "Standard_D4s_v3"
        sku.tier = "Standard"
        sku.resource_type = "virtualMachines"
        cap1 = MagicMock()
        cap1.name = "vCPUs"
        cap1.value = "4"
        cap2 = MagicMock()
        cap2.name = "MemoryGB"
        cap2.value = "16"
        sku.capabilities = [cap1, cap2]
        mock_compute.resource_skus.list.return_value = iter([sku])

        from agents.compute.tools import query_vm_sku_options

        result = query_vm_sku_options(
            subscription_id="sub",
            location="eastus",
            sku_family="Standard_D",
            thread_id="thread-1",
        )
        assert "skus" in result
        assert len(result["skus"]) >= 1


class TestQueryDiskHealth:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_disk_state(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        disk = MagicMock()
        disk.disk_state = "Attached"
        disk.disk_size_gb = 128
        disk.provisioning_state = "Succeeded"
        disk.disk_iops_read_write = 500
        disk.disk_m_bps_read_write = 60
        disk.encryption = MagicMock()
        disk.encryption.type = "EncryptionAtRestWithPlatformKey"
        mock_compute.disks.get.return_value = disk

        from agents.compute.tools import query_disk_health

        result = query_disk_health("rg1", "disk1", "sub", "thread-1")
        assert result["disk_state"] == "Attached"
        assert result["disk_size_gb"] == 128


class TestProposeVmRestart:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_creates_approval_record(self, mock_create_approval, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_create_approval.return_value = {"id": "appr_123", "status": "pending"}

        from agents.compute.tools import propose_vm_restart

        result = propose_vm_restart(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_group="rg",
            vm_name="vm1",
            subscription_id="sub",
            incident_id="inc-001",
            thread_id="thread-1",
            reason="High CPU post-deployment",
        )

        mock_create_approval.assert_called_once()
        assert result.get("status") == "pending_approval" or "approval_id" in result

    def test_propose_vm_restart_does_not_call_arm_directly(self):
        """propose_vm_restart must NOT import or use ComputeManagementClient.virtual_machines.restart."""
        from agents.compute import tools as compute_tools

        src = inspect.getsource(compute_tools.propose_vm_restart)
        assert "virtual_machines.restart" not in src
        assert "virtual_machines.begin_restart" not in src


class TestProposeVmResize:
    def test_propose_vm_resize_does_not_call_arm_directly(self):
        from agents.compute import tools as compute_tools

        src = inspect.getsource(compute_tools.propose_vm_resize)
        assert "virtual_machines.update" not in src
        assert "begin_update" not in src

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_creates_approval_record_with_target_sku(
        self, mock_create_approval, mock_identity, mock_instr
    ):
        mock_instr.return_value = _instrument_mock()
        mock_create_approval.return_value = {"id": "appr_resize", "status": "pending"}

        from agents.compute.tools import propose_vm_resize

        result = propose_vm_resize(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_group="rg",
            vm_name="vm1",
            subscription_id="sub",
            current_sku="Standard_D2s_v3",
            target_sku="Standard_D4s_v3",
            incident_id="inc-001",
            thread_id="thread-1",
            reason="CPU saturation",
        )

        mock_create_approval.assert_called_once()


class TestProposeVmRedeploy:
    def test_propose_vm_redeploy_does_not_call_arm_directly(self):
        from agents.compute import tools as compute_tools

        src = inspect.getsource(compute_tools.propose_vm_redeploy)
        assert "begin_redeploy" not in src
        assert "virtual_machines.redeploy" not in src
