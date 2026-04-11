"""Tests for EOL agent stub fixes — query_activity_log, query_resource_health, query_software_inventory (Phase 32).

Verifies that these functions call real Azure SDK clients instead of returning
placeholder stub data.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestEolQueryActivityLog:
    """Verify query_activity_log is a real SDK call, not a stub."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.eol.tools.MonitorManagementClient")
    @patch("agents.eol.tools.get_credential")
    def test_calls_monitor_management_client_activity_logs(
        self, mock_cred, mock_monitor_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_monitor = MagicMock()
        mock_monitor_cls.return_value = mock_monitor
        mock_monitor.activity_logs.list.return_value = iter([])

        from agents.eol.tools import query_activity_log

        result = query_activity_log(
            resource_ids=[
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
            ],
            timespan_hours=2,
        )

        mock_monitor.activity_logs.list.assert_called_once()
        assert "entries" in result
        assert result["query_status"] == "success"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.eol.tools.MonitorManagementClient", None)
    @patch("agents.eol.tools.get_credential")
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        from agents.eol.tools import query_activity_log

        result = query_activity_log(
            resource_ids=[
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
            ],
            timespan_hours=2,
        )

        assert result["query_status"] == "error"
        assert "error" in result

    def test_source_uses_sdk(self):
        import inspect

        from agents.eol import tools as eol_tools

        src = inspect.getsource(eol_tools.query_activity_log)
        assert "MonitorManagementClient" in src or "activity_logs.list" in src


class TestEolQueryResourceHealth:
    """Verify query_resource_health is a real SDK call, not a stub."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.eol.tools.MicrosoftResourceHealth")
    @patch("agents.eol.tools.get_credential")
    def test_calls_availability_statuses(
        self, mock_cred, mock_rh_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_rh = MagicMock()
        mock_rh_cls.return_value = mock_rh
        mock_status = MagicMock()
        mock_status.properties.availability_state.value = "Available"
        mock_status.properties.summary = "The resource is available"
        mock_status.properties.reason_type = None
        mock_status.properties.occurred_time = None
        mock_rh.availability_statuses.get_by_resource.return_value = mock_status

        from agents.eol.tools import query_resource_health

        result = query_resource_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        )

        mock_rh.availability_statuses.get_by_resource.assert_called_once()
        assert result.get("availability_state") == "Available"

    def test_source_uses_sdk(self):
        import inspect

        from agents.eol import tools as eol_tools

        src = inspect.getsource(eol_tools.query_resource_health)
        assert "MicrosoftResourceHealth" in src or "availability_statuses" in src


class TestEolQuerySoftwareInventory:
    """Verify query_software_inventory executes KQL via LogsQueryClient."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.eol.tools.LogsQueryClient")
    @patch("agents.eol.tools.LogsQueryStatus")
    @patch("agents.eol.tools.get_credential")
    def test_executes_kql_query(
        self, mock_cred, mock_status_cls, mock_logs_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_logs = MagicMock()
        mock_logs_cls.return_value = mock_logs
        mock_response = MagicMock()
        mock_response.status = mock_status_cls.SUCCESS
        mock_response.tables = []
        mock_logs.query_workspace.return_value = mock_response

        from agents.eol.tools import query_software_inventory

        result = query_software_inventory(
            workspace_id="ws-123",
            computer_names=None,
            timespan="P7D",
        )

        mock_logs.query_workspace.assert_called_once()
        assert result["query_status"] == "success"

    def test_source_uses_logs_query_client(self):
        import inspect

        from agents.eol import tools as eol_tools

        src = inspect.getsource(eol_tools.query_software_inventory)
        assert "LogsQueryClient" in src or "query_workspace" in src
