"""Tests for VMSS tools added to compute agent (Phase 32)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _instr_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryVmssInstances:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_instances_list(self, mock_cred, mock_compute_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        inst = MagicMock()
        inst.instance_id = "0"
        inst.vm_id = "vm-id-0"
        inst.provisioning_state = "Succeeded"
        mock_compute.virtual_machine_scale_set_vms.list.return_value = [inst]

        from agents.compute.tools import query_vmss_instances

        result = query_vmss_instances(
            resource_group="rg",
            vmss_name="vmss1",
            subscription_id="sub",
            thread_id="t1",
        )
        assert "instances" in result
        assert len(result["instances"]) == 1

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ComputeManagementClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()

        from agents.compute.tools import query_vmss_instances

        result = query_vmss_instances("rg", "vmss1", "sub", "t1")
        assert "error" in result


class TestQueryVmssAutoscale:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.MonitorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_autoscale_settings(self, mock_cred, mock_monitor_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_monitor = MagicMock()
        mock_monitor_cls.return_value = mock_monitor
        setting = MagicMock()
        setting.name = "autoscale-vmss1"
        setting.enabled = True
        setting.target_resource_uri = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/vmss1"
        setting.profiles = []
        mock_monitor.autoscale_settings.list_by_resource_group.return_value = [setting]

        from agents.compute.tools import query_vmss_autoscale

        result = query_vmss_autoscale(
            resource_group="rg",
            vmss_name="vmss1",
            subscription_id="sub",
            thread_id="t1",
        )
        assert "autoscale_settings" in result


class TestProposeVmssScale:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.create_approval_record")
    def test_creates_approval_record(self, mock_create, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_vmss", "status": "pending"}

        from agents.compute.tools import propose_vmss_scale

        result = propose_vmss_scale(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/vmss1",
            resource_group="rg",
            vmss_name="vmss1",
            subscription_id="sub",
            current_capacity=2,
            target_capacity=4,
            incident_id="inc-001",
            thread_id="t1",
            reason="Scale out due to load",
        )
        mock_create.assert_called_once()
        assert result["status"] == "pending_approval"

    def test_propose_vmss_scale_does_not_call_arm_directly(self):
        import inspect

        from agents.compute import tools as t

        src = inspect.getsource(t.propose_vmss_scale)
        assert "virtual_machine_scale_sets.update" not in src
        assert "begin_update" not in src
