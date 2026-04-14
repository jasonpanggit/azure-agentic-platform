"""Unit tests for FinOps Agent tools (Phase 52).

Tests all 6 finops tools + ALLOWED_MCP_TOOLS constants.
Each tool has success path, error path, and SDK-missing path tests.
Pattern follows agents/tests/compute/test_compute_cost.py — patches all
SDK model types (QueryDefinition, TimeframeType, etc.) alongside the client.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

# Patch targets for all CostManagement SDK model types
_CM_PATCHES = [
    "agents.finops.tools.CostManagementClient",
    "agents.finops.tools.QueryDefinition",
    "agents.finops.tools.TimeframeType",
    "agents.finops.tools.GranularityType",
    "agents.finops.tools.QueryTimePeriod",
    "agents.finops.tools.QueryDataset",
    "agents.finops.tools.QueryAggregation",
    "agents.finops.tools.QueryGrouping",
]


def _make_cm_mock():
    """Return a context-manager mock for instrument_tool_call."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


def _make_cost_result(rows, column_names=None):
    """Build a mock CostManagementClient query result with named columns."""
    if column_names is None:
        column_names = ["Cost", "BillingMonth", "Currency", "ResourceGroup"]
    result = MagicMock()
    result.columns = []
    for c in column_names:
        col = MagicMock()
        col.name = c
        result.columns.append(col)
    result.rows = rows
    return result


def _make_dp(average=None, total=None):
    """Build a single mock Monitor data point."""
    dp = MagicMock()
    dp.average = average
    dp.total = total
    dp.time_stamp = MagicMock()
    dp.time_stamp.isoformat.return_value = "2026-04-14T12:00:00+00:00"
    return dp


def _make_metric_response(metrics_data):
    """Build a mock MonitorManagementClient metrics.list() response."""
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


# ===========================================================================
# TestAllowedMcpTools (3 tests)
# ===========================================================================


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_mcp_tools_contains_monitor(self):
        from agents.finops.tools import ALLOWED_MCP_TOOLS
        assert "monitor" in ALLOWED_MCP_TOOLS

    def test_allowed_mcp_tools_contains_advisor(self):
        from agents.finops.tools import ALLOWED_MCP_TOOLS
        assert "advisor" in ALLOWED_MCP_TOOLS

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.finops.tools import ALLOWED_MCP_TOOLS
        assert all("*" not in tool for tool in ALLOWED_MCP_TOOLS)


# ===========================================================================
# TestGetSubscriptionCostBreakdown (5 tests)
# ===========================================================================


