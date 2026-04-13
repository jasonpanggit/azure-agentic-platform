"""Tests for AKS Container Insights (Log Analytics) metrics endpoint.

Tests cover:
- PARTIAL result handling: metrics are returned from partial_data
- SUCCESS result handling: standard path produces metrics
- Empty result: returns empty metrics list
- No workspace configured: returns fetch_error
- Computer filter removed: KQL no longer filters by cluster name on Computer field
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure auth is bypassed for all tests in this file
os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


# ---------------------------------------------------------------------------
# Module shim: azure.mgmt.containerservice is not installed locally.
# Inject a mock module so `from azure.mgmt.containerservice import ...`
# succeeds inside the endpoint function body.
# ---------------------------------------------------------------------------

_mock_containerservice = MagicMock()
if "azure.mgmt.containerservice" not in sys.modules:
    sys.modules.setdefault("azure.mgmt.containerservice", _mock_containerservice)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_la_metrics_result(status: str, rows: list, columns: list | None = None):
    """Build a mock LogsQueryClient.query_resource result for Perf table queries."""
    from azure.monitor.query import LogsQueryStatus

    status_enum = LogsQueryStatus.SUCCESS if status == "Success" else LogsQueryStatus.PARTIAL
    mock_result = MagicMock()
    mock_result.status = status_enum

    cols = columns or ["TimeGenerated", "Computer", "CounterName", "avg_CounterValue"]
    mock_table = MagicMock()
    mock_table.columns = [MagicMock() for _ in cols]
    for col_mock, col_name in zip(mock_table.columns, cols):
        col_mock.name = col_name
    mock_table.rows = rows

    if status_enum == LogsQueryStatus.SUCCESS:
        mock_result.tables = [mock_table] if rows else []
        mock_result.partial_data = None
    else:
        mock_result.partial_data = [mock_table] if rows else []
        mock_result.tables = None
        mock_result.partial_error = "partial timeout"

    return mock_result


def _aks_resource_id(
    name: str = "aks-test",
    rg: str = "rg-aks",
    sub: str = "sub-123",
) -> str:
    return (
        f"/subscriptions/{sub}/resourceGroups/{rg}"
        f"/providers/Microsoft.ContainerService/managedClusters/{name}"
    )


def _encode_resource_id(resource_id: str) -> str:
    import base64
    return base64.urlsafe_b64encode(resource_id.encode()).rstrip(b"=").decode()


def _mock_aks_cluster(workspace_id: str = "/sub/ws/test"):
    """Return a mock AKS cluster object with omsagent enabled."""
    cluster = MagicMock()
    omsagent = MagicMock()
    omsagent.enabled = True
    omsagent.config = {"logAnalyticsWorkspaceResourceID": workspace_id}
    cluster.addon_profiles = {"omsagent": omsagent}
    return cluster


@pytest.fixture()
def client():
    """TestClient with mock app.state (no real Azure connections)."""
    from services.api_gateway.main import app
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None
    from fastapi.testclient import TestClient
    return TestClient(app)


# ---------------------------------------------------------------------------
# PARTIAL result handling
# ---------------------------------------------------------------------------


class TestAKSLAMetricsPartialResult:
    """PARTIAL results from Log Analytics should produce valid metrics."""

    def test_partial_result_returns_metrics(self, client):
        """When Log Analytics returns PARTIAL, metrics are extracted from partial_data."""
        rid = _aks_resource_id()
        encoded = _encode_resource_id(rid)

        partial_rows = [
            ["2026-04-13T10:00:00Z", "aks-nodepool1-vmss000000", "cpuUsageNanoCores", 150000000.0],
            ["2026-04-13T10:05:00Z", "aks-nodepool1-vmss000000", "cpuUsageNanoCores", 160000000.0],
        ]
        mock_result = _make_la_metrics_result("Partial", partial_rows)
        mock_cluster = _mock_aks_cluster()

        # Mock ContainerServiceClient at the module attribute level so the
        # runtime `from azure.mgmt.containerservice import ContainerServiceClient`
        # inside the endpoint resolves to our mock.
        mock_csc = MagicMock()
        mock_csc.return_value.managed_clusters.get.return_value = mock_cluster
        _mock_containerservice.ContainerServiceClient = mock_csc

        with (
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", True),
            patch("azure.identity.DefaultAzureCredential"),
            patch("azure.monitor.query.LogsQueryClient") as MockLogs,
        ):
            MockLogs.return_value.query_resource.return_value = mock_result
            resp = client.get(f"/api/v1/aks/{encoded}/metrics/logs?timespan=PT1H")

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "log_analytics"
        assert len(data["metrics"]) >= 1
        # Verify timeseries data was extracted
        series = data["metrics"][0]
        assert len(series["timeseries"]) == 2
        assert series["timeseries"][0]["average"] == 150000000.0

    def test_success_result_returns_metrics(self, client):
        """Standard SUCCESS path still works correctly."""
        rid = _aks_resource_id()
        encoded = _encode_resource_id(rid)

        success_rows = [
            ["2026-04-13T10:00:00Z", "aks-nodepool1-vmss000000", "memoryWorkingSetBytes", 500000000.0],
        ]
        mock_result = _make_la_metrics_result("Success", success_rows)
        mock_cluster = _mock_aks_cluster()

        mock_csc = MagicMock()
        mock_csc.return_value.managed_clusters.get.return_value = mock_cluster
        _mock_containerservice.ContainerServiceClient = mock_csc

        with (
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", True),
            patch("azure.identity.DefaultAzureCredential"),
            patch("azure.monitor.query.LogsQueryClient") as MockLogs,
        ):
            MockLogs.return_value.query_resource.return_value = mock_result
            resp = client.get(f"/api/v1/aks/{encoded}/metrics/logs?timespan=PT1H")

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "log_analytics"
        assert len(data["metrics"]) == 1
        assert "Memory" in data["metrics"][0]["name"]

    def test_empty_result_returns_empty_metrics(self, client):
        """When KQL returns zero rows, metrics list is empty."""
        rid = _aks_resource_id()
        encoded = _encode_resource_id(rid)

        mock_result = _make_la_metrics_result("Success", [])
        mock_cluster = _mock_aks_cluster()

        mock_csc = MagicMock()
        mock_csc.return_value.managed_clusters.get.return_value = mock_cluster
        _mock_containerservice.ContainerServiceClient = mock_csc

        with (
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", True),
            patch("azure.identity.DefaultAzureCredential"),
            patch("azure.monitor.query.LogsQueryClient") as MockLogs,
        ):
            MockLogs.return_value.query_resource.return_value = mock_result
            resp = client.get(f"/api/v1/aks/{encoded}/metrics/logs?timespan=PT24H")

        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"] == []

    def test_no_workspace_returns_fetch_error(self, client):
        """When no LA workspace is configured, response includes fetch_error."""
        rid = _aks_resource_id()
        encoded = _encode_resource_id(rid)

        mock_cluster = MagicMock()
        mock_cluster.addon_profiles = {}

        mock_csc = MagicMock()
        mock_csc.return_value.managed_clusters.get.return_value = mock_cluster
        _mock_containerservice.ContainerServiceClient = mock_csc

        with (
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", True),
            patch("azure.identity.DefaultAzureCredential"),
            patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_RESOURCE_ID": ""}, clear=False),
        ):
            resp = client.get(f"/api/v1/aks/{encoded}/metrics/logs?timespan=PT1H")

        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"] == []
        assert "No Log Analytics workspace" in data.get("fetch_error", "")


class TestAKSLAMetricsKQLFilter:
    """Verify the Computer filter was correctly removed from KQL."""

    def test_kql_does_not_filter_by_computer(self):
        """The KQL query should NOT contain 'Computer has' filter."""
        import inspect
        from services.api_gateway.aks_endpoints import get_aks_la_metrics

        source = inspect.getsource(get_aks_la_metrics)
        assert 'Computer has' not in source, (
            "KQL should not filter by Computer — the workspace is already scoped to the cluster"
        )
