from __future__ import annotations
"""AKS Cluster Health Dashboard service (Phase 83).

Scans all AKS clusters via Azure Resource Graph, classifies health,
persists to Cosmos DB (container: aks_health, TTL 1h), and returns
structured summary data.

Never raises — all exceptions are caught and logged.
"""

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum supported Kubernetes version. Clusters below this are flagged outdated.
MINIMUM_K8S_VERSION: str = "1.28"
LATEST_STABLE_K8S: str = "1.28"  # reference floor; flagged if below this

# ---------------------------------------------------------------------------
# Lazy SDK imports
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions  # type: ignore[import]
    _ARG_AVAILABLE = True
except Exception as _e:  # noqa: BLE001
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    QueryRequestOptions = None  # type: ignore[assignment,misc]
    _ARG_AVAILABLE = False
    logger.warning("azure-mgmt-resourcegraph unavailable — AKS health scan disabled: %s", _e)


def _log_sdk_availability() -> None:
    logger.info("aks_health_service: resourcegraph_available=%s", _ARG_AVAILABLE)


_log_sdk_availability()

# ---------------------------------------------------------------------------
# KQL queries
# ---------------------------------------------------------------------------

_CLUSTERS_KQL = """
Resources
| where type =~ 'microsoft.containerservice/managedclusters'
| project
    arm_id = tolower(id),
    cluster_name = name,
    resource_group = resourceGroup,
    subscription_id = subscriptionId,
    location,
    kubernetes_version = tostring(properties.kubernetesVersion),
    power_state = tostring(properties.powerState.code),
    provisioning_state = tostring(properties.provisioningState),
    node_resource_group = tostring(properties.nodeResourceGroup),
    agent_pool_profiles = properties.agentPoolProfiles,
    network_profile = properties.networkProfile,
    fqdn = tostring(properties.fqdn),
    private_cluster = tobool(properties.apiServerAccessProfile.enablePrivateCluster),
    enable_rbac = tobool(properties.enableRBAC),
    tags
| order by cluster_name asc
"""

_NODE_POOLS_KQL = """
Resources
| where type =~ 'microsoft.containerservice/managedclusters/agentpools'
| project
    pool_id = tolower(id),
    pool_name = name,
    cluster_arm = tolower(tostring(split(id, '/agentPools/')[0])),
    subscription_id = subscriptionId,
    resource_group = resourceGroup,
    mode = tostring(properties.mode),
    vm_size = tostring(properties.vmSize),
    count = toint(properties.count),
    min_count = toint(properties.minCount),
    max_count = toint(properties.maxCount),
    enable_autoscaling = tobool(properties.enableAutoScaling),
    os_type = tostring(properties.osType),
    provisioning_state = tostring(properties.provisioningState),
    kubernetes_version = tostring(properties.currentOrchestratorVersion)
"""

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AKSCluster:
    cluster_id: str          # uuid5(NAMESPACE_URL, arm_id)
    arm_id: str
    cluster_name: str
    resource_group: str
    subscription_id: str
    location: str
    kubernetes_version: str
    power_state: str         # Running / Stopped
    provisioning_state: str
    node_count: int          # sum across all agent pools
    node_pools: List[Dict[str, Any]]  # [{name, count, vm_size, mode, autoscaling, state}]
    private_cluster: bool
    enable_rbac: bool
    fqdn: str
    health_status: str       # healthy / degraded / stopped / provisioning
    health_reasons: List[str]
    scanned_at: str
    ttl: int = 3600          # 1h


