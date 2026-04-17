from __future__ import annotations
"""AKS Chat function-calling tools.

Live Azure SDK tool functions exposed to the LLM via chat.completions
function calling. Each function is intentionally narrow and never raises —
errors are returned as structured dicts so the LLM can report them cleanly.

Tools:
  get_aks_cluster_info     — power state, K8s version, node pool count via ARG KQL
  get_aks_node_pools       — list node pools with vmSize/count/mode/provisioning_state
  get_aks_metrics          — platform metrics via Azure Monitor
  get_aks_workload_summary — pod counts via KubePodInventory KQL (Container Insights)
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subscription ID helper
# ---------------------------------------------------------------------------

def _extract_subscription_id(resource_id: str) -> str:
    parts = resource_id.lower().split("/")
    idx = parts.index("subscriptions")
    return resource_id.split("/")[idx + 1]


# ---------------------------------------------------------------------------
# SDK enum compat helper
# ---------------------------------------------------------------------------

def _str_val(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return obj.value if hasattr(obj, "value") else str(obj)


# ---------------------------------------------------------------------------
# Tool: get_aks_cluster_info
# ---------------------------------------------------------------------------

def get_aks_cluster_info(resource_id: str, credential: Any) -> dict:
    """Fetch AKS cluster power state, K8s version, node pool count, and provisioning state via ARG.

    Args:
        resource_id: Full ARM resource ID of the AKS cluster.
        credential: DefaultAzureCredential instance.

    Returns:
        Dict with cluster info or error.
    """
    start = time.monotonic()
    try:
        from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
        from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        kql = f"""
Resources
| where type =~ 'microsoft.containerservice/managedclusters'
| where id =~ '{resource_id}'
| extend agentPools = properties.agentPoolProfiles
| extend node_pool_count = array_length(agentPools)
| extend power_state = tostring(properties.powerState.code)
| project
    id, name, location,
    kubernetes_version = tostring(properties.kubernetesVersion),
    provisioning_state = tostring(properties.provisioningState),
    power_state,
    node_pool_count,
    fqdn = tostring(properties.fqdn),
    network_plugin = tostring(properties.networkProfile.networkPlugin),
    rbac_enabled = tobool(properties.enableRBAC)
