from __future__ import annotations
"""Tests for aks_health_service.py (Phase 83).

Covers:
- _stable_id: deterministic UUID generation
- _compare_k8s_version: version comparison
- _classify_health: all health states
- scan_aks_clusters: SDK unavailable, empty subscriptions, full scan, error handling
- persist_aks_data: happy path, error handling
- get_aks_clusters: filters, error handling
- get_aks_summary: computation, error handling
"""
import os

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.aks_health_service import (
    AKSCluster,
    _classify_health,
    _compare_k8s_version,
    _stable_id,
    get_aks_clusters,
    get_aks_summary,
    persist_aks_data,
    scan_aks_clusters,
)


# ---------------------------------------------------------------------------
# _stable_id
# ---------------------------------------------------------------------------

class TestStableId:
    def test_deterministic(self):
        a = _stable_id("/subscriptions/abc/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/mycluster")
        b = _stable_id("/subscriptions/abc/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/mycluster")
        assert a == b

    def test_different_ids_give_different_uuids(self):
        a = _stable_id("arm-id-one")
        b = _stable_id("arm-id-two")
        assert a != b

    def test_is_string(self):
        result = _stable_id("anything")
        assert isinstance(result, str)
        assert len(result) == 36  # UUID format


# ---------------------------------------------------------------------------
# _compare_k8s_version
# ---------------------------------------------------------------------------

class TestCompareK8sVersion:
    def test_equal_version(self):
        assert _compare_k8s_version("1.28", "1.28") is True

    def test_higher_version(self):
        assert _compare_k8s_version("1.30", "1.28") is True

    def test_lower_version(self):
        assert _compare_k8s_version("1.27", "1.28") is False

    def test_patch_version_ignored(self):
        assert _compare_k8s_version("1.28.5", "1.28") is True

    def test_unknown_version_does_not_flag(self):
        # Unknown versions should not be flagged (returns True = passes)
        assert _compare_k8s_version("", "1.28") is True

    def test_major_version_ahead(self):
        assert _compare_k8s_version("2.0", "1.28") is True


# ---------------------------------------------------------------------------
# _classify_health
# ---------------------------------------------------------------------------

class TestClassifyHealth:
    def _pool(self, state: str = "Succeeded", count: int = 2) -> dict:
        return {"name": "pool1", "count": count, "provisioning_state": state}

    def test_stopped_cluster(self):
        status, reasons = _classify_health("Stopped", "Succeeded", [self._pool()], True, "1.29")
        assert status == "stopped"
        assert reasons

    def test_creating_cluster(self):
        status, reasons = _classify_health("Running", "Creating", [self._pool()], True, "1.29")
        assert status == "provisioning"

    def test_deleting_cluster(self):
        status, _ = _classify_health("Running", "Deleting", [self._pool()], True, "1.29")
        assert status == "provisioning"

    def test_degraded_pool_not_ready(self):
        pool = {"name": "pool1", "count": 2, "provisioning_state": "Failed"}
        status, reasons = _classify_health("Running", "Succeeded", [pool], True, "1.29")
        assert status == "degraded"
        assert any("pool1" in r for r in reasons)

    def test_degraded_no_nodes(self):
        pool = {"name": "pool1", "count": 0, "provisioning_state": "Succeeded"}
        status, reasons = _classify_health("Running", "Succeeded", [pool], True, "1.29")
        assert status == "degraded"

    def test_degraded_no_rbac(self):
        status, reasons = _classify_health("Running", "Succeeded", [self._pool()], False, "1.29")
        assert status == "degraded"
        assert any("RBAC" in r for r in reasons)

    def test_degraded_outdated_version(self):
        status, reasons = _classify_health("Running", "Succeeded", [self._pool()], True, "1.26")
        assert status == "degraded"
        assert any("1.26" in r for r in reasons)

    def test_healthy_cluster(self):
        status, reasons = _classify_health("Running", "Succeeded", [self._pool()], True, "1.29")
        assert status == "healthy"
        assert reasons == []


# ---------------------------------------------------------------------------
# scan_aks_clusters
# ---------------------------------------------------------------------------

