"""Arc Servers tools for the Arc MCP Server (AGENT-005, MONITOR-004, MONITOR-005).

Tools expose HybridComputeManagementClient operations as @mcp.tool() endpoints.
All list tools exhaust ItemPaged automatically and return total_count (AGENT-006).

Disconnection threshold is configurable via ARC_DISCONNECT_ALERT_HOURS env var
(default: 1 hour). Servers exceeding the threshold get prolonged_disconnection=True
(MONITOR-004).

RBAC required on the Arc MCP Server's managed identity:
  - Reader on each subscription containing Arc resources
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from azure.mgmt.hybridcompute import HybridComputeManagementClient

from arc_mcp_server.auth import get_credential
from arc_mcp_server.models import (
    ArcExtensionHealth,
    ArcExtensionsListResult,
    ArcServerDetail,
    ArcServerSummary,
    ArcServersListResult,
)

# ---------------------------------------------------------------------------
# Disconnection threshold (MONITOR-004)
# ---------------------------------------------------------------------------

_DISCONNECT_ALERT_HOURS = int(os.environ.get("ARC_DISCONNECT_ALERT_HOURS", "1"))


def _get_hybridcompute_client(subscription_id: str) -> HybridComputeManagementClient:
    """Create a HybridComputeManagementClient for the given subscription.

    Clients are created per-call because they are subscription-scoped.
    The credential itself is cached via lru_cache in auth.py.
    """
    return HybridComputeManagementClient(
        credential=get_credential(),
        subscription_id=subscription_id,
    )


def _is_prolonged_disconnect(machine) -> bool:
    """Return True if machine has been disconnected longer than the threshold.

    MONITOR-004: flag servers where status==Disconnected and
    last_status_change is older than ARC_DISCONNECT_ALERT_HOURS.
    Unknown last_status_change is treated as prolonged (fail-safe).
    """
    if getattr(machine, "status", None) != "Disconnected":
        return False
    last_change = getattr(machine, "last_status_change", None)
    if last_change is None:
        return True  # Unknown duration — treat as prolonged
    threshold = datetime.now(timezone.utc) - timedelta(hours=_DISCONNECT_ALERT_HOURS)
    # last_status_change is a datetime from the SDK; ensure tz-aware comparison
    if last_change.tzinfo is None:
        last_change = last_change.replace(tzinfo=timezone.utc)
    return last_change < threshold


def _extract_resource_group(resource_id: str) -> str:
    """Extract resource group from ARM resource ID string.

    ARM ID format: /subscriptions/{sub}/resourceGroups/{rg}/providers/...
    """
    parts = resource_id.split("/")
    try:
        rg_index = next(i for i, p in enumerate(parts) if p.lower() == "resourcegroups")
        return parts[rg_index + 1]
    except (StopIteration, IndexError):
        return ""


def _serialize_machine(machine, subscription_id: str) -> ArcServerSummary:
    """Convert SDK Machine object to ArcServerSummary Pydantic model."""
    resource_id = getattr(machine, "id", "") or ""
    last_change = getattr(machine, "last_status_change", None)
    return ArcServerSummary(
        resource_id=resource_id,
        name=getattr(machine, "name", "") or "",
        resource_group=_extract_resource_group(resource_id),
        subscription_id=subscription_id,
        location=getattr(machine, "location", None),
        status=str(getattr(machine, "status", None) or ""),
        last_status_change=last_change.isoformat() if last_change else None,
        agent_version=getattr(machine, "agent_version", None),
        os_name=getattr(machine, "os_name", None),
        os_type=getattr(machine, "os_type", None),
        os_version=getattr(machine, "os_version", None),
        kind=str(getattr(machine, "kind", None) or ""),
        provisioning_state=getattr(machine, "provisioning_state", None),
        prolonged_disconnection=_is_prolonged_disconnect(machine),
    )


def _serialize_extension(ext) -> ArcExtensionHealth:
    """Convert SDK MachineExtension to ArcExtensionHealth Pydantic model."""
    props = getattr(ext, "properties", None)
    instance_view = getattr(props, "instance_view", None) if props else None
    status = getattr(instance_view, "status", None) if instance_view else None

    return ArcExtensionHealth(
        name=getattr(ext, "name", "") or "",
        publisher=getattr(props, "publisher", None) if props else None,
        extension_type=getattr(props, "type", None) if props else None,
        provisioning_state=getattr(props, "provisioning_state", None) if props else None,
        type_handler_version=getattr(props, "type_handler_version", None) if props else None,
        auto_upgrade_enabled=getattr(props, "enable_automatic_upgrade", None) if props else None,
        status_code=getattr(status, "code", None) if status else None,
        status_level=getattr(status, "level", None) if status else None,
        status_display=getattr(status, "display_status", None) if status else None,
        status_message=getattr(status, "message", None) if status else None,
    )


# ---------------------------------------------------------------------------
# Tool implementations (called by @mcp.tool() wrappers in server.py)
# ---------------------------------------------------------------------------


async def arc_servers_list_impl(
    subscription_id: str,
    resource_group: Optional[str] = None,
) -> ArcServersListResult:
    """List all Arc-enabled servers, exhausting all pages (AGENT-006).

    The Azure SDK ItemPaged iterator follows nextLink automatically.
    total_count equals len(servers) — the full estate count (AGENT-006).
    """
    client = _get_hybridcompute_client(subscription_id)

    paged = (
        client.machines.list_by_resource_group(resource_group)
        if resource_group
        else client.machines.list_by_subscription()
    )

    # Iterate to exhaustion — ItemPaged follows nextLink automatically (AGENT-006)
    servers = [_serialize_machine(m, subscription_id) for m in paged]

    return ArcServersListResult(
        subscription_id=subscription_id,
        resource_group=resource_group,
        servers=servers,
        total_count=len(servers),  # AGENT-006: MUST equal full count
    )


async def arc_servers_get_impl(
    subscription_id: str,
    resource_group: str,
    machine_name: str,
) -> ArcServerDetail:
    """Get a single Arc server by name with extension health."""
    client = _get_hybridcompute_client(subscription_id)
    machine = client.machines.get(resource_group, machine_name)
    resource_id = getattr(machine, "id", "") or ""
    last_change = getattr(machine, "last_status_change", None)

    # Retrieve extensions for this machine (MONITOR-005)
    extensions_paged = client.machine_extensions.list(resource_group, machine_name)
    extensions = [_serialize_extension(ext) for ext in extensions_paged]

    return ArcServerDetail(
        resource_id=resource_id,
        name=getattr(machine, "name", "") or "",
        resource_group=resource_group,
        subscription_id=subscription_id,
        location=getattr(machine, "location", None),
        status=str(getattr(machine, "status", None) or ""),
        last_status_change=last_change.isoformat() if last_change else None,
        agent_version=getattr(machine, "agent_version", None),
        os_name=getattr(machine, "os_name", None),
        os_type=getattr(machine, "os_type", None),
        os_version=getattr(machine, "os_version", None),
        kind=str(getattr(machine, "kind", None) or ""),
        provisioning_state=getattr(machine, "provisioning_state", None),
        prolonged_disconnection=_is_prolonged_disconnect(machine),
        extensions=extensions,
    )


async def arc_extensions_list_impl(
    subscription_id: str,
    resource_group: str,
    machine_name: str,
) -> ArcExtensionsListResult:
    """List all extensions on an Arc server with health status (MONITOR-005).

    Returns install status and version for: AMA, VM Insights (DependencyAgent),
    Change Tracking, and Azure Policy (GuestConfiguration).
    """
    client = _get_hybridcompute_client(subscription_id)
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.HybridCompute/machines/{machine_name}"
    )
    extensions_paged = client.machine_extensions.list(resource_group, machine_name)
    extensions = [_serialize_extension(ext) for ext in extensions_paged]

    return ArcExtensionsListResult(
        resource_id=resource_id,
        machine_name=machine_name,
        resource_group=resource_group,
        subscription_id=subscription_id,
        extensions=extensions,
        total_count=len(extensions),  # AGENT-006
    )
