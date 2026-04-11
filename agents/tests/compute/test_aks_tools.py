"""Tests for AKS tools added to compute agent (Phase 32)."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch


def _instr_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryAksClusterHealth:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ContainerServiceClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_cluster_state(self, mock_cred, mock_aks_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_aks = MagicMock()
        mock_aks_cls.return_value = mock_aks
        cluster = MagicMock()
        cluster.provisioning_state = "Succeeded"
        cluster.kubernetes_version = "1.29.0"
        cluster.power_state.code = "Running"
        cluster.fqdn = "aks1-dns.hcp.eastus.azmk8s.io"
        cluster.enable_rbac = True
        mock_aks.managed_clusters.get.return_value = cluster

        from agents.compute.tools import query_aks_cluster_health

        result = query_aks_cluster_health("rg", "aks1", "sub", "t1")
        assert result["provisioning_state"] == "Succeeded"
        assert result["kubernetes_version"] == "1.29.0"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ContainerServiceClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()

        from agents.compute.tools import query_aks_cluster_health

        result = query_aks_cluster_health("rg", "aks1", "sub", "t1")
        assert "error" in result


class TestQueryAksNodePools:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ContainerServiceClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_node_pools(self, mock_cred, mock_aks_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_aks = MagicMock()
        mock_aks_cls.return_value = mock_aks
        np = MagicMock()
        np.name = "nodepool1"
        np.count = 3
        np.vm_size = "Standard_D4s_v3"
        np.provisioning_state = "Succeeded"
        np.os_type = "Linux"
        mock_aks.agent_pools.list.return_value = [np]

        from agents.compute.tools import query_aks_node_pools

        result = query_aks_node_pools("rg", "aks1", "sub", "t1")
        assert "node_pools" in result
        assert len(result["node_pools"]) == 1


class TestQueryAksUpgradeProfile:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ContainerServiceClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_upgrade_versions(self, mock_cred, mock_aks_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_aks = MagicMock()
        mock_aks_cls.return_value = mock_aks
        upgrade = MagicMock()
        cp_upgrade = MagicMock()
        cp_upgrade.kubernetes_version = "1.29.0"
        inner_upgrade = MagicMock()
        inner_upgrade.kubernetes_version = "1.30.0"
        inner_upgrade.is_preview = False
        cp_upgrade.upgrades = [inner_upgrade]
        upgrade.control_plane_profile = cp_upgrade
        mock_aks.managed_clusters.get_upgrade_profile.return_value = upgrade

        from agents.compute.tools import query_aks_upgrade_profile

        result = query_aks_upgrade_profile("rg", "aks1", "sub", "t1")
        assert "current_version" in result
        assert "available_upgrades" in result


class TestProposeAksNodePoolScale:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.create_approval_record")
    def test_creates_approval_record(self, mock_create, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_aks", "status": "pending"}

        from agents.compute.tools import propose_aks_node_pool_scale

        result = propose_aks_node_pool_scale(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks1",
            resource_group="rg",
            cluster_name="aks1",
            node_pool_name="nodepool1",
            subscription_id="sub",
            target_count=5,
            incident_id="inc-001",
            thread_id="t1",
            reason="Scale out to handle load",
        )
        mock_create.assert_called_once()
        assert result["status"] == "pending_approval"

    def test_does_not_call_arm_directly(self):
        from agents.compute import tools as t

        src = inspect.getsource(t.propose_aks_node_pool_scale)
        assert "begin_create_or_update" not in src
        assert "agent_pools.create" not in src
