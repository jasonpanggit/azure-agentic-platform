"""Container Apps Agent tool functions — operational diagnostics and HITL proposals.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_metrics, monitor.query_logs,
    containerapps.list_apps, containerapps.get_app,
    containerapps.list_revisions, containerapps.get_revision
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

# ---------------------------------------------------------------------------
# Lazy SDK imports — azure-mgmt-* packages may not be installed in all envs
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
except ImportError:
    ContainerAppsAPIClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-containerapps-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — no wildcards permitted.
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_metrics",
    "monitor.query_logs",
    "containerapps.list_apps",
    "containerapps.get_app",
    "containerapps.list_revisions",
    "containerapps.get_revision",
]


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-appcontainers": "azure.mgmt.appcontainers",
        "azure-mgmt-monitor": "azure.mgmt.monitor",
        "azure-monitor-query": "azure.monitor.query",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("containerapps_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "containerapps_tools: sdk_missing | package=%s — tool will return error", pkg
            )


_log_sdk_availability()


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


# ===========================================================================
# Container Apps read tools
# ===========================================================================


@ai_function
def list_container_apps(
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """List all Container Apps in a resource group with operational summary (CA-LIST-001).

    Returns name, provisioning state, replica count, active revision name, and
    whether ingress is enabled for each app. Use as the first step when an
    operator asks for a Container Apps overview or when triaging a broad incident.

    Args:
        resource_group: Resource group to enumerate.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            subscription_id (str): Subscription queried.
            apps (list): Each entry contains app_name, provisioning_state,
                replica_count, active_revision_name, ingress_enabled.
            app_count (int): Total number of apps found.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="containerapps-agent",
        agent_id=agent_id,
        tool_name="list_container_apps",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if ContainerAppsAPIClient is None:
                raise ImportError("azure-mgmt-appcontainers is not installed")

            credential = get_credential()
            client = ContainerAppsAPIClient(credential, subscription_id)
            apps_iter = client.container_apps.list_by_resource_group(resource_group)

            apps: List[Dict[str, Any]] = []
            for app in apps_iter:
                ingress = getattr(app, "ingress", None)
                ingress_enabled = ingress is not None

                # Active revision name
                active_revision: Optional[str] = None
                try:
                    active_revision = getattr(app, "latest_ready_revision_name", None)
                except Exception:
                    pass

                # Running replica count — may be exposed on the app object
                replica_count: Optional[int] = None
                try:
                    replica_count = getattr(app, "running_status", None)
                    if replica_count is None:
                        # Some SDK versions expose it differently
                        scale = getattr(app, "scale", None)
                        if scale is not None:
                            replica_count = getattr(scale, "min_replicas", None)
                except Exception:
                    pass

                apps.append({
                    "app_name": getattr(app, "name", None),
                    "provisioning_state": str(getattr(app, "provisioning_state", None)),
                    "replica_count": replica_count,
                    "active_revision_name": active_revision,
                    "ingress_enabled": ingress_enabled,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "list_container_apps: complete | rg=%s app_count=%d duration_ms=%.0f",
                resource_group,
                len(apps),
                duration_ms,
            )
            return {
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "apps": apps,
                "app_count": len(apps),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "list_container_apps: failed | rg=%s error=%s duration_ms=%.0f",
                resource_group,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "apps": [],
                "app_count": 0,
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def get_container_app_health(
    app_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve detailed health and configuration for a single Container App (CA-HEALTH-001).

    Fetches ARM properties: replica count vs desired, active revision, last
    modified time, ingress configuration, and managed environment ID.
    Use as the primary diagnostic tool for any single-app incident.

    Args:
        app_name: Container App name.
        resource_group: Resource group containing the app.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            app_name (str): Container App name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            provisioning_state (str | None): ARM provisioning state.
            replica_count (int | None): Current running replica count.
            active_revision_name (str | None): Name of the currently active revision.
            last_modified_time (str | None): ISO 8601 timestamp of last modification.
            ingress_enabled (bool): Whether ingress is configured.
            ingress_external (bool | None): Whether ingress is externally accessible.
            ingress_fqdn (str | None): Fully-qualified domain name if ingress is enabled.
            managed_environment_id (str | None): Associated Container Apps Environment ID.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "app_name": app_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="containerapps-agent",
        agent_id=agent_id,
        tool_name="get_container_app_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if ContainerAppsAPIClient is None:
                raise ImportError("azure-mgmt-appcontainers is not installed")

            credential = get_credential()
            client = ContainerAppsAPIClient(credential, subscription_id)
            app = client.container_apps.get(resource_group, app_name)

            ingress = getattr(app, "ingress", None)
            ingress_enabled = ingress is not None
            ingress_external: Optional[bool] = None
            ingress_fqdn: Optional[str] = None
            if ingress is not None:
                ingress_external = getattr(ingress, "external", None)
                ingress_fqdn = getattr(ingress, "fqdn", None)

            # Last modified time
            last_modified: Optional[str] = None
            sys_data = getattr(app, "system_data", None)
            if sys_data is not None:
                lmt = getattr(sys_data, "last_modified_at", None)
                if lmt is not None:
                    last_modified = lmt.isoformat() if hasattr(lmt, "isoformat") else str(lmt)

            # Replica count: attempt from running_status or scale config
            replica_count: Optional[int] = None
            try:
                replica_count = getattr(app, "running_status", None)
                if replica_count is None:
                    scale = getattr(app, "scale", None)
                    if scale is not None:
                        replica_count = getattr(scale, "min_replicas", None)
            except Exception:
                pass

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_container_app_health: complete | app=%s state=%s duration_ms=%.0f",
                app_name,
                getattr(app, "provisioning_state", None),
                duration_ms,
            )
            return {
                "app_name": app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "provisioning_state": str(getattr(app, "provisioning_state", None)),
                "replica_count": replica_count,
                "active_revision_name": getattr(app, "latest_ready_revision_name", None),
                "last_modified_time": last_modified,
                "ingress_enabled": ingress_enabled,
                "ingress_external": ingress_external,
                "ingress_fqdn": ingress_fqdn,
                "managed_environment_id": getattr(app, "managed_environment_id", None),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_container_app_health: failed | app=%s error=%s duration_ms=%.0f",
                app_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "app_name": app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "provisioning_state": None,
                "replica_count": None,
                "active_revision_name": None,
                "last_modified_time": None,
                "ingress_enabled": False,
                "ingress_external": None,
                "ingress_fqdn": None,
                "managed_environment_id": None,
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def get_container_app_metrics(
    app_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 2,
) -> Dict[str, Any]:
    """Query Container App performance metrics from Azure Monitor (CA-METRICS-001).

    Retrieves request_count, avg_response_time_ms, replica_count_history,
    cpu_percent, and memory_percent via azure-monitor-query over the specified
    window. High cpu_percent (>80%) combined with elevated replica_count
    indicates active scale-out under load.

    Args:
        app_name: Container App name.
        resource_group: Resource group containing the app.
        subscription_id: Azure subscription ID.
        hours: Look-back window in hours (default: 2).

    Returns:
        Dict with keys:
            app_name (str): Container App name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            timespan_hours (int): Look-back window applied.
            request_count (int): Total requests in window.
            avg_response_time_ms (float | None): Average response time in ms.
            replica_count_avg (float | None): Average replica count in window.
            cpu_percent (float | None): Average CPU utilisation percentage.
            memory_percent (float | None): Average memory utilisation percentage.
            data_points (list): Raw per-metric time-series data.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "app_name": app_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "hours": hours,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="containerapps-agent",
        agent_id=agent_id,
        tool_name="get_container_app_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            resource_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.App/containerApps/{app_name}"
            )
            client = MonitorManagementClient(credential, subscription_id)

            timespan = f"PT{hours}H"
            metric_names = (
                "Requests,ResponseTime,Replicas,CpuUsageNanoCores,MemoryWorkingSetBytes"
            )
            response = client.metrics.list(
                resource_uri=resource_id,
                metricnames=metric_names,
                timespan=timespan,
                interval="PT5M",
                aggregation="Total,Average",
            )

            # Accumulators
            request_total: float = 0.0
            response_time_avgs: List[float] = []
            replica_avgs: List[float] = []
            cpu_avgs: List[float] = []
            mem_avgs: List[float] = []
            data_points: List[Dict[str, Any]] = []

            for metric in response.value:
                metric_name_val = metric.name.value if metric.name else ""
                for ts in metric.timeseries:
                    for dp in ts.data:
                        ts_str = dp.time_stamp.isoformat() if dp.time_stamp else None
                        data_points.append({
                            "metric": metric_name_val,
                            "timestamp": ts_str,
                            "average": dp.average,
                            "total": dp.total,
                        })
                        if metric_name_val == "Requests":
                            if dp.total is not None:
                                request_total += dp.total
                        elif metric_name_val == "ResponseTime":
                            if dp.average is not None:
                                response_time_avgs.append(dp.average)
                        elif metric_name_val == "Replicas":
                            if dp.average is not None:
                                replica_avgs.append(dp.average)
                        elif metric_name_val == "CpuUsageNanoCores":
                            if dp.average is not None:
                                # Convert nano-cores to percentage (1 vCore = 1e9 nano-cores)
                                cpu_avgs.append(dp.average / 1e9 * 100)
                        elif metric_name_val == "MemoryWorkingSetBytes":
                            if dp.average is not None:
                                # Percentage relative to 2 GiB default limit
                                mem_avgs.append(dp.average / (2 * 1024 ** 3) * 100)

            avg_response_time_ms: Optional[float] = (
                sum(response_time_avgs) / len(response_time_avgs)
                if response_time_avgs
                else None
            )
            replica_count_avg: Optional[float] = (
                sum(replica_avgs) / len(replica_avgs) if replica_avgs else None
            )
            cpu_percent: Optional[float] = (
                sum(cpu_avgs) / len(cpu_avgs) if cpu_avgs else None
            )
            memory_percent: Optional[float] = (
                sum(mem_avgs) / len(mem_avgs) if mem_avgs else None
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_container_app_metrics: complete | app=%s requests=%.0f "
                "cpu=%.1f%% duration_ms=%.0f",
                app_name,
                request_total,
                cpu_percent if cpu_percent is not None else 0.0,
                duration_ms,
            )
            return {
                "app_name": app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "request_count": int(request_total),
                "avg_response_time_ms": avg_response_time_ms,
                "replica_count_avg": replica_count_avg,
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "data_points": data_points,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_container_app_metrics: failed | app=%s error=%s duration_ms=%.0f",
                app_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "app_name": app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "request_count": 0,
                "avg_response_time_ms": None,
                "replica_count_avg": None,
                "cpu_percent": None,
                "memory_percent": None,
                "data_points": [],
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def get_container_app_logs(
    app_name: str,
    resource_group: str,
    subscription_id: str,
    lines: int = 100,
    severity: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve recent console log lines for a Container App via Log Analytics KQL (CA-LOGS-001).

    Queries `ContainerAppConsoleLogs_CL` in the Log Analytics workspace associated
    with the Container Apps Environment. Supports optional severity filtering
    (e.g. "Error", "Warning"). Use after metrics indicate elevated error rates
    or when an operator requests log evidence for a hypothesis.

    Args:
        app_name: Container App name.
        resource_group: Resource group containing the app.
        subscription_id: Azure subscription ID.
        lines: Maximum number of log lines to return (default: 100).
        severity: Optional log severity filter — "Error", "Warning", "Info", or None
            for all levels.

    Returns:
        Dict with keys:
            app_name (str): Container App name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            lines_requested (int): Max lines requested.
            severity_filter (str | None): Severity filter applied.
            log_entries (list): Each entry: timestamp, container_name, log, stream.
            log_count (int): Number of entries returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "app_name": app_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "lines": lines,
        "severity": severity,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="containerapps-agent",
        agent_id=agent_id,
        tool_name="get_container_app_logs",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if LogsQueryClient is None:
                raise ImportError("azure-monitor-query is not installed")

            credential = get_credential()
            client = LogsQueryClient(credential)

            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(hours=1)
            duration_dt = timedelta(hours=1)

            # Workspace ID derived from platform naming convention
            workspace_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.OperationalInsights/workspaces/law-{resource_group}"
            )

            severity_filter = (
                f'| where Log_s has "{severity}" ' if severity else ""
            )

            kql = f"""
ContainerAppConsoleLogs_CL
| where ContainerAppName_s =~ "{app_name}"
{severity_filter}| project TimeGenerated, ContainerName_s, Log_s, Stream_s
| order by TimeGenerated desc
| limit {lines}
"""
            log_entries: List[Dict[str, Any]] = []

            result = client.query_workspace(
                workspace_id=workspace_id,
                query=kql,
                timespan=duration_dt,
            )

            if LogsQueryStatus is not None and result.status == LogsQueryStatus.SUCCESS:
                for table in result.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        entry = dict(zip(col_names, row))
                        log_entries.append({
                            "timestamp": str(entry.get("TimeGenerated", "")),
                            "container_name": entry.get("ContainerName_s"),
                            "log": entry.get("Log_s"),
                            "stream": entry.get("Stream_s"),
                        })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_container_app_logs: complete | app=%s log_count=%d duration_ms=%.0f",
                app_name,
                len(log_entries),
                duration_ms,
            )
            return {
                "app_name": app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "lines_requested": lines,
                "severity_filter": severity,
                "log_entries": log_entries,
                "log_count": len(log_entries),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_container_app_logs: failed | app=%s error=%s duration_ms=%.0f",
                app_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "app_name": app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "lines_requested": lines,
                "severity_filter": severity,
                "log_entries": [],
                "log_count": 0,
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


# ===========================================================================
# HITL proposal tools
# ===========================================================================


@ai_function
def propose_container_app_scale(
    app_name: str,
    resource_group: str,
    subscription_id: str,
    min_replicas: int,
    max_replicas: int,
    reason: str,
) -> Dict[str, Any]:
    """Propose a Container App scale rule change for operator approval (CA-REMEDI-001).

    Generates a HITL approval request to adjust the min/max replica bounds on a
    Container App's active revision. The Container Apps Agent MUST NOT modify any
    scale rule directly — proposals only (REMEDI-001).

    Scaling is low-risk: increasing min_replicas ensures cold-start elimination;
    increasing max_replicas allows higher peak throughput. Both are reversible.

    Args:
        app_name: Container App name to scale.
        resource_group: Resource group containing the app.
        subscription_id: Azure subscription ID.
        min_replicas: Proposed minimum replica count.
        max_replicas: Proposed maximum replica count.
        reason: Human-readable justification for the scale change.

    Returns:
        Dict with mandatory approval_required=True and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "app_name": app_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "min_replicas": min_replicas,
        "max_replicas": max_replicas,
        "reason": reason,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="containerapps-agent",
        agent_id=agent_id,
        tool_name="propose_container_app_scale",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "proposal_type": "container_app_scale",
            "app_name": app_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "min_replicas": min_replicas,
            "max_replicas": max_replicas,
            "reason": reason,
            "risk_level": "low",
            "proposed_action": (
                f"Update Container App '{app_name}' scale rules to "
                f"min={min_replicas} / max={max_replicas} replicas in resource group "
                f"'{resource_group}' (subscription: {subscription_id})"
            ),
            "reversibility": (
                "Fully reversible — scale rules can be reverted to prior values at any time. "
                "No data loss risk. Replicas drain gracefully before termination."
            ),
            # REMEDI-001: All proposals require explicit human approval before execution.
            "approval_required": True,
        }


@ai_function
def propose_container_app_revision_activate(
    app_name: str,
    resource_group: str,
    subscription_id: str,
    revision_name: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose activating a specific Container App revision for operator approval (CA-REMEDI-002).

    Generates a HITL approval request to switch traffic to a named revision.
    This enables rollback to a known-good revision when a new deployment is
    causing errors. The Container Apps Agent MUST NOT activate revisions
    directly — proposals only (REMEDI-001).

    Revision activation is medium-risk: it changes the live traffic target and
    requires the named revision to exist and be in a healthy state.

    Args:
        app_name: Container App name.
        resource_group: Resource group containing the app.
        subscription_id: Azure subscription ID.
        revision_name: Name of the revision to activate (must already exist).
        reason: Human-readable justification (e.g. "rollback — v2 has elevated 5xx rate").

    Returns:
        Dict with mandatory approval_required=True and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "app_name": app_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "revision_name": revision_name,
        "reason": reason,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="containerapps-agent",
        agent_id=agent_id,
        tool_name="propose_container_app_revision_activate",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "proposal_type": "container_app_revision_activate",
            "app_name": app_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "revision_name": revision_name,
            "reason": reason,
            "risk_level": "medium",
            "proposed_action": (
                f"Activate revision '{revision_name}' on Container App '{app_name}' "
                f"in resource group '{resource_group}' (subscription: {subscription_id})"
            ),
            "reversibility": (
                "Reversible — re-activating the previous revision restores prior traffic target. "
                "Requires the previous revision to still exist and not have been deactivated. "
                "Brief traffic shift during activation (~seconds)."
            ),
            # REMEDI-001: All proposals require explicit human approval before execution.
            "approval_required": True,
        }
