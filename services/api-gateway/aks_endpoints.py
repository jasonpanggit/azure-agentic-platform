"""AKS cluster inventory and chat endpoints.

GET  /api/v1/aks                           — list AKS clusters in subscriptions via ARG
GET  /api/v1/aks/{resource_id_base64}      — AKS cluster detail including node pools
GET  /api/v1/aks/{resource_id_base64}/metrics  — Azure Monitor metrics for AKS
POST /api/v1/aks/{resource_id_base64}/monitoring — Enable Container Insights on AKS cluster
POST /api/v1/aks/{resource_id_base64}/chat     — resource-scoped chat for AKS investigation

When the Azure SDK packages are unavailable, all list endpoints return empty
structured responses matching the shape the frontend expects.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from services.api_gateway.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/aks", tags=["aks"])

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]
    _ARG_AVAILABLE = True
except ImportError:
    _ARG_AVAILABLE = False
    logger.warning("azure-mgmt-resourcegraph not available — AKS list returns empty")

try:
    from azure.mgmt.containerservice import ContainerServiceClient as _AKSClient  # type: ignore[import]
except ImportError:
    _AKSClient = None  # type: ignore[assignment,misc]

try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus  # type: ignore[import]
    _LOGS_QUERY_AVAILABLE = True
except ImportError:
    _LOGS_QUERY_AVAILABLE = False
    logger.warning("azure-monitor-query not available — AKS workload summary unavailable")

# AKS platform metric names (Microsoft.ContainerService/managedClusters namespace).
# metricnamespace MUST be specified or these will return empty.
# NOTE: apiserver_request_total is Prometheus-only — NOT a platform metric; excluded.
_AKS_METRIC_NAMES = [
    "node_cpu_usage_percentage",
    "node_memory_working_set_percentage",
    "node_memory_rss_percentage",
    "node_disk_usage_bytes",
    "node_network_in_bytes",
    "node_network_out_bytes",
    "kube_pod_status_ready",
    "kube_node_status_condition",
    "apiserver_cpu_usage_percentage",
    "cluster_autoscaler_unschedulable_pods_count",
]

AKS_METRIC_NAMESPACE = "Microsoft.ContainerService/managedClusters"


def _log_sdk_availability() -> None:
    logger.info(
        "aks_endpoints: azure-mgmt-resourcegraph available=%s containerservice available=%s",
        _ARG_AVAILABLE, _AKSClient is not None,
    )


_log_sdk_availability()


# ---------------------------------------------------------------------------
# Metrics constants
# ---------------------------------------------------------------------------

AKS_DEFAULT_METRICS = [
    "node_cpu_usage_percentage",
    "node_memory_working_set_percentage",
    "node_memory_rss_percentage",
    "node_disk_usage_bytes",
    "node_network_in_bytes",
    "node_network_out_bytes",
    "kube_pod_status_ready",
    "kube_node_status_condition",
    "apiserver_request_total",
    "cluster_autoscaler_unschedulable_pods_count",
]


def _decode_resource_id(encoded: str) -> str:
    """Decode base64url-encoded ARM resource ID."""
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    try:
        return base64.urlsafe_b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Invalid resource ID encoding: {exc}") from exc


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from ARM resource ID."""
    parts = resource_id.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "subscriptions" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _enum_value(obj: Any, default: str) -> str:
    """Safely extract a string value from an Azure SDK enum or plain string.

    Azure SDK enum objects (e.g. AgentPoolMode.SYSTEM) have a ``.value``
    attribute that holds the canonical string (e.g. "System").  Calling
    ``str()`` on them produces the full qualified name which is wrong.
    """
    if obj is None:
        return default
    if hasattr(obj, "value"):
        return obj.value or default
    return str(obj) or default


