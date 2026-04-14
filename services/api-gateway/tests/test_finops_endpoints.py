"""Tests for FinOps API gateway endpoints.

GET /api/v1/finops/cost-breakdown
GET /api/v1/finops/resource-cost
GET /api/v1/finops/idle-resources
GET /api/v1/finops/ri-utilization
GET /api/v1/finops/cost-forecast
GET /api/v1/finops/top-cost-drivers
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

# ---------------------------------------------------------------------------
# App fixture — standalone app with only the finops router + mock app.state
# ---------------------------------------------------------------------------

from services.api_gateway.finops_endpoints import router  # noqa: E402

_test_app = FastAPI()
_test_app.include_router(router)
_test_app.state.credential = MagicMock()

client = TestClient(_test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Shared mock factories
# ---------------------------------------------------------------------------

def _make_cost_result(rows: list, col_names: list | None = None) -> MagicMock:
    """Build a mock CostManagementClient query result."""
    if col_names is None:
        col_names = ["Cost", "Currency", "ResourceGroup"]
    mock_result = MagicMock()
    mock_result.columns = [MagicMock(name=n) for n in col_names]
    for i, col in enumerate(mock_result.columns):
        col.name = col_names[i]
    mock_result.rows = rows
    return mock_result


# ---------------------------------------------------------------------------
# TestCostBreakdown
# ---------------------------------------------------------------------------


class TestCostBreakdown:
    """Tests for GET /api/v1/finops/cost-breakdown"""

    def test_returns_200_with_valid_params(self):
        """Valid request returns 200 with breakdown and data_lag_note."""
        mock_result = _make_cost_result(
            rows=[[150.0, "USD", "rg-prod"], [75.0, "USD", "rg-dev"], [30.0, "USD", "rg-test"]],
            col_names=["Cost", "Currency", "ResourceGroup"],
        )
        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.QueryGrouping"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.return_value = mock_result
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/cost-breakdown",
                params={"subscription_id": "sub-abc", "days": 30, "group_by": "ResourceGroup"},
            )

        assert res.status_code == 200
        data = res.json()
        assert "breakdown" in data
        assert "data_lag_note" in data
        assert data["subscription_id"] == "sub-abc"
        assert data["group_by"] == "ResourceGroup"
        assert isinstance(data["breakdown"], list)

    def test_returns_422_on_invalid_group_by(self):
        """Invalid group_by value returns 422."""
        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
        ):
            mock_cm.return_value = MagicMock()
            res = client.get(
                "/api/v1/finops/cost-breakdown",
                params={"subscription_id": "sub-abc", "group_by": "Tag"},
            )

        assert res.status_code == 422

    def test_returns_422_on_days_out_of_range(self):
        """days=200 (> max 90) returns 422."""
        res = client.get(
            "/api/v1/finops/cost-breakdown",
            params={"subscription_id": "sub-abc", "days": 200},
        )
        assert res.status_code == 422

    def test_returns_422_on_days_below_minimum(self):
        """days=3 (< min 7) returns 422."""
        res = client.get(
            "/api/v1/finops/cost-breakdown",
            params={"subscription_id": "sub-abc", "days": 3},
        )
        assert res.status_code == 422

    def test_returns_error_on_sdk_exception(self):
        """SDK exception returns 500 with error field."""
        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.QueryGrouping"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.side_effect = Exception("Unauthorized")
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/cost-breakdown",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 500
        data = res.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# TestResourceCost
# ---------------------------------------------------------------------------


class TestResourceCost:
    """Tests for GET /api/v1/finops/resource-cost"""

    def test_returns_200_with_cost(self):
        """Valid request returns 200 with total_cost and AmortizedCost type."""
        mock_result = MagicMock()
        mock_result.columns = [MagicMock(), MagicMock()]
        mock_result.columns[0].name = "Cost"
        mock_result.columns[1].name = "Currency"
        mock_result.rows = [[250.0, "USD"]]

        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.return_value = mock_result
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/resource-cost",
                params={
                    "subscription_id": "sub-abc",
                    "resource_id": "/subscriptions/sub-abc/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                    "days": 30,
                },
            )

        assert res.status_code == 200
        data = res.json()
        assert "total_cost" in data
        assert data["cost_type"] == "AmortizedCost"
        assert "data_lag_note" in data

    def test_returns_422_on_missing_resource_id(self):
        """Omitting resource_id returns 422."""
        res = client.get(
            "/api/v1/finops/resource-cost",
            params={"subscription_id": "sub-abc"},
        )
        assert res.status_code == 422

    def test_returns_error_on_sdk_exception(self):
        """SDK exception returns 500 with error field."""
        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.side_effect = Exception("403 Forbidden")
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/resource-cost",
                params={
                    "subscription_id": "sub-abc",
                    "resource_id": "/subscriptions/sub-abc/providers/Microsoft.Compute/virtualMachines/vm1",
                },
            )

        assert res.status_code == 500
        data = res.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# TestIdleResources
# ---------------------------------------------------------------------------


class TestIdleResources:
    """Tests for GET /api/v1/finops/idle-resources"""

    def _make_vm_list(self, count: int = 2) -> list:
        return [
            {"id": f"/subscriptions/sub/providers/Microsoft.Compute/virtualMachines/vm{i}",
             "name": f"vm{i}", "resourceGroup": "rg-prod"}
            for i in range(count)
        ]

    def _make_metrics_response(self, avg_cpu: float, network_bytes: float) -> MagicMock:
        """Build a mock Monitor metrics response."""
        mock_response = MagicMock()

        cpu_metric = MagicMock()
        cpu_metric.name.value = "Percentage CPU"
        cpu_ts = MagicMock()
        cpu_ts.data = [MagicMock(average=avg_cpu)]
        cpu_metric.timeseries = [cpu_ts]

        net_in_metric = MagicMock()
        net_in_metric.name.value = "Network In Total"
        net_ts = MagicMock()
        net_ts.data = [MagicMock(total=network_bytes)]
        net_in_metric.timeseries = [net_ts]

        mock_response.value = [cpu_metric, net_in_metric]
        return mock_response

    def test_returns_200_with_idle_vms(self):
        """Two VMs with very low CPU and network are flagged as idle."""
        mock_arg_result = MagicMock()
        mock_arg_result.data = self._make_vm_list(2)

        low_metrics = self._make_metrics_response(avg_cpu=0.5, network_bytes=1000.0)

        with (
            patch("services.api_gateway.finops_endpoints.ResourceGraphClient") as mock_arg,
            patch("services.api_gateway.finops_endpoints.QueryRequest"),
            patch("services.api_gateway.finops_endpoints.MonitorManagementClient") as mock_mon,
        ):
            mock_arg.return_value.resources.return_value = mock_arg_result
            mock_mon.return_value.metrics.list.return_value = low_metrics

            res = client.get(
                "/api/v1/finops/idle-resources",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 200
        data = res.json()
        assert data["idle_count"] == 2
        assert len(data["idle_resources"]) == 2
        assert "vm_name" in data["idle_resources"][0]

    def test_returns_200_with_no_idle_vms(self):
        """VMs with high CPU are NOT flagged as idle."""
        mock_arg_result = MagicMock()
        mock_arg_result.data = self._make_vm_list(1)

        high_cpu_metrics = self._make_metrics_response(avg_cpu=85.0, network_bytes=500_000_000.0)

        with (
            patch("services.api_gateway.finops_endpoints.ResourceGraphClient") as mock_arg,
            patch("services.api_gateway.finops_endpoints.QueryRequest"),
            patch("services.api_gateway.finops_endpoints.MonitorManagementClient") as mock_mon,
        ):
            mock_arg.return_value.resources.return_value = mock_arg_result
            mock_mon.return_value.metrics.list.return_value = high_cpu_metrics

            res = client.get(
                "/api/v1/finops/idle-resources",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 200
        data = res.json()
        assert data["idle_count"] == 0
        assert data["idle_resources"] == []

    def test_cpu_threshold_param_accepted(self):
        """Custom threshold_cpu_pct is accepted and applied."""
        mock_arg_result = MagicMock()
        mock_arg_result.data = self._make_vm_list(1)

        # CPU at 4% — below custom threshold of 5%
        metrics = self._make_metrics_response(avg_cpu=4.0, network_bytes=100.0)

        with (
            patch("services.api_gateway.finops_endpoints.ResourceGraphClient") as mock_arg,
            patch("services.api_gateway.finops_endpoints.QueryRequest"),
            patch("services.api_gateway.finops_endpoints.MonitorManagementClient") as mock_mon,
        ):
            mock_arg.return_value.resources.return_value = mock_arg_result
            mock_mon.return_value.metrics.list.return_value = metrics

            res = client.get(
                "/api/v1/finops/idle-resources",
                params={"subscription_id": "sub-abc", "threshold_cpu_pct": 5.0},
            )

        assert res.status_code == 200
        data = res.json()
        # VM with 4% CPU is idle relative to 5% threshold
        assert data["idle_count"] == 1

    def test_returns_error_on_sdk_exception(self):
        """ARG exception returns 500 with error field."""
        with (
            patch("services.api_gateway.finops_endpoints.ResourceGraphClient") as mock_arg,
            patch("services.api_gateway.finops_endpoints.QueryRequest"),
            patch("services.api_gateway.finops_endpoints.MonitorManagementClient"),
        ):
            mock_arg.return_value.resources.side_effect = Exception("ARG unavailable")

            res = client.get(
                "/api/v1/finops/idle-resources",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 500
        data = res.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# TestRiUtilization
# ---------------------------------------------------------------------------


class TestRiUtilization:
    """Tests for GET /api/v1/finops/ri-utilization"""

    def _make_single_total_result(self, cost: float) -> MagicMock:
        mock_result = MagicMock()
        mock_result.columns = [MagicMock(), MagicMock()]
        mock_result.columns[0].name = "Cost"
        mock_result.columns[1].name = "Currency"
        mock_result.rows = [[cost, "USD"]]
        return mock_result

    def test_returns_200_with_ri_data(self):
        """Returns 200 with ri_benefit_estimated_usd and method=amortized_delta."""
        actual_result = self._make_single_total_result(8000.0)
        amortized_result = self._make_single_total_result(9000.0)

        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            # First call = ActualCost, second call = AmortizedCost
            mock_client.query.usage.side_effect = [actual_result, amortized_result]
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/ri-utilization",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 200
        data = res.json()
        assert "ri_benefit_estimated_usd" in data
        assert data["method"] == "amortized_delta"
        assert data["actual_cost_usd"] == 8000.0
        assert data["amortized_cost_usd"] == 9000.0

    def test_returns_200_with_data_lag_note(self):
        """Response always includes data_lag_note."""
        actual_result = self._make_single_total_result(5000.0)
        amortized_result = self._make_single_total_result(5500.0)

        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.side_effect = [actual_result, amortized_result]
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/ri-utilization",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 200
        data = res.json()
        assert "data_lag_note" in data

    def test_returns_error_on_sdk_exception(self):
        """SDK exception returns 500 with error field."""
        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.side_effect = Exception("Cost Management unavailable")
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/ri-utilization",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 500
        data = res.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# TestCostForecast
# ---------------------------------------------------------------------------


class TestCostForecast:
    """Tests for GET /api/v1/finops/cost-forecast"""

    def _make_mtd_result(self, spend: float) -> MagicMock:
        mock_result = MagicMock()
        mock_result.columns = [MagicMock(), MagicMock()]
        mock_result.columns[0].name = "Cost"
        mock_result.columns[1].name = "Currency"
        mock_result.rows = [[spend, "USD"]]
        return mock_result

    def test_returns_200_without_budget(self):
        """No budget_name → budget_amount_usd is None."""
        mtd_result = self._make_mtd_result(3000.0)

        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.return_value = mtd_result
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/cost-forecast",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 200
        data = res.json()
        assert "forecast_month_end_usd" in data
        assert data["budget_amount_usd"] is None
        assert "data_lag_note" in data

    def test_returns_200_with_budget_name(self):
        """With budget_name, budget_amount_usd and burn_rate_pct are populated."""
        mtd_result = self._make_mtd_result(5000.0)

        mock_budget = MagicMock()
        mock_budget.amount = 10000

        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.return_value = mtd_result
            mock_client.budgets.get.return_value = mock_budget
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/cost-forecast",
                params={"subscription_id": "sub-abc", "budget_name": "my-budget"},
            )

        assert res.status_code == 200
        data = res.json()
        assert data["budget_amount_usd"] == 10000.0
        assert "burn_rate_pct" in data

    def test_over_budget_flag_set(self):
        """When projected spend > budget, over_budget is True."""
        # Simulate: $12,000 spend on day 20 of a 30-day month
        # Daily burn = 12000 / 20 = 600; projected = 600 * 30 = $18,000 > $10,000 budget
        mtd_result = self._make_mtd_result(12000.0)

        mock_budget = MagicMock()
        mock_budget.amount = 10000

        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.return_value = mtd_result
            mock_client.budgets.get.return_value = mock_budget
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/cost-forecast",
                params={"subscription_id": "sub-abc", "budget_name": "my-budget"},
            )

        assert res.status_code == 200
        data = res.json()
        assert data["over_budget"] is True

    def test_returns_error_on_sdk_exception(self):
        """SDK exception returns 500 with error field."""
        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.side_effect = Exception("Service unavailable")
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/cost-forecast",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 500
        data = res.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# TestTopCostDrivers
# ---------------------------------------------------------------------------


class TestTopCostDrivers:
    """Tests for GET /api/v1/finops/top-cost-drivers"""

    def _make_service_result(self, service_rows: list) -> MagicMock:
        """Build mock result with ServiceName grouping."""
        mock_result = MagicMock()
        mock_result.columns = [MagicMock(), MagicMock(), MagicMock()]
        mock_result.columns[0].name = "Cost"
        mock_result.columns[1].name = "Currency"
        mock_result.columns[2].name = "ServiceName"
        mock_result.rows = service_rows
        return mock_result

    def test_returns_200_with_drivers(self):
        """Returns 200 with drivers list; first entry has rank=1."""
        rows = [
            [1000.0, "USD", "Virtual Machines"],
            [800.0, "USD", "Azure SQL Database"],
            [600.0, "USD", "App Service"],
            [400.0, "USD", "Storage"],
            [200.0, "USD", "Key Vault"],
        ]
        mock_result = self._make_service_result(rows)

        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.QueryGrouping"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.return_value = mock_result
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/top-cost-drivers",
                params={"subscription_id": "sub-abc", "n": 5},
            )

        assert res.status_code == 200
        data = res.json()
        assert len(data["drivers"]) == 5
        assert data["drivers"][0]["rank"] == 1
        assert "service_name" in data["drivers"][0]
        assert "data_lag_note" in data

    def test_n_validated_max_25(self):
        """n > 25 returns 422."""
        res = client.get(
            "/api/v1/finops/top-cost-drivers",
            params={"subscription_id": "sub-abc", "n": 100},
        )
        assert res.status_code == 422

    def test_n_validated_min_1(self):
        """n < 1 (n=0) returns 422."""
        res = client.get(
            "/api/v1/finops/top-cost-drivers",
            params={"subscription_id": "sub-abc", "n": 0},
        )
        assert res.status_code == 422

    def test_returns_error_on_sdk_exception(self):
        """SDK exception returns 500 with error field."""
        with (
            patch("services.api_gateway.finops_endpoints.CostManagementClient") as mock_cm,
            patch("services.api_gateway.finops_endpoints.QueryDefinition"),
            patch("services.api_gateway.finops_endpoints.QueryTimePeriod"),
            patch("services.api_gateway.finops_endpoints.QueryDataset"),
            patch("services.api_gateway.finops_endpoints.QueryAggregation"),
            patch("services.api_gateway.finops_endpoints.QueryGrouping"),
            patch("services.api_gateway.finops_endpoints.GranularityType"),
            patch("services.api_gateway.finops_endpoints.TimeframeType"),
        ):
            mock_client = MagicMock()
            mock_client.query.usage.side_effect = Exception("Rate limit exceeded")
            mock_cm.return_value = mock_client

            res = client.get(
                "/api/v1/finops/top-cost-drivers",
                params={"subscription_id": "sub-abc"},
            )

        assert res.status_code == 500
        data = res.json()
        assert "error" in data
