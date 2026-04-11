"""Tests for Patch agent stub fixes — query_activity_log and query_resource_health (Phase 32).

Verifies that these functions call real Azure SDK clients instead of returning
placeholder stub data.
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest


def _make_instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestPatchQueryActivityLog:
    """Verify query_activity_log is a real SDK call, not a stub."""

    @patch("agents.patch.tools.instrument_tool_call")
    @patch("agents.patch.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.patch.tools.MonitorManagementClient")
    @patch("agents.patch.tools.get_credential")
    def test_calls_monitor_management_client_activity_logs(
        self, mock_cred, mock_monitor_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_monitor = MagicMock()
        mock_monitor_cls.return_value = mock_monitor
        mock_monitor.activity_logs.list.return_value = iter([])

        from agents.patch.tools import query_activity_log

        result = query_activity_log(
            resource_ids=[
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
            ],
            timespan_hours=2,
        )

        mock_monitor.activity_logs.list.assert_called_once()
        assert "entries" in result
        assert result["query_status"] == "success"

    @patch("agents.patch.tools.instrument_tool_call")
    @patch("agents.patch.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.patch.tools.MonitorManagementClient", None)
    @patch("agents.patch.tools.get_credential")
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        from agents.patch.tools import query_activity_log

        result = query_activity_log(
            resource_ids=[
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
            ],
            timespan_hours=2,
        )

        assert result["query_status"] == "error"
        assert "error" in result

    def test_query_activity_log_source_uses_sdk(self):
        """Verify the source code calls MonitorManagementClient, not just returns stub data."""
        import inspect

        from agents.patch import tools as patch_tools

        src = inspect.getsource(patch_tools.query_activity_log)
        assert "MonitorManagementClient" in src or "activity_logs.list" in src
        assert "not_implemented" not in src.lower()


class TestPatchQueryResourceHealth:
    """Verify query_resource_health is a real SDK call, not a stub."""

    @patch("agents.patch.tools.instrument_tool_call")
    @patch("agents.patch.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.patch.tools.MicrosoftResourceHealth")
    @patch("agents.patch.tools.get_credential")
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

        from agents.patch.tools import query_resource_health

        result = query_resource_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        )

        mock_rh.availability_statuses.get_by_resource.assert_called_once()
        assert result.get("availability_state") == "Available"

    def test_query_resource_health_source_uses_sdk(self):
        """Verify the source code calls MicrosoftResourceHealth, not just returns stub data."""
        import inspect

        from agents.patch import tools as patch_tools

        src = inspect.getsource(patch_tools.query_resource_health)
        assert "MicrosoftResourceHealth" in src or "availability_statuses" in src
        assert "not_implemented" not in src.lower()