def _fetch_aks_workload_summary(
    credential: Any,
    la_workspace_resource_id: str,
    cluster_name: str,
) -> Optional[Dict[str, Any]]:
    """Query KubePodInventory in Log Analytics to get workload summary for an AKS cluster.

    Returns a dict with running_pods, crash_loop_pods, pending_pods, namespace_count,
    or None if the workspace has no Container Insights data.

    Uses a 30-minute lookback window (ago(30m)) to reliably capture data even
    when Container Insights ingestion has intermittent delays.  The timespan
    parameter is set to 1 hour to give the query engine sufficient context.
    """
    if not _LOGS_QUERY_AVAILABLE:
        logger.info("aks_workload_summary: azure-monitor-query SDK not available")
        return None
    if not la_workspace_resource_id:
        logger.info("aks_workload_summary: no workspace resource ID for cluster=%s", cluster_name)
        return None

    from datetime import timedelta

    try:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus  # type: ignore[import]
    except ImportError:
        return None

    try:
        client = LogsQueryClient(credential)
        # Use a 2-hour lookback to handle Container Insights ingestion delays
        # (typically 5-15 min but can be up to 90 min in degraded conditions).
        kql = f"""
KubePodInventory
| where TimeGenerated > ago(2h)
| where ClusterName =~ "{cluster_name}"
| summarize
    running_pods = countif(PodStatus == "Running"),
    crash_loop_pods = countif(ContainerStatusReason == "CrashLoopBackOff"),
    pending_pods = countif(PodStatus == "Pending"),
    namespace_count = dcount(Namespace)
"""
        result = client.query_resource(
            la_workspace_resource_id,
            kql,
            timespan=timedelta(hours=3),
        )

        # Handle both SUCCESS and PARTIAL results — partial results
        # have data in .partial_data instead of .tables.
        tables = None
        if result.status == LogsQueryStatus.SUCCESS:
            tables = getattr(result, "tables", None)
        elif result.status == LogsQueryStatus.PARTIAL:
            tables = getattr(result, "partial_data", None)
            logger.warning(
                "aks_workload_summary: partial result for cluster=%s error=%s",
                cluster_name,
                getattr(result, "partial_error", "unknown"),
            )

        if tables:
            table = tables[0]
            if table.rows:
                row = table.rows[0]
                # azure-monitor-query SDK versions differ: columns may be LogsTableColumn
                # objects (have .name) or plain strings depending on installed version.
                cols = [c.name if hasattr(c, "name") else str(c) for c in table.columns]
                row_dict = dict(zip(cols, row))
                running = int(row_dict.get("running_pods") or 0)
                crash = int(row_dict.get("crash_loop_pods") or 0)
                pending = int(row_dict.get("pending_pods") or 0)
                ns_count = int(row_dict.get("namespace_count") or 0)
                # Distinguish "KQL ran and found real data" from "KQL returned zeros"
                # so the frontend can show an appropriate message.
                source = "kql" if (running + crash + pending + ns_count) > 0 else "kql_empty"
                logger.info(
                    "aks_workload_summary: cluster=%s running=%d crash=%d pending=%d ns=%d source=%s",
                    cluster_name, running, crash, pending, ns_count, source,
                )
                return {
                    "running_pods": running,
                    "crash_loop_pods": crash,
                    "pending_pods": pending,
                    "namespace_count": ns_count,
                    "source": source,
                }
            # KQL summarize without 'by' returns 1 row even on empty input.
            # If we got tables but no rows, return zeros with kql_empty source.
            logger.info("aks_workload_summary: query returned empty rows for cluster=%s", cluster_name)
            return {
                "running_pods": 0,
                "crash_loop_pods": 0,
                "pending_pods": 0,
                "namespace_count": 0,
                "source": "kql_empty",
            }

        logger.info("aks_workload_summary: query returned no tables for cluster=%s", cluster_name)
    except Exception as exc:
        logger.warning("aks_workload_summary: query failed cluster=%s error=%s", cluster_name, exc)
    return None


def _fetch_system_pod_health_batch(
    credential: Any,
    la_workspace_resource_id: str,
    cluster_names: List[str],
) -> Dict[str, str]:
    """Batch-query Container Insights for kube-system pod health across multiple AKS clusters.

    Queries KubePodInventory in Log Analytics filtered to Namespace == 'kube-system',
    grouped by ClusterName.  Returns a dict mapping cluster_name -> 'healthy' | 'degraded' | 'unknown'.

    Uses a 30-minute lookback to reliably capture data even with ingestion delays.
    Clusters not present in the result are omitted from the returned dict (caller
    should fall back to 'unknown').
    """
    if not _LOGS_QUERY_AVAILABLE:
        return {}
    if not la_workspace_resource_id or not cluster_names:
        return {}

    from datetime import timedelta

    try:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus  # type: ignore[import]
    except ImportError:
        return {}

    try:
        client = LogsQueryClient(credential)
        # Build a case-insensitive cluster name filter for KQL
        cluster_filter = ", ".join(f'"{name}"' for name in cluster_names)
        kql = f"""
KubePodInventory
| where TimeGenerated > ago(2h)
| where Namespace == "kube-system"
| where ClusterName in~ ({cluster_filter})
| summarize
    running_pods = countif(PodStatus == "Running"),
    crash_loop_pods = countif(ContainerStatusReason == "CrashLoopBackOff"),
    pending_pods = countif(PodStatus == "Pending"),
    failed_pods = countif(PodStatus == "Failed")
    by ClusterName
"""
        result = client.query_resource(
            la_workspace_resource_id,
            kql,
            timespan=timedelta(hours=3),
        )

        tables = None
        if result.status == LogsQueryStatus.SUCCESS:
            tables = getattr(result, "tables", None)
        elif result.status == LogsQueryStatus.PARTIAL:
            tables = getattr(result, "partial_data", None)
            logger.warning("system_pod_health_batch: partial result")

        health_map: Dict[str, str] = {}
        if tables:
            table = tables[0]
            cols = [c.name if hasattr(c, "name") else str(c) for c in table.columns]
            for row in table.rows:
                row_dict = dict(zip(cols, row))
                cluster = str(row_dict.get("ClusterName", ""))
                crash_count = int(row_dict.get("crash_loop_pods") or 0)
                failed_count = int(row_dict.get("failed_pods") or 0)
                running_count = int(row_dict.get("running_pods") or 0)
                pending_count = int(row_dict.get("pending_pods") or 0)

                if crash_count > 0 or failed_count > 0:
                    health_map[cluster] = "degraded"
                elif running_count > 0 and pending_count == 0:
                    health_map[cluster] = "healthy"
                elif running_count > 0:
                    # Some pods running but others pending
                    health_map[cluster] = "degraded"
                else:
                    health_map[cluster] = "unknown"

        logger.info("system_pod_health_batch: queried %d clusters, resolved %d", len(cluster_names), len(health_map))
        return health_map
    except Exception as exc:
        logger.warning("system_pod_health_batch: query failed error=%s", exc)
        return {}


