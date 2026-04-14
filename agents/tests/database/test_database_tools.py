"""Unit tests for Database Agent tools (Phase 46).

Tests all 12 database tools + ALLOWED_MCP_TOOLS.
Each tool has success path, error path, and SDK-missing path tests.
Pattern follows agents/tests/sre/test_sre_tools.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# ALLOWED_MCP_TOOLS
# ===========================================================================


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_mcp_tools_has_exactly_six_entries(self):
        from agents.database.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 6

    def test_allowed_mcp_tools_contains_expected_entries(self):
        from agents.database.tools import ALLOWED_MCP_TOOLS

        expected = [
            "monitor.query_metrics",
            "monitor.query_logs",
            "cosmos.list_accounts",
            "cosmos.get_account",
            "postgres.list",
            "sql.list",
        ]
        for tool in expected:
            assert tool in ALLOWED_MCP_TOOLS, f"Missing: {tool}"

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.database.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "*" not in tool, f"Wildcard found in tool: {tool}"


# ===========================================================================
# get_cosmos_account_health
# ===========================================================================


class TestGetCosmosAccountHealth:
    """Verify get_cosmos_account_health returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.CosmosDBManagementClient")
    def test_returns_success_with_all_fields(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        mock_loc = MagicMock(
            location_name="East US",
            failover_priority=0,
            is_zone_redundant=True,
        )
        mock_consistency = MagicMock(default_consistency_level="Session")
        mock_backup = MagicMock()
        mock_backup.type = "Periodic"

        mock_account = MagicMock(
            provisioning_state="Succeeded",
            document_endpoint="https://myaccount.documents.azure.com:443/",
            consistency_policy=mock_consistency,
            enable_multiple_write_locations=False,
            locations=[mock_loc],
            backup_policy=mock_backup,
        )
        mock_client_cls.return_value.database_accounts.get.return_value = mock_account

        from agents.database.tools import get_cosmos_account_health

        result = get_cosmos_account_health(
            account_name="myaccount",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert result["provisioning_state"] == "Succeeded"
        assert result["consistency_level"] == "Session"
        assert result["multi_region_writes"] is False
        assert len(result["locations"]) == 1
        assert result["locations"][0]["location_name"] == "East US"
        assert result["backup_policy_type"] == "Periodic"

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.CosmosDBManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.database_accounts.get.side_effect = Exception(
            "CosmosDB unavailable"
        )

        from agents.database.tools import get_cosmos_account_health

        result = get_cosmos_account_health(
            account_name="myaccount",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "CosmosDB unavailable" in result["error"]
        assert result["provisioning_state"] is None
        assert result["locations"] == []

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.CosmosDBManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import get_cosmos_account_health

        result = get_cosmos_account_health(
            account_name="myaccount",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# get_cosmos_throughput_metrics
# ===========================================================================


class TestGetCosmosThroughputMetrics:
    """Verify get_cosmos_throughput_metrics returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    def _make_cosmos_account_id(self):
        return (
            "/subscriptions/sub-test-1/resourceGroups/rg/providers/"
            "Microsoft.DocumentDB/databaseAccounts/myaccount"
        )

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient")
    def test_returns_success_with_metrics(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        # Build mock metrics
        def make_metric(name_val, total=None, avg=None, maximum=None):
            dp = MagicMock(
                time_stamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                total=total,
                average=avg,
                maximum=maximum,
            )
            ts = MagicMock(data=[dp])
            metric = MagicMock(timeseries=[ts])
            metric.name = MagicMock(value=name_val)
            return metric

        mock_metrics = [
            make_metric("TotalRequestUnits", total=5000.0),
            make_metric("NormalizedRUConsumption", maximum=85.0),
            make_metric("ServerSideLatency", avg=12.5),
            make_metric("Http429s", total=3.0),
        ]
        mock_client_cls.return_value.metrics.list.return_value = MagicMock(
            value=mock_metrics
        )

        from agents.database.tools import get_cosmos_throughput_metrics

        result = get_cosmos_throughput_metrics(
            account_id=self._make_cosmos_account_id(),
        )

        assert result["query_status"] == "success"
        assert result["http_429_count"] == 3
        assert result["ru_utilization_pct"] == pytest.approx(85.0)
        assert result["server_side_latency_avg_ms"] == pytest.approx(12.5)
        assert len(result["total_request_units"]) == 1
        assert len(result["normalized_ru_consumption"]) == 1

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient")
    def test_returns_zero_429_when_no_throttling(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.metrics.list.return_value = MagicMock(value=[])

        from agents.database.tools import get_cosmos_throughput_metrics

        result = get_cosmos_throughput_metrics(
            account_id=self._make_cosmos_account_id(),
        )

        assert result["query_status"] == "success"
        assert result["http_429_count"] == 0
        assert result["ru_utilization_pct"] is None

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.metrics.list.side_effect = Exception(
            "Monitor unavailable"
        )

        from agents.database.tools import get_cosmos_throughput_metrics

        result = get_cosmos_throughput_metrics(
            account_id=self._make_cosmos_account_id(),
        )

        assert result["query_status"] == "error"
        assert "Monitor unavailable" in result["error"]

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import get_cosmos_throughput_metrics

        result = get_cosmos_throughput_metrics(
            account_id=self._make_cosmos_account_id(),
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# query_cosmos_diagnostic_logs
# ===========================================================================


class TestQueryCosmosDiagnosticLogs:
    """Verify query_cosmos_diagnostic_logs returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    def _make_logs_result(self, rows, col_names=None):
        """Build a mock LogsQueryResult with SUCCESS status."""
        from unittest.mock import MagicMock

        col_names = col_names or ["PartitionKeyRangeId", "RequestCount"]
        cols = [MagicMock(name=c) for c in col_names]
        table = MagicMock(columns=cols, rows=rows)
        result = MagicMock()
        result.tables = [table]

        # Patch LogsQueryStatus.SUCCESS comparison
        import agents.database.tools as tools_module
        if tools_module.LogsQueryStatus is not None:
            result.status = tools_module.LogsQueryStatus.SUCCESS
        else:
            result.status = "SUCCESS"

        return result

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient")
    @patch("agents.database.tools.LogsQueryStatus")
    def test_returns_success_with_hot_partitions(
        self, mock_status_cls, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        mock_status_cls.SUCCESS = "SUCCESS"

        hot_partition_rows = [["partition-0", 5000], ["partition-1", 3200]]
        col0, col1 = MagicMock(), MagicMock()
        col0.name = "PartitionKeyRangeId"
        col1.name = "RequestCount"
        table = MagicMock(columns=[col0, col1], rows=hot_partition_rows)
        mock_hp_result = MagicMock(tables=[table], status="SUCCESS")

        empty_result = MagicMock(tables=[], status="SUCCESS")

        mock_client_cls.return_value.query_workspace.side_effect = [
            mock_hp_result,  # hot partitions
            empty_result,    # throttled ops
            empty_result,    # high latency
        ]

        from agents.database.tools import query_cosmos_diagnostic_logs

        result = query_cosmos_diagnostic_logs(
            workspace_id="ws-test-1",
            account_name="myaccount",
        )

        assert result["query_status"] == "success"
        assert len(result["hot_partitions"]) == 2
        assert result["hot_partitions"][0]["PartitionKeyRangeId"] == "partition-0"

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient")
    @patch("agents.database.tools.LogsQueryStatus")
    def test_partial_failure_still_returns_success(
        self, mock_status_cls, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        """Even if sub-queries fail, overall status is success."""
        mock_instrument.return_value = self._make_instrument_mock()
        mock_status_cls.SUCCESS = "SUCCESS"

        mock_client_cls.return_value.query_workspace.side_effect = [
            Exception("Workspace not configured"),  # hot partitions fails
            Exception("Query timeout"),              # throttled fails
            Exception("Query timeout"),              # latency fails
        ]

        from agents.database.tools import query_cosmos_diagnostic_logs

        result = query_cosmos_diagnostic_logs(
            workspace_id="ws-test-1",
            account_name="myaccount",
        )

        assert result["query_status"] == "success"
        assert result["hot_partitions"] == []
        assert result["throttled_operations"] == []
        assert result["high_latency_operations"] == []

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient")
    def test_returns_error_when_client_init_fails(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.side_effect = Exception("Auth failed")

        from agents.database.tools import query_cosmos_diagnostic_logs

        result = query_cosmos_diagnostic_logs(
            workspace_id="ws-test-1",
            account_name="myaccount",
        )

        assert result["query_status"] == "error"
        assert "Auth failed" in result["error"]

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import query_cosmos_diagnostic_logs

        result = query_cosmos_diagnostic_logs(
            workspace_id="ws-test-1",
            account_name="myaccount",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# propose_cosmos_throughput_scale
# ===========================================================================


class TestProposeCosmosThroughputScale:
    """Verify propose_cosmos_throughput_scale returns HITL structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    def test_returns_approval_required_true(self, mock_identity, mock_instrument):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import propose_cosmos_throughput_scale

        result = propose_cosmos_throughput_scale(
            account_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/myaccount",
            container_id="mydb/mycontainer",
            current_ru=1000,
            proposed_ru=2000,
            rationale="NormalizedRUConsumption reached 95% for 30 minutes",
        )

        assert result["approval_required"] is True
        assert result["proposal_type"] == "cosmos_throughput_scale"
        assert result["current_ru"] == 1000
        assert result["proposed_ru"] == 2000
        assert result["ru_increase_pct"] == pytest.approx(100.0)

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    def test_risk_level_low_for_small_increase(self, mock_identity, mock_instrument):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import propose_cosmos_throughput_scale

        result = propose_cosmos_throughput_scale(
            account_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/myaccount",
            container_id="mydb/mycontainer",
            current_ru=1000,
            proposed_ru=1400,
            rationale="Moderate increase",
        )

        assert result["risk_level"] == "low"

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    def test_contains_all_required_fields(self, mock_identity, mock_instrument):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import propose_cosmos_throughput_scale

        result = propose_cosmos_throughput_scale(
            account_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/myaccount",
            container_id="mydb/mycontainer",
            current_ru=400,
            proposed_ru=800,
            rationale="Test",
        )

        required_fields = [
            "proposal_type", "account_id", "container_id", "current_ru",
            "proposed_ru", "ru_increase_pct", "rationale", "risk_level",
            "proposed_action", "reversibility", "approval_required",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"


# ===========================================================================
# get_postgres_server_health
# ===========================================================================


class TestGetPostgresServerHealth:
    """Verify get_postgres_server_health returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.PostgreSQLManagementClient")
    def test_returns_success_with_server_properties(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        mock_ha = MagicMock()
        mock_ha.state = "Healthy"
        mock_sku = MagicMock()
        mock_sku.name = "Standard_D4ds_v5"
        mock_storage = MagicMock(storage_size_gb=512)
        mock_backup = MagicMock(backup_retention_days=7)
        mock_server = MagicMock(
            state="Ready",
            high_availability=mock_ha,
            replication_role="Primary",
            sku=mock_sku,
            version="14",
            storage=mock_storage,
            backup=mock_backup,
        )
        mock_client_cls.return_value.servers.get.return_value = mock_server

        from agents.database.tools import get_postgres_server_health

        result = get_postgres_server_health(
            server_name="pg-test",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert "Ready" in result["state"]
        assert result["ha_state"] == "Healthy"
        assert result["sku_name"] == "Standard_D4ds_v5"
        assert result["storage_size_gb"] == 512
        assert result["backup_retention_days"] == 7

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.PostgreSQLManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.servers.get.side_effect = Exception("Server not found")

        from agents.database.tools import get_postgres_server_health

        result = get_postgres_server_health(
            server_name="pg-test",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "Server not found" in result["error"]

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.PostgreSQLManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import get_postgres_server_health

        result = get_postgres_server_health(
            server_name="pg-test",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# get_postgres_metrics
# ===========================================================================


class TestGetPostgresMetrics:
    """Verify get_postgres_metrics returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    def _make_server_id(self):
        return (
            "/subscriptions/sub-test-1/resourceGroups/rg/providers/"
            "Microsoft.DBforPostgreSQL/flexibleServers/pg-test"
        )

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient")
    def test_returns_success_with_metrics(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        dp = MagicMock(
            time_stamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            average=72.5,
            maximum=85.0,
            total=None,
        )
        ts = MagicMock(data=[dp])
        metric = MagicMock(timeseries=[ts])
        metric.name = MagicMock(value="cpu_percent")
        mock_client_cls.return_value.metrics.list.return_value = MagicMock(
            value=[metric]
        )

        from agents.database.tools import get_postgres_metrics

        result = get_postgres_metrics(server_id=self._make_server_id())

        assert result["query_status"] == "success"
        assert len(result["metrics"]) == 1
        assert result["metrics"][0]["metric_name"] == "cpu_percent"
        assert result["metrics"][0]["avg"] == pytest.approx(72.5)
        assert result["metrics"][0]["max"] == pytest.approx(85.0)

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.metrics.list.side_effect = Exception(
            "Metrics unavailable"
        )

        from agents.database.tools import get_postgres_metrics

        result = get_postgres_metrics(server_id=self._make_server_id())

        assert result["query_status"] == "error"
        assert "Metrics unavailable" in result["error"]

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import get_postgres_metrics

        result = get_postgres_metrics(server_id=self._make_server_id())

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# query_postgres_slow_queries
# ===========================================================================


class TestQueryPostgresSlowQueries:
    """Verify query_postgres_slow_queries returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient")
    @patch("agents.database.tools.LogsQueryStatus")
    def test_returns_success_with_slow_queries(
        self, mock_status_cls, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_status_cls.SUCCESS = "SUCCESS"

        col_names = ["TimeGenerated", "DurationMs", "Message", "Resource"]
        cols = []
        for cn in col_names:
            c = MagicMock()
            c.name = cn
            cols.append(c)
        rows = [
            ["2026-01-01T12:00:00Z", 4500.0, "duration: 4500 ms  statement: SELECT *...", "pg-test"],
            ["2026-01-01T12:05:00Z", 2300.0, "duration: 2300 ms  statement: UPDATE ...", "pg-test"],
        ]
        table = MagicMock(columns=cols, rows=rows)
        mock_result = MagicMock(tables=[table], status="SUCCESS")
        mock_client_cls.return_value.query_workspace.return_value = mock_result

        from agents.database.tools import query_postgres_slow_queries

        result = query_postgres_slow_queries(
            workspace_id="ws-test-1",
            server_name="pg-test",
        )

        assert result["query_status"] == "success"
        assert result["slow_query_count"] == 2
        assert result["slow_queries"][0]["DurationMs"] == pytest.approx(4500.0)

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.query_workspace.side_effect = Exception("LA timeout")

        from agents.database.tools import query_postgres_slow_queries

        result = query_postgres_slow_queries(
            workspace_id="ws-test-1",
            server_name="pg-test",
        )

        assert result["query_status"] == "error"
        assert "LA timeout" in result["error"]

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import query_postgres_slow_queries

        result = query_postgres_slow_queries(
            workspace_id="ws-test-1",
            server_name="pg-test",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# propose_postgres_sku_scale
# ===========================================================================


class TestProposePostgresSkuScale:
    """Verify propose_postgres_sku_scale returns HITL structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    def test_returns_approval_required_true(self, mock_identity, mock_instrument):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import propose_postgres_sku_scale

        result = propose_postgres_sku_scale(
            server_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-test",
            current_sku="Standard_D4ds_v5",
            proposed_sku="Standard_D8ds_v5",
            rationale="CPU sustained above 85% for 1 hour",
        )

        assert result["approval_required"] is True
        assert result["proposal_type"] == "postgres_sku_scale"
        assert result["current_sku"] == "Standard_D4ds_v5"
        assert result["proposed_sku"] == "Standard_D8ds_v5"

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    def test_contains_all_required_fields(self, mock_identity, mock_instrument):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import propose_postgres_sku_scale

        result = propose_postgres_sku_scale(
            server_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-test",
            current_sku="Standard_D4ds_v5",
            proposed_sku="Standard_D8ds_v5",
            rationale="Test",
        )

        required_fields = [
            "proposal_type", "server_id", "current_sku", "proposed_sku",
            "rationale", "risk_level", "proposed_action", "reversibility",
            "approval_required",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"


# ===========================================================================
# get_sql_database_health
# ===========================================================================


class TestGetSqlDatabaseHealth:
    """Verify get_sql_database_health returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.SqlManagementClient")
    def test_returns_success_with_database_properties(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        mock_db = MagicMock(
            status="Online",
            edition="Standard",
            current_service_objective_name="S3",
            zone_redundant=True,
            elastic_pool_id=None,
            max_size_bytes=268435456000,
        )
        mock_client_cls.return_value.databases.get.return_value = mock_db

        from agents.database.tools import get_sql_database_health

        result = get_sql_database_health(
            server_name="sql-test",
            database_name="mydb",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert "Online" in result["status"]
        assert result["edition"] == "Standard"
        assert result["service_objective"] == "S3"
        assert result["zone_redundant"] is True
        assert result["elastic_pool_id"] is None

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.SqlManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.databases.get.side_effect = Exception("SQL not found")

        from agents.database.tools import get_sql_database_health

        result = get_sql_database_health(
            server_name="sql-test",
            database_name="mydb",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "SQL not found" in result["error"]

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.SqlManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import get_sql_database_health

        result = get_sql_database_health(
            server_name="sql-test",
            database_name="mydb",
            resource_group="rg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# get_sql_dtu_metrics
# ===========================================================================


class TestGetSqlDtuMetrics:
    """Verify get_sql_dtu_metrics returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    def _make_database_id(self):
        return (
            "/subscriptions/sub-test-1/resourceGroups/rg/providers/"
            "Microsoft.Sql/servers/sql-test/databases/mydb"
        )

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient")
    def test_returns_success_with_dtu_metrics(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        def make_metric(name_val, avg=None, maximum=None, total=None):
            dp = MagicMock(
                time_stamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                average=avg,
                maximum=maximum,
                total=total,
            )
            ts = MagicMock(data=[dp])
            metric = MagicMock(timeseries=[ts])
            metric.name = MagicMock(value=name_val)
            return metric

        mock_metrics = [
            make_metric("dtu_consumption_percent", avg=70.0, maximum=92.0),
            make_metric("deadlock", total=5.0),
            make_metric("sessions_percent", avg=30.0, maximum=45.0),
        ]
        mock_client_cls.return_value.metrics.list.return_value = MagicMock(
            value=mock_metrics
        )

        from agents.database.tools import get_sql_dtu_metrics

        result = get_sql_dtu_metrics(database_id=self._make_database_id())

        assert result["query_status"] == "success"
        assert result["dtu_utilization_pct"] == pytest.approx(92.0)
        assert result["deadlock_count"] == 5
        assert len(result["metrics"]) == 3

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient")
    def test_returns_zero_deadlocks_when_no_data(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.metrics.list.return_value = MagicMock(value=[])

        from agents.database.tools import get_sql_dtu_metrics

        result = get_sql_dtu_metrics(database_id=self._make_database_id())

        assert result["query_status"] == "success"
        assert result["deadlock_count"] == 0
        assert result["dtu_utilization_pct"] is None

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.metrics.list.side_effect = Exception("SQL metrics unavailable")

        from agents.database.tools import get_sql_dtu_metrics

        result = get_sql_dtu_metrics(database_id=self._make_database_id())

        assert result["query_status"] == "error"
        assert "SQL metrics unavailable" in result["error"]

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.MonitorManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import get_sql_dtu_metrics

        result = get_sql_dtu_metrics(database_id=self._make_database_id())

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# query_sql_query_store
# ===========================================================================


class TestQuerySqlQueryStore:
    """Verify query_sql_query_store returns expected structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient")
    @patch("agents.database.tools.LogsQueryStatus")
    def test_returns_success_with_top_queries(
        self, mock_status_cls, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_status_cls.SUCCESS = "SUCCESS"

        col_names = ["query_id_d", "AvgDurationMs", "ExecutionCount"]
        cols = []
        for cn in col_names:
            c = MagicMock()
            c.name = cn
            cols.append(c)
        rows = [
            ["query-001", 850.0, 124],
            ["query-002", 520.0, 300],
        ]
        table = MagicMock(columns=cols, rows=rows)
        mock_result = MagicMock(tables=[table], status="SUCCESS")
        mock_client_cls.return_value.query_workspace.return_value = mock_result

        from agents.database.tools import query_sql_query_store

        result = query_sql_query_store(
            workspace_id="ws-test-1",
            server_name="sql-test",
            database_name="mydb",
        )

        assert result["query_status"] == "success"
        assert result["query_count"] == 2
        assert result["top_queries"][0]["query_id_d"] == "query-001"

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()
        mock_client_cls.return_value.query_workspace.side_effect = Exception("Workspace unavailable")

        from agents.database.tools import query_sql_query_store

        result = query_sql_query_store(
            workspace_id="ws-test-1",
            server_name="sql-test",
            database_name="mydb",
        )

        assert result["query_status"] == "error"
        assert "Workspace unavailable" in result["error"]

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    @patch("agents.database.tools.get_credential", return_value=MagicMock())
    @patch("agents.database.tools.LogsQueryClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import query_sql_query_store

        result = query_sql_query_store(
            workspace_id="ws-test-1",
            server_name="sql-test",
            database_name="mydb",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ===========================================================================
# propose_sql_elastic_pool_move
# ===========================================================================


class TestProposeSqlElasticPoolMove:
    """Verify propose_sql_elastic_pool_move returns HITL structure."""

    def _make_instrument_mock(self):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock())
        m.__exit__ = MagicMock(return_value=False)
        return m

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    def test_returns_approval_required_true(self, mock_identity, mock_instrument):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import propose_sql_elastic_pool_move

        result = propose_sql_elastic_pool_move(
            database_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Sql/servers/sql-test/databases/mydb",
            target_elastic_pool_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Sql/servers/sql-test/elasticPools/pool-1",
            rationale="DTU consumption averaging 90% — elastic pool sharing will reduce peak pressure",
        )

        assert result["approval_required"] is True
        assert result["proposal_type"] == "sql_elastic_pool_move"

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    def test_contains_all_required_fields(self, mock_identity, mock_instrument):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import propose_sql_elastic_pool_move

        result = propose_sql_elastic_pool_move(
            database_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Sql/servers/sql-test/databases/mydb",
            target_elastic_pool_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Sql/servers/sql-test/elasticPools/pool-1",
            rationale="Test",
        )

        required_fields = [
            "proposal_type", "database_id", "target_elastic_pool_id",
            "rationale", "risk_level", "proposed_action", "reversibility",
            "approval_required",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    @patch("agents.database.tools.instrument_tool_call")
    @patch("agents.database.tools.get_agent_identity", return_value="test-id")
    def test_risk_level_is_medium(self, mock_identity, mock_instrument):
        mock_instrument.return_value = self._make_instrument_mock()

        from agents.database.tools import propose_sql_elastic_pool_move

        result = propose_sql_elastic_pool_move(
            database_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Sql/servers/sql-test/databases/mydb",
            target_elastic_pool_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Sql/servers/sql-test/elasticPools/pool-1",
            rationale="Test",
        )

        assert result["risk_level"] == "medium"


# ===========================================================================
# _extract_subscription_id helper
# ===========================================================================


class TestExtractSubscriptionId:
    """Verify _extract_subscription_id helper."""

    def test_extracts_subscription_from_resource_id(self):
        from agents.database.tools import _extract_subscription_id

        resource_id = (
            "/subscriptions/abc-123/resourceGroups/rg/providers/"
            "Microsoft.DocumentDB/databaseAccounts/myaccount"
        )
        assert _extract_subscription_id(resource_id) == "abc-123"

    def test_raises_on_invalid_resource_id(self):
        from agents.database.tools import _extract_subscription_id

        with pytest.raises(ValueError, match="Cannot extract subscription_id"):
            _extract_subscription_id("not-a-valid-resource-id")

    def test_case_insensitive_extraction(self):
        from agents.database.tools import _extract_subscription_id

        resource_id = (
            "/SUBSCRIPTIONS/UPPER-CASE-SUB/resourceGroups/rg/providers/"
            "Microsoft.Sql/servers/myserver"
        )
        assert _extract_subscription_id(resource_id) == "upper-case-sub"
