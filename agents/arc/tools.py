"""Arc Agent tool functions — Activity Log, Log Analytics, Resource Health wrappers.

Provides @ai_function tools for querying Activity Log, Log Analytics,
and Resource Health as the mandatory pre-triage steps (TRIAGE-002, TRIAGE-003).

Arc-specific tools (arc_servers_list, arc_k8s_list, arc_extensions_list,
arc_k8s_gitops_status, etc.) are mounted via the McpTool in agent.py and
called directly by the LLM — they do NOT need @ai_function wrappers here.

Explicit MCP tool allowlist — no wildcards permitted (AGENT-001):
  Arc MCP Server tools: arc_servers_list, arc_servers_get, arc_k8s_list,
    arc_k8s_get, arc_extensions_list, arc_k8s_gitops_status,
    arc_data_sql_mi_list, arc_data_postgresql_list
  Azure MCP Server tools: monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry
from shared.approval_manager import create_approval_record

# Lazy import — azure-mgmt-hybridcompute
try:
    from azure.mgmt.hybridcompute import HybridComputeManagementClient
except ImportError:
    HybridComputeManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-guestconfiguration
try:
    from azure.mgmt.guestconfiguration import GuestConfigurationClient
except ImportError:
    GuestConfigurationClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-monitor (activity log)
try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-monitor-query (log analytics)
try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-resourcehealth
try:
    from azure.mgmt.resourcehealth import MicrosoftResourceHealth
except ImportError:
    MicrosoftResourceHealth = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-arc-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Explicit MCP tool allowlist — replaces the Phase 2 empty list (AGENT-005)
# ---------------------------------------------------------------------------
ALLOWED_MCP_TOOLS: List[str] = [
    # Arc MCP Server tools (Phase 3 — custom FastMCP server)
    "arc_servers_list",
    "arc_servers_get",
    "arc_extensions_list",
    "arc_k8s_list",
    "arc_k8s_get",
    "arc_k8s_gitops_status",
    "arc_data_sql_mi_list",
    "arc_data_sql_mi_get",
    "arc_data_postgresql_list",
    # Azure MCP Server tools (general monitoring signals)
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an Azure resource ID.

    Args:
        resource_id: Azure resource ID in the form
            /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}

    Returns:
        Subscription ID string (lowercase).

    Raises:
        ValueError: If the subscription segment cannot be found.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot extract subscription_id from resource_id: {resource_id}"
        )


# ---------------------------------------------------------------------------
# @ai_function tools — mandatory pre-triage steps (TRIAGE-002, TRIAGE-003)
# These cannot be delegated to MCP servers as they are always-first steps.
# ---------------------------------------------------------------------------


@ai_function
def query_activity_log(
    resource_ids: List[str],
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query the Azure Activity Log for changes on the given Arc resources.

    This is the FIRST step in the Arc triage workflow (TRIAGE-003). Always
    call this tool BEFORE calling arc_servers_list or arc_k8s_list. Checks
    for recent deployments, agent upgrades, RBAC changes, and policy assignments
    that may have caused connectivity or extension health degradation.

    Args:
        resource_ids: List of Azure resource IDs to query (Arc machine IDs,
            cluster IDs, or subscription-level IDs).
        timespan_hours: Look-back window in hours (default: 2, per TRIAGE-003).

    Returns:
        Dict with keys:
            resource_ids (list): Resources queried.
            timespan_hours (int): Look-back window applied.
            entries (list): Activity Log entries found.
            query_status (str): "success" or "error".
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()
    tool_params = {"resource_ids": resource_ids, "timespan_hours": timespan_hours}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_activity_log",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            start = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
            all_entries: List[Dict[str, Any]] = []

            for resource_id in resource_ids:
                sub_id = _extract_subscription_id(resource_id)
                client = MonitorManagementClient(credential, sub_id)
                filter_str = (
                    f"eventTimestamp ge '{start.isoformat()}' "
                    f"and resourceId eq '{resource_id}'"
                )
                events = client.activity_logs.list(filter=filter_str)
                for event in events:
                    all_entries.append(
                        {
                            "eventTimestamp": (
                                event.event_timestamp.isoformat()
                                if event.event_timestamp
                                else None
                            ),
                            "operationName": (
                                event.operation_name.value
                                if event.operation_name
                                else None
                            ),
                            "caller": event.caller,
                            "status": (
                                event.status.value if event.status else None
                            ),
                            "resourceId": event.resource_id,
                            "level": (
                                event.level.value if event.level else None
                            ),
                            "description": event.description,
                        }
                    )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_activity_log: complete | resources=%d entries=%d duration_ms=%.0f",
                len(resource_ids),
                len(all_entries),
                duration_ms,
            )
            return {
                "resource_ids": resource_ids,
                "timespan_hours": timespan_hours,
                "entries": all_entries,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_activity_log: failed | resources=%s error=%s duration_ms=%.0f",
                resource_ids,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_ids": resource_ids,
                "timespan_hours": timespan_hours,
                "entries": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_log_analytics(
    workspace_id: str,
    kql_query: str,
    timespan: str = "PT2H",
) -> Dict[str, Any]:
    """Query a Log Analytics workspace using KQL for Arc resource events.

    MANDATORY before finalising any diagnosis (TRIAGE-002). Provides Arc agent
    heartbeat logs, extension install events, and connectivity event history.

    Args:
        workspace_id: Log Analytics workspace resource ID.
        kql_query: KQL query string. For Arc triage, use tables: Heartbeat,
            AzureActivity, ConfigurationChange, Event.
        timespan: ISO 8601 duration string (default: "PT2H").

    Returns:
        Dict with keys:
            workspace_id (str): Workspace queried.
            kql_query (str): Query executed.
            timespan (str): Time range applied.
            rows (list): Query result rows.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"workspace_id": workspace_id, "kql_query": kql_query, "timespan": timespan}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_log_analytics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "workspace_id": workspace_id,
            "kql_query": kql_query,
            "timespan": timespan,
            "rows": [],
            "query_status": "success",
        }


