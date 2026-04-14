"""App Service Agent tool functions — Web Apps, App Service Plans, and Function Apps.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_metrics, monitor.query_logs,
    appservice.list_sites, appservice.get_site,
    appservice.list_plans, appservice.get_plan
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
    from azure.mgmt.web import WebSiteManagementClient
except ImportError:
    WebSiteManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-appservice-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — no wildcards permitted.
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_metrics",
    "monitor.query_logs",
    "appservice.list_sites",
    "appservice.get_site",
    "appservice.list_plans",
    "appservice.get_plan",
]


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-web": "azure.mgmt.web",
        "azure-mgmt-monitor": "azure.mgmt.monitor",
        "azure-monitor-query": "azure.monitor.query",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("appservice_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "appservice_tools: sdk_missing | package=%s — tool will return error", pkg
            )


_log_sdk_availability()


# Import canonical helper — replaces local _extract_subscription_id copy
from agents.shared.subscription_utils import extract_subscription_id as _extract_subscription_id


# ===========================================================================
# App Service / Web App tools
# ===========================================================================


@ai_function
def get_app_service_health(
    site_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve Azure App Service / Web App health and configuration (AS-WEB-001).

    Fetches ARM properties for the site including running state, app service plan,
    SKU tier, SSL certificate expiry, custom domains, and worker count.
    Use as the first diagnostic step for any App Service incident.

    Args:
        site_name: App Service / Web App name.
        resource_group: Resource group containing the site.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            site_name (str): Site name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            state (str | None): Site state ("Running", "Stopped", etc.).
            app_service_plan (str | None): Associated App Service plan name.
            sku (str | None): SKU tier (e.g. "P2v3", "S1").
            worker_count (int | None): Number of worker instances.
            custom_domains (list): List of custom hostname bindings.
            ssl_cert_expiry_days (int | None): Minimum days until any SSL cert expires.
            https_only (bool | None): Whether HTTPS-only redirect is enabled.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "site_name": site_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="appservice-agent",
        agent_id=agent_id,
        tool_name="get_app_service_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if WebSiteManagementClient is None:
                raise ImportError("azure-mgmt-web is not installed")

            credential = get_credential()
            client = WebSiteManagementClient(credential, subscription_id)
            site = client.web_apps.get(resource_group, site_name)

            # Extract server farm (App Service plan) info
            server_farm_id = getattr(site, "server_farm_id", None)
            app_service_plan: Optional[str] = None
            sku: Optional[str] = None
            worker_count: Optional[int] = None
            if server_farm_id:
                # Parse plan name from resource ID
                parts = server_farm_id.split("/")
                if parts:
                    app_service_plan = parts[-1]
                # Fetch plan details for SKU and worker count
                try:
                    plan_rg = resource_group
                    # Extract RG from the server_farm_id if present
                    lower_parts = server_farm_id.lower().split("/")
                    rg_idx = next(
                        (i for i, p in enumerate(lower_parts) if p == "resourcegroups"),
                        None,
                    )
                    if rg_idx is not None and rg_idx + 1 < len(lower_parts):
                        plan_rg = lower_parts[rg_idx + 1]
                    plan = client.app_service_plans.get(plan_rg, app_service_plan)
                    plan_sku = getattr(plan, "sku", None)
                    if plan_sku is not None:
                        sku = getattr(plan_sku, "name", None)
                    worker_count = getattr(plan, "current_number_of_workers", None)
                except Exception as plan_exc:
                    logger.warning(
                        "get_app_service_health: failed to fetch plan details | plan=%s error=%s",
                        app_service_plan,
                        plan_exc,
                    )

            # Extract custom domains
            host_names: List[str] = list(getattr(site, "host_names", None) or [])
            custom_domains = [h for h in host_names if not h.endswith(".azurewebsites.net")]

            # SSL cert expiry — iterate hostname SSL states
            ssl_cert_expiry_days: Optional[int] = None
            try:
                ssl_states = getattr(site, "host_name_ssl_states", None) or []
                now_utc = datetime.now(timezone.utc)
                min_days: Optional[int] = None
                for ssl_state in ssl_states:
                    expiry = getattr(ssl_state, "to_update", None)
                    if expiry is None:
                        # try certificate thumbprint lookup
                        thumbprint = getattr(ssl_state, "thumbprint", None)
                        if thumbprint:
                            try:
                                cert = client.certificates.get(resource_group, thumbprint)
                                expiry = getattr(cert, "expiration_date", None)
                            except Exception:
                                pass
                    if expiry is not None:
                        if not expiry.tzinfo:
                            expiry = expiry.replace(tzinfo=timezone.utc)
                        days_left = (expiry - now_utc).days
                        if min_days is None or days_left < min_days:
                            min_days = days_left
                ssl_cert_expiry_days = min_days
            except Exception as ssl_exc:
                logger.warning(
                    "get_app_service_health: SSL cert check failed | site=%s error=%s",
                    site_name,
                    ssl_exc,
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_app_service_health: complete | site=%s state=%s duration_ms=%.0f",
                site_name,
                getattr(site, "state", None),
                duration_ms,
            )
            return {
                "site_name": site_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "state": getattr(site, "state", None),
                "app_service_plan": app_service_plan,
                "sku": sku,
                "worker_count": worker_count,
                "custom_domains": custom_domains,
                "ssl_cert_expiry_days": ssl_cert_expiry_days,
                "https_only": getattr(site, "https_only", None),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_app_service_health: failed | site=%s error=%s duration_ms=%.0f",
                site_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "site_name": site_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "state": None,
                "app_service_plan": None,
                "sku": None,
                "worker_count": None,
                "custom_domains": [],
                "ssl_cert_expiry_days": None,
                "https_only": None,
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def get_app_service_metrics(
    site_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 4,
) -> Dict[str, Any]:
    """Query App Service performance metrics from Azure Monitor (AS-WEB-002).

    Retrieves requests_per_second, avg_response_time_ms, http5xx_rate_pct,
    cpu_percent, and memory_percent via azure-monitor-query over the specified
    window. High http5xx_rate_pct (>1%) combined with cpu_percent >80% indicates
    resource exhaustion under load.

    Args:
        site_name: App Service / Web App name.
        resource_group: Resource group containing the site.
        subscription_id: Azure subscription ID.
        hours: Look-back window in hours (default: 4).

    Returns:
        Dict with keys:
            site_name (str): Site name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            timespan_hours (int): Look-back window applied.
            requests_per_second (float | None): Average requests/sec in window.
            avg_response_time_ms (float | None): Average response time in ms.
            http5xx_rate_pct (float | None): HTTP 5xx error rate percentage.
            cpu_percent (float | None): Average CPU utilisation percentage.
            memory_percent (float | None): Average memory utilisation percentage.
            data_points (list): Raw per-metric time-series data.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "site_name": site_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "hours": hours,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="appservice-agent",
        agent_id=agent_id,
        tool_name="get_app_service_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            sub_id = subscription_id
            resource_id = (
                f"/subscriptions/{sub_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Web/sites/{site_name}"
            )
            client = MonitorManagementClient(credential, sub_id)

            timespan = f"PT{hours}H"
            metric_names = "Requests,AverageResponseTime,Http5xx,CpuPercentage,MemoryPercentage"
            response = client.metrics.list(
                resource_uri=resource_id,
                metricnames=metric_names,
                timespan=timespan,
                interval="PT5M",
                aggregation="Total,Average,Maximum",
            )

            # Accumulators
            requests_totals: List[float] = []
            response_time_avgs: List[float] = []
            http5xx_totals: List[float] = []
            requests_grand_total: float = 0.0
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
                            "maximum": dp.maximum,
                        })
                        if metric_name_val == "Requests":
                            if dp.total is not None:
                                requests_totals.append(dp.total)
                                requests_grand_total += dp.total
                        elif metric_name_val == "AverageResponseTime":
                            if dp.average is not None:
                                response_time_avgs.append(dp.average)
                        elif metric_name_val == "Http5xx":
                            if dp.total is not None:
                                http5xx_totals.append(dp.total)
                        elif metric_name_val == "CpuPercentage":
                            if dp.average is not None:
                                cpu_avgs.append(dp.average)
                        elif metric_name_val == "MemoryPercentage":
                            if dp.average is not None:
                                mem_avgs.append(dp.average)

            # Compute summary stats
            window_seconds = hours * 3600
            requests_per_second: Optional[float] = (
                requests_grand_total / window_seconds if requests_grand_total > 0 else 0.0
            )
            avg_response_time_ms: Optional[float] = (
                sum(response_time_avgs) / len(response_time_avgs)
                if response_time_avgs
                else None
            )
            http5xx_total = sum(http5xx_totals)
            http5xx_rate_pct: Optional[float] = (
                (http5xx_total / requests_grand_total * 100)
                if requests_grand_total > 0
                else 0.0
            )
            cpu_percent: Optional[float] = (
                sum(cpu_avgs) / len(cpu_avgs) if cpu_avgs else None
            )
            memory_percent: Optional[float] = (
                sum(mem_avgs) / len(mem_avgs) if mem_avgs else None
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_app_service_metrics: complete | site=%s rps=%.2f "
                "http5xx_pct=%.2f%% cpu=%.1f%% duration_ms=%.0f",
                site_name,
                requests_per_second if requests_per_second is not None else 0.0,
                http5xx_rate_pct if http5xx_rate_pct is not None else 0.0,
                cpu_percent if cpu_percent is not None else 0.0,
                duration_ms,
            )
            return {
                "site_name": site_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "requests_per_second": requests_per_second,
                "avg_response_time_ms": avg_response_time_ms,
                "http5xx_rate_pct": http5xx_rate_pct,
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "data_points": data_points,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_app_service_metrics: failed | site=%s error=%s duration_ms=%.0f",
                site_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "site_name": site_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "requests_per_second": None,
                "avg_response_time_ms": None,
                "http5xx_rate_pct": None,
                "cpu_percent": None,
                "memory_percent": None,
                "data_points": [],
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


# ===========================================================================
# Function App tools
# ===========================================================================


@ai_function
def get_function_app_health(
    function_app_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve Azure Function App health and execution statistics (AS-FUNC-001).

    Fetches ARM properties for the Function App (runtime version, state, plan)
    and queries Azure Monitor metrics for invocation count, failure rate, p95
    execution duration, and throttle count over the last hour.

    Args:
        function_app_name: Function App name.
        resource_group: Resource group containing the Function App.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            function_app_name (str): Function App name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            state (str | None): App state ("Running", "Stopped", etc.).
            runtime_version (str | None): Functions runtime version (e.g. "~4").
            function_count (int | None): Number of deployed functions.
            invocation_count_1h (int): Total invocations in last hour.
            failure_rate_percent (float | None): Failure rate percentage.
            duration_p95_ms (float | None): 95th percentile execution duration ms.
            throttle_count (int): Total throttled invocations in last hour.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "function_app_name": function_app_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="appservice-agent",
        agent_id=agent_id,
        tool_name="get_function_app_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if WebSiteManagementClient is None:
                raise ImportError("azure-mgmt-web is not installed")

            credential = get_credential()
            web_client = WebSiteManagementClient(credential, subscription_id)

            # Fetch ARM site properties
            site = web_client.web_apps.get(resource_group, function_app_name)
            state = getattr(site, "state", None)

            # Extract runtime version from site config app settings
            runtime_version: Optional[str] = None
            try:
                app_settings = web_client.web_apps.list_application_settings(
                    resource_group, function_app_name
                )
                settings_dict = getattr(app_settings, "properties", {}) or {}
                runtime_version = settings_dict.get("FUNCTIONS_EXTENSION_VERSION")
            except Exception as settings_exc:
                logger.warning(
                    "get_function_app_health: failed to get app settings | app=%s error=%s",
                    function_app_name,
                    settings_exc,
                )

            # Count deployed functions
            function_count: Optional[int] = None
            try:
                functions_list = list(
                    web_client.web_apps.list_functions(resource_group, function_app_name)
                )
                function_count = len(functions_list)
            except Exception as func_exc:
                logger.warning(
                    "get_function_app_health: failed to list functions | app=%s error=%s",
                    function_app_name,
                    func_exc,
                )

            # Fetch Azure Monitor metrics for last hour
            invocation_count_1h: int = 0
            failure_rate_percent: Optional[float] = None
            duration_p95_ms: Optional[float] = None
            throttle_count: int = 0

            if MonitorManagementClient is not None:
                try:
                    resource_id = (
                        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                        f"/providers/Microsoft.Web/sites/{function_app_name}"
                    )
                    mon_client = MonitorManagementClient(credential, subscription_id)
                    metric_names = "FunctionExecutionCount,FunctionExecutionUnits,Http5xx"
                    response = mon_client.metrics.list(
                        resource_uri=resource_id,
                        metricnames=metric_names,
                        timespan="PT1H",
                        interval="PT5M",
                        aggregation="Total,Maximum",
                    )
                    exec_count_total: float = 0.0
                    http5xx_total: float = 0.0
                    exec_unit_maxes: List[float] = []

                    for metric in response.value:
                        metric_name_val = metric.name.value if metric.name else ""
                        for ts in metric.timeseries:
                            for dp in ts.data:
                                if metric_name_val == "FunctionExecutionCount":
                                    if dp.total is not None:
                                        exec_count_total += dp.total
                                elif metric_name_val == "FunctionExecutionUnits":
                                    if dp.maximum is not None:
                                        exec_unit_maxes.append(dp.maximum)
                                elif metric_name_val == "Http5xx":
                                    if dp.total is not None:
                                        http5xx_total += dp.total

                    invocation_count_1h = int(exec_count_total)
                    if exec_count_total > 0:
                        failure_rate_percent = round(
                            http5xx_total / exec_count_total * 100, 2
                        )
                    if exec_unit_maxes:
                        duration_p95_ms = max(exec_unit_maxes)

                except Exception as mon_exc:
                    logger.warning(
                        "get_function_app_health: monitor metrics failed | app=%s error=%s",
                        function_app_name,
                        mon_exc,
                    )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_function_app_health: complete | app=%s state=%s "
                "invocations=%d failure_rate=%.2f%% duration_ms=%.0f",
                function_app_name,
                state,
                invocation_count_1h,
                failure_rate_percent if failure_rate_percent is not None else 0.0,
                duration_ms,
            )
            return {
                "function_app_name": function_app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "state": state,
                "runtime_version": runtime_version,
                "function_count": function_count,
                "invocation_count_1h": invocation_count_1h,
                "failure_rate_percent": failure_rate_percent,
                "duration_p95_ms": duration_p95_ms,
                "throttle_count": throttle_count,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_function_app_health: failed | app=%s error=%s duration_ms=%.0f",
                function_app_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "function_app_name": function_app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "state": None,
                "runtime_version": None,
                "function_count": None,
                "invocation_count_1h": 0,
                "failure_rate_percent": None,
                "duration_p95_ms": None,
                "throttle_count": 0,
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def query_app_insights_failures(
    app_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 2,
) -> Dict[str, Any]:
    """Query Application Insights for top exceptions and dependency failures (AS-AI-001).

    Queries Log Analytics via azure-monitor-query LogsQueryClient. Surfaces:
    - Top 5 exception types by count in the time window.
    - Dependency failures (failed calls to external services, databases, etc.).

    Requires Application Insights diagnostic settings to forward exceptions and
    dependency telemetry to a Log Analytics workspace. Uses the workspace linked
    to the Application Insights resource for the named app.

    Args:
        app_name: Application name as it appears in Application Insights telemetry.
        resource_group: Resource group (used to derive workspace ID via naming convention).
        subscription_id: Azure subscription ID.
        hours: Look-back window in hours (default: 2).

    Returns:
        Dict with keys:
            app_name (str): Application name filter applied.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            timespan_hours (int): Look-back window applied.
            top_exceptions (list): Top 5 exception types by occurrence count.
            dependency_failures (list): Failed dependency calls (max 50).
            exception_count (int): Total exceptions in window.
            dependency_failure_count (int): Total dependency failures in window.
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
        agent_name="appservice-agent",
        agent_id=agent_id,
        tool_name="query_app_insights_failures",
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
            start_dt = end_dt - timedelta(hours=hours)
            duration_dt = timedelta(hours=hours)

            # Derive workspace ID from subscription + resource group convention
            # Platform uses a shared Log Analytics workspace per resource group
            workspace_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.OperationalInsights/workspaces/law-{resource_group}"
            )

            # Top exceptions by count
            exceptions_kql = f"""
exceptions
| where timestamp between (datetime({start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})
    .. datetime({end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}))
| where cloud_RoleName =~ "{app_name}" or isempty(cloud_RoleName)
| summarize ExceptionCount = count() by type, outerMessage
| top 5 by ExceptionCount desc
"""
            # Dependency failures
            dependency_kql = f"""
dependencies
| where timestamp between (datetime({start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})
    .. datetime({end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}))
| where cloud_RoleName =~ "{app_name}" or isempty(cloud_RoleName)
| where success == false
| project timestamp, name, target, resultCode, duration, type
| order by timestamp desc
| limit 50
"""
            top_exceptions: List[Dict[str, Any]] = []
            dependency_failures: List[Dict[str, Any]] = []

            # Execute exceptions query
            try:
                exc_result = client.query_workspace(
                    workspace_id=workspace_id,
                    query=exceptions_kql,
                    timespan=duration_dt,
                )
                if LogsQueryStatus is not None and exc_result.status == LogsQueryStatus.SUCCESS:
                    for table in exc_result.tables:
                        col_names = [col.name for col in table.columns]
                        for row in table.rows:
                            top_exceptions.append(dict(zip(col_names, row)))
            except Exception as exc_err:
                logger.warning(
                    "query_app_insights_failures: exceptions query failed | app=%s error=%s",
                    app_name,
                    exc_err,
                )

            # Execute dependency failures query
            try:
                dep_result = client.query_workspace(
                    workspace_id=workspace_id,
                    query=dependency_kql,
                    timespan=duration_dt,
                )
                if LogsQueryStatus is not None and dep_result.status == LogsQueryStatus.SUCCESS:
                    for table in dep_result.tables:
                        col_names = [col.name for col in table.columns]
                        for row in table.rows:
                            dependency_failures.append(dict(zip(col_names, row)))
            except Exception as dep_err:
                logger.warning(
                    "query_app_insights_failures: dependency query failed | app=%s error=%s",
                    app_name,
                    dep_err,
                )

            exception_count = sum(
                int(row.get("ExceptionCount", 0)) for row in top_exceptions
            )
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_app_insights_failures: complete | app=%s exceptions=%d "
                "dep_failures=%d duration_ms=%.0f",
                app_name,
                exception_count,
                len(dependency_failures),
                duration_ms,
            )
            return {
                "app_name": app_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "top_exceptions": top_exceptions,
                "dependency_failures": dependency_failures,
                "exception_count": exception_count,
                "dependency_failure_count": len(dependency_failures),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_app_insights_failures: failed | app=%s error=%s duration_ms=%.0f",
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
                "top_exceptions": [],
                "dependency_failures": [],
                "exception_count": 0,
                "dependency_failure_count": 0,
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


# ===========================================================================
# HITL proposal tools
# ===========================================================================


@ai_function
def propose_app_service_restart(
    site_name: str,
    resource_group: str,
    subscription_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose a safe App Service / Web App restart for operator approval (AS-REMEDI-001).

    Generates a HITL approval request. The App Service Agent MUST NOT restart
    any site directly — proposals only (REMEDI-001). Restarts are low-risk for
    App Service plans with multiple workers (rolling restart) but cause brief
    downtime on single-instance plans.

    Args:
        site_name: App Service / Web App name to restart.
        resource_group: Resource group containing the site.
        subscription_id: Azure subscription ID.
        reason: Human-readable justification for the restart.

    Returns:
        Dict with mandatory approval_required=True and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "site_name": site_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "reason": reason,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="appservice-agent",
        agent_id=agent_id,
        tool_name="propose_app_service_restart",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "proposal_type": "app_service_restart",
            "site_name": site_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "reason": reason,
            "risk_level": "low",
            "proposed_action": (
                f"Restart App Service site '{site_name}' in resource group "
                f"'{resource_group}' (subscription: {subscription_id})"
            ),
            "reversibility": (
                "Not directly reversible — restart is an in-place operation. "
                "Multi-worker plans perform a rolling restart with zero downtime. "
                "Single-instance plans may experience brief (< 30s) downtime."
            ),
            # REMEDI-001: All proposals require explicit human approval before execution.
            "approval_required": True,
        }


@ai_function
def propose_function_app_scale_out(
    function_app_name: str,
    resource_group: str,
    subscription_id: str,
    target_instances: int,
    reason: str,
) -> Dict[str, Any]:
    """Propose a Function App scale-out to additional instances for operator approval (AS-REMEDI-002).

    Generates a HITL approval request. The App Service Agent MUST NOT scale
    any Function App directly — proposals only (REMEDI-001). Scale-out is
    low-risk as it adds capacity without removing existing instances.

    Args:
        function_app_name: Function App name to scale out.
        resource_group: Resource group containing the Function App.
        subscription_id: Azure subscription ID.
        target_instances: Target number of worker instances.
        reason: Human-readable justification for the scale action.

    Returns:
        Dict with mandatory approval_required=True and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "function_app_name": function_app_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "target_instances": target_instances,
        "reason": reason,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="appservice-agent",
        agent_id=agent_id,
        tool_name="propose_function_app_scale_out",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "proposal_type": "function_app_scale_out",
            "function_app_name": function_app_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "target_instances": target_instances,
            "reason": reason,
            "risk_level": "low",
            "proposed_action": (
                f"Scale out Function App '{function_app_name}' to "
                f"{target_instances} instance(s) in resource group '{resource_group}' "
                f"(subscription: {subscription_id})"
            ),
            "reversibility": (
                "Fully reversible — scale-in can reduce instances back to prior count "
                "at any time. No data loss risk."
            ),
            # REMEDI-001: All proposals require explicit human approval before execution.
            "approval_required": True,
        }
