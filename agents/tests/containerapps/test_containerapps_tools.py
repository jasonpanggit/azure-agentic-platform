"""Unit tests for Container Apps Agent tools (Phase 48).

Tests all 6 Container Apps tools + ALLOWED_MCP_TOOLS.
Each tool has success path, error path, and SDK-missing path tests.
Pattern follows agents/tests/appservice/test_appservice_tools.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _make_cm_mock():
    """Return a context-manager mock for instrument_tool_call."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


# ===========================================================================
# ALLOWED_MCP_TOOLS
# ===========================================================================


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_mcp_tools_has_exactly_six_entries(self):
        from agents.containerapps.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 6

    def test_allowed_mcp_tools_contains_expected_entries(self):
        from agents.containerapps.tools import ALLOWED_MCP_TOOLS

        expected = [
            "monitor.query_metrics",
            "monitor.query_logs",
            "containerapps.list_apps",
            "containerapps.get_app",
            "containerapps.list_revisions",
            "containerapps.get_revision",
        ]
        for tool in expected:
            assert tool in ALLOWED_MCP_TOOLS, f"Missing: {tool}"

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.containerapps.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "*" not in tool, f"Wildcard found in tool: {tool}"

    def test_allowed_mcp_tools_is_list(self):
        from agents.containerapps.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)


# ===========================================================================
# list_container_apps
# ===========================================================================