@dataclass
class AKSHealthSummary:
    total_clusters: int
    healthy: int
    degraded: int
    stopped: int
    total_nodes: int
    clusters_without_rbac: int
    clusters_without_private_api: int
    outdated_version_count: int


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _stable_id(arm_id: str) -> str:
    """Derive a stable UUID from the ARM resource ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, arm_id.lower()))


def _compare_k8s_version(version: str, minimum: str) -> bool:
    """Return True if version >= minimum (semver-like major.minor comparison)."""
    try:
        v_parts = [int(x) for x in version.split(".")[:2]]
        m_parts = [int(x) for x in minimum.split(".")[:2]]
        return v_parts >= m_parts
    except (ValueError, AttributeError):
        return True  # Unknown version — don't flag it


def _classify_health(
    power_state: str,
    provisioning_state: str,
    node_pools: List[Dict[str, Any]],
    enable_rbac: bool,
    kubernetes_version: str,
) -> tuple[str, List[str]]:
    """Classify cluster health and return (status, reasons)."""
    reasons: List[str] = []

    if power_state.lower() == "stopped":
        return "stopped", ["Cluster is stopped"]

    if provisioning_state in ("Creating", "Updating", "Deleting"):
        return "provisioning", [f"Cluster provisioning_state={provisioning_state}"]

    # Check node pools
    pool_issues = [
        p["name"]
        for p in node_pools
        if p.get("provisioning_state", "Succeeded") != "Succeeded"
    ]
    if pool_issues:
        reasons.append(f"Node pools not ready: {', '.join(pool_issues)}")

    total_nodes = sum(p.get("count", 0) for p in node_pools)
    if total_nodes == 0:
        reasons.append("No nodes provisioned")

    if not enable_rbac:
        reasons.append("RBAC not enabled")

    if not _compare_k8s_version(kubernetes_version, MINIMUM_K8S_VERSION):
        reasons.append(f"Kubernetes version {kubernetes_version} below minimum {MINIMUM_K8S_VERSION}")

    if reasons:
        return "degraded", reasons

    return "healthy", []


# ---------------------------------------------------------------------------
# Core scan function
# ---------------------------------------------------------------------------


def scan_aks_clusters(
    credential: Any,
    subscription_ids: List[str],
) -> List[AKSCluster]:
    """Scan AKS clusters via ARG and return classified health objects.

    Never raises.
    """
    start_time = time.monotonic()

    if not _ARG_AVAILABLE:
        logger.warning("aks_health_service.scan: ARG SDK unavailable — returning empty")
        return []

    if not subscription_ids:
        logger.info("aks_health_service.scan: no subscription_ids provided")
        return []

    try:
        client = ResourceGraphClient(credential)

        # --- Fetch clusters ---
        cluster_rows: List[Dict[str, Any]] = []
        skip_token: Optional[str] = None
        while True:
            options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
            req = QueryRequest(subscriptions=subscription_ids, query=_CLUSTERS_KQL, options=options)
            resp = client.resources(req)
            cluster_rows.extend(resp.data or [])
            skip_token = resp.skip_token
            if not skip_token:
                break

        # --- Fetch node pools ---
        pool_rows: List[Dict[str, Any]] = []
        skip_token = None
        while True:
            options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
            req = QueryRequest(subscriptions=subscription_ids, query=_NODE_POOLS_KQL, options=options)
            resp = client.resources(req)
            pool_rows.extend(resp.data or [])
            skip_token = resp.skip_token
            if not skip_token:
                break

        # Build pool map: cluster_arm -> [pool dicts]
        pool_map: Dict[str, List[Dict[str, Any]]] = {}
        for pool in pool_rows:
            cluster_arm = str(pool.get("cluster_arm", "")).lower()
            pool_map.setdefault(cluster_arm, []).append({
                "name": str(pool.get("pool_name", "")),
                "count": int(pool.get("count") or 0),
                "vm_size": str(pool.get("vm_size", "")),
                "mode": str(pool.get("mode", "User")),
                "autoscaling": bool(pool.get("enable_autoscaling", False)),
                "state": str(pool.get("provisioning_state", "Unknown")),
                "os_type": str(pool.get("os_type", "Linux")),
                "min_count": pool.get("min_count"),
                "max_count": pool.get("max_count"),
                "provisioning_state": str(pool.get("provisioning_state", "Unknown")),
                "kubernetes_version": str(pool.get("kubernetes_version", "")),
            })

        scanned_at = datetime.now(tz=timezone.utc).isoformat()
        clusters: List[AKSCluster] = []

        for row in cluster_rows:
            arm_id = str(row.get("arm_id", "")).lower()
            node_pools = pool_map.get(arm_id, [])
            node_count = sum(p["count"] for p in node_pools)

            kubernetes_version = str(row.get("kubernetes_version", ""))
            power_state = str(row.get("power_state", "Running"))
            provisioning_state = str(row.get("provisioning_state", "Succeeded"))
            enable_rbac = bool(row.get("enable_rbac", False))

            health_status, health_reasons = _classify_health(
                power_state,
                provisioning_state,
                node_pools,
                enable_rbac,
                kubernetes_version,
            )

            clusters.append(AKSCluster(
                cluster_id=_stable_id(arm_id),
                arm_id=arm_id,
                cluster_name=str(row.get("cluster_name", "")),
                resource_group=str(row.get("resource_group", "")),
                subscription_id=str(row.get("subscription_id", "")),
                location=str(row.get("location", "")),
                kubernetes_version=kubernetes_version,
                power_state=power_state,
                provisioning_state=provisioning_state,
                node_count=node_count,
                node_pools=node_pools,
                private_cluster=bool(row.get("private_cluster", False)),
                enable_rbac=enable_rbac,
                fqdn=str(row.get("fqdn", "") or ""),
                health_status=health_status,
                health_reasons=health_reasons,
                scanned_at=scanned_at,
            ))

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "aks_health_service.scan: clusters=%d duration_ms=%.1f",
            len(clusters), duration_ms,
        )
        return clusters

    except Exception as exc:  # noqa: BLE001
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_health_service.scan: error=%s duration_ms=%.1f", exc, duration_ms)
        return []


# ---------------------------------------------------------------------------
# Cosmos DB persistence
# ---------------------------------------------------------------------------


def persist_aks_data(
    cosmos_client: Any,
    db_name: str,
    clusters: List[AKSCluster],
) -> None:
    """Upsert AKS cluster records into Cosmos DB. Never raises."""
    if not clusters:
        return

    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("aks_health")
        for cluster in clusters:
            doc = asdict(cluster)
            doc["id"] = cluster.cluster_id
            # Cosmos DB partition key
            doc["subscription_id"] = cluster.subscription_id
            container.upsert_item(doc)
        logger.info("aks_health_service.persist: upserted %d clusters", len(clusters))
    except Exception as exc:  # noqa: BLE001
        logger.error("aks_health_service.persist: error=%s", exc)


# ---------------------------------------------------------------------------
# Cosmos DB reads
# ---------------------------------------------------------------------------


def get_aks_clusters(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    health_status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query AKS cluster records from Cosmos DB. Never raises."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("aks_health")
        conditions: List[str] = []
        parameters: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = [f"@sub{i}" for i in range(len(subscription_ids))]
            conditions.append(f"c.subscription_id IN ({', '.join(placeholders)})")
            for i, sid in enumerate(subscription_ids):
                parameters.append({"name": f"@sub{i}", "value": sid})

        if health_status:
            conditions.append("c.health_status = @health_status")
            parameters.append({"name": "@health_status", "value": health_status})

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM c {where_clause} ORDER BY c.cluster_name ASC"

        items = list(container.query_items(
            query=query,
            parameters=parameters if parameters else None,
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("aks_health_service.get_clusters: error=%s", exc)
        return []


def get_aks_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Compute AKS health summary from Cosmos DB records. Never raises."""
    try:
        clusters = get_aks_clusters(cosmos_client, db_name)
        total = len(clusters)
        healthy = sum(1 for c in clusters if c.get("health_status") == "healthy")
        degraded = sum(1 for c in clusters if c.get("health_status") == "degraded")
        stopped = sum(1 for c in clusters if c.get("health_status") == "stopped")
        total_nodes = sum(int(c.get("node_count", 0)) for c in clusters)
        without_rbac = sum(1 for c in clusters if not c.get("enable_rbac", True))
        without_private = sum(1 for c in clusters if not c.get("private_cluster", True))
        outdated = sum(
            1 for c in clusters
            if not _compare_k8s_version(str(c.get("kubernetes_version", "1.99")), MINIMUM_K8S_VERSION)
        )
        return {
            "total_clusters": total,
            "healthy": healthy,
            "degraded": degraded,
            "stopped": stopped,
            "total_nodes": total_nodes,
            "clusters_without_rbac": without_rbac,
            "clusters_without_private_api": without_private,
            "outdated_version_count": outdated,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("aks_health_service.get_summary: error=%s", exc)
        return {
            "total_clusters": 0,
            "healthy": 0,
            "degraded": 0,
            "stopped": 0,
            "total_nodes": 0,
            "clusters_without_rbac": 0,
            "clusters_without_private_api": 0,
            "outdated_version_count": 0,
        }
