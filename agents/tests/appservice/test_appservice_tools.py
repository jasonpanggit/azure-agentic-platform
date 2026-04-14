"""Unit tests for App Service Agent tools (Phase 47).

Tests all 6 App Service tools + ALLOWED_MCP_TOOLS.
Each tool has success path, error path, and SDK-missing path tests.
Pattern follows agents/tests/database/test_database_tools.py.
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
        from agents.appservice.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 6

    def test_allowed_mcp_tools_contains_expected_entries(self):
        from agents.appservice.tools import ALLOWED_MCP_TOOLS

        expected = [
            "monitor.query_metrics",
            "monitor.query_logs",
            "appservice.list_sites",
            "appservice.get_site",
            "appservice.list_plans",
            "appservice.get_plan",
        ]
        for tool in expected:
            assert tool in ALLOWED_MCP_TOOLS, f"Missing: {tool}"

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.appservice.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "*" not in tool, f"Wildcard found in tool: {tool}"

    def test_allowed_mcp_tools_is_list(self):
        from agents.appservice.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)


# ===========================================================================
# get_app_service_health
# ===========================================================================


class TestGetAppServiceHealth:
    """Verify get_app_service_health returns expected structure."""

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.WebSiteManagementClient")
    def test_returns_success_with_all_fields(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        mock_plan = MagicMock()
        mock_plan.sku = MagicMock(name="P2v3")
        mock_plan.sku.name = "P2v3"
        mock_plan.current_number_of_workers = 2

        mock_site = MagicMock()
        mock_site.state = "Running"
        mock_site.server_farm_id = (
            "/subscriptions/sub-1/resourceGroups/rg-test/providers"
            "/Microsoft.Web/serverfarms/plan-prod"
        )
        mock_site.host_names = ["myapp.azurewebsites.net", "myapp.contoso.com"]
        mock_site.host_name_ssl_states = []
        mock_site.https_only = True

        web_client_instance = MagicMock()
        web_client_instance.web_apps.get.return_value = mock_site
        web_client_instance.app_service_plans.get.return_value = mock_plan
        mock_client_cls.return_value = web_client_instance

        from agents.appservice.tools import get_app_service_health

        result = get_app_service_health(
            site_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["site_name"] == "myapp"
        assert result["state"] == "Running"
        assert result["https_only"] is True
        assert result["app_service_plan"] == "plan-prod"
        assert result["sku"] == "P2v3"
        assert result["worker_count"] == 2
        assert "myapp.contoso.com" in result["custom_domains"]
        assert "myapp.azurewebsites.net" not in result["custom_domains"]
        assert "duration_ms" in result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.WebSiteManagementClient")
    def test_returns_error_on_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.web_apps.get.side_effect = Exception("ARM 404")

        from agents.appservice.tools import get_app_service_health

        result = get_app_service_health(
            site_name="missing-site",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "ARM 404" in result["error"]
        assert result["state"] is None
        assert result["custom_domains"] == []
        assert "duration_ms" in result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        import agents.appservice.tools as tools_module

        original = tools_module.WebSiteManagementClient
        tools_module.WebSiteManagementClient = None
        try:
            from agents.appservice.tools import get_app_service_health

            result = get_app_service_health(
                site_name="myapp",
                resource_group="rg-test",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "azure-mgmt-web" in result["error"]
        finally:
            tools_module.WebSiteManagementClient = original

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.WebSiteManagementClient")
    def test_custom_domains_excludes_azurewebsites(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        mock_site = MagicMock()
        mock_site.state = "Running"
        mock_site.server_farm_id = None
        mock_site.host_names = [
            "app.azurewebsites.net",
            "app.scm.azurewebsites.net",
            "app.example.com",
        ]
        mock_site.host_name_ssl_states = []
        mock_site.https_only = False

        mock_client_cls.return_value.web_apps.get.return_value = mock_site

        from agents.appservice.tools import get_app_service_health

        result = get_app_service_health(
            site_name="app",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert "app.example.com" in result["custom_domains"]
        assert "app.azurewebsites.net" not in result["custom_domains"]

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.WebSiteManagementClient")
    def test_no_server_farm_id_returns_none_plan(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        mock_site = MagicMock()
        mock_site.state = "Stopped"
        mock_site.server_farm_id = None
        mock_site.host_names = []
        mock_site.host_name_ssl_states = []
        mock_site.https_only = None

        mock_client_cls.return_value.web_apps.get.return_value = mock_site

        from agents.appservice.tools import get_app_service_health

        result = get_app_service_health(
            site_name="stopped-app",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["app_service_plan"] is None
        assert result["sku"] is None
        assert result["worker_count"] is None


# ===========================================================================
# get_app_service_metrics
# ===========================================================================


class TestGetAppServiceMetrics:
    """Verify get_app_service_metrics returns expected structure."""

    def _make_dp(self, metric_name, total=None, average=None, maximum=None):
        dp = MagicMock()
        dp.time_stamp = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
        dp.total = total
        dp.average = average
        dp.maximum = maximum
        return dp

    def _make_metric_response(self, metrics_data):
        """Build a mock metrics list response from {metric_name: [dp, ...]} dict."""
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

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.MonitorManagementClient")
    def test_returns_success_with_computed_rates(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        metrics_data = {
            "Requests": [self._make_dp("Requests", total=14400.0)],  # 14400 req / 4h = 1 rps
            "AverageResponseTime": [self._make_dp("AverageResponseTime", average=250.0)],
            "Http5xx": [self._make_dp("Http5xx", total=144.0)],  # 1% of 14400
            "CpuPercentage": [self._make_dp("CpuPercentage", average=45.0)],
            "MemoryPercentage": [self._make_dp("MemoryPercentage", average=60.0)],
        }
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response(
            metrics_data
        )

        from agents.appservice.tools import get_app_service_metrics

        result = get_app_service_metrics(
            site_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
            hours=4,
        )

        assert result["query_status"] == "success"
        assert result["site_name"] == "myapp"
        assert result["timespan_hours"] == 4
        assert result["requests_per_second"] == pytest.approx(1.0, abs=0.01)
        assert result["avg_response_time_ms"] == pytest.approx(250.0)
        assert result["http5xx_rate_pct"] == pytest.approx(1.0, abs=0.01)
        assert result["cpu_percent"] == pytest.approx(45.0)
        assert result["memory_percent"] == pytest.approx(60.0)
        assert isinstance(result["data_points"], list)
        assert "duration_ms" in result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.MonitorManagementClient")
    def test_returns_error_on_monitor_exception(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.side_effect = Exception("Monitor timeout")

        from agents.appservice.tools import get_app_service_metrics

        result = get_app_service_metrics(
            site_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "Monitor timeout" in result["error"]
        assert result["requests_per_second"] is None
        assert result["data_points"] == []
        assert "duration_ms" in result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        import agents.appservice.tools as tools_module

        original = tools_module.MonitorManagementClient
        tools_module.MonitorManagementClient = None
        try:
            from agents.appservice.tools import get_app_service_metrics

            result = get_app_service_metrics(
                site_name="myapp",
                resource_group="rg-test",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "azure-mgmt-monitor" in result["error"]
        finally:
            tools_module.MonitorManagementClient = original

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.MonitorManagementClient")
    def test_zero_requests_gives_zero_rps_and_rate(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        metrics_data = {
            "Requests": [self._make_dp("Requests", total=0.0)],
        }
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response(
            metrics_data
        )

        from agents.appservice.tools import get_app_service_metrics

        result = get_app_service_metrics(
            site_name="idle-app",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["requests_per_second"] == pytest.approx(0.0)
        assert result["http5xx_rate_pct"] == pytest.approx(0.0)

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.MonitorManagementClient")
    def test_default_hours_is_four(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response({})

        from agents.appservice.tools import get_app_service_metrics

        result = get_app_service_metrics(
            site_name="app",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["timespan_hours"] == 4


# ===========================================================================
# get_function_app_health
# ===========================================================================


class TestGetFunctionAppHealth:
    """Verify get_function_app_health returns expected structure."""

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.MonitorManagementClient")
    @patch("agents.appservice.tools.WebSiteManagementClient")
    def test_returns_success_with_all_fields(
        self,
        mock_web_cls,
        mock_mon_cls,
        mock_cred,
        mock_identity,
        mock_instrument,
    ):
        mock_instrument.return_value = _make_cm_mock()

        mock_site = MagicMock()
        mock_site.state = "Running"

        mock_settings = MagicMock()
        mock_settings.properties = {"FUNCTIONS_EXTENSION_VERSION": "~4"}

        mock_func1 = MagicMock()
        mock_func2 = MagicMock()

        web_instance = MagicMock()
        web_instance.web_apps.get.return_value = mock_site
        web_instance.web_apps.list_application_settings.return_value = mock_settings
        web_instance.web_apps.list_functions.return_value = [mock_func1, mock_func2]
        mock_web_cls.return_value = web_instance

        # Monitor metrics — FunctionExecutionCount=200, Http5xx=10
        exec_dp = MagicMock()
        exec_dp.total = 200.0
        exec_dp.maximum = None
        exec_ts = MagicMock()
        exec_ts.data = [exec_dp]
        exec_metric = MagicMock()
        exec_metric.name = MagicMock(value="FunctionExecutionCount")
        exec_metric.timeseries = [exec_ts]

        http5xx_dp = MagicMock()
        http5xx_dp.total = 10.0
        http5xx_dp.maximum = None
        http5xx_ts = MagicMock()
        http5xx_ts.data = [http5xx_dp]
        http5xx_metric = MagicMock()
        http5xx_metric.name = MagicMock(value="Http5xx")
        http5xx_metric.timeseries = [http5xx_ts]

        units_dp = MagicMock()
        units_dp.total = None
        units_dp.maximum = 1200.0
        units_ts = MagicMock()
        units_ts.data = [units_dp]
        units_metric = MagicMock()
        units_metric.name = MagicMock(value="FunctionExecutionUnits")
        units_metric.timeseries = [units_ts]

        mon_response = MagicMock()
        mon_response.value = [exec_metric, http5xx_metric, units_metric]
        mock_mon_cls.return_value.metrics.list.return_value = mon_response

        from agents.appservice.tools import get_function_app_health

        result = get_function_app_health(
            function_app_name="myfunc",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["function_app_name"] == "myfunc"
        assert result["state"] == "Running"
        assert result["runtime_version"] == "~4"
        assert result["function_count"] == 2
        assert result["invocation_count_1h"] == 200
        assert result["failure_rate_percent"] == pytest.approx(5.0)
        assert result["duration_p95_ms"] == pytest.approx(1200.0)
        assert result["throttle_count"] == 0
        assert "duration_ms" in result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.WebSiteManagementClient")
    def test_returns_error_on_exception(
        self, mock_web_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_web_cls.return_value.web_apps.get.side_effect = Exception("Not found")

        from agents.appservice.tools import get_function_app_health

        result = get_function_app_health(
            function_app_name="missing-func",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "Not found" in result["error"]
        assert result["state"] is None
        assert result["invocation_count_1h"] == 0
        assert result["throttle_count"] == 0
        assert "duration_ms" in result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    def test_returns_error_when_web_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        import agents.appservice.tools as tools_module

        original = tools_module.WebSiteManagementClient
        tools_module.WebSiteManagementClient = None
        try:
            from agents.appservice.tools import get_function_app_health

            result = get_function_app_health(
                function_app_name="myfunc",
                resource_group="rg-test",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "azure-mgmt-web" in result["error"]
        finally:
            tools_module.WebSiteManagementClient = original

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.MonitorManagementClient")
    @patch("agents.appservice.tools.WebSiteManagementClient")
    def test_zero_invocations_gives_none_failure_rate(
        self,
        mock_web_cls,
        mock_mon_cls,
        mock_cred,
        mock_identity,
        mock_instrument,
    ):
        mock_instrument.return_value = _make_cm_mock()

        mock_site = MagicMock()
        mock_site.state = "Running"
        mock_settings = MagicMock()
        mock_settings.properties = {}

        web_instance = MagicMock()
        web_instance.web_apps.get.return_value = mock_site
        web_instance.web_apps.list_application_settings.return_value = mock_settings
        web_instance.web_apps.list_functions.return_value = []
        mock_web_cls.return_value = web_instance

        exec_dp = MagicMock()
        exec_dp.total = 0.0
        exec_dp.maximum = None
        exec_ts = MagicMock()
        exec_ts.data = [exec_dp]
        exec_metric = MagicMock()
        exec_metric.name = MagicMock(value="FunctionExecutionCount")
        exec_metric.timeseries = [exec_ts]

        mon_response = MagicMock()
        mon_response.value = [exec_metric]
        mock_mon_cls.return_value.metrics.list.return_value = mon_response

        from agents.appservice.tools import get_function_app_health

        result = get_function_app_health(
            function_app_name="idle-func",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["invocation_count_1h"] == 0
        assert result["failure_rate_percent"] is None

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.MonitorManagementClient")
    @patch("agents.appservice.tools.WebSiteManagementClient")
    def test_monitor_failure_still_returns_arm_data(
        self,
        mock_web_cls,
        mock_mon_cls,
        mock_cred,
        mock_identity,
        mock_instrument,
    ):
        mock_instrument.return_value = _make_cm_mock()

        mock_site = MagicMock()
        mock_site.state = "Running"
        mock_settings = MagicMock()
        mock_settings.properties = {"FUNCTIONS_EXTENSION_VERSION": "~4"}

        web_instance = MagicMock()
        web_instance.web_apps.get.return_value = mock_site
        web_instance.web_apps.list_application_settings.return_value = mock_settings
        web_instance.web_apps.list_functions.return_value = []
        mock_web_cls.return_value = web_instance

        mock_mon_cls.return_value.metrics.list.side_effect = Exception("Monitor unavailable")

        from agents.appservice.tools import get_function_app_health

        result = get_function_app_health(
            function_app_name="myfunc",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        # ARM data should still be present even when Monitor fails gracefully
        assert result["query_status"] == "success"
        assert result["state"] == "Running"
        assert result["runtime_version"] == "~4"
        assert result["invocation_count_1h"] == 0


# ===========================================================================
# query_app_insights_failures
# ===========================================================================


class TestQueryAppInsightsFailures:
    """Verify query_app_insights_failures returns expected structure."""

    def _make_logs_result(self, rows, col_names=None):
        """Build a mock LogsQueryResult."""
        if col_names is None:
            col_names = ["type", "outerMessage", "ExceptionCount"]
        mock_col = [MagicMock(name=c) for c in col_names]
        for i, c in enumerate(col_names):
            mock_col[i].name = c
        mock_table = MagicMock()
        mock_table.columns = mock_col
        mock_table.rows = rows
        from unittest.mock import MagicMock as MM

        result = MM()
        result.tables = [mock_table]
        return result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.LogsQueryStatus")
    @patch("agents.appservice.tools.LogsQueryClient")
    def test_returns_success_with_exceptions_and_deps(
        self, mock_logs_cls, mock_status_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        exc_rows = [
            ["System.NullReferenceException", "Object reference not set", 45],
            ["System.TimeoutException", "Operation timed out", 12],
        ]
        dep_rows = [
            [
                datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc),
                "GET /api/users",
                "sqlserver.database.windows.net",
                "500",
                250.0,
                "SQL",
            ]
        ]

        exc_result = self._make_logs_result(
            exc_rows, col_names=["type", "outerMessage", "ExceptionCount"]
        )
        dep_result = self._make_logs_result(
            dep_rows,
            col_names=["timestamp", "name", "target", "resultCode", "duration", "type"],
        )

        mock_status_cls.SUCCESS = "Success"
        exc_result.status = "Success"
        dep_result.status = "Success"

        client_instance = MagicMock()
        client_instance.query_workspace.side_effect = [exc_result, dep_result]
        mock_logs_cls.return_value = client_instance

        from agents.appservice.tools import query_app_insights_failures

        result = query_app_insights_failures(
            app_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
            hours=2,
        )

        assert result["query_status"] == "success"
        assert result["app_name"] == "myapp"
        assert result["timespan_hours"] == 2
        assert len(result["top_exceptions"]) == 2
        assert len(result["dependency_failures"]) == 1
        assert result["exception_count"] == 57  # 45 + 12
        assert result["dependency_failure_count"] == 1
        assert "duration_ms" in result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.LogsQueryClient")
    def test_returns_error_on_client_exception(
        self, mock_logs_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_logs_cls.side_effect = Exception("Workspace not found")

        from agents.appservice.tools import query_app_insights_failures

        result = query_app_insights_failures(
            app_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "Workspace not found" in result["error"]
        assert result["top_exceptions"] == []
        assert result["dependency_failures"] == []
        assert result["exception_count"] == 0
        assert "duration_ms" in result

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        import agents.appservice.tools as tools_module

        original = tools_module.LogsQueryClient
        tools_module.LogsQueryClient = None
        try:
            from agents.appservice.tools import query_app_insights_failures

            result = query_app_insights_failures(
                app_name="myapp",
                resource_group="rg-test",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "azure-monitor-query" in result["error"]
        finally:
            tools_module.LogsQueryClient = original

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    @patch("agents.appservice.tools.get_credential", return_value=MagicMock())
    @patch("agents.appservice.tools.LogsQueryStatus")
    @patch("agents.appservice.tools.LogsQueryClient")
    def test_partial_query_failure_returns_empty_lists(
        self, mock_logs_cls, mock_status_cls, mock_cred, mock_identity, mock_instrument
    ):
        """Both sub-queries fail gracefully — top-level query_status should still be success."""
        mock_instrument.return_value = _make_cm_mock()

        client_instance = MagicMock()
        client_instance.query_workspace.side_effect = Exception("Sub-query timeout")
        mock_logs_cls.return_value = client_instance

        from agents.appservice.tools import query_app_insights_failures

        result = query_app_insights_failures(
            app_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
        )

        # Both sub-queries fail silently; overall status is success
        assert result["query_status"] == "success"
        assert result["top_exceptions"] == []
        assert result["dependency_failures"] == []
        assert result["exception_count"] == 0

    def test_default_hours_is_two(self):
        """Default hours parameter should be 2."""
        import inspect

        from agents.appservice.tools import query_app_insights_failures

        sig = inspect.signature(query_app_insights_failures)
        # The underlying function is wrapped by @ai_function; check __wrapped__ if present
        fn = getattr(query_app_insights_failures, "__wrapped__", query_app_insights_failures)
        sig = inspect.signature(fn)
        assert sig.parameters["hours"].default == 2


# ===========================================================================
# propose_app_service_restart
# ===========================================================================


class TestProposeAppServiceRestart:
    """Verify propose_app_service_restart always returns approval_required=True."""

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_returns_approval_required_true(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_app_service_restart

        result = propose_app_service_restart(
            site_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
            reason="Site returning 500 errors for 15 minutes; health check failing.",
        )

        assert result["approval_required"] is True

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_risk_level_is_low(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_app_service_restart

        result = propose_app_service_restart(
            site_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
            reason="Memory leak detected.",
        )

        assert result["risk_level"] == "low"

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_proposal_type_is_correct(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_app_service_restart

        result = propose_app_service_restart(
            site_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
            reason="Health check failing.",
        )

        assert result["proposal_type"] == "app_service_restart"

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_all_fields_present(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_app_service_restart

        result = propose_app_service_restart(
            site_name="myapp",
            resource_group="rg-test",
            subscription_id="sub-1",
            reason="Periodic restart to clear leaked handles.",
        )

        expected_keys = {
            "proposal_type",
            "site_name",
            "resource_group",
            "subscription_id",
            "reason",
            "risk_level",
            "proposed_action",
            "reversibility",
            "approval_required",
        }
        assert expected_keys.issubset(result.keys())

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_proposed_action_contains_site_name(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_app_service_restart

        result = propose_app_service_restart(
            site_name="webapp-prod",
            resource_group="rg-prod",
            subscription_id="sub-prod",
            reason="Unhealthy.",
        )

        assert "webapp-prod" in result["proposed_action"]

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_reason_preserved_in_result(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_app_service_restart

        reason_text = "cpu_percent exceeded 95% for 10 consecutive minutes"
        result = propose_app_service_restart(
            site_name="app",
            resource_group="rg",
            subscription_id="sub",
            reason=reason_text,
        )

        assert result["reason"] == reason_text


# ===========================================================================
# propose_function_app_scale_out
# ===========================================================================


class TestProposeFunctionAppScaleOut:
    """Verify propose_function_app_scale_out always returns approval_required=True."""

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_returns_approval_required_true(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_function_app_scale_out

        result = propose_function_app_scale_out(
            function_app_name="myfunc",
            resource_group="rg-test",
            subscription_id="sub-1",
            target_instances=5,
            reason="Throttling detected — invocation queue depth rising.",
        )

        assert result["approval_required"] is True

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_risk_level_is_low(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_function_app_scale_out

        result = propose_function_app_scale_out(
            function_app_name="myfunc",
            resource_group="rg-test",
            subscription_id="sub-1",
            target_instances=3,
            reason="High failure rate.",
        )

        assert result["risk_level"] == "low"

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_proposal_type_is_correct(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_function_app_scale_out

        result = propose_function_app_scale_out(
            function_app_name="myfunc",
            resource_group="rg-test",
            subscription_id="sub-1",
            target_instances=4,
            reason="Scale for load.",
        )

        assert result["proposal_type"] == "function_app_scale_out"

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_target_instances_preserved(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_function_app_scale_out

        result = propose_function_app_scale_out(
            function_app_name="func",
            resource_group="rg",
            subscription_id="sub",
            target_instances=10,
            reason="Need more.",
        )

        assert result["target_instances"] == 10

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_all_fields_present(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_function_app_scale_out

        result = propose_function_app_scale_out(
            function_app_name="myfunc",
            resource_group="rg-test",
            subscription_id="sub-1",
            target_instances=5,
            reason="Scale needed.",
        )

        expected_keys = {
            "proposal_type",
            "function_app_name",
            "resource_group",
            "subscription_id",
            "target_instances",
            "reason",
            "risk_level",
            "proposed_action",
            "reversibility",
            "approval_required",
        }
        assert expected_keys.issubset(result.keys())

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_proposed_action_contains_function_app_name(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_function_app_scale_out

        result = propose_function_app_scale_out(
            function_app_name="payments-func",
            resource_group="rg-prod",
            subscription_id="sub-prod",
            target_instances=6,
            reason="High load.",
        )

        assert "payments-func" in result["proposed_action"]
        assert "6" in result["proposed_action"]

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_reason_preserved_in_result(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_function_app_scale_out

        reason_text = "throttle_count exceeded 100 in last 1h"
        result = propose_function_app_scale_out(
            function_app_name="func",
            resource_group="rg",
            subscription_id="sub",
            target_instances=3,
            reason=reason_text,
        )

        assert result["reason"] == reason_text

    @patch("agents.appservice.tools.instrument_tool_call")
    @patch("agents.appservice.tools.get_agent_identity", return_value="test-id")
    def test_reversibility_mentions_scale_in(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.appservice.tools import propose_function_app_scale_out

        result = propose_function_app_scale_out(
            function_app_name="func",
            resource_group="rg",
            subscription_id="sub",
            target_instances=2,
            reason="Load.",
        )

        assert "reversible" in result["reversibility"].lower() or "scale" in result["reversibility"].lower()
