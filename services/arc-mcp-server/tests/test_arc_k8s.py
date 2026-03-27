"""Unit tests for Arc Kubernetes tools (AGENT-005, AGENT-006, MONITOR-006).

Tests cover:
  - Cluster pagination exhaustion (AGENT-006)
  - Flux GitOps detection via ARM (MONITOR-006)
  - Flux compliance state surfacing
  - ConnectedCluster field serialisation
  - Empty-result handling
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from arc_mcp_server.tools.arc_k8s import (
    _get_flux_configs,
    arc_k8s_get_impl,
    arc_k8s_gitops_status_impl,
    arc_k8s_list_impl,
)


def _make_flux_config(
    name: str,
    compliance_state: str = "Compliant",
    repository_url: str = "https://github.com/org/gitops-repo",
    branch: str = "main",
) -> MagicMock:
    """Create a mock FluxConfiguration for testing."""
    cfg = MagicMock()
    cfg.name = name
    cfg.compliance_state = compliance_state
    cfg.provisioning_state = "Succeeded"
    cfg.source_kind = "GitRepository"
    git_repo = MagicMock()
    git_repo.url = repository_url
    git_repo.ref = {"branch": branch}
    cfg.git_repository = git_repo
    cfg.sync_interval_in_seconds = 600
    return cfg


# ---------------------------------------------------------------------------
# AGENT-006: K8s pagination exhaustion
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_list_exhausts_pagination(sample_clusters_105):
    """AGENT-006: arc_k8s_list_impl returns all 105 clusters, total_count == 105."""
    with patch(
        "arc_mcp_server.tools.arc_k8s._get_k8s_client"
    ) as mock_k8s_factory, patch(
        "arc_mcp_server.tools.arc_k8s._get_config_client"
    ) as mock_config_factory:
        mock_k8s = MagicMock()
        mock_k8s.connected_cluster.list_by_subscription.return_value = iter(
            sample_clusters_105
        )
        mock_k8s_factory.return_value = mock_k8s

        result = await arc_k8s_list_impl(
            subscription_id="sub-test-001",
            include_flux=False,
        )

    assert result.total_count == 105
    assert len(result.clusters) == 105
    assert result.subscription_id == "sub-test-001"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_list_rg_scope(sample_clusters_105):
    """arc_k8s_list_impl uses list_by_resource_group when resource_group is given."""
    subset = sample_clusters_105[:8]
    with patch("arc_mcp_server.tools.arc_k8s._get_k8s_client") as mock_k8s_factory:
        mock_k8s = MagicMock()
        mock_k8s.connected_cluster.list_by_resource_group.return_value = iter(subset)
        mock_k8s_factory.return_value = mock_k8s

        result = await arc_k8s_list_impl(
            subscription_id="sub-test-001",
            resource_group="rg-k8s-test",
        )

    assert result.total_count == 8
    mock_k8s.connected_cluster.list_by_resource_group.assert_called_once_with(
        "rg-k8s-test"
    )
    mock_k8s.connected_cluster.list_by_subscription.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_list_empty():
    """arc_k8s_list_impl handles empty subscription gracefully."""
    with patch("arc_mcp_server.tools.arc_k8s._get_k8s_client") as mock_k8s_factory:
        mock_k8s = MagicMock()
        mock_k8s.connected_cluster.list_by_subscription.return_value = iter([])
        mock_k8s_factory.return_value = mock_k8s

        result = await arc_k8s_list_impl(subscription_id="sub-empty")

    assert result.total_count == 0
    assert result.clusters == []


# ---------------------------------------------------------------------------
# MONITOR-006: Flux GitOps detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_flux_configs_returns_configs():
    """MONITOR-006: _get_flux_configs returns FluxConfiguration objects."""
    cfg1 = _make_flux_config("flux-config-01", compliance_state="Compliant")
    cfg2 = _make_flux_config("flux-config-02", compliance_state="NonCompliant")

    mock_config_client = MagicMock()
    mock_config_client.flux_configurations.list.return_value = iter([cfg1, cfg2])

    configs = _get_flux_configs(
        mock_config_client,
        resource_group="rg-k8s-test",
        cluster_name="arc-cluster-0001",
    )

    assert len(configs) == 2
    names = {c.name for c in configs}
    assert "flux-config-01" in names
    assert "flux-config-02" in names
    compliant = next(c for c in configs if c.name == "flux-config-01")
    assert compliant.compliance_state == "Compliant"
    non_compliant = next(c for c in configs if c.name == "flux-config-02")
    assert non_compliant.compliance_state == "NonCompliant"


@pytest.mark.unit
def test_get_flux_configs_no_flux():
    """MONITOR-006: _get_flux_configs returns empty list when no Flux configured."""
    mock_config_client = MagicMock()
    mock_config_client.flux_configurations.list.return_value = iter([])

    configs = _get_flux_configs(mock_config_client, "rg-test", "cluster-no-flux")

    assert configs == []


@pytest.mark.unit
def test_get_flux_configs_permission_error_returns_empty():
    """MONITOR-006: _get_flux_configs returns [] on permission denied — no exception."""
    mock_config_client = MagicMock()
    mock_config_client.flux_configurations.list.side_effect = Exception(
        "AuthorizationFailed"
    )

    configs = _get_flux_configs(mock_config_client, "rg-test", "cluster-no-perm")

    assert configs == []  # Fail-safe: empty list, not exception


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_gitops_status_with_flux():
    """MONITOR-006: arc_k8s_gitops_status_impl surfaces flux_detected=True and configs."""
    cfg1 = _make_flux_config("gitops-config", compliance_state="Compliant")

    with patch(
        "arc_mcp_server.tools.arc_k8s._get_config_client"
    ) as mock_config_factory:
        mock_config = MagicMock()
        mock_config.flux_configurations.list.return_value = iter([cfg1])
        mock_config_factory.return_value = mock_config

        result = await arc_k8s_gitops_status_impl(
            subscription_id="sub-test-001",
            resource_group="rg-k8s-test",
            cluster_name="arc-cluster-0001",
        )

    assert result["flux_detected"] is True
    assert result["total_configurations"] == 1
    assert result["configurations"][0]["compliance_state"] == "Compliant"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_gitops_status_no_flux():
    """MONITOR-006: arc_k8s_gitops_status_impl returns flux_detected=False when no Flux."""
    with patch(
        "arc_mcp_server.tools.arc_k8s._get_config_client"
    ) as mock_config_factory:
        mock_config = MagicMock()
        mock_config.flux_configurations.list.return_value = iter([])
        mock_config_factory.return_value = mock_config

        result = await arc_k8s_gitops_status_impl(
            subscription_id="sub-test-001",
            resource_group="rg-k8s-test",
            cluster_name="arc-cluster-no-flux",
        )

    assert result["flux_detected"] is False
    assert result["total_configurations"] == 0
    assert result["configurations"] == []


# ---------------------------------------------------------------------------
# arc_k8s_get_impl — single cluster with Flux
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_get_with_flux(sample_clusters_105):
    """arc_k8s_get_impl includes Flux configurations for single cluster."""
    single_cluster = sample_clusters_105[0]
    flux_cfg = _make_flux_config("gitops-prod", compliance_state="Compliant")

    with patch(
        "arc_mcp_server.tools.arc_k8s._get_k8s_client"
    ) as mock_k8s_factory, patch(
        "arc_mcp_server.tools.arc_k8s._get_config_client"
    ) as mock_config_factory:
        mock_k8s = MagicMock()
        mock_k8s.connected_cluster.get.return_value = single_cluster
        mock_k8s_factory.return_value = mock_k8s

        mock_config = MagicMock()
        mock_config.flux_configurations.list.return_value = iter([flux_cfg])
        mock_config_factory.return_value = mock_config

        result = await arc_k8s_get_impl(
            subscription_id="sub-test-001",
            resource_group="rg-arc-k8s-test",
            cluster_name="arc-cluster-0000",
        )

    assert result.flux_detected is True
    assert len(result.flux_configurations) == 1
    assert result.flux_configurations[0].compliance_state == "Compliant"
