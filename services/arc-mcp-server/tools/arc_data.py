"""Arc Data Services tools for the Arc MCP Server (AGENT-005).

Exposes AzureArcDataManagementClient for Arc SQL Managed Instances and
Arc PostgreSQL instances. All list tools exhaust pagination (AGENT-006).

NOTE: azure-mgmt-azurearcdata==1.0.0 is the only stable version and has
sparse coverage. If SDK operations are insufficient, fall back to ARM REST
calls via azure-mgmt-resource. Verify client.sql_managed_instances.list()
and client.postgresql_instances.list() method signatures at implementation.

Package: azure-mgmt-azurearcdata==1.0.0 (NOT azure-mgmt-arcdata — that package
does not exist on PyPI as of March 2026).
"""
from __future__ import annotations

from arc_mcp_server.auth import get_credential
from arc_mcp_server.models import (
    ArcPostgreSQLListResult,
    ArcPostgreSQLSummary,
    ArcSqlMiListResult,
    ArcSqlMiSummary,
)


def _get_arcdata_client(subscription_id: str):
    """Create AzureArcDataManagementClient for the given subscription."""
    from azure.mgmt.azurearcdata import AzureArcDataManagementClient

    return AzureArcDataManagementClient(
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


def _serialize_sql_mi(instance, subscription_id: str) -> ArcSqlMiSummary:
    """Convert SDK SqlManagedInstance to ArcSqlMiSummary."""
    resource_id = getattr(instance, "id", "") or ""
    props = getattr(instance, "properties", None)

    def _prop(name: str):
        val = getattr(props, name, None) if props else None
        if val is None:
            val = getattr(instance, name, None)
        return val

    return ArcSqlMiSummary(
        resource_id=resource_id,
        name=getattr(instance, "name", "") or "",
        resource_group=_extract_resource_group(resource_id),
        subscription_id=subscription_id,
        location=getattr(instance, "location", None),
        state=str(_prop("state") or ""),
        edition=_prop("edition"),
        v_cores=_prop("v_cores"),
        provisioning_state=_prop("provisioning_state"),
    )


def _serialize_postgresql(instance, subscription_id: str) -> ArcPostgreSQLSummary:
    """Convert SDK PostgreSqlInstance to ArcPostgreSQLSummary."""
    resource_id = getattr(instance, "id", "") or ""
    props = getattr(instance, "properties", None)

    def _prop(name: str):
        val = getattr(props, name, None) if props else None
        if val is None:
            val = getattr(instance, name, None)
        return val

    return ArcPostgreSQLSummary(
        resource_id=resource_id,
        name=getattr(instance, "name", "") or "",
        resource_group=_extract_resource_group(resource_id),
        subscription_id=subscription_id,
        location=getattr(instance, "location", None),
        state=str(_prop("state") or ""),
        provisioning_state=_prop("provisioning_state"),
    )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def arc_data_sql_mi_list_impl(subscription_id: str) -> ArcSqlMiListResult:
    """List all Arc-enabled SQL Managed Instances in a subscription (AGENT-006).

    Iterates ItemPaged to exhaustion. total_count equals len(instances).

    NOTE: If azure-mgmt-azurearcdata==1.0.0 raises AttributeError on
    client.sql_managed_instances.list(), use list_in_subscription() or
    direct ARM REST call as fallback. Verify at implementation time.
    """
    client = _get_arcdata_client(subscription_id)

    # Exhaust all pages (AGENT-006)
    instances = [_serialize_sql_mi(i, subscription_id) for i in client.sql_managed_instances.list()]

    return ArcSqlMiListResult(
        subscription_id=subscription_id,
        instances=instances,
        total_count=len(instances),  # AGENT-006
    )


async def arc_data_postgresql_list_impl(subscription_id: str) -> ArcPostgreSQLListResult:
    """List all Arc-enabled PostgreSQL instances in a subscription (AGENT-006).

    Iterates ItemPaged to exhaustion. total_count equals len(instances).
    """
    client = _get_arcdata_client(subscription_id)

    instances = [_serialize_postgresql(i, subscription_id) for i in client.postgresql_instances.list()]

    return ArcPostgreSQLListResult(
        subscription_id=subscription_id,
        instances=instances,
        total_count=len(instances),  # AGENT-006
    )


async def arc_data_sql_mi_get_impl(
    subscription_id: str,
    resource_group: str,
    instance_name: str,
) -> ArcSqlMiSummary:
    """Get a single Arc SQL Managed Instance by name."""
    client = _get_arcdata_client(subscription_id)
    instance = client.sql_managed_instances.get(resource_group, instance_name)
    return _serialize_sql_mi(instance, subscription_id)