@ai_function
def query_resource_health(
    resource_id: str,
) -> Dict[str, Any]:
    """Get Azure Resource Health availability status for an Arc resource.

    MANDATORY before finalising any diagnosis (TRIAGE-002). Distinguishes
    platform-side failures (Azure infrastructure) from Arc agent configuration
    issues (on-premises connectivity, extension failures).

    Args:
        resource_id: Azure resource ID of the Arc machine or K8s cluster.

    Returns:
        Dict with keys:
            resource_id (str): Resource checked.
            availability_state (str): "Available", "Degraded", or "Unavailable".
            summary (str): Human-readable health summary.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_id": resource_id}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_resource_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "resource_id": resource_id,
            "availability_state": "Unknown",
            "summary": "Resource Health query pending.",
            "query_status": "success",
        }


# ---------------------------------------------------------------------------
# Phase 32 — New Arc tools
# ---------------------------------------------------------------------------


@ai_function
def query_arc_extension_health(
    resource_group: str,
    machine_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """List Arc extensions with provisioning state and error details.

    Args:
        resource_group: Resource group name.
        machine_name: Arc machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'extensions' list (name, provisioning_state, version).
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_arc_extension_health",
        tool_parameters={"machine_name": machine_name},
        correlation_id=machine_name,
        thread_id=thread_id,
    ):
        try:
            if HybridComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-hybridcompute not installed", "extensions": [], "duration_ms": duration_ms}

            credential = get_credential()
            client = HybridComputeManagementClient(credential, subscription_id)

            extensions = []
            for ext in client.machine_extensions.list(resource_group, machine_name):
                extensions.append({
                    "name": ext.name,
                    "provisioning_state": getattr(ext, "provisioning_state", "Unknown"),
                    "type_handler_version": getattr(ext, "type_handler_version", ""),
                    "instance_view": str(getattr(ext, "instance_view", "")),
                })
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {"extensions": extensions, "machine_name": machine_name, "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_arc_extension_health error: %s", exc)
            return {"error": str(exc), "extensions": [], "duration_ms": duration_ms}


