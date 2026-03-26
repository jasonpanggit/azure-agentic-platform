"""Arc MCP Server — FastMCP server with all Arc tool registrations (AGENT-005).

Tools:
  Arc Servers (HybridComputeManagementClient):
    - arc_servers_list         — list all Arc servers with connectivity status (MONITOR-004)
    - arc_servers_get          — get a single Arc server with extension health (MONITOR-005)
    - arc_extensions_list      — list extensions on a machine (MONITOR-005)

  Arc Kubernetes (ConnectedKubernetesClient):
    - arc_k8s_list             — list all Arc K8s clusters
    - arc_k8s_get              — get a cluster with Flux GitOps status (MONITOR-006)
    - arc_k8s_gitops_status    — dedicated GitOps reconciliation query (MONITOR-006)

  Arc Data Services (AzureArcDataManagementClient):
    - arc_data_sql_mi_list     — list Arc SQL Managed Instances
    - arc_data_sql_mi_get      — get a single Arc SQL MI
    - arc_data_postgresql_list — list Arc PostgreSQL instances

Transport: streamable-http on port 8080 (stateless_http=True for multi-replica).
Authentication: DefaultAzureCredential (see auth.py).
"""
from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from arc_mcp_server.tools.arc_data import (
    arc_data_postgresql_list_impl,
    arc_data_sql_mi_get_impl,
    arc_data_sql_mi_list_impl,
)
from arc_mcp_server.tools.arc_k8s import (
    arc_k8s_get_impl,
    arc_k8s_gitops_status_impl,
    arc_k8s_list_impl,
)
from arc_mcp_server.tools.arc_servers import (
    arc_extensions_list_impl,
    arc_servers_get_impl,
    arc_servers_list_impl,
)

# stateless_http=True: disables session management — required for multi-replica
# Container App deployment where each request may land on a different replica.
mcp = FastMCP("arc-mcp-server", stateless_http=True)


# ---------------------------------------------------------------------------
# Arc Servers tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def arc_servers_list(
    subscription_id: str,
    resource_group: Optional[str] = None,
) -> dict:
    """List all Arc-enabled servers in a subscription with connectivity status.

    Exhausts all nextLink pages in the Azure ARM response. Returns total_count
    equal to the full estate count — no page is silently dropped (AGENT-006).

    Servers where status == 'Disconnected' and the duration exceeds the
    configured threshold have prolonged_disconnection set to True (MONITOR-004).

    Args:
        subscription_id: Azure subscription ID to query.
        resource_group: Optional resource group filter. Omit to list all servers
            across the entire subscription.

    Returns:
        ArcServersListResult with servers list and total_count.
    """
    result = await arc_servers_list_impl(subscription_id, resource_group)
    return result.model_dump()


@mcp.tool()
async def arc_servers_get(
    subscription_id: str,
    resource_group: str,
    machine_name: str,
) -> dict:
    """Get a single Arc-enabled server with extension health details.

    Returns connectivity status, agent version, OS information, and the full
    extension inventory (AMA, VM Insights, Change Tracking, Policy) (MONITOR-005).

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Resource group containing the Arc machine.
        machine_name: Name of the Arc-enabled machine.

    Returns:
        ArcServerDetail with machine info and extensions list.
    """
    result = await arc_servers_get_impl(subscription_id, resource_group, machine_name)
    return result.model_dump()


@mcp.tool()
async def arc_extensions_list(
    subscription_id: str,
    resource_group: str,
    machine_name: str,
) -> dict:
    """List all extensions on an Arc-enabled server with health status.

    Returns install status and version for all extensions, including:
    AMA (AzureMonitorWindowsAgent/Linux), VM Insights (DependencyAgent),
    Change Tracking, and Azure Policy (GuestConfiguration) (MONITOR-005).

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Resource group containing the Arc machine.
        machine_name: Name of the Arc-enabled machine.

    Returns:
        ArcExtensionsListResult with extensions and total_count.
    """
    result = await arc_extensions_list_impl(subscription_id, resource_group, machine_name)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Arc Kubernetes tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def arc_k8s_list(
    subscription_id: str,
    resource_group: Optional[str] = None,
    include_flux: bool = False,
) -> dict:
    """List all Arc-enabled Kubernetes clusters in a subscription.

    Exhausts all nextLink pages. Returns total_count equal to the full cluster
    count — no page silently dropped (AGENT-006).

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Optional resource group filter.
        include_flux: When True, fetches Flux configurations per cluster
            (adds one ARM call per cluster). Default False for bulk listing.

    Returns:
        ArcK8sListResult with clusters and total_count.
    """
    result = await arc_k8s_list_impl(subscription_id, resource_group, include_flux)
    return result.model_dump()


@mcp.tool()
async def arc_k8s_get(
    subscription_id: str,
    resource_group: str,
    cluster_name: str,
) -> dict:
    """Get a single Arc K8s cluster with Flux GitOps reconciliation status.

    Returns connectivity status, Kubernetes version, distribution, node count,
    and all Flux configurations with compliance state (MONITOR-006).

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Resource group containing the cluster.
        cluster_name: Name of the Arc-enabled Kubernetes cluster.

    Returns:
        ArcK8sSummary with cluster info and Flux configurations.
    """
    result = await arc_k8s_get_impl(subscription_id, resource_group, cluster_name)
    return result.model_dump()


@mcp.tool()
async def arc_k8s_gitops_status(
    subscription_id: str,
    resource_group: str,
    cluster_name: str,
) -> dict:
    """Get GitOps reconciliation status for an Arc K8s cluster (MONITOR-006).

    Returns Flux compliance state, repository URL, branch, and sync interval
    for each Flux configuration on the cluster.

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Resource group containing the cluster.
        cluster_name: Name of the Arc-enabled Kubernetes cluster.

    Returns:
        Dict with flux_detected flag, configurations list, and total_configurations.
    """
    return await arc_k8s_gitops_status_impl(subscription_id, resource_group, cluster_name)


# ---------------------------------------------------------------------------
# Arc Data Services tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def arc_data_sql_mi_list(subscription_id: str) -> dict:
    """List all Arc-enabled SQL Managed Instances in a subscription.

    Exhausts all nextLink pages. Returns total_count (AGENT-006).

    Args:
        subscription_id: Azure subscription ID.

    Returns:
        ArcSqlMiListResult with instances and total_count.
    """
    result = await arc_data_sql_mi_list_impl(subscription_id)
    return result.model_dump()


@mcp.tool()
async def arc_data_sql_mi_get(
    subscription_id: str,
    resource_group: str,
    instance_name: str,
) -> dict:
    """Get a single Arc-enabled SQL Managed Instance by name.

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Resource group containing the instance.
        instance_name: Name of the Arc SQL Managed Instance.

    Returns:
        ArcSqlMiSummary with instance details.
    """
    result = await arc_data_sql_mi_get_impl(subscription_id, resource_group, instance_name)
    return result.model_dump()


@mcp.tool()
async def arc_data_postgresql_list(subscription_id: str) -> dict:
    """List all Arc-enabled PostgreSQL instances in a subscription.

    Exhausts all nextLink pages. Returns total_count (AGENT-006).

    Args:
        subscription_id: Azure subscription ID.

    Returns:
        ArcPostgreSQLListResult with instances and total_count.
    """
    result = await arc_data_postgresql_list_impl(subscription_id)
    return result.model_dump()