"""
        client = ResourceGraphClient(credential)
        resp = client.resources(QueryRequest(subscriptions=[sub_id], query=kql.strip()))

        if not resp.data:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning("aks_chat_tools: get_aks_cluster_info not_found resource=%s duration_ms=%d",
                           resource_id[-60:], duration_ms)
            return {"query_status": "not_found", "resource_id": resource_id}

        row = resp.data[0]
        raw_power = str(row.get("power_state", "")).lower()
        if "running" in raw_power:
            power_state = "running"
        elif "stopped" in raw_power:
            power_state = "stopped"
        else:
            power_state = raw_power or "unknown"

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("aks_chat_tools: get_aks_cluster_info | resource=%s state=%s duration_ms=%d",
                    resource_id[-60:], power_state, duration_ms)
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "name": row.get("name"),
            "location": row.get("location"),
            "kubernetes_version": row.get("kubernetes_version"),
            "provisioning_state": row.get("provisioning_state"),
            "power_state": power_state,
            "power_state_raw": row.get("power_state"),
            "node_pool_count": row.get("node_pool_count", 0),
            "fqdn": row.get("fqdn") or None,
            "network_plugin": row.get("network_plugin"),
            "rbac_enabled": bool(row.get("rbac_enabled", False)),
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("aks_chat_tools: get_aks_cluster_info failed | resource=%s error=%s duration_ms=%d",
                       resource_id[-60:], exc, duration_ms)
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Tool: get_aks_node_pools
# ---------------------------------------------------------------------------

def get_aks_node_pools(resource_id: str, credential: Any) -> dict:
    """List AKS node pools with vmSize, count, mode, and provisioning state.

    Args:
        resource_id: Full ARM resource ID of the AKS cluster.
        credential: DefaultAzureCredential instance.

    Returns:
        Dict with node pool list or error.
    """
    start = time.monotonic()
    try:
        from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        parts = resource_id.split("/")
        rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
        resource_group = parts[rg_index + 1] if rg_index >= 0 else ""
        cluster_name = parts[-1]

        client = ContainerServiceClient(credential, sub_id)
        pools = []
        for pool in client.agent_pools.list(resource_group, cluster_name):
            mode_val = _str_val(pool.mode) or "User"
            pools.append({
                "name": pool.name or "",
                "vm_size": pool.vm_size or "",
                "count": pool.count or 0,
                "mode": mode_val,
                "os_type": _str_val(pool.os_type) or "Linux",
                "provisioning_state": pool.provisioning_state or "unknown",
                "min_count": pool.min_count,
                "max_count": pool.max_count,
                "power_state": _str_val(getattr(getattr(pool, "power_state", None), "code", None)),
            })

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("aks_chat_tools: get_aks_node_pools | resource=%s pools=%d duration_ms=%d",
                    resource_id[-60:], len(pools), duration_ms)
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "cluster_name": cluster_name,
            "node_pool_count": len(pools),
            "node_pools": pools,
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("aks_chat_tools: get_aks_node_pools failed | resource=%s error=%s duration_ms=%d",
                       resource_id[-60:], exc, duration_ms)
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Tool: get_aks_metrics
# ---------------------------------------------------------------------------

def get_aks_metrics(
    resource_id: str,
    credential: Any,
    metric_names: Optional[list[str]] = None,
    timespan_hours: int = 1,
    interval: str = "PT5M",
) -> dict:
    """Fetch Azure Monitor platform metrics for an AKS cluster.

    Args:
        resource_id: Full ARM resource ID of the AKS cluster.
        credential: DefaultAzureCredential instance.
        metric_names: List of metric names. Defaults to key AKS metrics if omitted.
        timespan_hours: How many hours back to query (default 1).
        interval: ISO 8601 granularity (default PT5M = 5-minute buckets).

    Returns:
        Dict with metrics data or error.
    """
    if metric_names is None:
        metric_names = [
            "node_cpu_usage_percentage",
            "node_memory_working_set_percentage",
            "kube_pod_status_ready",
            "kube_node_status_condition",
        ]

    start = time.monotonic()
    try:
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        client = MonitorManagementClient(credential, sub_id)

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=timespan_hours)
        timespan = f"{start_time.isoformat()}/{end_time.isoformat()}"

        results: dict[str, dict] = {}
        for metric_name in metric_names:
            try:
                response = client.metrics.list(
                    resource_uri=resource_id,
                    metricnames=metric_name,
                    metricnamespace="Microsoft.ContainerService/managedClusters",
                    timespan=timespan,
                    interval=interval,
                    aggregation="Average,Maximum,Minimum",
                )
                for metric in response.value:
                    name = _str_val(metric.name) or metric_name
                    unit = _str_val(metric.unit) or ""
                    datapoints = []
                    for ts in metric.timeseries:
                        for dp in ts.data:
                            if dp.time_stamp and (dp.average is not None or dp.maximum is not None):
                                datapoints.append({
                                    "timestamp": dp.time_stamp.isoformat(),
                                    "average": round(dp.average, 2) if dp.average is not None else None,
                                    "maximum": round(dp.maximum, 2) if dp.maximum is not None else None,
                                    "minimum": round(dp.minimum, 2) if dp.minimum is not None else None,
                                })
                    results[name] = {"unit": unit, "datapoints": datapoints[-12:]}
            except Exception as metric_exc:
                logger.warning("aks_chat_tools: get_aks_metrics skipping metric=%r error=%s",
                               metric_name, metric_exc)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("aks_chat_tools: get_aks_metrics | resource=%s metrics=%d duration_ms=%d",
                    resource_id[-60:], len(results), duration_ms)
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "timespan_hours": timespan_hours,
            "interval": interval,
            "metrics": results,
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("aks_chat_tools: get_aks_metrics failed | resource=%s error=%s duration_ms=%d",
                       resource_id[-60:], exc, duration_ms)
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# Workspace ID resolver helper
# ---------------------------------------------------------------------------

def _resolve_workspace_id(resource_id: str, credential: Any) -> Optional[str]:
    """Resolve Log Analytics workspace GUID from AKS cluster's omsagent addon profile.

    Looks up the workspace resource ID via ContainerServiceClient, then resolves
    the GUID via LogAnalyticsManagementClient.workspaces.get().

    Returns the workspace GUID string, or None if unavailable.
    """
    try:
        from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]
        from azure.mgmt.loganalytics import LogAnalyticsManagementClient  # type: ignore[import]

        sub_id = _extract_subscription_id(resource_id)
        parts = resource_id.split("/")
        rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
        resource_group = parts[rg_index + 1] if rg_index >= 0 else ""
        cluster_name = parts[-1]

        aks_client = ContainerServiceClient(credential, sub_id)
        cluster = aks_client.managed_clusters.get(resource_group, cluster_name)

        profiles = cluster.addon_profiles or {}
        omsagent = profiles.get("omsagent")
        if not omsagent or not getattr(omsagent, "enabled", False):
            return None

        la_config = getattr(omsagent, "config", None) or {}
        workspace_resource_id: Optional[str] = la_config.get("logAnalyticsWorkspaceResourceID")
        if not workspace_resource_id:
            return None

        # Resolve resource ID → GUID
        ws_parts = workspace_resource_id.split("/")
        ws_rg_index = next((i for i, p in enumerate(ws_parts) if p.lower() == "resourcegroups"), -1)
        ws_sub_id = ws_parts[ws_parts.index("subscriptions") + 1] if "subscriptions" in [p.lower() for p in ws_parts] else sub_id
        ws_rg = ws_parts[ws_rg_index + 1] if ws_rg_index >= 0 else ""
        ws_name = ws_parts[-1]

        la_client = LogAnalyticsManagementClient(credential, ws_sub_id)
        workspace = la_client.workspaces.get(ws_rg, ws_name)
        return workspace.customer_id  # This is the GUID used in query_workspace calls

    except Exception as exc:
        logger.warning("aks_chat_tools: _resolve_workspace_id failed resource=%s error=%s",
                       resource_id[-60:], exc)
        return None


# ---------------------------------------------------------------------------
# Tool: get_aks_workload_summary
# ---------------------------------------------------------------------------

def get_aks_workload_summary(
    resource_id: str,
    credential: Any,
    workspace_id: Optional[str] = None,
) -> dict:
    """Fetch pod counts via KubePodInventory KQL on Log Analytics (Container Insights).

    Args:
        resource_id: Full ARM resource ID of the AKS cluster.
        credential: DefaultAzureCredential instance.
        workspace_id: Log Analytics workspace GUID. If None/empty, attempts auto-discovery
                      from the cluster's omsagent addon profile. Returns no_workspace if
                      Container Insights is not configured.

    Returns:
        Dict with running_pods, pending_pods, failed_pods, unknown_pods totals or error.
    """
    start = time.monotonic()

    # Auto-discover workspace ID if not supplied
    if not workspace_id:
        workspace_id = _resolve_workspace_id(resource_id, credential)

    if not workspace_id:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("aks_chat_tools: get_aks_workload_summary no_workspace resource=%s duration_ms=%d",
                    resource_id[-60:], duration_ms)
        return {
            "query_status": "no_workspace",
            "message": "Container Insights not configured",
            "resource_id": resource_id,
        }

    cluster_name = resource_id.split("/")[-1]

    try:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus  # type: ignore[import]

        client = LogsQueryClient(credential)
        kql = f"""