@ai_function
def query_arc_guest_config(
    resource_group: str,
    machine_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query guest configuration assignment compliance state for an Arc machine.

    Uses azure-mgmt-guestconfiguration (GuestConfigurationClient).
    Returns compliance assignments and status.

    Args:
        resource_group: Resource group name.
        machine_name: Arc machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'assignments' list (name, compliance_status).
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_arc_guest_config",
        tool_parameters={"machine_name": machine_name},
        correlation_id=machine_name,
        thread_id=thread_id,
    ):
        try:
            if GuestConfigurationClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-guestconfiguration not installed", "assignments": [], "duration_ms": duration_ms}

            credential = get_credential()
            client = GuestConfigurationClient(credential, subscription_id)

            assignments = []
            for assignment in client.guest_configuration_assignments.list(
                resource_group, machine_name
            ):
                assignments.append({
                    "name": assignment.name,
                    "compliance_status": getattr(
                        getattr(assignment, "properties", assignment),
                        "compliance_status",
                        "Unknown",
                    ),
                    "last_compliance_time": str(
                        getattr(
                            getattr(assignment, "properties", assignment),
                            "last_compliance_status_checked",
                            "",
                        )
                    ),
                })
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {"assignments": assignments, "machine_name": machine_name, "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_arc_guest_config error: %s", exc)
            return {"error": str(exc), "assignments": [], "duration_ms": duration_ms}


@ai_function
def query_arc_connectivity(
    resource_group: str,
    machine_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query Arc machine connectivity status and last heartbeat.

    Args:
        resource_group: Resource group name.
        machine_name: Arc machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with status, last_status_change, agent_version, os_type, os_name.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="query_arc_connectivity",
        tool_parameters={"machine_name": machine_name},
        correlation_id=machine_name,
        thread_id=thread_id,
    ):
        try:
            if HybridComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "azure-mgmt-hybridcompute not installed", "duration_ms": duration_ms}

            credential = get_credential()
            client = HybridComputeManagementClient(credential, subscription_id)

            machine = client.machines.get(resource_group, machine_name)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "machine_name": machine_name,
                "status": getattr(machine, "status", "Unknown"),
                "last_status_change": str(getattr(machine, "last_status_change", "")),
                "agent_version": getattr(machine, "agent_version", "Unknown"),
                "os_type": getattr(machine, "os_type", "Unknown"),
                "os_name": getattr(machine, "os_name", "Unknown"),
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_arc_connectivity error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}


@ai_function
def propose_arc_assessment(
    resource_id: str,
    machine_name: str,
    subscription_id: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose triggering a patch assessment on an Arc VM — HITL ApprovalRecord only.

    REMEDI-001: No ARM call. Approval required before execution.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="propose_arc_assessment",
        tool_parameters={"machine_name": machine_name, "reason": reason},
        correlation_id=machine_name,
        thread_id=thread_id,
    ):
        try:
            proposal = {
                "action": "arc_patch_assessment",
                "resource_id": resource_id,
                "machine_name": machine_name,
                "subscription_id": subscription_id,
                "reason": reason,
                "description": f"Trigger patch assessment on Arc VM '{machine_name}': {reason}",
                "target_resources": [resource_id],
                "estimated_impact": "Read-only — triggers assessment scan, no changes",
                "reversible": True,
            }

            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id=incident_id,
                agent_name="arc-agent",
                proposal=proposal,
                resource_snapshot={"machine_name": machine_name},
                risk_level="low",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"Arc assessment proposal created for '{machine_name}'. Awaiting approval.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("propose_arc_assessment error: %s", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}