class TestScanAksClusters:
    def test_returns_empty_when_sdk_unavailable(self):
        with patch("services.api_gateway.aks_health_service._ARG_AVAILABLE", False):
            result = scan_aks_clusters(MagicMock(), ["sub-1"])
        assert result == []

    def test_returns_empty_when_no_subscriptions(self):
        with patch("services.api_gateway.aks_health_service._ARG_AVAILABLE", True):
            result = scan_aks_clusters(MagicMock(), [])
        assert result == []

    def test_full_scan_returns_clusters(self):
        cluster_row = {
            "arm_id": "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.containerservice/managedclusters/mycluster",
            "cluster_name": "mycluster",
            "resource_group": "rg",
            "subscription_id": "sub1",
            "location": "eastus",
            "kubernetes_version": "1.29",
            "power_state": "Running",
            "provisioning_state": "Succeeded",
            "private_cluster": True,
            "enable_rbac": True,
            "fqdn": "mycluster.hcp.eastus.azmk8s.io",
            "tags": {},
        }
        pool_row = {
            "pool_id": "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.containerservice/managedclusters/mycluster/agentpools/nodepool1",
            "pool_name": "nodepool1",
            "cluster_arm": "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.containerservice/managedclusters/mycluster",
            "subscription_id": "sub1",
            "resource_group": "rg",
            "mode": "System",
            "vm_size": "Standard_D4s_v3",
            "count": 3,
            "min_count": None,
            "max_count": None,
            "enable_autoscaling": False,
            "os_type": "Linux",
            "provisioning_state": "Succeeded",
            "kubernetes_version": "1.29",
        }

        mock_resp_clusters = MagicMock()
        mock_resp_clusters.data = [cluster_row]
        mock_resp_clusters.skip_token = None

        mock_resp_pools = MagicMock()
        mock_resp_pools.data = [pool_row]
        mock_resp_pools.skip_token = None

        mock_client = MagicMock()
        mock_client.resources.side_effect = [mock_resp_clusters, mock_resp_pools]

        with patch("services.api_gateway.aks_health_service._ARG_AVAILABLE", True), \
             patch("services.api_gateway.aks_health_service.ResourceGraphClient", return_value=mock_client), \
             patch("services.api_gateway.aks_health_service.QueryRequest", side_effect=lambda **kw: MagicMock()), \
             patch("services.api_gateway.aks_health_service.QueryRequestOptions", side_effect=lambda **kw: MagicMock()):
            result = scan_aks_clusters(MagicMock(), ["sub1"])

        assert len(result) == 1
        cluster = result[0]
        assert cluster.cluster_name == "mycluster"
        assert cluster.health_status == "healthy"
        assert cluster.node_count == 3
        assert len(cluster.node_pools) == 1

    def test_scan_never_raises_on_exception(self):
        with patch("services.api_gateway.aks_health_service._ARG_AVAILABLE", True), \
             patch("services.api_gateway.aks_health_service.ResourceGraphClient", side_effect=RuntimeError("boom")):
            result = scan_aks_clusters(MagicMock(), ["sub1"])
        assert result == []

    def test_stopped_cluster_classified_correctly(self):
        cluster_row = {
            "arm_id": "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.containerservice/managedclusters/stopped",
            "cluster_name": "stopped",
            "resource_group": "rg",
            "subscription_id": "sub1",
            "location": "eastus",
            "kubernetes_version": "1.29",
            "power_state": "Stopped",
            "provisioning_state": "Succeeded",
            "private_cluster": False,
            "enable_rbac": True,
            "fqdn": "",
            "tags": {},
        }
        mock_resp = MagicMock()
        mock_resp.data = [cluster_row]
        mock_resp.skip_token = None
        mock_pool_resp = MagicMock()
        mock_pool_resp.data = []
        mock_pool_resp.skip_token = None
        mock_client = MagicMock()
        mock_client.resources.side_effect = [mock_resp, mock_pool_resp]

        with patch("services.api_gateway.aks_health_service._ARG_AVAILABLE", True), \
             patch("services.api_gateway.aks_health_service.ResourceGraphClient", return_value=mock_client), \
             patch("services.api_gateway.aks_health_service.QueryRequest", side_effect=lambda **kw: MagicMock()), \
             patch("services.api_gateway.aks_health_service.QueryRequestOptions", side_effect=lambda **kw: MagicMock()):
            result = scan_aks_clusters(MagicMock(), ["sub1"])

        assert result[0].health_status == "stopped"


