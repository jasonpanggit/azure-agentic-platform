"""Tests for new Arc agent tools (Phase 32)."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch


def _instr_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryArcExtensionHealth:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.HybridComputeManagementClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_extension_list(self, mock_cred, mock_hc_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_hc = MagicMock()
        mock_hc_cls.return_value = mock_hc
        ext = MagicMock()
        ext.name = "MicrosoftMonitoringAgent"
        ext.provisioning_state = "Failed"
        ext.type_handler_version = "1.0.0"
        ext.instance_view = ""
        mock_hc.machine_extensions.list.return_value = [ext]

        from agents.arc.tools import query_arc_extension_health

        result = query_arc_extension_health("rg", "arc-vm1", "sub", "t1")
        assert "extensions" in result
        assert len(result["extensions"]) == 1

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.HybridComputeManagementClient", None)
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_arc_extension_health

        result = query_arc_extension_health("rg", "arc-vm1", "sub", "t1")
        assert "error" in result


class TestQueryArcGuestConfig:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.GuestConfigurationClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_assignments_list(self, mock_cred, mock_gc_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_gc = MagicMock()
        mock_gc_cls.return_value = mock_gc
        assignment = MagicMock()
        assignment.name = "WindowsBaseline"
        assignment.properties.compliance_status = "Compliant"
        assignment.properties.last_compliance_status_checked = "2026-04-10T12:00:00Z"
        mock_gc.guest_configuration_assignments.list.return_value = [assignment]

        from agents.arc.tools import query_arc_guest_config

        result = query_arc_guest_config("rg", "arc-vm1", "sub", "t1")
        assert "assignments" in result

    def test_uses_guest_configuration_client_not_run_commands(self):
        """Confirm correct SDK: GuestConfigurationClient, NOT machine_run_commands."""
        from agents.arc import tools as arc_tools

        src = inspect.getsource(arc_tools.query_arc_guest_config)
        assert "GuestConfigurationClient" in src
        assert "machine_run_commands" not in src


class TestQueryArcConnectivity:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.HybridComputeManagementClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_connectivity_status(self, mock_cred, mock_hc_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_hc = MagicMock()
        mock_hc_cls.return_value = mock_hc
        machine = MagicMock()
        machine.status = "Connected"
        machine.last_status_change = "2026-04-10T12:00:00Z"
        machine.agent_version = "1.0.0"
        machine.os_type = "Linux"
        machine.os_name = "Ubuntu"
        mock_hc.machines.get.return_value = machine

        from agents.arc.tools import query_arc_connectivity

        result = query_arc_connectivity("rg", "arc-vm1", "sub", "t1")
        assert "status" in result
        assert result["machine_name"] == "arc-vm1"


class TestProposeArcAssessment:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.create_approval_record")
    def test_creates_approval_record(self, mock_create, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_arc", "status": "pending"}

        from agents.arc.tools import propose_arc_assessment

        result = propose_arc_assessment(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1",
            machine_name="arc-vm1",
            subscription_id="sub",
            incident_id="inc-001",
            thread_id="t1",
            reason="Refresh patch compliance data",
        )
        mock_create.assert_called_once()
        assert result["status"] == "pending_approval"