class TestGetSubscriptionCostBreakdown:
    """Verify get_subscription_cost_breakdown returns expected structure."""

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_returns_success_with_breakdown(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [
            [100.0, "2026-04", "USD", "rg-compute"],
            [500.0, "2026-04", "USD", "rg-network"],
            [200.0, "2026-04", "USD", "rg-storage"],
        ]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency", "ResourceGroup"]
        )

        from agents.finops.tools import get_subscription_cost_breakdown

        result = get_subscription_cost_breakdown(
            subscription_id="sub-1", days=30, group_by="ResourceGroup"
        )

        assert result["query_status"] == "success"
        assert result["total_cost"] > 0
        assert len(result["breakdown"]) == 3
        assert result["data_lag_note"]

    def test_invalid_group_by_returns_error(self):
        """Validation fires before SDK check — always returns error without SDK."""
        import agents.finops.tools as tools_module

        # Save and patch CostManagementClient to non-None so validation guard runs first
        original = tools_module.CostManagementClient
        tools_module.CostManagementClient = MagicMock()
        try:
            from agents.finops.tools import get_subscription_cost_breakdown

            result = get_subscription_cost_breakdown(
                subscription_id="sub-1", days=30, group_by="Tag"
            )

            assert result["query_status"] == "error"
            error_lower = result["error"].lower()
            assert "allowlist" in error_lower or "invalid" in error_lower
        finally:
            tools_module.CostManagementClient = original

    def test_sdk_missing_returns_error(self):
        import agents.finops.tools as tools_module

        original = tools_module.CostManagementClient
        tools_module.CostManagementClient = None
        try:
            from agents.finops.tools import get_subscription_cost_breakdown

            result = get_subscription_cost_breakdown(
                subscription_id="sub-1", days=30, group_by="ResourceGroup"
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.CostManagementClient = original

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_azure_error_returns_error(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.side_effect = Exception("BudgetNotFound")

        from agents.finops.tools import get_subscription_cost_breakdown

        result = get_subscription_cost_breakdown(
            subscription_id="sub-1", days=30, group_by="ResourceGroup"
        )

        assert result["query_status"] == "error"
        assert result["duration_ms"] >= 0

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_breakdown_sorted_by_cost_descending(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [
            [100.0, "2026-04", "USD", "rg-a"],
            [500.0, "2026-04", "USD", "rg-b"],
            [200.0, "2026-04", "USD", "rg-c"],
        ]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency", "ResourceGroup"]
        )

        from agents.finops.tools import get_subscription_cost_breakdown

        result = get_subscription_cost_breakdown(
            subscription_id="sub-1", days=30, group_by="ResourceGroup"
        )

        assert result["query_status"] == "success"
        assert result["breakdown"][0]["cost"] == 500.0
        assert result["breakdown"][2]["cost"] == 100.0


# ===========================================================================
# TestGetResourceCost (4 tests)
# ===========================================================================


class TestGetResourceCost:
    """Verify get_resource_cost returns expected structure."""

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_returns_success_with_amortized_cost(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [[150.0, "2026-04", "USD"]]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency"]
        )

        from agents.finops.tools import get_resource_cost

        result = get_resource_cost(
            subscription_id="sub-1",
            resource_id="/subscriptions/sub-1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            days=30,
        )

        assert result["query_status"] == "success"
        assert result["cost_type"] == "AmortizedCost"
        assert result["total_cost"] >= 0
        assert result["data_lag_note"]

    def test_sdk_missing_returns_error(self):
        import agents.finops.tools as tools_module

        original = tools_module.CostManagementClient
        tools_module.CostManagementClient = None
        try:
            from agents.finops.tools import get_resource_cost

            result = get_resource_cost(
                subscription_id="sub-1",
                resource_id="/subscriptions/sub-1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.CostManagementClient = original

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_azure_error_returns_error(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.side_effect = Exception("ResourceNotFound")

        from agents.finops.tools import get_resource_cost

        result = get_resource_cost(
            subscription_id="sub-1",
            resource_id="/subscriptions/sub-1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
        )

        assert result["query_status"] == "error"

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_resource_id_preserved_in_response(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [[75.0, "2026-04", "USD"]]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency"]
        )
        resource_id = "/subscriptions/abc/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"

        from agents.finops.tools import get_resource_cost

        result = get_resource_cost(subscription_id="abc", resource_id=resource_id)

        assert result["resource_id"] == resource_id


# ===========================================================================
# TestIdentifyIdleResources (6 tests)
# ===========================================================================


class TestIdentifyIdleResources:
    """Verify identify_idle_resources returns expected structure."""

    def _make_vm(self, name="vm-idle-1", resource_group="rg-prod", sub="sub-1"):
        return {
            "id": f"/subscriptions/{sub}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{name}",
            "name": name,
            "resourceGroup": resource_group,
        }

    @patch("agents.finops.tools.create_approval_record")
    @patch("agents.finops.tools.get_resource_cost")
    @patch("agents.finops.tools.MonitorManagementClient")
    @patch("agents.finops.tools.QueryRequestOptions")
    @patch("agents.finops.tools.QueryRequest")
    @patch("agents.finops.tools.ResourceGraphClient")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    def test_returns_success_with_idle_vms(
        self,
        mock_cred,
        mock_arg_cls,
        mock_qreq,
        mock_qreqopt,
        mock_monitor_cls,
        mock_get_cost,
        mock_create_approval,
    ):
        vm1 = self._make_vm("vm-idle-1")
        vm2 = self._make_vm("vm-idle-2")
        arg_result = MagicMock()
        arg_result.data = [vm1, vm2]
        mock_arg_cls.return_value.resources.return_value = arg_result

        cpu_dp = _make_dp(average=0.5)
        net_in_dp = _make_dp(total=100.0)
        net_out_dp = _make_dp(total=100.0)
        mock_monitor_cls.return_value.metrics.list.return_value = _make_metric_response({
            "Percentage CPU": [cpu_dp],
            "Network In Total": [net_in_dp],
            "Network Out Total": [net_out_dp],
        })

        mock_get_cost.return_value = {"query_status": "success", "total_cost": 150.0}
        mock_create_approval.return_value = {"id": "appr_test123"}

        from agents.finops.tools import identify_idle_resources

        result = identify_idle_resources(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["idle_count"] == 2
        assert result["idle_resources"][0]["monthly_cost_usd"] == 150.0
        assert result["idle_resources"][0]["approval_id"] is not None

    @patch("agents.finops.tools.MonitorManagementClient")
    @patch("agents.finops.tools.QueryRequestOptions")
    @patch("agents.finops.tools.QueryRequest")
    @patch("agents.finops.tools.ResourceGraphClient")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    def test_non_idle_vms_excluded(
        self, mock_cred, mock_arg_cls, mock_qreq, mock_qreqopt, mock_monitor_cls
    ):
        vm1 = self._make_vm("vm-busy-1")
        arg_result = MagicMock()
        arg_result.data = [vm1]
        mock_arg_cls.return_value.resources.return_value = arg_result

        cpu_dp = _make_dp(average=45.0)
        net_in_dp = _make_dp(total=0.0)
        net_out_dp = _make_dp(total=0.0)
        mock_monitor_cls.return_value.metrics.list.return_value = _make_metric_response({
            "Percentage CPU": [cpu_dp],
            "Network In Total": [net_in_dp],
            "Network Out Total": [net_out_dp],
        })

        from agents.finops.tools import identify_idle_resources

        result = identify_idle_resources(subscription_id="sub-1")

        assert result["idle_count"] == 0
        assert result["idle_resources"] == []

    def test_arg_sdk_missing_returns_error(self):
        import agents.finops.tools as tools_module

        original = tools_module.ResourceGraphClient
        tools_module.ResourceGraphClient = None
        try:
            from agents.finops.tools import identify_idle_resources

            result = identify_idle_resources(subscription_id="sub-1")
            assert result["query_status"] == "error"
        finally:
            tools_module.ResourceGraphClient = original

    def test_monitor_sdk_missing_returns_error(self):
        import agents.finops.tools as tools_module

        original = tools_module.MonitorManagementClient
        tools_module.MonitorManagementClient = None
        try:
            from agents.finops.tools import identify_idle_resources

            result = identify_idle_resources(subscription_id="sub-1")
            assert result["query_status"] == "error"
        finally:
            tools_module.MonitorManagementClient = original

    @patch("agents.finops.tools.ResourceGraphClient")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    def test_azure_error_returns_error(self, mock_cred, mock_arg_cls):
        mock_arg_cls.return_value.resources.side_effect = Exception("Forbidden")

        from agents.finops.tools import identify_idle_resources

        result = identify_idle_resources(subscription_id="sub-1")

        assert result["query_status"] == "error"

    @patch("agents.finops.tools.get_resource_cost")
    @patch("agents.finops.tools.MonitorManagementClient")
    @patch("agents.finops.tools.QueryRequestOptions")
    @patch("agents.finops.tools.QueryRequest")
    @patch("agents.finops.tools.ResourceGraphClient")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    def test_approval_record_missing_does_not_crash(
        self, mock_cred, mock_arg_cls, mock_qreq, mock_qreqopt, mock_monitor_cls, mock_get_cost
    ):
        import agents.finops.tools as tools_module

        original_create = tools_module.create_approval_record
        tools_module.create_approval_record = None
        try:
            vm1 = self._make_vm("vm-idle-1")
            arg_result = MagicMock()
            arg_result.data = [vm1]
            mock_arg_cls.return_value.resources.return_value = arg_result

            cpu_dp = _make_dp(average=0.3)
            net_in_dp = _make_dp(total=10.0)
            net_out_dp = _make_dp(total=10.0)
            mock_monitor_cls.return_value.metrics.list.return_value = _make_metric_response({
                "Percentage CPU": [cpu_dp],
                "Network In Total": [net_in_dp],
                "Network Out Total": [net_out_dp],
            })
            mock_get_cost.return_value = {"query_status": "success", "total_cost": 100.0}

            from agents.finops.tools import identify_idle_resources

            result = identify_idle_resources(subscription_id="sub-1")

            assert result["query_status"] == "success"
            assert result["idle_resources"][0].get("approval_id") is None
        finally:
            tools_module.create_approval_record = original_create


# ===========================================================================
# TestGetReservedInstanceUtilisation (4 tests)
# ===========================================================================


class TestGetReservedInstanceUtilisation:
    """Verify get_reserved_instance_utilisation returns expected structure."""

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_returns_success_with_ri_benefit(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        # First call = ActualCost ($9,000), second call = AmortizedCost ($8,000)
        actual_result = _make_cost_result([[9000.0, "2026-04", "USD"]], ["Cost", "BillingMonth", "Currency"])
        amortized_result = _make_cost_result([[8000.0, "2026-04", "USD"]], ["Cost", "BillingMonth", "Currency"])
        mock_cm.return_value.query.usage.side_effect = [actual_result, amortized_result]

        from agents.finops.tools import get_reserved_instance_utilisation

        result = get_reserved_instance_utilisation(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["ri_benefit_estimated_usd"] == pytest.approx(-1000.0)
        assert result["method"] == "amortized_delta"
        assert result["data_lag_note"]

    def test_sdk_missing_returns_error(self):
        import agents.finops.tools as tools_module

        original = tools_module.CostManagementClient
        tools_module.CostManagementClient = None
        try:
            from agents.finops.tools import get_reserved_instance_utilisation

            result = get_reserved_instance_utilisation(subscription_id="sub-1")
            assert result["query_status"] == "error"
        finally:
            tools_module.CostManagementClient = original

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_azure_error_returns_error(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.side_effect = Exception("AuthorizationFailed")

        from agents.finops.tools import get_reserved_instance_utilisation

        result = get_reserved_instance_utilisation(subscription_id="sub-1")

        assert result["query_status"] == "error"

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_utilisation_note_present(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        actual_result = _make_cost_result([[5000.0, "2026-04", "USD"]], ["Cost", "BillingMonth", "Currency"])
        amortized_result = _make_cost_result([[4500.0, "2026-04", "USD"]], ["Cost", "BillingMonth", "Currency"])
        mock_cm.return_value.query.usage.side_effect = [actual_result, amortized_result]

        from agents.finops.tools import get_reserved_instance_utilisation

        result = get_reserved_instance_utilisation(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["utilisation_note"] is not None
        assert len(result["utilisation_note"]) > 0


# ===========================================================================
# TestGetCostForecast (5 tests)
# ===========================================================================


class TestGetCostForecast:
    """Verify get_cost_forecast returns expected structure."""

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_returns_success_with_forecast_no_budget(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [[3200.0, "2026-04", "USD"]]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency"]
        )

        from agents.finops.tools import get_cost_forecast

        result = get_cost_forecast(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["current_spend_usd"] == pytest.approx(3200.0)
        assert result["forecast_month_end_usd"] > result["current_spend_usd"]
        assert result["budget_amount_usd"] is None
        assert result["data_lag_note"]

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_over_budget_flag_set(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [[11000.0, "2026-04", "USD"]]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency"]
        )
        budget_mock = MagicMock()
        budget_mock.amount = 10000.0
        mock_cm.return_value.budgets.get.return_value = budget_mock

        from agents.finops.tools import get_cost_forecast

        result = get_cost_forecast(subscription_id="sub-1", budget_name="prod-budget")

        assert result["query_status"] == "success"
        assert result["over_budget"] is True
        assert result["burn_rate_pct"] > 100

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_under_budget_no_flag(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [[2000.0, "2026-04", "USD"]]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency"]
        )
        budget_mock = MagicMock()
        budget_mock.amount = 10000.0
        mock_cm.return_value.budgets.get.return_value = budget_mock

        from agents.finops.tools import get_cost_forecast

        result = get_cost_forecast(subscription_id="sub-1", budget_name="prod-budget")

        assert result["query_status"] == "success"
        assert result["over_budget"] is False

    def test_sdk_missing_returns_error(self):
        import agents.finops.tools as tools_module

        original = tools_module.CostManagementClient
        tools_module.CostManagementClient = None
        try:
            from agents.finops.tools import get_cost_forecast

            result = get_cost_forecast(subscription_id="sub-1")
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.CostManagementClient = original

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_budget_not_found_returns_forecast_only(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [[5000.0, "2026-04", "USD"]]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency"]
        )
        mock_cm.return_value.budgets.get.side_effect = Exception("BudgetNotFound")

        from agents.finops.tools import get_cost_forecast

        result = get_cost_forecast(subscription_id="sub-1", budget_name="missing-budget")

        assert result["query_status"] == "success"
        assert result["budget_amount_usd"] is None
        assert "budget_error" in result


# ===========================================================================
# TestGetTopCostDrivers (5 tests)
# ===========================================================================


class TestGetTopCostDrivers:
    """Verify get_top_cost_drivers returns expected structure."""

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_returns_success_with_drivers(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        rows = [
            [2000.0, "2026-04", "USD", "Virtual Machines"],
            [1500.0, "2026-04", "USD", "Storage"],
            [800.0, "2026-04", "USD", "Networking"],
            [400.0, "2026-04", "USD", "SQL Database"],
            [200.0, "2026-04", "USD", "App Service"],
        ]
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            rows, ["Cost", "BillingMonth", "Currency", "ServiceName"]
        )

        from agents.finops.tools import get_top_cost_drivers

        result = get_top_cost_drivers(subscription_id="sub-1", n=5)

        assert result["query_status"] == "success"
        assert len(result["drivers"]) == 5
        assert result["drivers"][0]["rank"] == 1
        assert result["drivers"][0]["cost_usd"] >= result["drivers"][1]["cost_usd"]

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_n_clamped_to_max_25(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            [], ["Cost", "BillingMonth", "Currency", "ServiceName"]
        )

        from agents.finops.tools import get_top_cost_drivers

        result = get_top_cost_drivers(subscription_id="sub-1", n=100)

        assert result["n"] <= 25

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_n_clamped_to_min_1(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            [], ["Cost", "BillingMonth", "Currency", "ServiceName"]
        )

        from agents.finops.tools import get_top_cost_drivers

        result = get_top_cost_drivers(subscription_id="sub-1", n=0)

        assert result["query_status"] == "success"
        assert result["n"] >= 1

    def test_sdk_missing_returns_error(self):
        import agents.finops.tools as tools_module

        original = tools_module.CostManagementClient
        tools_module.CostManagementClient = None
        try:
            from agents.finops.tools import get_top_cost_drivers

            result = get_top_cost_drivers(subscription_id="sub-1")
            assert result["query_status"] == "error"
        finally:
            tools_module.CostManagementClient = original

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_data_lag_note_present(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            [], ["Cost", "BillingMonth", "Currency", "ServiceName"]
        )

        from agents.finops.tools import get_top_cost_drivers

        result = get_top_cost_drivers(subscription_id="sub-1")

        assert result["data_lag_note"]


# ===========================================================================
# TestDataLagNote (2 tests)
# ===========================================================================


class TestDataLagNote:
    """Cross-tool guard: every cost tool includes data_lag_note in success responses."""

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_cost_breakdown_includes_lag_note(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            [[100.0, "2026-04", "USD", "rg-1"]], ["Cost", "BillingMonth", "Currency", "ResourceGroup"]
        )

        from agents.finops.tools import get_subscription_cost_breakdown

        result = get_subscription_cost_breakdown(
            subscription_id="sub-1", days=30, group_by="ResourceGroup"
        )

        assert "data_lag_note" in result
        assert len(result["data_lag_note"]) > 0

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_cost_forecast_includes_lag_note(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            [[1000.0, "2026-04", "USD"]], ["Cost", "BillingMonth", "Currency"]
        )

        from agents.finops.tools import get_cost_forecast

        result = get_cost_forecast(subscription_id="sub-1")

        assert "data_lag_note" in result
        assert len(result["data_lag_note"]) > 0


# ===========================================================================
# TestDurationMs (3 tests)
# ===========================================================================


class TestDurationMs:
    """Cross-tool guard: every tool returns duration_ms in both success and error paths."""

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_breakdown_success_has_duration_ms(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.return_value = _make_cost_result(
            [[100.0, "2026-04", "USD", "rg-1"]], ["Cost", "BillingMonth", "Currency", "ResourceGroup"]
        )

        from agents.finops.tools import get_subscription_cost_breakdown

        result = get_subscription_cost_breakdown(
            subscription_id="sub-1", days=30, group_by="ResourceGroup"
        )

        assert "duration_ms" in result
        assert result["duration_ms"] >= 0

    @patch("agents.finops.tools.instrument_tool_call")
    @patch("agents.finops.tools.get_agent_identity", return_value="test-id")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    @patch("agents.finops.tools.QueryGrouping")
    @patch("agents.finops.tools.QueryAggregation")
    @patch("agents.finops.tools.QueryDataset")
    @patch("agents.finops.tools.QueryTimePeriod")
    @patch("agents.finops.tools.GranularityType")
    @patch("agents.finops.tools.TimeframeType")
    @patch("agents.finops.tools.QueryDefinition")
    @patch("agents.finops.tools.CostManagementClient")
    def test_breakdown_error_has_duration_ms(
        self, mock_cm, mock_qd, mock_tf, mock_gt, mock_qtp, mock_qds, mock_qa, mock_qg,
        mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_cm.return_value.query.usage.side_effect = Exception("SDK error")

        from agents.finops.tools import get_subscription_cost_breakdown

        result = get_subscription_cost_breakdown(
            subscription_id="sub-1", days=30, group_by="ResourceGroup"
        )

        assert "duration_ms" in result
        assert result["duration_ms"] >= 0

    @patch("agents.finops.tools.MonitorManagementClient")
    @patch("agents.finops.tools.ResourceGraphClient")
    @patch("agents.finops.tools.get_credential", return_value=MagicMock())
    def test_identify_idle_success_has_duration_ms(
        self, mock_cred, mock_arg_cls, mock_monitor_cls
    ):
        arg_result = MagicMock()
        arg_result.data = []
        mock_arg_cls.return_value.resources.return_value = arg_result

        from agents.finops.tools import identify_idle_resources

        result = identify_idle_resources(subscription_id="sub-1")

        assert "duration_ms" in result


# ===========================================================================
# TestValidGroupBy (3 tests)
# ===========================================================================


class TestValidGroupBy:
    """Verify _VALID_GROUP_BY allowlist is enforced correctly."""

    def test_resource_group_is_valid(self):
        import agents.finops.tools as tools_module
        assert "ResourceGroup" in tools_module._VALID_GROUP_BY

    def test_resource_type_is_valid(self):
        import agents.finops.tools as tools_module
        assert "ResourceType" in tools_module._VALID_GROUP_BY

    def test_service_name_is_valid(self):
        import agents.finops.tools as tools_module
        assert "ServiceName" in tools_module._VALID_GROUP_BY