# ---------------------------------------------------------------------------
# persist_aks_data
# ---------------------------------------------------------------------------

class TestPersistAksData:
    def _make_cluster(self) -> AKSCluster:
        return AKSCluster(
            cluster_id="uuid-1",
            arm_id="/subscriptions/sub1/rg/rg/providers/microsoft.containerservice/managedclusters/c",
            cluster_name="c",
            resource_group="rg",
            subscription_id="sub1",
            location="eastus",
            kubernetes_version="1.29",
            power_state="Running",
            provisioning_state="Succeeded",
            node_count=2,
            node_pools=[],
            private_cluster=True,
            enable_rbac=True,
            fqdn="c.hcp.eastus.azmk8s.io",
            health_status="healthy",
            health_reasons=[],
            scanned_at="2026-04-17T00:00:00Z",
        )

    def test_upserts_items(self):
        mock_container = MagicMock()
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        persist_aks_data(mock_cosmos, "aap", [self._make_cluster()])
        mock_container.upsert_item.assert_called_once()

    def test_never_raises_on_error(self):
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.side_effect = RuntimeError("cosmos down")
        # Should not raise
        persist_aks_data(mock_cosmos, "aap", [self._make_cluster()])

    def test_no_op_on_empty_list(self):
        mock_cosmos = MagicMock()
        persist_aks_data(mock_cosmos, "aap", [])
        mock_cosmos.get_database_client.assert_not_called()


# ---------------------------------------------------------------------------
# get_aks_clusters
# ---------------------------------------------------------------------------

class TestGetAksClusters:
    def _make_cosmos(self, items: list) -> MagicMock:
        mock_container = MagicMock()
        mock_container.query_items.return_value = items
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db
        return mock_cosmos

    def test_returns_items(self):
        cosmos = self._make_cosmos([{"cluster_id": "1", "subscription_id": "sub1"}])
        result = get_aks_clusters(cosmos, "aap")
        assert len(result) == 1

    def test_with_subscription_filter(self):
        cosmos = self._make_cosmos([])
        get_aks_clusters(cosmos, "aap", subscription_ids=["sub1"])
        call_kwargs = cosmos.get_database_client().get_container_client().query_items.call_args
        assert "sub1" in str(call_kwargs)

    def test_with_health_filter(self):
        cosmos = self._make_cosmos([])
        get_aks_clusters(cosmos, "aap", health_status="degraded")
        call_kwargs = cosmos.get_database_client().get_container_client().query_items.call_args
        assert "degraded" in str(call_kwargs)

    def test_never_raises(self):
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.side_effect = RuntimeError("boom")
        result = get_aks_clusters(mock_cosmos, "aap")
        assert result == []


# ---------------------------------------------------------------------------
# get_aks_summary
# ---------------------------------------------------------------------------

class TestGetAksSummary:
    def _make_clusters(self) -> list:
        return [
            {"health_status": "healthy", "node_count": 5, "enable_rbac": True, "private_cluster": True, "kubernetes_version": "1.29"},
            {"health_status": "degraded", "node_count": 3, "enable_rbac": False, "private_cluster": False, "kubernetes_version": "1.27"},
            {"health_status": "stopped", "node_count": 0, "enable_rbac": True, "private_cluster": True, "kubernetes_version": "1.29"},
        ]

    def test_correct_counts(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = self._make_clusters()
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        summary = get_aks_summary(mock_cosmos, "aap")
        assert summary["total_clusters"] == 3
        assert summary["healthy"] == 1
        assert summary["degraded"] == 1
        assert summary["stopped"] == 1
        assert summary["total_nodes"] == 8
        assert summary["clusters_without_rbac"] == 1
        assert summary["clusters_without_private_api"] == 1
        assert summary["outdated_version_count"] == 1

    def test_never_raises(self):
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.side_effect = RuntimeError("boom")
        result = get_aks_summary(mock_cosmos, "aap")
        assert result["total_clusters"] == 0