class TestListContainerApps:
    """Verify list_container_apps returns expected structure."""

    def _make_app_mock(self, name, state, active_rev=None, has_ingress=True):
        app = MagicMock()
        app.name = name
        app.provisioning_state = state
        app.latest_ready_revision_name = active_rev
        app.ingress = MagicMock() if has_ingress else None
        app.running_status = None
        app.scale = None
        return app

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.ContainerAppsAPIClient")
    def test_returns_success_with_app_list(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        apps = [
            self._make_app_mock("ca-compute-prod", "Succeeded", "ca-compute-prod--abc123"),
            self._make_app_mock("ca-network-prod", "Succeeded", "ca-network-prod--def456"),
        ]
        mock_client_cls.return_value.container_apps.list_by_resource_group.return_value = iter(
            apps
        )

        from agents.containerapps.tools import list_container_apps

        result = list_container_apps(
            resource_group="rg-aap-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["resource_group"] == "rg-aap-prod"
        assert result["subscription_id"] == "sub-1"
        assert result["app_count"] == 2
        assert len(result["apps"]) == 2
        assert result["apps"][0]["app_name"] == "ca-compute-prod"
        assert result["apps"][0]["ingress_enabled"] is True
        assert "duration_ms" in result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.ContainerAppsAPIClient")
    def test_returns_empty_list_when_no_apps(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.container_apps.list_by_resource_group.return_value = iter(
            []
        )

        from agents.containerapps.tools import list_container_apps

        result = list_container_apps(resource_group="empty-rg", subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["app_count"] == 0
        assert result["apps"] == []

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.ContainerAppsAPIClient")
    def test_returns_error_on_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.container_apps.list_by_resource_group.side_effect = (
            Exception("ARM 403")
        )

        from agents.containerapps.tools import list_container_apps

        result = list_container_apps(resource_group="rg-test", subscription_id="sub-1")

        assert result["query_status"] == "error"
        assert "ARM 403" in result["error"]
        assert result["apps"] == []
        assert result["app_count"] == 0
        assert "duration_ms" in result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.containerapps.tools as tools_module

        original = tools_module.ContainerAppsAPIClient
        tools_module.ContainerAppsAPIClient = None
        try:
            from agents.containerapps.tools import list_container_apps

            result = list_container_apps(resource_group="rg-test", subscription_id="sub-1")
            assert result["query_status"] == "error"
            assert "azure-mgmt-appcontainers" in result["error"]
        finally:
            tools_module.ContainerAppsAPIClient = original

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.ContainerAppsAPIClient")
    def test_ingress_disabled_app_shows_false(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        apps = [self._make_app_mock("ca-internal", "Succeeded", has_ingress=False)]
        mock_client_cls.return_value.container_apps.list_by_resource_group.return_value = iter(
            apps
        )

        from agents.containerapps.tools import list_container_apps

        result = list_container_apps(resource_group="rg-test", subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["apps"][0]["ingress_enabled"] is False


# ===========================================================================
# get_container_app_health
# ===========================================================================


class TestGetContainerAppHealth:
    """Verify get_container_app_health returns expected structure."""

    def _make_app_mock(self):
        app = MagicMock()
        app.provisioning_state = "Succeeded"
        app.latest_ready_revision_name = "ca-api-prod--v1abc"
        app.running_status = 2
        app.managed_environment_id = (
            "/subscriptions/sub-1/resourceGroups/rg-prod"
            "/providers/Microsoft.App/managedEnvironments/env-prod"
        )

        ingress = MagicMock()
        ingress.external = True
        ingress.fqdn = "ca-api-prod.bluefield-abc.eastus.azurecontainerapps.io"
        app.ingress = ingress

        sys_data = MagicMock()
        sys_data.last_modified_at = datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc)
        app.system_data = sys_data

        return app

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.ContainerAppsAPIClient")
    def test_returns_success_with_all_fields(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.container_apps.get.return_value = self._make_app_mock()

        from agents.containerapps.tools import get_container_app_health

        result = get_container_app_health(
            app_name="ca-api-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["app_name"] == "ca-api-prod"
        assert result["provisioning_state"] == "Succeeded"
        assert result["replica_count"] == 2
        assert result["active_revision_name"] == "ca-api-prod--v1abc"
        assert result["ingress_enabled"] is True
        assert result["ingress_external"] is True
        assert "azurecontainerapps.io" in result["ingress_fqdn"]
        assert result["managed_environment_id"] is not None
        assert "duration_ms" in result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.ContainerAppsAPIClient")
    def test_no_ingress_shows_false(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        app = MagicMock()
        app.provisioning_state = "Succeeded"
        app.latest_ready_revision_name = "rev-1"
        app.running_status = 1
        app.ingress = None
        app.managed_environment_id = "/env/id"
        app.system_data = None

        mock_client_cls.return_value.container_apps.get.return_value = app

        from agents.containerapps.tools import get_container_app_health

        result = get_container_app_health(
            app_name="internal-app", resource_group="rg", subscription_id="sub-1"
        )

        assert result["query_status"] == "success"
        assert result["ingress_enabled"] is False
        assert result["ingress_external"] is None
        assert result["ingress_fqdn"] is None

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.ContainerAppsAPIClient")
    def test_returns_error_on_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.container_apps.get.side_effect = Exception("Not found")

        from agents.containerapps.tools import get_container_app_health

        result = get_container_app_health(
            app_name="missing-app", resource_group="rg", subscription_id="sub-1"
        )

        assert result["query_status"] == "error"
        assert "Not found" in result["error"]
        assert result["provisioning_state"] is None
        assert result["ingress_enabled"] is False
        assert "duration_ms" in result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.containerapps.tools as tools_module

        original = tools_module.ContainerAppsAPIClient
        tools_module.ContainerAppsAPIClient = None
        try:
            from agents.containerapps.tools import get_container_app_health

            result = get_container_app_health(
                app_name="app", resource_group="rg", subscription_id="sub-1"
            )
            assert result["query_status"] == "error"
            assert "azure-mgmt-appcontainers" in result["error"]
        finally:
            tools_module.ContainerAppsAPIClient = original

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.ContainerAppsAPIClient")
    def test_last_modified_time_is_iso_string(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.container_apps.get.return_value = self._make_app_mock()

        from agents.containerapps.tools import get_container_app_health

        result = get_container_app_health(
            app_name="ca-api-prod", resource_group="rg-prod", subscription_id="sub-1"
        )

        assert result["query_status"] == "success"
        assert result["last_modified_time"] is not None
        assert "2026" in result["last_modified_time"]


# ===========================================================================
# get_container_app_metrics
# ===========================================================================


class TestGetContainerAppMetrics:
    """Verify get_container_app_metrics returns expected structure."""

    def _make_dp(self, total=None, average=None):
        dp = MagicMock()
        dp.time_stamp = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
        dp.total = total
        dp.average = average
        return dp

    def _make_metric_response(self, metrics_data):
        mock_metrics = []
        for name, dps in metrics_data.items():
            mock_ts = MagicMock()
            mock_ts.data = dps
            mock_metric = MagicMock()
            mock_metric.name = MagicMock(value=name)
            mock_metric.timeseries = [mock_ts]
            mock_metrics.append(mock_metric)
        response = MagicMock()
        response.value = mock_metrics
        return response

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.MonitorManagementClient")
    def test_returns_success_with_all_metrics(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        # CpuUsageNanoCores: 500_000_000 nano = 50% of 1 vCore
        # MemoryWorkingSetBytes: 1_073_741_824 bytes = 50% of 2GiB
        metrics_data = {
            "Requests": [self._make_dp(total=1200.0)],
            "ResponseTime": [self._make_dp(average=180.0)],
            "Replicas": [self._make_dp(average=3.0)],
            "CpuUsageNanoCores": [self._make_dp(average=500_000_000.0)],
            "MemoryWorkingSetBytes": [self._make_dp(average=1_073_741_824.0)],
        }
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response(
            metrics_data
        )

        from agents.containerapps.tools import get_container_app_metrics

        result = get_container_app_metrics(
            app_name="ca-api-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            hours=2,
        )

        assert result["query_status"] == "success"
        assert result["app_name"] == "ca-api-prod"
        assert result["timespan_hours"] == 2
        assert result["request_count"] == 1200
        assert result["avg_response_time_ms"] == pytest.approx(180.0)
        assert result["replica_count_avg"] == pytest.approx(3.0)
        assert result["cpu_percent"] == pytest.approx(50.0, abs=0.1)
        assert result["memory_percent"] == pytest.approx(50.0, abs=0.1)
        assert isinstance(result["data_points"], list)
        assert "duration_ms" in result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.MonitorManagementClient")
    def test_returns_error_on_monitor_exception(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.side_effect = Exception("Monitor unavailable")

        from agents.containerapps.tools import get_container_app_metrics

        result = get_container_app_metrics(
            app_name="ca-api-prod", resource_group="rg", subscription_id="sub-1"
        )

        assert result["query_status"] == "error"
        assert "Monitor unavailable" in result["error"]
        assert result["request_count"] == 0
        assert result["data_points"] == []
        assert "duration_ms" in result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.containerapps.tools as tools_module

        original = tools_module.MonitorManagementClient
        tools_module.MonitorManagementClient = None
        try:
            from agents.containerapps.tools import get_container_app_metrics

            result = get_container_app_metrics(
                app_name="app", resource_group="rg", subscription_id="sub-1"
            )
            assert result["query_status"] == "error"
            assert "azure-mgmt-monitor" in result["error"]
        finally:
            tools_module.MonitorManagementClient = original

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.MonitorManagementClient")
    def test_default_hours_is_two(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response({})

        from agents.containerapps.tools import get_container_app_metrics

        result = get_container_app_metrics(
            app_name="app", resource_group="rg", subscription_id="sub-1"
        )

        assert result["timespan_hours"] == 2

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.MonitorManagementClient")
    def test_no_data_returns_none_for_optional_fields(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response({})

        from agents.containerapps.tools import get_container_app_metrics

        result = get_container_app_metrics(
            app_name="app", resource_group="rg", subscription_id="sub-1"
        )

        assert result["query_status"] == "success"
        assert result["request_count"] == 0
        assert result["avg_response_time_ms"] is None
        assert result["replica_count_avg"] is None
        assert result["cpu_percent"] is None
        assert result["memory_percent"] is None


# ===========================================================================
# get_container_app_logs
# ===========================================================================


class TestGetContainerAppLogs:
    """Verify get_container_app_logs returns expected structure."""

    def _make_logs_result(self, rows, col_names=None):
        if col_names is None:
            col_names = ["TimeGenerated", "ContainerName_s", "Log_s", "Stream_s"]
        mock_cols = []
        for c in col_names:
            col = MagicMock()
            col.name = c
            mock_cols.append(col)
        mock_table = MagicMock()
        mock_table.columns = mock_cols
        mock_table.rows = rows
        result = MagicMock()
        result.tables = [mock_table]
        return result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.LogsQueryStatus")
    @patch("agents.containerapps.tools.LogsQueryClient")
    def test_returns_success_with_log_entries(
        self, mock_logs_cls, mock_status_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        rows = [
            [
                datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc),
                "ca-api-prod",
                "Error: connection refused",
                "stderr",
            ],
            [
                datetime(2026, 4, 14, 11, 59, 0, tzinfo=timezone.utc),
                "ca-api-prod",
                "Starting up...",
                "stdout",
            ],
        ]
        log_result = self._make_logs_result(rows)
        mock_status_cls.SUCCESS = "Success"
        log_result.status = "Success"
        mock_logs_cls.return_value.query_workspace.return_value = log_result

        from agents.containerapps.tools import get_container_app_logs

        result = get_container_app_logs(
            app_name="ca-api-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            lines=50,
        )

        assert result["query_status"] == "success"
        assert result["app_name"] == "ca-api-prod"
        assert result["lines_requested"] == 50
        assert result["log_count"] == 2
        assert len(result["log_entries"]) == 2
        assert result["log_entries"][0]["stream"] == "stderr"
        assert "duration_ms" in result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.LogsQueryStatus")
    @patch("agents.containerapps.tools.LogsQueryClient")
    def test_severity_filter_preserved_in_result(
        self, mock_logs_cls, mock_status_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        log_result = self._make_logs_result([])
        mock_status_cls.SUCCESS = "Success"
        log_result.status = "Success"
        mock_logs_cls.return_value.query_workspace.return_value = log_result

        from agents.containerapps.tools import get_container_app_logs

        result = get_container_app_logs(
            app_name="app",
            resource_group="rg",
            subscription_id="sub-1",
            severity="Error",
        )

        assert result["severity_filter"] == "Error"
        assert result["query_status"] == "success"

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    @patch("agents.containerapps.tools.LogsQueryClient")
    def test_returns_error_on_client_exception(
        self, mock_logs_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_logs_cls.side_effect = Exception("Workspace not found")

        from agents.containerapps.tools import get_container_app_logs

        result = get_container_app_logs(
            app_name="app", resource_group="rg", subscription_id="sub-1"
        )

        assert result["query_status"] == "error"
        assert "Workspace not found" in result["error"]
        assert result["log_entries"] == []
        assert result["log_count"] == 0
        assert "duration_ms" in result

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    @patch("agents.containerapps.tools.get_credential", return_value=MagicMock())
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.containerapps.tools as tools_module

        original = tools_module.LogsQueryClient
        tools_module.LogsQueryClient = None
        try:
            from agents.containerapps.tools import get_container_app_logs

            result = get_container_app_logs(
                app_name="app", resource_group="rg", subscription_id="sub-1"
            )
            assert result["query_status"] == "error"
            assert "azure-monitor-query" in result["error"]
        finally:
            tools_module.LogsQueryClient = original

    def test_default_lines_is_100(self):
        import inspect

        from agents.containerapps.tools import get_container_app_logs

        fn = getattr(get_container_app_logs, "__wrapped__", get_container_app_logs)
        sig = inspect.signature(fn)
        assert sig.parameters["lines"].default == 100

    def test_default_severity_is_none(self):
        import inspect

        from agents.containerapps.tools import get_container_app_logs

        fn = getattr(get_container_app_logs, "__wrapped__", get_container_app_logs)
        sig = inspect.signature(fn)
        assert sig.parameters["severity"].default is None


# ===========================================================================
# propose_container_app_scale
# ===========================================================================


class TestProposeContainerAppScale:
    """Verify propose_container_app_scale always returns approval_required=True."""

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_returns_approval_required_true(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_scale

        result = propose_container_app_scale(
            app_name="ca-api-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            min_replicas=2,
            max_replicas=10,
            reason="Replica saturation detected — avg replicas at max for 30 minutes.",
        )

        assert result["approval_required"] is True

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_risk_level_is_low(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_scale

        result = propose_container_app_scale(
            app_name="ca-api-prod",
            resource_group="rg",
            subscription_id="sub-1",
            min_replicas=1,
            max_replicas=5,
            reason="Load increase anticipated.",
        )

        assert result["risk_level"] == "low"

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_proposal_type_is_correct(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_scale

        result = propose_container_app_scale(
            app_name="app",
            resource_group="rg",
            subscription_id="sub-1",
            min_replicas=2,
            max_replicas=8,
            reason="Scale out needed.",
        )

        assert result["proposal_type"] == "container_app_scale"

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_all_fields_present(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_scale

        result = propose_container_app_scale(
            app_name="ca-api-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            min_replicas=2,
            max_replicas=10,
            reason="Scale needed.",
        )

        expected_keys = {
            "proposal_type",
            "app_name",
            "resource_group",
            "subscription_id",
            "min_replicas",
            "max_replicas",
            "reason",
            "risk_level",
            "proposed_action",
            "reversibility",
            "approval_required",
        }
        assert expected_keys.issubset(result.keys())

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_proposed_action_contains_app_name_and_replicas(
        self, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_scale

        result = propose_container_app_scale(
            app_name="payments-api",
            resource_group="rg-prod",
            subscription_id="sub-prod",
            min_replicas=3,
            max_replicas=15,
            reason="High traffic.",
        )

        assert "payments-api" in result["proposed_action"]
        assert "3" in result["proposed_action"]
        assert "15" in result["proposed_action"]

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_replica_values_preserved(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_scale

        result = propose_container_app_scale(
            app_name="app",
            resource_group="rg",
            subscription_id="sub",
            min_replicas=2,
            max_replicas=20,
            reason="Need more capacity.",
        )

        assert result["min_replicas"] == 2
        assert result["max_replicas"] == 20

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_reason_preserved(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_scale

        reason_text = "cpu_percent exceeded 80% for 20 consecutive minutes"
        result = propose_container_app_scale(
            app_name="app",
            resource_group="rg",
            subscription_id="sub",
            min_replicas=1,
            max_replicas=5,
            reason=reason_text,
        )

        assert result["reason"] == reason_text

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_reversibility_mentions_reversible(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_scale

        result = propose_container_app_scale(
            app_name="app",
            resource_group="rg",
            subscription_id="sub",
            min_replicas=1,
            max_replicas=5,
            reason="Load.",
        )

        assert "reversible" in result["reversibility"].lower()


# ===========================================================================
# propose_container_app_revision_activate
# ===========================================================================


class TestProposeContainerAppRevisionActivate:
    """Verify propose_container_app_revision_activate always returns approval_required=True."""

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_returns_approval_required_true(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_revision_activate

        result = propose_container_app_revision_activate(
            app_name="ca-api-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            revision_name="ca-api-prod--v0abc",
            reason="Rollback: v1 has 10% 5xx rate since deployment.",
        )

        assert result["approval_required"] is True

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_risk_level_is_medium(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_revision_activate

        result = propose_container_app_revision_activate(
            app_name="app",
            resource_group="rg",
            subscription_id="sub-1",
            revision_name="app--v0",
            reason="Bad deployment.",
        )

        assert result["risk_level"] == "medium"

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_proposal_type_is_correct(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_revision_activate

        result = propose_container_app_revision_activate(
            app_name="app",
            resource_group="rg",
            subscription_id="sub-1",
            revision_name="app--v0",
            reason="Rollback.",
        )

        assert result["proposal_type"] == "container_app_revision_activate"

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_all_fields_present(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_revision_activate

        result = propose_container_app_revision_activate(
            app_name="ca-api-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            revision_name="ca-api-prod--v0",
            reason="Rollback.",
        )

        expected_keys = {
            "proposal_type",
            "app_name",
            "resource_group",
            "subscription_id",
            "revision_name",
            "reason",
            "risk_level",
            "proposed_action",
            "reversibility",
            "approval_required",
        }
        assert expected_keys.issubset(result.keys())

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_proposed_action_contains_app_and_revision(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_revision_activate

        result = propose_container_app_revision_activate(
            app_name="payments-api",
            resource_group="rg-prod",
            subscription_id="sub-prod",
            revision_name="payments-api--v1abc",
            reason="Rollback.",
        )

        assert "payments-api" in result["proposed_action"]
        assert "payments-api--v1abc" in result["proposed_action"]

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_revision_name_preserved(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_revision_activate

        result = propose_container_app_revision_activate(
            app_name="app",
            resource_group="rg",
            subscription_id="sub",
            revision_name="app--rollback-target",
            reason="Error spike.",
        )

        assert result["revision_name"] == "app--rollback-target"

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_reason_preserved(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_revision_activate

        reason_text = "5xx error rate spiked to 12% within 5 minutes of v2 deployment"
        result = propose_container_app_revision_activate(
            app_name="app",
            resource_group="rg",
            subscription_id="sub",
            revision_name="app--v1",
            reason=reason_text,
        )

        assert result["reason"] == reason_text

    @patch("agents.containerapps.tools.instrument_tool_call")
    @patch("agents.containerapps.tools.get_agent_identity", return_value="test-id")
    def test_reversibility_mentions_revision(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.containerapps.tools import propose_container_app_revision_activate

        result = propose_container_app_revision_activate(
            app_name="app",
            resource_group="rg",
            subscription_id="sub",
            revision_name="app--v0",
            reason="Rollback.",
        )

        lower_rev = result["reversibility"].lower()
        assert "revision" in lower_rev or "reversible" in lower_rev