def _fetch_single_metric_aks(
    client: Any,
    resource_id: str,
    metric_name: str,
    timespan: str,
    interval: str,
) -> Optional[Dict[str, Any]]:
    """Fetch a single AKS metric from Azure Monitor.

    Returns a parsed metric dict ``{name, unit, timeseries}`` or ``None`` when
    the metric is unsupported or returns no data.  Exceptions are caught
    per-metric so one unsupported metric cannot poison the whole batch.
    """
    try:
        response = client.metrics.list(
            resource_uri=resource_id,
            metricnames=metric_name,
            metricnamespace=AKS_METRIC_NAMESPACE,
            timespan=timespan,
            interval=interval,
            aggregation="Average,Maximum,Minimum",
        )
        for metric in response.value:
            timeseries = []
            for ts in metric.timeseries:
                for dp in ts.data:
                    if dp.time_stamp:
                        timeseries.append({
                            "timestamp": dp.time_stamp.isoformat(),
                            "average": dp.average,
                            "maximum": dp.maximum,
                            "minimum": dp.minimum,
                        })
            name_val = (
                metric.name.value if hasattr(metric.name, "value")
                else str(metric.name) if metric.name else None
            )
            unit_val = (
                metric.unit.value if hasattr(metric.unit, "value")
                else str(metric.unit) if metric.unit else None
            )
            return {"name": name_val, "unit": unit_val, "timeseries": timeseries}
        # response.value was empty — metric unsupported for this resource type
        return None
    except Exception as exc:
        logger.warning("aks_metrics: skipping metric=%r | error=%s", metric_name, exc)
        return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AKSChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None


class AKSChatResponse(BaseModel):
    thread_id: str
    run_id: str
    status: str = "created"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_aks_clusters(
    subscriptions: str = Query(..., description="Comma-separated subscription IDs"),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """List AKS clusters across subscriptions via Azure Resource Graph.

    Returns structured empty response when ARG SDK unavailable.
    """
    start_time = time.monotonic()
    subscription_ids = [s.strip() for s in subscriptions.split(",") if s.strip()]

    if not _ARG_AVAILABLE or not subscription_ids:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_list: sdk_unavailable duration_ms=%.1f", duration_ms)
        return {"clusters": [], "total": 0}

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        credential = DefaultAzureCredential()
        client = ResourceGraphClient(credential)

        kql = """Resources
| where type =~ 'microsoft.containerservice/managedclusters'
| extend agentPools = properties.agentPoolProfiles
| extend total_nodes = toint(coalesce(agentPools[0]['count'], '0'))
    + toint(coalesce(agentPools[1]['count'], '0'))
    + toint(coalesce(agentPools[2]['count'], '0'))
    + toint(coalesce(agentPools[3]['count'], '0'))
    + toint(coalesce(agentPools[4]['count'], '0'))
| project id, name, resourceGroup, subscriptionId, location,
    kubernetes_version = tostring(properties.kubernetesVersion),
    fqdn = tostring(properties.fqdn),
    network_plugin = tostring(properties.networkProfile.networkPlugin),
    rbac_enabled = iff(tobool(properties.enableRBAC) == true, 1, 0),
    node_pool_count = array_length(agentPools),
    node_pools_ready = iff(tostring(properties.provisioningState) =~ 'Succeeded', array_length(agentPools), 0),
    total_nodes,
    active_alert_count = 0,
    omsagent_workspace = tostring(properties.addonProfiles.omsagent.config.logAnalyticsWorkspaceResourceID),
    omsagent_enabled = tobool(properties.addonProfiles.omsagent.enabled)"""

        if search:
            search_safe = search.replace("'", "")
            kql += f"\n| where name contains '{search_safe}'"

        kql += f"\n| limit {limit}"

        request = QueryRequest(subscriptions=subscription_ids, query=kql)
        response = client.resources(request)
        rows = response.data or []

        fallback_workspace = os.environ.get("LOG_ANALYTICS_WORKSPACE_RESOURCE_ID", "")
        clusters = [
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "resource_group": r.get("resourceGroup", ""),
                "subscription_id": r.get("subscriptionId", ""),
                "location": r.get("location", ""),
                "kubernetes_version": r.get("kubernetes_version", ""),
                "latest_available_version": None,
                "node_pool_count": r.get("node_pool_count", 0) or 0,
                "node_pools_ready": r.get("node_pools_ready", 0) or 0,
                "total_nodes": r.get("total_nodes", 0) or 0,   # Summed from agentPoolProfiles via ARG
                "ready_nodes": 0,   # Not available in list view; accurate count available in detail endpoint
                "system_pod_health": "unknown",  # enriched below via Container Insights
                "fqdn": r.get("fqdn") or None,
                "network_plugin": r.get("network_plugin", ""),
                # ARG tobool() returns int 0/1 — normalise to Python bool
                "rbac_enabled": bool(r.get("rbac_enabled", False)),
                "active_alert_count": 0,
                # Per-cluster Container Insights workspace (may be empty string if CI not enabled)
                "_la_workspace": r.get("omsagent_workspace") or fallback_workspace,
            }
            for r in rows
        ]

        # Enrich system_pod_health via batch Container Insights query.
        # Groups clusters by their per-cluster omsagent workspace so that clusters
        # reporting to different workspaces are all handled correctly.
        # Falls back gracefully to 'unknown' if CI is unavailable.
        if clusters and _LOGS_QUERY_AVAILABLE:
            import concurrent.futures
            from collections import defaultdict

            # Group clusters by their Log Analytics workspace resource ID
            workspace_to_clusters: dict = defaultdict(list)
            for c in clusters:
                ws = c["_la_workspace"]
                if ws:
                    workspace_to_clusters[ws].append(c)

            if workspace_to_clusters:
                futures_map = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    for ws, ws_clusters in workspace_to_clusters.items():
                        cluster_names = [c["name"] for c in ws_clusters]
                        f = executor.submit(
                            _fetch_system_pod_health_batch,
                            credential,
                            ws,
                            cluster_names,
                        )
                        futures_map[f] = ws_clusters

                    for future, ws_clusters in futures_map.items():
                        try:
                            health_map = future.result(timeout=10)
                        except Exception as health_exc:
                            logger.warning("aks_list: system_pod_health enrichment failed error=%s", health_exc)
                            health_map = {}

                        for cluster in ws_clusters:
                            health = health_map.get(cluster["name"])
                            if health is not None:
                                cluster["system_pod_health"] = health

        # Strip internal enrichment field before returning
        for c in clusters:
            c.pop("_la_workspace", None)

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_list: total=%d duration_ms=%.1f", len(clusters), duration_ms)
        return {"clusters": clusters, "total": len(clusters)}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_list: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"clusters": [], "total": 0, "fetch_error": str(exc)}


