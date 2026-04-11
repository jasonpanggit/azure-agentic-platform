"""AKS cluster inventory and chat endpoints.

GET  /api/v1/aks                           — list AKS clusters in subscriptions via ARG
GET  /api/v1/aks/{resource_id_base64}      — AKS cluster detail including node pools
GET  /api/v1/aks/{resource_id_base64}/metrics  — Azure Monitor metrics for AKS
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


def _log_sdk_availability() -> None:
    logger.info("aks_endpoints: azure-mgmt-resourcegraph available=%s", _ARG_AVAILABLE)


_log_sdk_availability()


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
| project id, name, resourceGroup, subscriptionId, location,
    kubernetes_version = tostring(properties.kubernetesVersion),
    latest_available_version = tostring(properties.currentKubernetesVersion),
    fqdn = tostring(properties.fqdn),
    network_plugin = tostring(properties.networkProfile.networkPlugin),
    rbac_enabled = tobool(properties.enableRBAC),
    node_pool_count = array_length(properties.agentPoolProfiles),
    total_nodes = 0,
    ready_nodes = 0,
    node_pools_ready = 0,
    system_pod_health = 'unknown',
    active_alert_count = 0"""

        if search:
            search_safe = search.replace("'", "")
            kql += f"\n| where name contains '{search_safe}'"

        kql += f"\n| limit {limit}"

        request = QueryRequest(subscriptions=subscription_ids, query=kql)
        response = client.resources(request)
        rows = response.data or []

        clusters = [
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "resource_group": r.get("resourceGroup", ""),
                "subscription_id": r.get("subscriptionId", ""),
                "location": r.get("location", ""),
                "kubernetes_version": r.get("kubernetes_version", ""),
                "latest_available_version": None,  # Simplified — same as current means up to date
                "node_pool_count": r.get("node_pool_count", 0),
                "node_pools_ready": r.get("node_pool_count", 0),
                "total_nodes": 0,
                "ready_nodes": 0,
                "system_pod_health": "unknown",
                "fqdn": r.get("fqdn") or None,
                "network_plugin": r.get("network_plugin", ""),
                "rbac_enabled": r.get("rbac_enabled", False),
                "active_alert_count": 0,
            }
            for r in rows
        ]

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_list: total=%d duration_ms=%.1f", len(clusters), duration_ms)
        return {"clusters": clusters, "total": len(clusters)}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_list: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"clusters": [], "total": 0}


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

        for pool in (cluster.agent_pool_profiles or []):
            pool_count = pool.count or 0
            total_nodes += pool_count
            ready_nodes += pool_count  # ARM does not expose per-pool node health; assumes all nodes ready
            pools_ready += 1
            node_pools.append({
                "name": pool.name or "",
                "vm_size": pool.vm_size or "",
                "node_count": pool_count,
                "ready_node_count": pool_count,
                "mode": str(pool.mode or "User"),
                "os_type": str(pool.os_type or "Linux"),
                "min_count": pool.min_count,
                "max_count": pool.max_count,
                "provisioning_state": pool.provisioning_state or "unknown",
            })

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_detail: resource_id=%s node_pools=%d duration_ms=%.1f", resource_id[:60], len(node_pools), duration_ms)
        return {
            "id": resource_id,
            "name": cluster.name or cluster_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "location": cluster.location or "",
            "kubernetes_version": cluster.kubernetes_version or "",
            "latest_available_version": None,
            "node_pool_count": len(node_pools),
            "node_pools_ready": pools_ready,
            "total_nodes": total_nodes,
            "ready_nodes": ready_nodes,
            "system_pod_health": "unknown",
            "fqdn": cluster.fqdn,
            "network_plugin": (cluster.network_profile.network_plugin if cluster.network_profile else ""),
            "rbac_enabled": cluster.enable_rbac or False,
            "active_alert_count": 0,
            "node_pools": node_pools,
            "workload_summary": None,
            "active_incidents": [],
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_detail: resource_id=%s error=%s duration_ms=%.1f", resource_id[:60], exc, duration_ms)
        return {"error": str(exc)}


@router.get("/{resource_id_base64}/metrics")
async def get_aks_metrics(
    resource_id_base64: str,
    timespan: str = Query("PT24H"),
    interval: str = Query("PT5M"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get Azure Monitor metrics for an AKS cluster."""
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"resource_id": "", "timespan": timespan, "interval": interval, "metrics": []}

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("aks_metrics: resource_id=%s timespan=%s duration_ms=%.1f", resource_id[:60], timespan, duration_ms)
    return {"resource_id": resource_id, "timespan": timespan, "interval": interval, "metrics": []}


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
