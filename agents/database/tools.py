"""Database Agent tool functions — Cosmos DB, PostgreSQL Flexible Server, Azure SQL diagnostics.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_metrics, monitor.query_logs,
    cosmos.list_accounts, cosmos.get_account,
    postgres.list, sql.list
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
    from azure.mgmt.cosmosdb import CosmosDBManagementClient
except ImportError:
    CosmosDBManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient
except ImportError:
    PostgreSQLManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.sql import SqlManagementClient
except ImportError:
    SqlManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-database-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — no wildcards permitted.
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_metrics",
    "monitor.query_logs",
    "cosmos.list_accounts",
    "cosmos.get_account",
    "postgres.list",
    "sql.list",
]


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-cosmosdb": "azure.mgmt.cosmosdb",
        "azure-mgmt-rdbms": "azure.mgmt.rdbms.postgresql_flexibleservers",
        "azure-mgmt-sql": "azure.mgmt.sql",
        "azure-mgmt-monitor": "azure.mgmt.monitor",
        "azure-monitor-query": "azure.monitor.query",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("database_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "database_tools: sdk_missing | package=%s — tool will return error", pkg
            )


_log_sdk_availability()


# Import canonical helper — replaces local _extract_subscription_id copy
from agents.shared.subscription_utils import extract_subscription_id as _extract_subscription_id


# ===========================================================================
# Cosmos DB tools
# ===========================================================================


@ai_function
def get_cosmos_account_health(
    account_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve Cosmos DB account health, provisioning state, and backup policy (DB-COSMOS-001).

    Fetches ARM properties for the account including availability zones, consistency
    level, multi-region writes, and backup policy details. Use as the first diagnostic
    step when a Cosmos DB incident is received.

    Args:
        account_name: Cosmos DB account name.
        resource_group: Resource group containing the account.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            account_name (str): Account name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            provisioning_state (str | None): ARM provisioning state.
            document_endpoint (str | None): SQL API endpoint.
            consistency_level (str | None): Default consistency policy level.
            multi_region_writes (bool | None): Whether multi-region writes are enabled.
            locations (list): List of failover regions.
            backup_policy_type (str | None): "Periodic" or "Continuous".
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "account_name": account_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="get_cosmos_account_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if CosmosDBManagementClient is None:
                raise ImportError("azure-mgmt-cosmosdb is not installed")

            credential = get_credential()
            client = CosmosDBManagementClient(credential, subscription_id)
            account = client.database_accounts.get(resource_group, account_name)

            # Extract locations safely
            locations: List[Dict[str, Any]] = []
            for loc in getattr(account, "locations", None) or []:
                locations.append({
                    "location_name": getattr(loc, "location_name", None),
                    "failover_priority": getattr(loc, "failover_priority", None),
                    "is_zone_redundant": getattr(loc, "is_zone_redundant", None),
                })

            # Extract consistency policy
            consistency = getattr(account, "consistency_policy", None)
            consistency_level = (
                str(getattr(consistency, "default_consistency_level", None))
                if consistency is not None
                else None
            )

            # Extract backup policy type
            backup = getattr(account, "backup_policy", None)
            backup_type = None
            if backup is not None:
                backup_type = getattr(backup, "type", None)
                if backup_type is None:
                    # Distinguish by class name (Periodic vs Continuous)
                    backup_type = type(backup).__name__.replace("BackupPolicy", "")

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_cosmos_account_health: complete | account=%s state=%s duration_ms=%.0f",
                account_name,
                getattr(account, "provisioning_state", None),
                duration_ms,
            )
            return {
                "account_name": account_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "provisioning_state": getattr(account, "provisioning_state", None),
                "document_endpoint": getattr(account, "document_endpoint", None),
                "consistency_level": consistency_level,
                "multi_region_writes": getattr(account, "enable_multiple_write_locations", None),
                "locations": locations,
                "backup_policy_type": backup_type,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_cosmos_account_health: failed | account=%s error=%s duration_ms=%.0f",
                account_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "account_name": account_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "provisioning_state": None,
                "document_endpoint": None,
                "consistency_level": None,
                "multi_region_writes": None,
                "locations": [],
                "backup_policy_type": None,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def get_cosmos_throughput_metrics(
    account_id: str,
    database_name: Optional[str] = None,
    container_name: Optional[str] = None,
    timespan: str = "PT2H",
) -> Dict[str, Any]:
    """Query Cosmos DB throughput and throttling metrics from Azure Monitor (DB-COSMOS-002).

    Retrieves TotalRequestUnits, NormalizedRUConsumption, Http429s, and
    ServerSideLatency to surface RU utilisation percentage and throttle rate.
    High NormalizedRUConsumption (>80%) indicates near-capacity and 429 risk.

    Args:
        account_id: Cosmos DB account resource ID.
        database_name: Optional database name for resource-level scoping.
        container_name: Optional container name for resource-level scoping.
        timespan: ISO 8601 duration (default: "PT2H").

    Returns:
        Dict with keys:
            account_id (str): Account resource ID.
            timespan (str): Time range applied.
            total_request_units (list): TotalRequestUnits time series data.
            normalized_ru_consumption (list): NormalizedRUConsumption data points.
            http_429_count (int): Total 429 (throttled) responses in window.
            server_side_latency_avg_ms (float | None): Average server-side latency.
            ru_utilization_pct (float | None): Max NormalizedRUConsumption in window.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "account_id": account_id,
        "database_name": database_name,
        "container_name": container_name,
        "timespan": timespan,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="get_cosmos_throughput_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(account_id)
            client = MonitorManagementClient(credential, sub_id)

            metric_names = "TotalRequestUnits,NormalizedRUConsumption,ServerSideLatency,Http429s"
            response = client.metrics.list(
                resource_uri=account_id,
                metricnames=metric_names,
                timespan=timespan,
                interval="PT5M",
                aggregation="Total,Average,Maximum",
            )

            ru_data: List[Dict[str, Any]] = []
            normalized_data: List[Dict[str, Any]] = []
            latency_averages: List[float] = []
            http_429_total: float = 0.0
            ru_utilization_values: List[float] = []

            for metric in response.value:
                metric_name_val = metric.name.value if metric.name else ""
                for ts in metric.timeseries:
                    for dp in ts.data:
                        ts_str = dp.time_stamp.isoformat() if dp.time_stamp else None
                        if metric_name_val == "TotalRequestUnits":
                            ru_data.append({
                                "timestamp": ts_str,
                                "total": dp.total,
                            })
                        elif metric_name_val == "NormalizedRUConsumption":
                            normalized_data.append({
                                "timestamp": ts_str,
                                "maximum": dp.maximum,
                            })
                            if dp.maximum is not None:
                                ru_utilization_values.append(dp.maximum)
                        elif metric_name_val == "ServerSideLatency":
                            if dp.average is not None:
                                latency_averages.append(dp.average)
                        elif metric_name_val == "Http429s":
                            if dp.total is not None:
                                http_429_total += dp.total

            server_side_latency_avg: Optional[float] = (
                sum(latency_averages) / len(latency_averages)
                if latency_averages
                else None
            )
            ru_utilization_pct: Optional[float] = (
                max(ru_utilization_values) if ru_utilization_values else None
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_cosmos_throughput_metrics: complete | account=%s "
                "429s=%.0f ru_util=%.1f%% duration_ms=%.0f",
                account_id,
                http_429_total,
                ru_utilization_pct if ru_utilization_pct is not None else 0.0,
                duration_ms,
            )
            return {
                "account_id": account_id,
                "timespan": timespan,
                "total_request_units": ru_data,
                "normalized_ru_consumption": normalized_data,
                "http_429_count": int(http_429_total),
                "server_side_latency_avg_ms": server_side_latency_avg,
                "ru_utilization_pct": ru_utilization_pct,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_cosmos_throughput_metrics: failed | account=%s error=%s duration_ms=%.0f",
                account_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "account_id": account_id,
                "timespan": timespan,
                "total_request_units": [],
                "normalized_ru_consumption": [],
                "http_429_count": 0,
                "server_side_latency_avg_ms": None,
                "ru_utilization_pct": None,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_cosmos_diagnostic_logs(
    workspace_id: str,
    account_name: str,
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query Cosmos DB diagnostic logs for hot partitions and throttled ops (DB-COSMOS-003).

    Queries Log Analytics via azure-monitor-query LogsQueryClient. Surfaces:
    - Top partition keys by request count (hot partition detection)
    - Operations with status code 429 (throttled)
    - Operations with p99 latency > 100ms

    Requires Cosmos DB diagnostic settings to be configured to send
    DataPlaneRequests logs to a Log Analytics workspace.

    Args:
        workspace_id: Log Analytics workspace resource ID.
        account_name: Cosmos DB account name (used as a filter in KQL).
        timespan_hours: Look-back window in hours (default: 2).

    Returns:
        Dict with keys:
            workspace_id (str): Workspace queried.
            account_name (str): Account name filter applied.
            timespan_hours (int): Look-back window applied.
            hot_partitions (list): Top partition keys by request count (max 10).
            throttled_operations (list): Operations returning HTTP 429 (max 50).
            high_latency_operations (list): Ops with avg latency > 100ms (max 50).
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "workspace_id": workspace_id,
        "account_name": account_name,
        "timespan_hours": timespan_hours,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="query_cosmos_diagnostic_logs",
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
            start_dt = end_dt - timedelta(hours=timespan_hours)

            # Hot partition query: top partition keys by request volume
            hot_partition_kql = f"""
CDBDataPlaneRequests
| where AccountName =~ "{account_name}"
| where TimeGenerated between (datetime({start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})
    .. datetime({end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}))
| summarize RequestCount = count() by PartitionKeyRangeId, OperationName
| top 10 by RequestCount desc
"""
            # 429 throttled operations query
            throttled_kql = f"""
CDBDataPlaneRequests
| where AccountName =~ "{account_name}"
| where TimeGenerated between (datetime({start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})
    .. datetime({end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}))
| where StatusCode == 429
| project TimeGenerated, OperationName, PartitionKeyRangeId, RequestCharge, DurationMs
| top 50 by TimeGenerated desc
"""
            # High-latency operations query
            latency_kql = f"""
CDBDataPlaneRequests
| where AccountName =~ "{account_name}"
| where TimeGenerated between (datetime({start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})
    .. datetime({end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}))
| summarize AvgDurationMs = avg(DurationMs), Count = count() by OperationName
| where AvgDurationMs > 100
| top 50 by AvgDurationMs desc
"""
            duration_dt = timedelta(hours=timespan_hours)

            hot_partitions: List[Dict[str, Any]] = []
            throttled_ops: List[Dict[str, Any]] = []
            high_latency_ops: List[Dict[str, Any]] = []

            # Execute hot partition query
            try:
                hp_result = client.query_workspace(
                    workspace_id=workspace_id,
                    query=hot_partition_kql,
                    timespan=duration_dt,
                )
                if LogsQueryStatus is not None and hp_result.status == LogsQueryStatus.SUCCESS:
                    for table in hp_result.tables:
                        col_names = [col.name for col in table.columns]
                        for row in table.rows:
                            hot_partitions.append(dict(zip(col_names, row)))
            except Exception as hp_exc:
                logger.warning("query_cosmos_diagnostic_logs: hot_partition query failed | error=%s", hp_exc)

            # Execute 429 query
            try:
                throttle_result = client.query_workspace(
                    workspace_id=workspace_id,
                    query=throttled_kql,
                    timespan=duration_dt,
                )
                if LogsQueryStatus is not None and throttle_result.status == LogsQueryStatus.SUCCESS:
                    for table in throttle_result.tables:
                        col_names = [col.name for col in table.columns]
                        for row in table.rows:
                            throttled_ops.append(dict(zip(col_names, row)))
            except Exception as t_exc:
                logger.warning("query_cosmos_diagnostic_logs: throttle query failed | error=%s", t_exc)

            # Execute latency query
            try:
                lat_result = client.query_workspace(
                    workspace_id=workspace_id,
                    query=latency_kql,
                    timespan=duration_dt,
                )
                if LogsQueryStatus is not None and lat_result.status == LogsQueryStatus.SUCCESS:
                    for table in lat_result.tables:
                        col_names = [col.name for col in table.columns]
                        for row in table.rows:
                            high_latency_ops.append(dict(zip(col_names, row)))
            except Exception as lat_exc:
                logger.warning("query_cosmos_diagnostic_logs: latency query failed | error=%s", lat_exc)

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_cosmos_diagnostic_logs: complete | account=%s hot=%d throttled=%d "
                "high_latency=%d duration_ms=%.0f",
                account_name,
                len(hot_partitions),
                len(throttled_ops),
                len(high_latency_ops),
                duration_ms,
            )
            return {
                "workspace_id": workspace_id,
                "account_name": account_name,
                "timespan_hours": timespan_hours,
                "hot_partitions": hot_partitions,
                "throttled_operations": throttled_ops,
                "high_latency_operations": high_latency_ops,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_cosmos_diagnostic_logs: failed | account=%s error=%s duration_ms=%.0f",
                account_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "workspace_id": workspace_id,
                "account_name": account_name,
                "timespan_hours": timespan_hours,
                "hot_partitions": [],
                "throttled_operations": [],
                "high_latency_operations": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def propose_cosmos_throughput_scale(
    account_id: str,
    container_id: str,
    current_ru: int,
    proposed_ru: int,
    rationale: str,
) -> Dict[str, Any]:
    """Propose a Cosmos DB container throughput increase for operator approval (DB-COSMOS-004).

    Generates a HITL approval request. The Database Agent MUST NOT execute any
    throughput change directly — proposals only (REMEDI-001).

    Args:
        account_id: Cosmos DB account resource ID.
        container_id: Container resource ID (or logical path: db/container).
        current_ru: Current provisioned RU/s.
        proposed_ru: Proposed new RU/s value.
        rationale: Human-readable justification for the scale action.

    Returns:
        Dict with mandatory approval_required=True and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "account_id": account_id,
        "container_id": container_id,
        "current_ru": current_ru,
        "proposed_ru": proposed_ru,
        "rationale": rationale,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="propose_cosmos_throughput_scale",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        ru_increase_pct = round((proposed_ru - current_ru) / max(current_ru, 1) * 100, 1)
        risk_level = "low" if ru_increase_pct <= 50 else ("medium" if ru_increase_pct <= 200 else "high")

        return {
            "proposal_type": "cosmos_throughput_scale",
            "account_id": account_id,
            "container_id": container_id,
            "current_ru": current_ru,
            "proposed_ru": proposed_ru,
            "ru_increase_pct": ru_increase_pct,
            "rationale": rationale,
            "risk_level": risk_level,
            "proposed_action": (
                f"Increase Cosmos DB container throughput from {current_ru} RU/s "
                f"to {proposed_ru} RU/s ({ru_increase_pct:+.0f}%)"
            ),
            "reversibility": "Fully reversible — throughput can be decreased at any time.",
            # REMEDI-001: All proposals require explicit human approval before execution.
            "approval_required": True,
        }


# ===========================================================================
# PostgreSQL Flexible Server tools
# ===========================================================================


@ai_function
def get_postgres_server_health(
    server_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve PostgreSQL Flexible Server health and configuration (DB-PG-001).

    Fetches ARM properties including HA state, replication role, SKU, storage
    percent, and maintenance window configuration. First diagnostic step for
    PostgreSQL incidents.

    Args:
        server_name: PostgreSQL Flexible Server name.
        resource_group: Resource group containing the server.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            server_name (str): Server name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            state (str | None): Server state ("Ready", "Stopped", etc.).
            ha_state (str | None): High availability state.
            replication_role (str | None): "Primary", "Replica", etc.
            sku_name (str | None): SKU tier and vCores (e.g. "Standard_D4ds_v5").
            version (str | None): PostgreSQL version.
            storage_size_gb (int | None): Allocated storage in GB.
            backup_retention_days (int | None): Backup retention policy in days.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "server_name": server_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="get_postgres_server_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if PostgreSQLManagementClient is None:
                raise ImportError("azure-mgmt-rdbms is not installed")

            credential = get_credential()
            client = PostgreSQLManagementClient(credential, subscription_id)
            server = client.servers.get(resource_group, server_name)

            # Extract HA state safely
            ha = getattr(server, "high_availability", None)
            ha_state = str(getattr(ha, "state", None)) if ha is not None else None

            # Extract SKU
            sku = getattr(server, "sku", None)
            sku_name = getattr(sku, "name", None) if sku is not None else None

            # Extract storage
            storage = getattr(server, "storage", None)
            storage_size_gb = getattr(storage, "storage_size_gb", None) if storage is not None else None

            # Extract backup retention
            backup = getattr(server, "backup", None)
            backup_days = getattr(backup, "backup_retention_days", None) if backup is not None else None

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_postgres_server_health: complete | server=%s state=%s duration_ms=%.0f",
                server_name,
                getattr(server, "state", None),
                duration_ms,
            )
            return {
                "server_name": server_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "state": str(getattr(server, "state", None)),
                "ha_state": ha_state,
                "replication_role": str(getattr(server, "replication_role", None)),
                "sku_name": sku_name,
                "version": str(getattr(server, "version", None)),
                "storage_size_gb": storage_size_gb,
                "backup_retention_days": backup_days,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_postgres_server_health: failed | server=%s error=%s duration_ms=%.0f",
                server_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "server_name": server_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "state": None,
                "ha_state": None,
                "replication_role": None,
                "sku_name": None,
                "version": None,
                "storage_size_gb": None,
                "backup_retention_days": None,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def get_postgres_metrics(
    server_id: str,
    timespan: str = "PT2H",
    interval: str = "PT5M",
) -> Dict[str, Any]:
    """Query PostgreSQL Flexible Server performance metrics from Azure Monitor (DB-PG-002).

    Retrieves cpu_percent, memory_percent, storage_percent, connections_failed,
    connections_succeeded, and io_consumption_percent. High cpu_percent (>80%)
    combined with connections_failed indicates resource exhaustion.

    Args:
        server_id: PostgreSQL Flexible Server resource ID.
        timespan: ISO 8601 duration (default: "PT2H").
        interval: Metric granularity interval (default: "PT5M").

    Returns:
        Dict with keys:
            server_id (str): Server resource ID.
            timespan (str): Time range applied.
            interval (str): Granularity applied.
            metrics (list): Per-metric time series with avg, max, and data points.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "server_id": server_id,
        "timespan": timespan,
        "interval": interval,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="get_postgres_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(server_id)
            client = MonitorManagementClient(credential, sub_id)

            metric_names = (
                "cpu_percent,memory_percent,storage_percent,"
                "connections_failed,connections_succeeded,io_consumption_percent"
            )
            response = client.metrics.list(
                resource_uri=server_id,
                metricnames=metric_names,
                timespan=timespan,
                interval=interval,
                aggregation="Average,Maximum,Total",
            )

            metrics: List[Dict[str, Any]] = []
            for metric in response.value:
                metric_name_val = metric.name.value if metric.name else None
                averages: List[float] = []
                maximums: List[float] = []
                data_points: List[Dict[str, Any]] = []

                for ts in metric.timeseries:
                    for dp in ts.data:
                        ts_str = dp.time_stamp.isoformat() if dp.time_stamp else None
                        data_points.append({
                            "timestamp": ts_str,
                            "average": dp.average,
                            "maximum": dp.maximum,
                            "total": dp.total,
                        })
                        if dp.average is not None:
                            averages.append(dp.average)
                        if dp.maximum is not None:
                            maximums.append(dp.maximum)

                metrics.append({
                    "metric_name": metric_name_val,
                    "avg": sum(averages) / len(averages) if averages else None,
                    "max": max(maximums) if maximums else None,
                    "data_points": data_points,
                    "data_point_count": len(data_points),
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_postgres_metrics: complete | server=%s metrics=%d duration_ms=%.0f",
                server_id,
                len(metrics),
                duration_ms,
            )
            return {
                "server_id": server_id,
                "timespan": timespan,
                "interval": interval,
                "metrics": metrics,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_postgres_metrics: failed | server=%s error=%s duration_ms=%.0f",
                server_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "server_id": server_id,
                "timespan": timespan,
                "interval": interval,
                "metrics": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_postgres_slow_queries(
    workspace_id: str,
    server_name: str,
    timespan_hours: int = 2,
    threshold_ms: int = 1000,
) -> Dict[str, Any]:
    """Query PostgreSQL slow query log events from Log Analytics (DB-PG-003).

    Queries AzureDiagnostics via LogsQueryClient. Surfaces queries exceeding
    the latency threshold. Requires PostgreSQL diagnostic settings to send
    PostgreSQLLogs to a Log Analytics workspace.

    Args:
        workspace_id: Log Analytics workspace resource ID.
        server_name: PostgreSQL Flexible Server name (used as KQL filter).
        timespan_hours: Look-back window in hours (default: 2).
        threshold_ms: Minimum duration in milliseconds to include (default: 1000ms).

    Returns:
        Dict with keys:
            workspace_id (str): Workspace queried.
            server_name (str): Server name filter applied.
            timespan_hours (int): Look-back window applied.
            threshold_ms (int): Latency threshold applied.
            slow_queries (list): Slow query log events (max 50).
            slow_query_count (int): Total slow queries found.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "workspace_id": workspace_id,
        "server_name": server_name,
        "timespan_hours": timespan_hours,
        "threshold_ms": threshold_ms,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="query_postgres_slow_queries",
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
            start_dt = end_dt - timedelta(hours=timespan_hours)

            kql = f"""
AzureDiagnostics
| where ResourceType =~ "FLEXIBLESERVERS"
| where Resource =~ "{server_name}"
| where TimeGenerated between (datetime({start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})
    .. datetime({end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}))
| where Category == "PostgreSQLLogs"
| where Message contains "duration:"
| extend DurationMs = todouble(extract(@"duration: ([0-9.]+) ms", 1, Message))
| where DurationMs >= {threshold_ms}
| project TimeGenerated, DurationMs, Message, Resource
| order by DurationMs desc
| limit 50
"""
            duration_dt = timedelta(hours=timespan_hours)
            result = client.query_workspace(
                workspace_id=workspace_id,
                query=kql,
                timespan=duration_dt,
            )

            slow_queries: List[Dict[str, Any]] = []
            if LogsQueryStatus is not None and result.status == LogsQueryStatus.SUCCESS:
                for table in result.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        slow_queries.append(dict(zip(col_names, row)))

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_postgres_slow_queries: complete | server=%s slow=%d duration_ms=%.0f",
                server_name,
                len(slow_queries),
                duration_ms,
            )
            return {
                "workspace_id": workspace_id,
                "server_name": server_name,
                "timespan_hours": timespan_hours,
                "threshold_ms": threshold_ms,
                "slow_queries": slow_queries,
                "slow_query_count": len(slow_queries),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_postgres_slow_queries: failed | server=%s error=%s duration_ms=%.0f",
                server_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "workspace_id": workspace_id,
                "server_name": server_name,
                "timespan_hours": timespan_hours,
                "threshold_ms": threshold_ms,
                "slow_queries": [],
                "slow_query_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def propose_postgres_sku_scale(
    server_id: str,
    current_sku: str,
    proposed_sku: str,
    rationale: str,
) -> Dict[str, Any]:
    """Propose a PostgreSQL Flexible Server SKU change for operator approval (DB-PG-004).

    Generates a HITL approval request. The Database Agent MUST NOT execute any
    SKU change directly — proposals only (REMEDI-001).

    Args:
        server_id: PostgreSQL Flexible Server resource ID.
        current_sku: Current SKU name (e.g. "Standard_D4ds_v5").
        proposed_sku: Proposed SKU name (e.g. "Standard_D8ds_v5").
        rationale: Human-readable justification for the scale action.

    Returns:
        Dict with mandatory approval_required=True and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "server_id": server_id,
        "current_sku": current_sku,
        "proposed_sku": proposed_sku,
        "rationale": rationale,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="propose_postgres_sku_scale",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "proposal_type": "postgres_sku_scale",
            "server_id": server_id,
            "current_sku": current_sku,
            "proposed_sku": proposed_sku,
            "rationale": rationale,
            "risk_level": "medium",
            "proposed_action": (
                f"Scale PostgreSQL Flexible Server from SKU '{current_sku}' "
                f"to '{proposed_sku}'"
            ),
            "reversibility": (
                "Reversible — SKU can be scaled back down, "
                "but requires a brief service restart (HA failover minimises downtime)."
            ),
            # REMEDI-001: All proposals require explicit human approval before execution.
            "approval_required": True,
        }


# ===========================================================================
# Azure SQL Database tools
# ===========================================================================


@ai_function
def get_sql_database_health(
    server_name: str,
    database_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve Azure SQL Database health, service tier, and elastic pool info (DB-SQL-001).

    Fetches ARM properties including database status, service tier (DTU/vCore),
    edition, zone redundancy, and elastic pool membership.

    Args:
        server_name: Azure SQL logical server name.
        database_name: Database name.
        resource_group: Resource group containing the server.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            server_name (str): SQL server name.
            database_name (str): Database name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            status (str | None): Database status (Online, Offline, etc.).
            edition (str | None): Service tier edition.
            service_objective (str | None): Service level objective (DTU/vCore tier).
            zone_redundant (bool | None): Whether zone redundancy is enabled.
            elastic_pool_id (str | None): Elastic pool resource ID if in pool.
            max_size_bytes (int | None): Maximum database size in bytes.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "server_name": server_name,
        "database_name": database_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="get_sql_database_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if SqlManagementClient is None:
                raise ImportError("azure-mgmt-sql is not installed")

            credential = get_credential()
            client = SqlManagementClient(credential, subscription_id)
            db = client.databases.get(resource_group, server_name, database_name)

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_sql_database_health: complete | server=%s db=%s status=%s duration_ms=%.0f",
                server_name,
                database_name,
                getattr(db, "status", None),
                duration_ms,
            )
            return {
                "server_name": server_name,
                "database_name": database_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "status": str(getattr(db, "status", None)),
                "edition": getattr(db, "edition", None),
                "service_objective": getattr(db, "current_service_objective_name", None),
                "zone_redundant": getattr(db, "zone_redundant", None),
                "elastic_pool_id": getattr(db, "elastic_pool_id", None),
                "max_size_bytes": getattr(db, "max_size_bytes", None),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_sql_database_health: failed | server=%s db=%s error=%s duration_ms=%.0f",
                server_name,
                database_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "server_name": server_name,
                "database_name": database_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "status": None,
                "edition": None,
                "service_objective": None,
                "zone_redundant": None,
                "elastic_pool_id": None,
                "max_size_bytes": None,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def get_sql_dtu_metrics(
    database_id: str,
    timespan: str = "PT2H",
    interval: str = "PT5M",
) -> Dict[str, Any]:
    """Query Azure SQL Database DTU/vCore utilisation metrics from Azure Monitor (DB-SQL-002).

    Retrieves dtu_consumption_percent, cpu_percent, storage_percent, deadlock,
    failed_connections, and sessions_percent. High dtu_consumption_percent (>80%)
    indicates resource pressure and potential query performance degradation.

    Args:
        database_id: Azure SQL Database resource ID.
        timespan: ISO 8601 duration (default: "PT2H").
        interval: Metric granularity interval (default: "PT5M").

    Returns:
        Dict with keys:
            database_id (str): Database resource ID.
            timespan (str): Time range applied.
            interval (str): Granularity applied.
            metrics (list): Per-metric time series with avg, max, data points.
            dtu_utilization_pct (float | None): Max DTU consumption in window.
            deadlock_count (int): Total deadlocks in the window.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "database_id": database_id,
        "timespan": timespan,
        "interval": interval,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="get_sql_dtu_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(database_id)
            client = MonitorManagementClient(credential, sub_id)

            metric_names = (
                "dtu_consumption_percent,cpu_percent,storage_percent,"
                "deadlock,failed_connections,sessions_percent"
            )
            response = client.metrics.list(
                resource_uri=database_id,
                metricnames=metric_names,
                timespan=timespan,
                interval=interval,
                aggregation="Average,Maximum,Total",
            )

            metrics: List[Dict[str, Any]] = []
            dtu_maximums: List[float] = []
            deadlock_total: float = 0.0

            for metric in response.value:
                metric_name_val = metric.name.value if metric.name else None
                averages: List[float] = []
                maximums: List[float] = []
                data_points: List[Dict[str, Any]] = []

                for ts in metric.timeseries:
                    for dp in ts.data:
                        ts_str = dp.time_stamp.isoformat() if dp.time_stamp else None
                        data_points.append({
                            "timestamp": ts_str,
                            "average": dp.average,
                            "maximum": dp.maximum,
                            "total": dp.total,
                        })
                        if dp.average is not None:
                            averages.append(dp.average)
                        if dp.maximum is not None:
                            maximums.append(dp.maximum)
                            if metric_name_val == "dtu_consumption_percent":
                                dtu_maximums.append(dp.maximum)
                        if metric_name_val == "deadlock" and dp.total is not None:
                            deadlock_total += dp.total

                metrics.append({
                    "metric_name": metric_name_val,
                    "avg": sum(averages) / len(averages) if averages else None,
                    "max": max(maximums) if maximums else None,
                    "data_points": data_points,
                    "data_point_count": len(data_points),
                })

            dtu_utilization_pct: Optional[float] = (
                max(dtu_maximums) if dtu_maximums else None
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_sql_dtu_metrics: complete | db=%s dtu_util=%.1f%% "
                "deadlocks=%.0f duration_ms=%.0f",
                database_id,
                dtu_utilization_pct if dtu_utilization_pct is not None else 0.0,
                deadlock_total,
                duration_ms,
            )
            return {
                "database_id": database_id,
                "timespan": timespan,
                "interval": interval,
                "metrics": metrics,
                "dtu_utilization_pct": dtu_utilization_pct,
                "deadlock_count": int(deadlock_total),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_sql_dtu_metrics: failed | db=%s error=%s duration_ms=%.0f",
                database_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "database_id": database_id,
                "timespan": timespan,
                "interval": interval,
                "metrics": [],
                "dtu_utilization_pct": None,
                "deadlock_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_sql_query_store(
    workspace_id: str,
    server_name: str,
    database_name: str,
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query Azure SQL top slow queries via Log Analytics (DB-SQL-003).

    Queries AzureDiagnostics and AzureMetrics via LogsQueryClient to surface
    top queries by average execution duration. Requires SQL diagnostic settings
    sending QueryStoreRuntimeStatistics or AuditEvent logs to the workspace.

    Args:
        workspace_id: Log Analytics workspace resource ID.
        server_name: Azure SQL logical server name (KQL filter).
        database_name: Database name (KQL filter).
        timespan_hours: Look-back window in hours (default: 2).

    Returns:
        Dict with keys:
            workspace_id (str): Workspace queried.
            server_name (str): Server filter applied.
            database_name (str): Database filter applied.
            timespan_hours (int): Look-back window applied.
            top_queries (list): Top queries by avg duration (max 20).
            query_count (int): Number of distinct queries found.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "workspace_id": workspace_id,
        "server_name": server_name,
        "database_name": database_name,
        "timespan_hours": timespan_hours,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="query_sql_query_store",
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
            start_dt = end_dt - timedelta(hours=timespan_hours)

            kql = f"""
AzureDiagnostics
| where ResourceType =~ "SERVERS/DATABASES"
| where Resource =~ "{server_name}"
| where TimeGenerated between (datetime({start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})
    .. datetime({end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}))
| where Category == "QueryStoreRuntimeStatistics"
| extend AvgDurationMs = todouble(column_ifexists("avg_duration_d", 0)) / 1000.0
| summarize AvgDurationMs = avg(AvgDurationMs), ExecutionCount = sum(todouble(
    column_ifexists("count_executions_d", 1)))
    by query_id_d
| where AvgDurationMs > 0
| top 20 by AvgDurationMs desc
"""
            duration_dt = timedelta(hours=timespan_hours)
            result = client.query_workspace(
                workspace_id=workspace_id,
                query=kql,
                timespan=duration_dt,
            )

            top_queries: List[Dict[str, Any]] = []
            if LogsQueryStatus is not None and result.status == LogsQueryStatus.SUCCESS:
                for table in result.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        top_queries.append(dict(zip(col_names, row)))

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_sql_query_store: complete | server=%s db=%s "
                "queries=%d duration_ms=%.0f",
                server_name,
                database_name,
                len(top_queries),
                duration_ms,
            )
            return {
                "workspace_id": workspace_id,
                "server_name": server_name,
                "database_name": database_name,
                "timespan_hours": timespan_hours,
                "top_queries": top_queries,
                "query_count": len(top_queries),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_sql_query_store: failed | server=%s db=%s error=%s duration_ms=%.0f",
                server_name,
                database_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "workspace_id": workspace_id,
                "server_name": server_name,
                "database_name": database_name,
                "timespan_hours": timespan_hours,
                "top_queries": [],
                "query_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def propose_sql_elastic_pool_move(
    database_id: str,
    target_elastic_pool_id: str,
    rationale: str,
) -> Dict[str, Any]:
    """Propose moving an Azure SQL Database into an elastic pool for operator approval (DB-SQL-004).

    Generates a HITL approval request. The Database Agent MUST NOT execute any
    database tier change directly — proposals only (REMEDI-001).

    Args:
        database_id: Azure SQL Database resource ID.
        target_elastic_pool_id: Target elastic pool resource ID.
        rationale: Human-readable justification for the move.

    Returns:
        Dict with mandatory approval_required=True and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "database_id": database_id,
        "target_elastic_pool_id": target_elastic_pool_id,
        "rationale": rationale,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="database-agent",
        agent_id=agent_id,
        tool_name="propose_sql_elastic_pool_move",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "proposal_type": "sql_elastic_pool_move",
            "database_id": database_id,
            "target_elastic_pool_id": target_elastic_pool_id,
            "rationale": rationale,
            "risk_level": "medium",
            "proposed_action": (
                f"Move Azure SQL Database '{database_id}' into "
                f"elastic pool '{target_elastic_pool_id}'"
            ),
            "reversibility": (
                "Reversible — database can be removed from the elastic pool "
                "and returned to a standalone tier. Brief performance impact during move."
            ),
            # REMEDI-001: All proposals require explicit human approval before execution.
            "approval_required": True,
        }
