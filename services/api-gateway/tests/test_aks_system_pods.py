"""Tests for AKS system pod health enrichment.

Tests cover:
- _fetch_system_pod_health_batch: healthy, degraded, unknown, SDK unavailable, query failure
- list_aks_clusters: enrichment wiring — system_pod_health populated from batch query
- list_aks_clusters: graceful fallback to 'unknown' when Container Insights unavailable
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# Ensure auth is bypassed for all tests in this file
os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_logs_result(status: str, rows: list, columns: list | None = None):
    """Build a mock LogsQueryClient.query_resource result."""
    from azure.monitor.query import LogsQueryStatus

    status_enum = LogsQueryStatus.SUCCESS if status == "Success" else LogsQueryStatus.PARTIAL
    mock_result = MagicMock()
    mock_result.status = status_enum

    if rows:
        cols = columns or ["ClusterName", "running_pods", "crash_loop_pods", "pending_pods", "failed_pods"]
        mock_table = MagicMock()
        mock_table.columns = [MagicMock() for _ in cols]
        # Override .name for each column mock (MagicMock(name=...) sets internal _mock_name)
        for col_mock, col_name in zip(mock_table.columns, cols):
            col_mock.name = col_name
        mock_table.rows = rows
        if status_enum == LogsQueryStatus.SUCCESS:
            mock_result.tables = [mock_table]
            mock_result.partial_data = None
        else:
            mock_result.partial_data = [mock_table]
            mock_result.tables = None
            mock_result.partial_error = "partial"
    else:
        mock_result.tables = []
        mock_result.partial_data = None

    return mock_result


def _sample_arg_row(
    name: str = "aks-srelab",
    resource_group: str = "rg-aks",
    subscription_id: str = "sub1",
    kubernetes_version: str = "1.28.5",
) -> dict:
    return {
        "id": f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.ContainerService/managedClusters/{name}",
        "name": name,
        "resourceGroup": resource_group,
        "subscriptionId": subscription_id,
        "location": "eastus",
        "kubernetes_version": kubernetes_version,
        "fqdn": f"{name}.hcp.eastus.azmk8s.io",
        "network_plugin": "azure",
        "rbac_enabled": 1,
        "node_pool_count": 2,
        "node_pools_ready": 2,
        "total_nodes": 3,
        "active_alert_count": 0,
    }


# ---------------------------------------------------------------------------
# _fetch_system_pod_health_batch unit tests
# ---------------------------------------------------------------------------


class TestFetchSystemPodHealthBatch:
    """Unit tests for _fetch_system_pod_health_batch."""

    def test_returns_empty_when_sdk_unavailable(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        with patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", False):
            result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", ["aks-1"])
        assert result == {}

    def test_returns_empty_when_no_workspace(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        result = _fetch_system_pod_health_batch(MagicMock(), "", ["aks-1"])
        assert result == {}

    def test_returns_empty_when_no_cluster_names(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", [])
        assert result == {}

    def test_healthy_when_all_running_no_failures(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        mock_result = _make_logs_result("Success", [
            ["aks-srelab", 5, 0, 0, 0],
        ])

        with patch("azure.monitor.query.LogsQueryClient") as MockClient:
            MockClient.return_value.query_resource.return_value = mock_result
            result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", ["aks-srelab"])

        assert result == {"aks-srelab": "healthy"}

    def test_degraded_when_crash_loop(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        mock_result = _make_logs_result("Success", [
            ["aks-prod", 4, 1, 0, 0],
        ])

        with patch("azure.monitor.query.LogsQueryClient") as MockClient:
            MockClient.return_value.query_resource.return_value = mock_result
            result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", ["aks-prod"])

        assert result == {"aks-prod": "degraded"}

    def test_degraded_when_failed_pods(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        mock_result = _make_logs_result("Success", [
            ["aks-dev", 3, 0, 0, 2],
        ])

        with patch("azure.monitor.query.LogsQueryClient") as MockClient:
            MockClient.return_value.query_resource.return_value = mock_result
            result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", ["aks-dev"])

        assert result == {"aks-dev": "degraded"}

    def test_degraded_when_pending_and_running(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        mock_result = _make_logs_result("Success", [
            ["aks-staging", 3, 0, 2, 0],
        ])

        with patch("azure.monitor.query.LogsQueryClient") as MockClient:
            MockClient.return_value.query_resource.return_value = mock_result
            result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", ["aks-staging"])

        assert result == {"aks-staging": "degraded"}

    def test_unknown_when_no_running_pods(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        mock_result = _make_logs_result("Success", [
            ["aks-empty", 0, 0, 0, 0],
        ])

        with patch("azure.monitor.query.LogsQueryClient") as MockClient:
            MockClient.return_value.query_resource.return_value = mock_result
            result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", ["aks-empty"])

        assert result == {"aks-empty": "unknown"}

    def test_multiple_clusters_in_batch(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        mock_result = _make_logs_result("Success", [
            ["aks-prod", 5, 0, 0, 0],
            ["aks-dev", 3, 1, 0, 0],
        ])

        with patch("azure.monitor.query.LogsQueryClient") as MockClient:
            MockClient.return_value.query_resource.return_value = mock_result
            result = _fetch_system_pod_health_batch(
                MagicMock(), "/sub/ws/1", ["aks-prod", "aks-dev", "aks-staging"]
            )

        assert result["aks-prod"] == "healthy"
        assert result["aks-dev"] == "degraded"
        assert "aks-staging" not in result

    def test_graceful_on_query_failure(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        with patch("azure.monitor.query.LogsQueryClient") as MockClient:
            MockClient.return_value.query_resource.side_effect = Exception("timeout")
            result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", ["aks-1"])

        assert result == {}

    def test_handles_partial_result(self):
        from services.api_gateway.aks_endpoints import _fetch_system_pod_health_batch

        mock_result = _make_logs_result("Partial", [
            ["aks-partial", 4, 0, 0, 0],
        ])

        with patch("azure.monitor.query.LogsQueryClient") as MockClient:
            MockClient.return_value.query_resource.return_value = mock_result
            result = _fetch_system_pod_health_batch(MagicMock(), "/sub/ws/1", ["aks-partial"])

        assert result == {"aks-partial": "healthy"}


# ---------------------------------------------------------------------------
# list_aks_clusters endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """TestClient with mock app.state (no real Azure connections)."""
    from services.api_gateway.main import app
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestListAKSClusters:
    """Integration tests for GET /api/v1/aks system_pod_health enrichment."""

    def test_enriches_system_pod_health_from_container_insights(self, client):
        """When Container Insights returns data, system_pod_health is enriched."""
        mock_arg_response = MagicMock()
        mock_arg_response.data = [_sample_arg_row(name="aks-srelab")]

        health_map = {"aks-srelab": "healthy"}

        with (
            patch("services.api_gateway.aks_endpoints._ARG_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints.ResourceGraphClient", create=True) as MockARG,
            patch("services.api_gateway.aks_endpoints.QueryRequest", create=True),
            patch("azure.identity.DefaultAzureCredential"),
            patch("services.api_gateway.aks_endpoints._fetch_system_pod_health_batch", return_value=health_map),
            patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_RESOURCE_ID": "/sub/ws/1"}),
        ):
            MockARG.return_value.resources.return_value = mock_arg_response
            resp = client.get("/api/v1/aks?subscriptions=sub1")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["clusters"]) == 1
        assert data["clusters"][0]["system_pod_health"] == "healthy"

    def test_falls_back_to_unknown_when_no_workspace(self, client):
        """When LOG_ANALYTICS_WORKSPACE_RESOURCE_ID is unset, system_pod_health stays 'unknown'."""
        mock_arg_response = MagicMock()
        mock_arg_response.data = [_sample_arg_row(name="aks-srelab")]

        with (
            patch("services.api_gateway.aks_endpoints._ARG_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints.ResourceGraphClient", create=True) as MockARG,
            patch("services.api_gateway.aks_endpoints.QueryRequest", create=True),
            patch("azure.identity.DefaultAzureCredential"),
            patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_RESOURCE_ID": ""}, clear=False),
        ):
            MockARG.return_value.resources.return_value = mock_arg_response
            resp = client.get("/api/v1/aks?subscriptions=sub1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["clusters"][0]["system_pod_health"] == "unknown"

    def test_falls_back_to_unknown_when_logs_sdk_unavailable(self, client):
        """When azure-monitor-query is not installed, system_pod_health stays 'unknown'."""
        mock_arg_response = MagicMock()
        mock_arg_response.data = [_sample_arg_row(name="aks-srelab")]

        with (
            patch("services.api_gateway.aks_endpoints._ARG_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", False),
            patch("services.api_gateway.aks_endpoints.ResourceGraphClient", create=True) as MockARG,
            patch("services.api_gateway.aks_endpoints.QueryRequest", create=True),
            patch("azure.identity.DefaultAzureCredential"),
            patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_RESOURCE_ID": "/sub/ws/1"}),
        ):
            MockARG.return_value.resources.return_value = mock_arg_response
            resp = client.get("/api/v1/aks?subscriptions=sub1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["clusters"][0]["system_pod_health"] == "unknown"

    def test_enrichment_failure_degrades_gracefully(self, client):
        """When the batch query raises, system_pod_health stays 'unknown'."""
        mock_arg_response = MagicMock()
        mock_arg_response.data = [_sample_arg_row(name="aks-srelab")]

        with (
            patch("services.api_gateway.aks_endpoints._ARG_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints.ResourceGraphClient", create=True) as MockARG,
            patch("services.api_gateway.aks_endpoints.QueryRequest", create=True),
            patch("azure.identity.DefaultAzureCredential"),
            patch("services.api_gateway.aks_endpoints._fetch_system_pod_health_batch", side_effect=Exception("boom")),
            patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_RESOURCE_ID": "/sub/ws/1"}),
        ):
            MockARG.return_value.resources.return_value = mock_arg_response
            resp = client.get("/api/v1/aks?subscriptions=sub1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["clusters"][0]["system_pod_health"] == "unknown"

    def test_multiple_clusters_enriched(self, client):
        """Multiple clusters in the list get their individual system_pod_health values."""
        mock_arg_response = MagicMock()
        mock_arg_response.data = [
            _sample_arg_row(name="aks-prod"),
            _sample_arg_row(name="aks-dev"),
            _sample_arg_row(name="aks-staging"),
        ]

        health_map = {"aks-prod": "healthy", "aks-dev": "degraded"}

        with (
            patch("services.api_gateway.aks_endpoints._ARG_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints._LOGS_QUERY_AVAILABLE", True),
            patch("services.api_gateway.aks_endpoints.ResourceGraphClient", create=True) as MockARG,
            patch("services.api_gateway.aks_endpoints.QueryRequest", create=True),
            patch("azure.identity.DefaultAzureCredential"),
            patch("services.api_gateway.aks_endpoints._fetch_system_pod_health_batch", return_value=health_map),
            patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_RESOURCE_ID": "/sub/ws/1"}),
        ):
            MockARG.return_value.resources.return_value = mock_arg_response
            resp = client.get("/api/v1/aks?subscriptions=sub1")

        assert resp.status_code == 200
        data = resp.json()
        clusters_by_name = {c["name"]: c for c in data["clusters"]}
        assert clusters_by_name["aks-prod"]["system_pod_health"] == "healthy"
        assert clusters_by_name["aks-dev"]["system_pod_health"] == "degraded"
        # aks-staging not in health_map -> stays 'unknown'
        assert clusters_by_name["aks-staging"]["system_pod_health"] == "unknown"
