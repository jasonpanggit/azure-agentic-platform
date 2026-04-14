"""Unit tests for Compute Agent tools (query_os_version and ALLOWED_MCP_TOOLS)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ALLOWED_MCP_TOOLS
# ---------------------------------------------------------------------------


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_tools_is_list(self):
        from agents.compute.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)

    def test_no_wildcard_in_allowed_tools(self):
        from agents.compute.tools import ALLOWED_MCP_TOOLS

        for entry in ALLOWED_MCP_TOOLS:
            assert "*" not in entry, f"Wildcard found in tool: {entry}"

    def test_allowed_tools_contains_expected_entries(self):
        from agents.compute.tools import ALLOWED_MCP_TOOLS

        assert "compute" in ALLOWED_MCP_TOOLS
        assert "monitor" in ALLOWED_MCP_TOOLS
        assert "resourcehealth" in ALLOWED_MCP_TOOLS
        assert "advisor" in ALLOWED_MCP_TOOLS
        assert "appservice" in ALLOWED_MCP_TOOLS

    def test_allowed_mcp_tools_has_exactly_five_entries(self):
        from agents.compute.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 5

    def test_allowed_mcp_tools_no_dotted_names(self):
        """v2 uses namespace names, not dotted names."""
        from agents.compute.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "." not in tool, (
                f"Dotted tool name '{tool}' found — must use v2 namespace name"
            )


# ---------------------------------------------------------------------------
# query_os_version
# ---------------------------------------------------------------------------


def _make_empty_response():
    resp = MagicMock()
    resp.data = []
    resp.skip_token = None
    return resp


def _make_instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryOsVersion:
    """Verify query_os_version — ARG calls, pagination, and error handling."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_returns_success_status_on_empty_response(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_rg_cls.return_value.resources.return_value = _make_empty_response()

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/vm-1"],
            subscription_ids=["sub-1"],
        )

        assert result["query_status"] == "success"
        assert result["machines"] == []
        assert result["total_count"] == 0

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_returns_vm_machines_with_resource_type_field(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        vm_row = {
            "id": "/sub/vm-1",
            "name": "vm1",
            "osName": "Ubuntu 22.04",
            "resourceType": "vm",
        }
        vm_resp = MagicMock()
        vm_resp.data = [vm_row]
        vm_resp.skip_token = None

        # VM query returns 1 row; Arc query returns empty
        mock_rg_cls.return_value.resources.side_effect = [vm_resp, _make_empty_response()]

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/vm-1"],
            subscription_ids=["sub-1"],
        )

        assert len(result["machines"]) == 1
        assert result["machines"][0]["resourceType"] == "vm"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_returns_arc_machines_with_resource_type_field(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        arc_row = {
            "id": "/sub/arc-1",
            "name": "arc1",
            "osType": "linux",
            "osSku": "22.04",
            "resourceType": "arc",
        }
        arc_resp = MagicMock()
        arc_resp.data = [arc_row]
        arc_resp.skip_token = None

        # VM query empty; Arc query returns 1 row
        mock_rg_cls.return_value.resources.side_effect = [_make_empty_response(), arc_resp]

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/arc-1"],
            subscription_ids=["sub-1"],
        )

        assert len(result["machines"]) == 1
        assert result["machines"][0]["osSku"] == "22.04"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_paginates_via_skip_token(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        row = {"id": "/sub/vm-1", "name": "vm1"}

        page1 = MagicMock()
        page1.data = [row]
        page1.skip_token = "tok1"

        page2 = MagicMock()
        page2.data = [row]
        page2.skip_token = None

        # VM query: page1 + page2; Arc query: empty
        mock_rg_cls.return_value.resources.side_effect = [page1, page2, _make_empty_response()]

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/vm-1"],
            subscription_ids=["sub-1"],
        )

        assert result["total_count"] == 2
        assert result["query_status"] == "success"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_returns_error_status_on_exception(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_rg_cls.return_value.resources.side_effect = Exception("ARG unavailable")

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/vm-1"],
            subscription_ids=["sub-1"],
        )

        assert result["query_status"] == "error"
        assert "ARG unavailable" in result["error"]

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_filters_by_resource_ids_in_kql(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_rg_cls.return_value.resources.return_value = _make_empty_response()

        captured_requests = []
        mock_qr.side_effect = lambda **kw: (captured_requests.append(kw), MagicMock(**kw))[1]

        from agents.compute.tools import query_os_version

        query_os_version(
            resource_ids=["/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],
            subscription_ids=["sub-1"],
        )

        # Verify the KQL passed to QueryRequest contains the in~ filter
        assert len(captured_requests) >= 1
        first_kql = captured_requests[0]["query"]
        assert "in~" in first_kql
        assert "vm1" in first_kql


# ---------------------------------------------------------------------------
# ComputeAgentWiring
# ---------------------------------------------------------------------------


def _make_agent_framework_mock():
    """Build a minimal agent_framework mock that records ChatAgent() call_args."""
    mock_af = MagicMock()
    mock_af.ChatAgent = MagicMock(return_value=MagicMock())
    mock_af.ai_function = lambda f: f  # passthrough decorator
    mock_af.tool = lambda f: f         # passthrough decorator
    return mock_af


def _make_azure_mocks():
    """Stubs for azure packages to avoid import errors in environments without them."""
    shared_auth_mock = MagicMock()
    shared_auth_mock.get_foundry_client = MagicMock(return_value=MagicMock())
    shared_auth_mock.get_agent_identity = MagicMock(return_value="test-entra-id")
    shared_auth_mock.get_credential = MagicMock(return_value=MagicMock())

    shared_otel_mock = MagicMock()
    shared_otel_mock.setup_telemetry = MagicMock(return_value=MagicMock())
    shared_otel_mock.instrument_tool_call = MagicMock()

    return {
        "azure.identity": MagicMock(),
        "azure.ai.projects": MagicMock(),
        "shared.auth": shared_auth_mock,
        "shared.otel": shared_otel_mock,
    }


class TestComputeAgentWiring:
    """Verify query_os_version is wired into the compute agent."""

    def test_query_os_version_in_agent_tools(self):
        """create_compute_agent must pass query_os_version in its tools list."""
        mock_af = _make_agent_framework_mock()
        azure_mocks = _make_azure_mocks()

        # Evict cached module so the mock takes effect on re-import
        for key in list(sys.modules.keys()):
            if "agents.compute.agent" in key or key == "compute.agent":
                del sys.modules[key]

        extra_mocks = {"agent_framework": mock_af, **azure_mocks}
        with patch.dict("sys.modules", extra_mocks):
            import agents.compute.agent as _mod
            _mod.create_compute_agent()

        call_kwargs = mock_af.ChatAgent.call_args[1]
        tools = call_kwargs.get("tools", [])
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]
        assert "query_os_version" in tool_names


# ---------------------------------------------------------------------------
# query_activity_log
# ---------------------------------------------------------------------------


class TestQueryActivityLog:
    """Verify query_activity_log calls MonitorManagementClient and handles errors."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.MonitorManagementClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_success_returns_entries(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        mock_event = MagicMock()
        mock_event.event_timestamp.isoformat.return_value = "2026-04-01T10:00:00+00:00"
        mock_event.operation_name.value = "Microsoft.Compute/virtualMachines/restart/action"
        mock_event.caller = "user@example.com"
        mock_event.status.value = "Succeeded"
        mock_event.resource_id = (
            "/subscriptions/sub123/resourceGroups/rg1/providers/"
            "Microsoft.Compute/virtualMachines/vm1"
        )
        mock_event.level.value = "Informational"
        mock_event.description = None

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.activity_logs.list.return_value = [mock_event]

        from agents.compute.tools import query_activity_log

        result = query_activity_log(
            resource_ids=[
                "/subscriptions/sub123/resourceGroups/rg1/providers/"
                "Microsoft.Compute/virtualMachines/vm1"
            ],
            timespan_hours=2,
        )

        assert result["query_status"] == "success"
        assert len(result["entries"]) == 1
        assert (
            result["entries"][0]["operationName"]
            == "Microsoft.Compute/virtualMachines/restart/action"
        )
        assert result["entries"][0]["caller"] == "user@example.com"
        assert "resource_ids" in result
        assert "timespan_hours" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.MonitorManagementClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.side_effect = Exception("Auth failed")

        from agents.compute.tools import query_activity_log

        result = query_activity_log(
            resource_ids=[
                "/subscriptions/sub123/resourceGroups/rg1/providers/"
                "Microsoft.Compute/virtualMachines/vm1"
            ]
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "Auth failed" in result["error"]
        assert result["entries"] == []

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.MonitorManagementClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_multiple_resource_ids_each_get_queried(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.activity_logs.list.return_value = []

        from agents.compute.tools import query_activity_log

        resource_ids = [
            "/subscriptions/sub123/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            "/subscriptions/sub123/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm2",
        ]
        result = query_activity_log(resource_ids=resource_ids)

        assert result["query_status"] == "success"
        # activity_logs.list should be called once per resource_id
        assert mock_client.activity_logs.list.call_count == 2


# ---------------------------------------------------------------------------
# query_log_analytics
# ---------------------------------------------------------------------------


class TestQueryLogAnalytics:
    """Verify query_log_analytics uses LogsQueryClient and handles edge cases."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_success_returns_rows(
        self, mock_cred, mock_status_cls, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        # Build mock column and row
        mock_col = MagicMock()
        mock_col.name = "Computer"
        mock_table = MagicMock()
        mock_table.columns = [mock_col]
        mock_table.rows = [["vm1.example.com"]]

        mock_response = MagicMock()
        mock_response.status = mock_status_cls.SUCCESS
        mock_response.tables = [mock_table]

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.query_workspace.return_value = mock_response

        from agents.compute.tools import query_log_analytics

        result = query_log_analytics(
            workspace_id="workspace-abc",
            kql_query="Heartbeat | take 1",
            timespan="PT1H",
        )

        assert result["query_status"] == "success"
        assert len(result["rows"]) == 1
        assert result["rows"][0]["Computer"] == "vm1.example.com"
        mock_client.query_workspace.assert_called_once_with(
            workspace_id="workspace-abc",
            query="Heartbeat | take 1",
            timespan="PT1H",
        )

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.side_effect = Exception("Log Analytics unavailable")

        from agents.compute.tools import query_log_analytics

        result = query_log_analytics(
            workspace_id="workspace-abc",
            kql_query="Heartbeat | take 1",
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "Log Analytics unavailable" in result["error"]
        assert result["rows"] == []

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_empty_workspace_id_returns_skipped(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        from agents.compute.tools import query_log_analytics

        result = query_log_analytics(
            workspace_id="",
            kql_query="Heartbeat | take 1",
        )

        assert result["query_status"] == "skipped"
        assert result["rows"] == []

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_none_workspace_id_returns_skipped(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        from agents.compute.tools import query_log_analytics

        result = query_log_analytics(
            workspace_id=None,  # type: ignore[arg-type]
            kql_query="Heartbeat | take 1",
        )

        assert result["query_status"] == "skipped"
        assert result["rows"] == []


# ---------------------------------------------------------------------------
# query_resource_health
# ---------------------------------------------------------------------------


class TestQueryResourceHealth:
    """Verify query_resource_health uses MicrosoftResourceHealth and handles errors."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.MicrosoftResourceHealth")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_success_returns_availability_state(
        self, mock_cred, mock_health_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        mock_status = MagicMock()
        mock_status.properties.availability_state.value = "Available"
        mock_status.properties.summary = "The resource is available."
        mock_status.properties.reason_type = "Unplanned"
        mock_status.properties.occurred_time.isoformat.return_value = "2026-04-01T08:00:00+00:00"

        mock_client = MagicMock()
        mock_health_cls.return_value = mock_client
        mock_client.availability_statuses.get_by_resource.return_value = mock_status

        from agents.compute.tools import query_resource_health

        resource_id = (
            "/subscriptions/sub123/resourceGroups/rg1/providers/"
            "Microsoft.Compute/virtualMachines/vm1"
        )
        result = query_resource_health(resource_id=resource_id)

        assert result["query_status"] == "success"
        assert result["availability_state"] == "Available"
        assert result["summary"] == "The resource is available."
        assert result["resource_id"] == resource_id
        mock_client.availability_statuses.get_by_resource.assert_called_once_with(
            resource_uri=resource_id,
            expand="recommendedActions",
        )

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.MicrosoftResourceHealth")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_health_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_health_cls.side_effect = Exception("Resource health API unavailable")

        from agents.compute.tools import query_resource_health

        result = query_resource_health(
            resource_id=(
                "/subscriptions/sub123/resourceGroups/rg1/providers/"
                "Microsoft.Compute/virtualMachines/vm1"
            )
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "Resource health API unavailable" in result["error"]
        assert result["availability_state"] == "Unknown"


# ---------------------------------------------------------------------------
# query_monitor_metrics
# ---------------------------------------------------------------------------


class TestQueryMonitorMetrics:
    """Verify query_monitor_metrics calls MonitorManagementClient.metrics.list."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.MonitorManagementClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_success_returns_metrics(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        mock_dp = MagicMock()
        mock_dp.time_stamp.isoformat.return_value = "2026-04-01T10:00:00+00:00"
        mock_dp.average = 42.5
        mock_dp.maximum = 88.0
        mock_dp.minimum = 12.3

        mock_ts = MagicMock()
        mock_ts.data = [mock_dp]

        mock_metric = MagicMock()
        mock_metric.name.value = "Percentage CPU"
        mock_metric.unit.value = "Percent"
        mock_metric.timeseries = [mock_ts]

        mock_response = MagicMock()
        mock_response.value = [mock_metric]

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.metrics.list.return_value = mock_response

        from agents.compute.tools import query_monitor_metrics

        resource_id = (
            "/subscriptions/sub123/resourceGroups/rg1/providers/"
            "Microsoft.Compute/virtualMachines/vm1"
        )
        result = query_monitor_metrics(
            resource_id=resource_id,
            metric_names=["Percentage CPU"],
            timespan="PT2H",
            interval="PT5M",
        )

        assert result["query_status"] == "success"
        assert len(result["metrics"]) == 1
        assert result["metrics"][0]["name"] == "Percentage CPU"
        assert result["metrics"][0]["unit"] == "Percent"
        assert len(result["metrics"][0]["timeseries"]) == 1
        assert result["metrics"][0]["timeseries"][0]["average"] == 42.5
        mock_client.metrics.list.assert_called_once_with(
            resource_uri=resource_id,
            metricnames="Percentage CPU",
            timespan="PT2H",
            interval="PT5M",
            aggregation="Average,Maximum,Minimum",
        )

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.MonitorManagementClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.side_effect = Exception("Metrics API unavailable")

        from agents.compute.tools import query_monitor_metrics

        result = query_monitor_metrics(
            resource_id=(
                "/subscriptions/sub123/resourceGroups/rg1/providers/"
                "Microsoft.Compute/virtualMachines/vm1"
            ),
            metric_names=["Percentage CPU"],
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "Metrics API unavailable" in result["error"]
        assert result["metrics"] == []

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.MonitorManagementClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_multiple_metric_names_joined_with_comma(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_response = MagicMock()
        mock_response.value = []

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.metrics.list.return_value = mock_response

        from agents.compute.tools import query_monitor_metrics

        query_monitor_metrics(
            resource_id=(
                "/subscriptions/sub123/resourceGroups/rg1/providers/"
                "Microsoft.Compute/virtualMachines/vm1"
            ),
            metric_names=["Percentage CPU", "Disk Read Bytes/sec"],
        )

        call_kwargs = mock_client.metrics.list.call_args[1]
        assert call_kwargs["metricnames"] == "Percentage CPU,Disk Read Bytes/sec"
