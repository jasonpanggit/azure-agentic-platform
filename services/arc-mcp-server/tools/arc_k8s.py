"""Arc Kubernetes tools for the Arc MCP Server (AGENT-005, MONITOR-006).

Tools expose ConnectedKubernetesClient and SourceControlConfigurationClient
operations. Flux GitOps status is detected via ARM-native flux_configurations
API — no direct Kubernetes API access required (MONITOR-006).

All list tools exhaust ItemPaged and return total_count (AGENT-006).
"""
from __future__ import annotations

from typing import Optional

from azure.mgmt.hybridkubernetes import ConnectedKubernetesClient
from azure.mgmt.kubernetesconfiguration import SourceControlConfigurationClient

from arc_mcp_server.auth import get_credential
from arc_mcp_server.models import (
    ArcFluxConfiguration,
    ArcK8sListResult,
    ArcK8sSummary,
)


def _get_k8s_client(subscription_id: str) -> ConnectedKubernetesClient:
    return ConnectedKubernetesClient(
        credential=get_credential(),
        subscription_id=subscription_id,
    )


def _get_config_client(subscription_id: str) -> SourceControlConfigurationClient:
    return SourceControlConfigurationClient(
        credential=get_credential(),
        subscription_id=subscription_id,
    )


def _extract_resource_group(resource_id: str) -> str:
    """Extract resource group from ARM resource ID."""
    parts = resource_id.split("/")
    try:
        rg_index = next(i for i, p in enumerate(parts) if p.lower() == "resourcegroups")
        return parts[rg_index + 1]
    except (StopIteration, IndexError):
        return ""


def _get_flux_configs(
    config_client: SourceControlConfigurationClient,
    resource_group: str,
    cluster_name: str,
) -> list[ArcFluxConfiguration]:
    """Retrieve Flux configurations for a connected cluster (MONITOR-006).

    Uses ARM-native SourceControlConfigurationClient — no kubectl access.
    Returns empty list if Flux is not configured or permission is denied.
    """
    try:
        configs_paged = config_client.flux_configurations.list(
            resource_group_name=resource_group,
            cluster_rp="Microsoft.Kubernetes",
            cluster_resource_name="connectedClusters",
            cluster_name=cluster_name,
        )
        result = []
        for cfg in configs_paged:
            git_repo = getattr(cfg, "git_repository", None)
            result.append(
                ArcFluxConfiguration(
                    name=getattr(cfg, "name", "") or "",
                    compliance_state=getattr(cfg, "compliance_state", None),
                    provisioning_state=getattr(cfg, "provisioning_state", None),
                    source_kind=getattr(cfg, "source_kind", None),
                    repository_url=getattr(git_repo, "url", None) if git_repo else None,
                    branch=getattr(git_repo, "ref", {}).get("branch") if git_repo else None,
                    sync_interval_in_seconds=getattr(cfg, "sync_interval_in_seconds", None),
                )
            )
        return result
    except Exception:
        # Permission denied or Flux not configured — return empty list
        return []


def _serialize_cluster(
    cluster,
    subscription_id: str,
    flux_configs: list[ArcFluxConfiguration] | None = None,
) -> ArcK8sSummary:
    """Convert SDK ConnectedCluster to ArcK8sSummary Pydantic model."""
    resource_id = getattr(cluster, "id", "") or ""
    props = getattr(cluster, "properties", None)

    # Handle both direct attributes and properties sub-object across SDK versions
    def _prop(name: str):
        val = getattr(props, name, None) if props else None
        if val is None:
            val = getattr(cluster, name, None)
        return val

    last_conn = _prop("last_connectivity_time")
    flux_list = flux_configs or []

    return ArcK8sSummary(
        resource_id=resource_id,
        name=getattr(cluster, "name", "") or "",
        resource_group=_extract_resource_group(resource_id),
        subscription_id=subscription_id,
        location=getattr(cluster, "location", None),
        connectivity_status=str(_prop("connectivity_status") or ""),
        last_connectivity_time=last_conn.isoformat() if last_conn else None,
        kubernetes_version=_prop("kubernetes_version"),
        distribution=_prop("distribution"),
        total_node_count=_prop("total_node_count"),
        total_core_count=_prop("total_core_count"),
        agent_version=_prop("agent_version"),
        provisioning_state=_prop("provisioning_state"),
        flux_detected=len(flux_list) > 0,
        flux_configurations=flux_list,
    )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def arc_k8s_list_impl(
    subscription_id: str,
    resource_group: Optional[str] = None,
    include_flux: bool = False,
) -> ArcK8sListResult:
    """List all Arc-enabled Kubernetes clusters (AGENT-006).

    Iterates ItemPaged to exhaustion, following all nextLink pages.
    total_count equals len(clusters) — the full estate count (AGENT-006).

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Optional filter by resource group.
        include_flux: When True, fetches Flux configurations per cluster.
            This adds N additional ARM calls. Default False for bulk listing.
    """
    k8s_client = _get_k8s_client(subscription_id)
    config_client = _get_config_client(subscription_id) if include_flux else None

    paged = (
        k8s_client.connected_cluster.list_by_resource_group(resource_group)
        if resource_group
        else k8s_client.connected_cluster.list_by_subscription()
    )

    clusters = []
    for cluster in paged:  # Exhausts all nextLink pages automatically (AGENT-006)
        resource_id = getattr(cluster, "id", "") or ""
        rg = _extract_resource_group(resource_id)
        cluster_name = getattr(cluster, "name", "") or ""

        flux_configs = None
        if include_flux and config_client:
            flux_configs = _get_flux_configs(config_client, rg, cluster_name)

        clusters.append(_serialize_cluster(cluster, subscription_id, flux_configs))

    return ArcK8sListResult(
        subscription_id=subscription_id,
        resource_group=resource_group,
        clusters=clusters,
        total_count=len(clusters),  # AGENT-006: MUST equal full count
    )


async def arc_k8s_get_impl(
    subscription_id: str,
    resource_group: str,
    cluster_name: str,
) -> ArcK8sSummary:
    """Get a single Arc K8s cluster with Flux GitOps status (MONITOR-006).

    Always fetches Flux configurations for the single cluster.
    """
    k8s_client = _get_k8s_client(subscription_id)
    config_client = _get_config_client(subscription_id)

    cluster = k8s_client.connected_cluster.get(resource_group, cluster_name)
    flux_configs = _get_flux_configs(config_client, resource_group, cluster_name)

    return _serialize_cluster(cluster, subscription_id, flux_configs)


async def arc_k8s_gitops_status_impl(
    subscription_id: str,
    resource_group: str,
    cluster_name: str,
) -> dict:
    """Get GitOps reconciliation status for an Arc K8s cluster (MONITOR-006).

    Returns Flux compliance state, repository URL, and sync status for each
    Flux configuration. Returns flux_detected=False if Flux is not configured.
    """
    config_client = _get_config_client(subscription_id)
    flux_configs = _get_flux_configs(config_client, resource_group, cluster_name)

    return {
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "cluster_name": cluster_name,
        "flux_detected": len(flux_configs) > 0,
        "configurations": [cfg.model_dump() for cfg in flux_configs],
        "total_configurations": len(flux_configs),
    }