KubePodInventory
| where TimeGenerated > ago(2h)
| where ClusterName =~ "{cluster_name}"
| summarize arg_max(TimeGenerated, *) by PodUid
| summarize
    running_pods  = countif(PodStatus == "Running"),
    pending_pods  = countif(PodStatus == "Pending"),
    failed_pods   = countif(PodStatus == "Failed"),
    unknown_pods  = countif(PodStatus == "Unknown"),
    total_pods    = count()
"""
        result = client.query_workspace(
            workspace_id=workspace_id,
            query=kql,
            timespan=timedelta(hours=3),
        )

        tables = None
        if result.status == LogsQueryStatus.SUCCESS:
            tables = getattr(result, "tables", None)
        elif result.status == LogsQueryStatus.PARTIAL:
            tables = getattr(result, "partial_data", None)
            logger.warning("aks_chat_tools: get_aks_workload_summary partial result cluster=%s", cluster_name)

        if tables and tables[0].rows:
            table = tables[0]
            cols = [c.name if hasattr(c, "name") else str(c) for c in table.columns]
            row_dict = dict(zip(cols, table.rows[0]))
            running = int(row_dict.get("running_pods") or 0)
            pending = int(row_dict.get("pending_pods") or 0)
            failed = int(row_dict.get("failed_pods") or 0)
            unknown = int(row_dict.get("unknown_pods") or 0)
            total = int(row_dict.get("total_pods") or 0)

            duration_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "aks_chat_tools: get_aks_workload_summary | cluster=%s running=%d pending=%d failed=%d duration_ms=%d",
                cluster_name, running, pending, failed, duration_ms,
            )
            return {
                "query_status": "success",
                "resource_id": resource_id,
                "cluster_name": cluster_name,
                "running_pods": running,
                "pending_pods": pending,
                "failed_pods": failed,
                "unknown_pods": unknown,
                "total_pods": total,
            }

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("aks_chat_tools: get_aks_workload_summary empty result cluster=%s duration_ms=%d",
                    cluster_name, duration_ms)
        return {
            "query_status": "success",
            "resource_id": resource_id,
            "cluster_name": cluster_name,
            "running_pods": 0,
            "pending_pods": 0,
            "failed_pods": 0,
            "unknown_pods": 0,
            "total_pods": 0,
            "note": "No pod data found in Container Insights (table may be empty or ingestion delayed)",
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("aks_chat_tools: get_aks_workload_summary failed | resource=%s error=%s duration_ms=%d",
                       resource_id[-60:], exc, duration_ms)
        return {"query_status": "error", "error": str(exc), "resource_id": resource_id}


# ---------------------------------------------------------------------------
# OpenAI function schemas
# ---------------------------------------------------------------------------

AKS_CHAT_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_aks_cluster_info",
            "description": (
                "Fetch AKS cluster overview from Azure Resource Graph: power state (running/stopped), "
                "Kubernetes version, node pool count, provisioning state, FQDN, network plugin, and RBAC status. "
                "Use this when the user asks about cluster status, version, or general cluster details."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aks_node_pools",
            "description": (
                "List all node pools for an AKS cluster: name, VM size, node count, mode (System/User), "
                "OS type, provisioning state, and autoscaler min/max counts. "
                "Use this when the user asks about node pools, node sizes, node counts, or scaling configuration."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aks_metrics",
            "description": (
                "Fetch live Azure Monitor platform metrics for an AKS cluster: "
                "node CPU percentage, node memory working set percentage, "
                "pod readiness counts (kube_pod_status_ready), and node condition (kube_node_status_condition). "
                "Use this when the user asks about cluster performance, CPU, memory, or node health metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Metric names to fetch. Defaults to key AKS metrics if omitted. "
                            "Valid values: 'node_cpu_usage_percentage', 'node_memory_working_set_percentage', "
                            "'kube_pod_status_ready', 'kube_node_status_condition'."
                        ),
                    },
                    "timespan_hours": {
                        "type": "integer",
                        "description": "How many hours back to query. Default 1. Use 24 for daily trend.",
                        "default": 1,
                    },
                    "interval": {
                        "type": "string",
                        "description": "Metric granularity as ISO 8601 duration. Default PT5M (5 min). Use PT1H for hourly.",
                        "default": "PT5M",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aks_workload_summary",
            "description": (
                "Fetch pod counts from Container Insights (Log Analytics KubePodInventory table): "
                "running pods, pending pods, failed pods, unknown pods, and total. "
                "Requires Container Insights to be enabled on the cluster. "
                "Use this when the user asks about workloads, pod health, running pods, or pending/failed pods."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": (
                            "Log Analytics workspace GUID (not resource ID). "
                            "If omitted, the tool will attempt to auto-discover it from the cluster's "
                            "Container Insights addon profile. Provide explicitly if auto-discovery fails."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher — called by aks_chat.py when the LLM requests a tool
# ---------------------------------------------------------------------------

def dispatch_tool_call(
    tool_name: str,
    tool_args: dict,
    resource_id: str,
    credential: Any,
) -> str:
    """Execute a tool call and return result as a JSON string for the LLM."""
    logger.info("aks_chat_tools: dispatch | tool=%s args=%s", tool_name, tool_args)

    if tool_name == "get_aks_cluster_info":
        result = get_aks_cluster_info(resource_id=resource_id, credential=credential)
    elif tool_name == "get_aks_node_pools":
        result = get_aks_node_pools(resource_id=resource_id, credential=credential)
    elif tool_name == "get_aks_metrics":
        result = get_aks_metrics(
            resource_id=resource_id,
            credential=credential,
            metric_names=tool_args.get("metric_names"),
            timespan_hours=tool_args.get("timespan_hours", 1),
            interval=tool_args.get("interval", "PT5M"),
        )
    elif tool_name == "get_aks_workload_summary":
        result = get_aks_workload_summary(
            resource_id=resource_id,
            credential=credential,
            workspace_id=tool_args.get("workspace_id"),
        )
    else:
        result = {"query_status": "error", "error": f"Unknown tool: {tool_name}"}

    return json.dumps(result, default=str)