@router.get("/{resource_id_base64}")
async def get_aks_detail(
    resource_id_base64: str,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get AKS cluster detail including node pools and workload summary."""
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    if not _ARG_AVAILABLE:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_detail: sdk_unavailable resource_id=%s duration_ms=%.1f", resource_id[:60], duration_ms)
        return {
            "id": resource_id,
            "name": resource_id.split("/")[-1],
            "resource_group": "",
            "subscription_id": _extract_subscription_id(resource_id),
            "location": "",
            "kubernetes_version": "",
            "latest_available_version": None,
            "node_pool_count": 0,
            "node_pools_ready": 0,
            "total_nodes": 0,
            "ready_nodes": 0,
            "system_pod_health": "unknown",
            "fqdn": None,
            "network_plugin": "",
            "rbac_enabled": False,
            "active_alert_count": 0,
            "node_pools": [],
            "workload_summary": None,
            "active_incidents": [],
        }

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]
        credential = DefaultAzureCredential()
        subscription_id = _extract_subscription_id(resource_id)
        parts = resource_id.split("/")
        rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
        resource_group = parts[rg_index + 1] if rg_index >= 0 else ""
        cluster_name = parts[-1]

        aks_client = ContainerServiceClient(credential, subscription_id)
        cluster = aks_client.managed_clusters.get(resource_group, cluster_name)

        node_pools = []
        total_nodes = 0
        ready_nodes = 0
        pools_ready = 0

        # Use agent_pools.list() for accurate ready_node_count via provisioning_state + power_state
        # Fall back to cluster.agent_pool_profiles if _AKSClient shim is unavailable
        try:
            if _AKSClient is not None:
                pools_iter = aks_client.agent_pools.list(resource_group, cluster_name)
            else:
                raise ImportError("ContainerServiceClient shim unavailable")

            for pool in pools_iter:
                pool_count = pool.count or 0
                total_nodes += pool_count
                # A pool is ready when provisioning succeeded and its nodes are powered on
                power_code = getattr(getattr(pool, "power_state", None), "code", None)
                if pool.provisioning_state == "Succeeded" and power_code == "Running":
                    pool_ready_count = pool_count
                else:
                    pool_ready_count = 0
                ready_nodes += pool_ready_count
                if pool_ready_count > 0:
                    pools_ready += 1
                node_pools.append({
                    "name": pool.name or "",
                    "vm_size": pool.vm_size or "",
                    "node_count": pool_count,
                    "ready_node_count": pool_ready_count,
                    "mode": _enum_value(pool.mode, "User"),
                    "os_type": _enum_value(pool.os_type, "Linux"),
                    "min_count": pool.min_count,
                    "max_count": pool.max_count,
                    "provisioning_state": pool.provisioning_state or "unknown",
                })
        except Exception as pool_exc:
            logger.warning("aks_detail: agent_pools.list failed, falling back to agent_pool_profiles error=%s", pool_exc)
            node_pools = []
            total_nodes = 0
            ready_nodes = 0
            pools_ready = 0
            for pool in (cluster.agent_pool_profiles or []):
                pool_count = pool.count or 0
                total_nodes += pool_count
                ready_nodes += pool_count
                pools_ready += 1
                node_pools.append({
                    "name": pool.name or "",
                    "vm_size": pool.vm_size or "",
                    "node_count": pool_count,
                    "ready_node_count": pool_count,
                    "mode": _enum_value(pool.mode, "User"),
                    "os_type": _enum_value(pool.os_type, "Linux"),
                    "min_count": pool.min_count,
                    "max_count": pool.max_count,
                    "provisioning_state": pool.provisioning_state or "unknown",
                })

        # Read addon profiles to surface monitoring status to the UI
        profiles = cluster.addon_profiles or {}
        omsagent = profiles.get("omsagent")
        azmon = profiles.get("azureMonitorMetrics")
        # Extract the linked LA workspace resource ID from the omsagent config (if present)
        omsagent_config = getattr(omsagent, "config", None) or {}
        la_workspace_resource_id: Optional[str] = (
            omsagent_config.get("logAnalyticsWorkspaceResourceID")
            or os.environ.get("LOG_ANALYTICS_WORKSPACE_RESOURCE_ID", "") or None
        )

        # Fetch the latest available K8s version from the upgrade profile
        latest_available_version: Optional[str] = None
        try:
            upgrade_profile = aks_client.managed_clusters.get_upgrade_profile(resource_group, cluster_name)
            upgrades = (
                upgrade_profile.control_plane_profile.upgrades
                if upgrade_profile.control_plane_profile
                else None
            )
            if upgrades:
                # Pick the highest non-preview version available
                ga_versions = [u.kubernetes_version for u in upgrades if not u.is_preview and u.kubernetes_version]
                if ga_versions:
                    latest_available_version = sorted(ga_versions, reverse=True)[0]
        except Exception as upgrade_exc:
            logger.debug("aks_detail: upgrade profile unavailable error=%s", upgrade_exc)

        # Fetch workload summary from Container Insights (KubePodInventory) if available.
        # Falls back to a node-pool-derived estimate when Container Insights is not
        # enabled or the KQL query fails / times out.
        workload_summary: Optional[Dict[str, Any]] = None
        if la_workspace_resource_id and bool(omsagent and omsagent.enabled):
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _fetch_aks_workload_summary, credential, la_workspace_resource_id, cluster.name or cluster_name
                )
                try:
                    workload_summary = future.result(timeout=15)
                except Exception as ws_exc:
                    logger.warning("aks_detail: workload_summary fetch failed error=%s", ws_exc)

        # Fallback: provide a minimal workload summary derived from node pool
        # info so the Workloads tab always renders cards instead of "no data".
        if workload_summary is None:
            workload_summary = {
                "running_pods": 0,
                "crash_loop_pods": 0,
                "pending_pods": 0,
                "namespace_count": 0,
                "source": "fallback",
            }

        # Derive system_pod_health from kube-system namespace pods specifically.
        # The workload_summary covers ALL namespaces — system pod health must
        # reflect only kube-system pods (coredns, kube-proxy, etc.).
        system_pod_health = "unknown"
        is_fallback = workload_summary.get("source") == "fallback"
        if not is_fallback and la_workspace_resource_id:
            health_map = _fetch_system_pod_health_batch(
                credential, la_workspace_resource_id, [cluster.name or cluster_name]
            )
            system_pod_health = health_map.get(cluster.name or cluster_name, "unknown")
        elif not is_fallback:
            # Container Insights data available but no workspace ID for targeted query;
            # fall back to all-namespace derivation.
            if workload_summary.get("crash_loop_pods", 0) > 0:
                system_pod_health = "degraded"
            elif workload_summary.get("running_pods", 0) > 0:
                system_pod_health = "healthy"

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_detail: resource_id=%s node_pools=%d workload_summary=%s system_pod_health=%s duration_ms=%.1f", resource_id[:60], len(node_pools), workload_summary is not None, system_pod_health, duration_ms)
        return {
            "id": resource_id,
            "name": cluster.name or cluster_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "location": cluster.location or "",
            "kubernetes_version": cluster.kubernetes_version or "",
            "latest_available_version": latest_available_version,
            "node_pool_count": len(node_pools),
            "node_pools_ready": pools_ready,
            "total_nodes": total_nodes,
            "ready_nodes": ready_nodes,
            "system_pod_health": system_pod_health,
            "fqdn": cluster.fqdn,
            "network_plugin": (cluster.network_profile.network_plugin if cluster.network_profile else ""),
            "rbac_enabled": cluster.enable_rbac or False,
            "active_alert_count": 0,
            "container_insights_enabled": bool(omsagent and omsagent.enabled),
            "managed_prometheus_enabled": bool(azmon and azmon.enabled),
            "log_analytics_workspace_resource_id": la_workspace_resource_id,
            "node_pools": node_pools,
            "workload_summary": workload_summary,
            "active_incidents": [],
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_detail: error=%s duration_ms=%.1f", exc, duration_ms)
        return {
            "id": resource_id,
            "name": resource_id.split("/")[-1],
            "resource_group": "",
            "subscription_id": _extract_subscription_id(resource_id),
            "location": "",
            "kubernetes_version": "",
            "latest_available_version": None,
            "node_pool_count": 0,
            "node_pools_ready": 0,
            "total_nodes": 0,
            "ready_nodes": 0,
            "system_pod_health": "unknown",
            "fqdn": None,
            "network_plugin": "",
            "rbac_enabled": False,
            "active_alert_count": 0,
            "node_pools": [],
            "workload_summary": None,
            "active_incidents": [],
            "fetch_error": str(exc),
        }


@router.get("/{resource_id_base64}/workloads")
async def get_aks_workloads(
    resource_id_base64: str,
    status_filter: str = Query(
        "",
        description="Filter pods by status: 'Running', 'CrashLoopBackOff', 'Pending', or '' for all",
    ),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get detailed workload data for an AKS cluster.

    Returns pod lists per status and namespace breakdown.
    Queries KubePodInventory in Log Analytics (Container Insights).

    Returns:
        pods: list of {name, namespace, status, node, controller_name} (max 200)
        namespaces: list of {name, running_pods, crash_loop_pods, pending_pods, total_pods}
        total_pods: aggregate pod count
        source: 'kql' | 'kql_empty' | 'unavailable'
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID", "pods": [], "namespaces": [], "total_pods": 0, "source": "unavailable"}

    if not _LOGS_QUERY_AVAILABLE:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_workloads: logs_unavailable resource_id=%s duration_ms=%.1f", resource_id[:60], duration_ms)
        return {"pods": [], "namespaces": [], "total_pods": 0, "source": "unavailable"}

    from datetime import timedelta

    try:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus  # type: ignore[import]
    except ImportError:
        return {"pods": [], "namespaces": [], "total_pods": 0, "source": "unavailable"}

    # Resolve Log Analytics workspace from the cluster detail endpoint logic —
    # we need the workspace resource ID.  Re-derive it from the cluster's addon profile.
    workspace_resource_id: Optional[str] = None
    cluster_name = resource_id.split("/")[-1]
    subscription_id = _extract_subscription_id(resource_id)
    parts = resource_id.split("/")
    rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
    resource_group = parts[rg_index + 1] if rg_index >= 0 else ""

    if _ARG_AVAILABLE:
        try:
            from azure.identity import DefaultAzureCredential  # type: ignore[import]
            from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]
            credential = DefaultAzureCredential()
            aks_client = ContainerServiceClient(credential, subscription_id)
            cluster = aks_client.managed_clusters.get(resource_group, cluster_name)
            addon = getattr(cluster, "addon_profiles", None) or {}
            oms = addon.get("omsagent") or addon.get("omsAgent")
            if oms and getattr(oms, "enabled", False):
                la_config = getattr(oms, "config", None) or {}
                workspace_resource_id = la_config.get("logAnalyticsWorkspaceResourceID") or la_config.get("logAnalyticsWorkspaceResourceId")
        except Exception as exc:
            logger.warning("aks_workloads: workspace_discovery failed cluster=%s error=%s", cluster_name, exc)

    if not workspace_resource_id:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_workloads: no_workspace cluster=%s duration_ms=%.1f", cluster_name, duration_ms)
        return {"pods": [], "namespaces": [], "total_pods": 0, "source": "unavailable", "reason": "No Log Analytics workspace configured"}

    try:
        credential = DefaultAzureCredential()  # type: ignore[possibly-undefined]
        client = LogsQueryClient(credential)

        # Build status filter clause
        status_clause = ""
        if status_filter == "CrashLoopBackOff":
            status_clause = '| where ContainerStatusReason == "CrashLoopBackOff"'
        elif status_filter in ("Running", "Pending"):
            status_clause = f'| where PodStatus == "{status_filter}"'

        # Query 1: Pod list (max 200 rows, most recent snapshot per pod)
        pod_kql = f"""
KubePodInventory
| where TimeGenerated > ago(2h)
| where ClusterName =~ "{cluster_name}"
{status_clause}
| summarize arg_max(TimeGenerated, *) by PodUid
| project
    Name = PodName,
    Namespace,
    Status = PodStatus,
    StatusReason = ContainerStatusReason,
    Node = Computer,
    ControllerName,
    ControllerKind
| take 200
"""
        # Query 2: Namespace breakdown
        ns_kql = f"""
KubePodInventory
| where TimeGenerated > ago(2h)
| where ClusterName =~ "{cluster_name}"
| summarize arg_max(TimeGenerated, *) by PodUid
| summarize
    running_pods = countif(PodStatus == "Running"),
    crash_loop_pods = countif(ContainerStatusReason == "CrashLoopBackOff"),
    pending_pods = countif(PodStatus == "Pending"),
    total_pods = count()
  by Namespace
| order by total_pods desc
"""

        import asyncio
        loop = asyncio.get_event_loop()

        def _run_pod_query() -> List[Dict[str, Any]]:
            result = client.query_resource(workspace_resource_id, pod_kql, timespan=timedelta(hours=3))
            pods: List[Dict[str, Any]] = []
            tables = None
            if result.status == LogsQueryStatus.SUCCESS:
                tables = getattr(result, "tables", None)
            elif result.status == LogsQueryStatus.PARTIAL:
                tables = getattr(result, "partial_data", None)
            if tables and tables[0].rows:
                table = tables[0]
                cols = [c.name if hasattr(c, "name") else str(c) for c in table.columns]
                for row in table.rows:
                    rd = dict(zip(cols, row))
                    status = str(rd.get("Status") or "")
                    reason = str(rd.get("StatusReason") or "")
                    display_status = reason if reason and reason != "None" else status
                    pods.append({
                        "name": str(rd.get("Name") or ""),
                        "namespace": str(rd.get("Namespace") or ""),
                        "status": display_status,
                        "node": str(rd.get("Node") or "").split(".")[0],  # short hostname
                        "controller_name": str(rd.get("ControllerName") or ""),
                        "controller_kind": str(rd.get("ControllerKind") or ""),
                    })
            return pods

        def _run_ns_query() -> List[Dict[str, Any]]:
            result = client.query_resource(workspace_resource_id, ns_kql, timespan=timedelta(hours=3))
            namespaces: List[Dict[str, Any]] = []
            tables = None
            if result.status == LogsQueryStatus.SUCCESS:
                tables = getattr(result, "tables", None)
            elif result.status == LogsQueryStatus.PARTIAL:
                tables = getattr(result, "partial_data", None)
            if tables and tables[0].rows:
                table = tables[0]
                cols = [c.name if hasattr(c, "name") else str(c) for c in table.columns]
                for row in table.rows:
                    rd = dict(zip(cols, row))
                    namespaces.append({
                        "name": str(rd.get("Namespace") or ""),
                        "running_pods": int(rd.get("running_pods") or 0),
                        "crash_loop_pods": int(rd.get("crash_loop_pods") or 0),
                        "pending_pods": int(rd.get("pending_pods") or 0),
                        "total_pods": int(rd.get("total_pods") or 0),
                    })
            return namespaces

        # Run both queries in thread pool (SDK is sync)
        pods_result, ns_result = await asyncio.gather(
            loop.run_in_executor(None, _run_pod_query),
            loop.run_in_executor(None, _run_ns_query),
        )

        total = sum(n["total_pods"] for n in ns_result)
        source = "kql" if (len(pods_result) > 0 or total > 0) else "kql_empty"
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "aks_workloads: cluster=%s pods=%d namespaces=%d source=%s duration_ms=%.1f",
            cluster_name, len(pods_result), len(ns_result), source, duration_ms,
        )
        return {
            "pods": pods_result,
            "namespaces": ns_result,
            "total_pods": total,
            "source": source,
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning("aks_workloads: query_failed cluster=%s error=%s duration_ms=%.1f", cluster_name, exc, duration_ms)
        return {"pods": [], "namespaces": [], "total_pods": 0, "source": "unavailable", "reason": str(exc)}


@router.get("/{resource_id_base64}/metrics")
async def get_aks_metrics(
    resource_id_base64: str,
    metrics: str = Query(
        ",".join(AKS_DEFAULT_METRICS[:6]),
        description="Comma-separated Azure Monitor metric names",
    ),
    timespan: str = Query("PT24H", description="ISO 8601 duration"),
    interval: str = Query("PT5M", description="ISO 8601 interval"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get Azure Monitor metrics for an AKS cluster.

    Each metric is fetched concurrently.  AKS-specific metrics (node_cpu_usage_percentage,
    node_memory_rss_percentage) will surface as empty timeseries if the cluster does not
    emit them — acceptable graceful degradation.  Falls back to empty metrics list on error.
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"resource_id": "", "timespan": timespan, "interval": interval, "metrics": []}

    subscription_id = _extract_subscription_id(resource_id)
    if not subscription_id:
        return {"resource_id": resource_id, "timespan": timespan, "interval": interval, "metrics": []}

    metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    logger.info(
        "aks_metrics: request | resource=%s metrics=%d timespan=%s",
        resource_id[-60:], len(metric_names), timespan,
    )

    try:
        import asyncio
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]

        credential = DefaultAzureCredential()
        client = MonitorManagementClient(credential, subscription_id)
        loop = asyncio.get_event_loop()

        tasks = [
            loop.run_in_executor(
                None,
                _fetch_single_metric_aks,
                client,
                resource_id,
                name,
                timespan,
                interval,
            )
            for name in metric_names
        ]
        results = await asyncio.gather(*tasks)
        metrics_out = [r for r in results if r is not None]

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "aks_metrics: complete | resource=%s requested=%d returned=%d duration_ms=%.0f",
            resource_id[-60:], len(metric_names), len(metrics_out), duration_ms,
        )
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "interval": interval,
            "metrics": metrics_out,
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "aks_metrics: failed | resource=%s error=%s duration_ms=%.0f",
            resource_id[-60:], exc, duration_ms,
        )
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "interval": interval,
            "metrics": [],
            "fetch_error": str(exc),
        }



@router.get("/{resource_id_base64}/metrics/logs")
async def get_aks_la_metrics(
    resource_id_base64: str,
    timespan: str = Query("PT24H", description="ISO 8601 duration like PT1H, PT6H, PT24H, P7D"),
    interval: str = Query("PT5M", description="ISO 8601 bucket interval"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Query Container Insights (Log Analytics) for AKS node metrics.

    Queries Perf table for:
      - Node CPU utilisation percentage
      - Node memory working set percentage
      - Node disk reads/writes

    Returns MetricSeries-compatible list so the frontend can render sparklines.
    Returns empty metrics with source="log_analytics" if Container Insights is not
    configured or has no data.
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"resource_id": "", "timespan": timespan, "metrics": [], "source": "log_analytics"}

    if not _LOGS_QUERY_AVAILABLE:
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "metrics": [],
            "source": "log_analytics",
            "fetch_error": "azure-monitor-query not installed",
        }

    # Resolve workspace from omsagent config
    subscription_id = _extract_subscription_id(resource_id)
    parts = resource_id.split("/")
    rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
    resource_group = parts[rg_index + 1] if rg_index >= 0 else ""
    cluster_name = parts[-1]

    la_workspace_resource_id: Optional[str] = None
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]
        credential = DefaultAzureCredential()
        aks_client = ContainerServiceClient(credential, subscription_id)
        cluster = aks_client.managed_clusters.get(resource_group, cluster_name)
        profiles = cluster.addon_profiles or {}
        omsagent = profiles.get("omsagent")
        omsagent_config = getattr(omsagent, "config", None) or {}
        la_workspace_resource_id = (
            omsagent_config.get("logAnalyticsWorkspaceResourceID")
            or os.environ.get("LOG_ANALYTICS_WORKSPACE_RESOURCE_ID", "") or None
        )
    except Exception as exc:
        logger.warning("aks_la_metrics: failed to resolve workspace error=%s", exc)

    if not la_workspace_resource_id:
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "metrics": [],
            "source": "log_analytics",
            "fetch_error": "No Log Analytics workspace configured for this cluster",
        }

    # Map ISO 8601 timespan to timedelta
    from datetime import timedelta
    _TIMESPAN_MAP: Dict[str, timedelta] = {
        "PT1H": timedelta(hours=1),
        "PT6H": timedelta(hours=6),
        "PT24H": timedelta(hours=24),
        "P7D": timedelta(days=7),
    }
    td = _TIMESPAN_MAP.get(timespan, timedelta(hours=24))

    # Map ISO 8601 interval to minutes for KQL bin()
    _INTERVAL_MINUTES: Dict[str, int] = {
        "PT1M": 1, "PT5M": 5, "PT15M": 15, "PT30M": 30, "PT1H": 60,
    }
    bin_minutes = _INTERVAL_MINUTES.get(interval, 5)

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]  # noqa: F811
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus  # type: ignore[import]
        credential = DefaultAzureCredential()
        client = LogsQueryClient(credential)

        kql = f"""
Perf
| where TimeGenerated > ago({int(td.total_seconds())}s)
| where ObjectName == "K8SNode"
| where CounterName in ("cpuUsageNanoCores", "memoryWorkingSetBytes", "memoryRssBytes")
| where Computer has "{cluster_name}"
| summarize avg(CounterValue) by bin(TimeGenerated, {bin_minutes}m), Computer, CounterName
| order by TimeGenerated asc
"""
        result = client.query_resource(
            la_workspace_resource_id,
            kql,
            timespan=td,
        )

        metrics_out: List[Dict[str, Any]] = []
        if result.status == LogsQueryStatus.SUCCESS and result.tables:
            table = result.tables[0]
            # azure-monitor-query SDK versions differ: columns may be LogsTableColumn
            # objects (have .name) or plain strings depending on installed version.
            cols = [c.name if hasattr(c, 'name') else str(c) for c in table.columns]

            # Group rows by (Computer, CounterName)
            from collections import defaultdict
            series_map: Dict[tuple, List[Dict]] = defaultdict(list)
            for row in table.rows:
                row_dict = dict(zip(cols, row))
                key = (str(row_dict.get("Computer", "")), str(row_dict.get("CounterName", "")))
                series_map[key].append(row_dict)

            _COUNTER_LABELS = {
                "cpuUsageNanoCores": ("Node CPU (nanocores)", "NanoCores"),
                "memoryWorkingSetBytes": ("Node Memory Working Set", "Bytes"),
                "memoryRssBytes": ("Node Memory RSS", "Bytes"),
            }

            for (computer, counter_name), rows in series_map.items():
                label, unit = _COUNTER_LABELS.get(counter_name, (counter_name, ""))
                timeseries = [
                    {
                        "timestamp": str(r.get("TimeGenerated", "")),
                        "average": float(r.get("avg_CounterValue", 0) or 0),
                        "maximum": None,
                    }
                    for r in sorted(rows, key=lambda r: str(r.get("TimeGenerated", "")))
                ]
                metrics_out.append({
                    "name": f"{label} ({computer.split('/')[-1]})",
                    "unit": unit,
                    "timeseries": timeseries,
                })

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_la_metrics: resource=%s series=%d duration_ms=%.0f", resource_id[-60:], len(metrics_out), duration_ms)
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "metrics": metrics_out,
            "source": "log_analytics",
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_la_metrics: error=%s duration_ms=%.0f", exc, duration_ms)
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "metrics": [],
            "source": "log_analytics",
            "fetch_error": str(exc),
        }


@router.post("/{resource_id_base64}/monitoring")
async def enable_aks_container_insights(
    resource_id_base64: str,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Enable Container Insights on the AKS cluster using the platform's central LAW.

    Reads LOG_ANALYTICS_WORKSPACE_RESOURCE_ID from env.  Returns immediately with
    an error if the env var is not configured.  The actual enablement calls
    begin_create_or_update which may take 2-3 minutes.
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"success": False, "error": "Invalid resource ID"}

    workspace_resource_id = os.environ.get("LOG_ANALYTICS_WORKSPACE_RESOURCE_ID", "")
    if not workspace_resource_id:
        logger.warning("enable_aks_ci: LOG_ANALYTICS_WORKSPACE_RESOURCE_ID not set")
        return {"success": False, "error": "LOG_ANALYTICS_WORKSPACE_RESOURCE_ID not configured"}

    subscription_id = _extract_subscription_id(resource_id)
    parts = resource_id.split("/")
    rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
    resource_group = parts[rg_index + 1] if rg_index >= 0 else ""
    cluster_name = parts[-1]

    try:
        import asyncio
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]
        from azure.mgmt.containerservice.models import ManagedClusterAddonProfile  # type: ignore[import]

        credential = DefaultAzureCredential()
        aks_client = ContainerServiceClient(credential, subscription_id)
        cluster = aks_client.managed_clusters.get(resource_group, cluster_name)

        cluster.addon_profiles = cluster.addon_profiles or {}
        cluster.addon_profiles["omsagent"] = ManagedClusterAddonProfile(
            enabled=True,
            config={"logAnalyticsWorkspaceResourceID": workspace_resource_id},
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: aks_client.managed_clusters.begin_create_or_update(
                resource_group, cluster_name, cluster
            ).result(),
        )

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "enable_aks_ci: enabled cluster=%s workspace=%s duration_ms=%.0f",
            cluster_name, workspace_resource_id, duration_ms,
        )
        return {"success": True, "cluster": cluster_name, "workspace": workspace_resource_id}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("enable_aks_ci: failed cluster=%s error=%s duration_ms=%.0f", cluster_name, exc, duration_ms)
        return {"success": False, "error": str(exc)}


@router.post("/{resource_id_base64}/chat")
async def aks_chat(
    resource_id_base64: str,
    request: AKSChatRequest,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Resource-scoped chat for AKS cluster investigation.

    Routes to the compute agent directly (AKS tools are in the compute agent).
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    try:
        from services.api_gateway.chat import create_chat_thread  # type: ignore[import]

        agent_id = os.environ.get("COMPUTE_AGENT_ID", "")
        if not agent_id:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning("aks_chat: COMPUTE_AGENT_ID not set duration_ms=%.1f", duration_ms)
            return {"error": "COMPUTE_AGENT_ID not configured"}

        context = f"AKS Cluster: {resource_id}\nMessage: {request.message}"
        thread_id, run_id = await create_chat_thread(
            agent_id=agent_id,
            message=context,
            thread_id=request.thread_id,
        )
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_chat: thread_id=%s run_id=%s duration_ms=%.1f", thread_id, run_id, duration_ms)
        return {"thread_id": thread_id, "run_id": run_id, "status": "created"}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_chat: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"error": str(exc)}
