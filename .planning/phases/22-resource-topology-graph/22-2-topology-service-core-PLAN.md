---
wave: 2
depends_on: [22-1]
requirements: [TOPO-001, TOPO-002, TOPO-003]
autonomous: true
files_modified:
  - services/api-gateway/arg_helper.py          # new — shared ARG query helper
  - services/api-gateway/topology.py            # new — TopologyClient, BFS, sync task
---

# Plan 22-2: Topology Service Core

Create the core topology service: a shared ARG query helper (consolidating the duplicated `_run_arg_query` from `vm_inventory.py` and `patch_endpoints.py`), a `TopologyDocument` Pydantic model, and a `TopologyClient` class with bootstrap, incremental sync, blast-radius BFS, path query, and snapshot methods. A background asyncio task keeps the graph fresh to within 15 minutes (TOPO-003).

---

<task id="22-2-01">
<title>Create services/api-gateway/arg_helper.py — shared ARG query helper</title>

<read_first>
- `services/api-gateway/vm_inventory.py` lines 40–76 — the `_run_arg_query` implementation to canonicalize
- `services/api-gateway/patch_endpoints.py` lines 28–70 — the duplicate implementation; confirm they are functionally identical before extracting
</read_first>

<action>
Create `services/api-gateway/arg_helper.py` with the following content. This extracts the duplicated `_run_arg_query` into a shared module. The existing callers (`vm_inventory.py`, `patch_endpoints.py`) do NOT need to be updated in this phase — they continue using their local copies. The topology service imports from here directly.

```python
"""Shared Azure Resource Graph query helper.

Extracted from vm_inventory.py and patch_endpoints.py (which contain identical
copies). New modules (topology.py) import from here. Existing modules retain
their local copies until a future cleanup phase.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def run_arg_query(
    credential: Any,
    subscription_ids: List[str],
    kql: str,
) -> List[Dict[str, Any]]:
    """Execute an Azure Resource Graph query with automatic pagination.

    Exhausts all skip_token pages and returns the complete result set.

    Args:
        credential: Azure credential (DefaultAzureCredential or compatible).
        subscription_ids: List of subscription IDs to scope the query.
        kql: KQL query string.

    Returns:
        List of result row dicts from ARG. Empty list if no results.

    Raises:
        Exception: On ARG API failure (caller decides whether to retry or degrade).
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    client = ResourceGraphClient(credential)
    all_rows: List[Dict[str, Any]] = []
    skip_token: Optional[str] = None

    while True:
        options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
        request = QueryRequest(
            subscriptions=subscription_ids,
            query=kql,
            options=options,
        )
        response = client.resources(request)
        all_rows.extend(response.data)

        skip_token = response.skip_token
        if not skip_token:
            break

    logger.debug(
        "arg_helper: query complete | rows=%d subscriptions=%d",
        len(all_rows),
        len(subscription_ids),
    )
    return all_rows
```
</action>

<acceptance_criteria>
```bash
# File exists and is importable
python -c "from services.api_gateway.arg_helper import run_arg_query; print('OK')"

# Function signature is correct
python -c "
import inspect
from services.api_gateway.arg_helper import run_arg_query
sig = inspect.signature(run_arg_query)
params = list(sig.parameters.keys())
assert params == ['credential', 'subscription_ids', 'kql'], f'Wrong params: {params}'
print('signature OK')
"
```
</acceptance_criteria>
</task>

---

<task id="22-2-02">
<title>Create services/api-gateway/topology.py — TopologyDocument, TopologyClient</title>

<read_first>
- `services/api-gateway/arg_helper.py` — the `run_arg_query` function just created (task 22-2-01)
- `services/api-gateway/dependencies.py` — `get_credential`, `get_cosmos_client` patterns; `app.state.credential` and `app.state.cosmos_client` are initialized in lifespan
- `services/api-gateway/models.py` — existing Pydantic BaseModel patterns (field naming, Optional usage, docstrings)
- `services/api-gateway/main.py` lines 169–194 — the lifespan function pattern where `app.state` is set; topology client initialization will be added here in Plan 22-3
- `.planning/phases/22-resource-topology-graph/22-CONTEXT.md` — full document schema, relationship types, BFS design decisions
</read_first>

<action>
Create `services/api-gateway/topology.py` with the full topology service implementation:

```python
"""Resource topology graph service — adjacency-list in Cosmos DB.

Maintains a real-time property graph of all Azure resources and their
relationships. Uses ARG for bulk bootstrap and incremental sync every
15 minutes (TOPO-001, TOPO-003).

Architecture:
- TopologyDocument: Pydantic model for a single graph node
- TopologyClient: manages Cosmos container, bootstrap, sync, and graph queries
- Background task: launched in lifespan, syncs every TOPOLOGY_SYNC_INTERVAL_SECONDS
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from services.api_gateway.arg_helper import run_arg_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOPOLOGY_SYNC_INTERVAL_SECONDS: int = int(
    os.environ.get("TOPOLOGY_SYNC_INTERVAL_SECONDS", "900")  # 15 minutes
)
TOPOLOGY_CONTAINER_NAME: str = os.environ.get("TOPOLOGY_CONTAINER_NAME", "topology")
COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")

# Resource types included in the topology graph. Extend as new resource types
# are added to the platform scope.
_TOPOLOGY_RESOURCE_TYPES = (
    "microsoft.compute/virtualmachines",
    "microsoft.network/networkinterfaces",
    "microsoft.network/virtualnetworks",
    "microsoft.network/subnets",
    "microsoft.network/publicipaddresses",
    "microsoft.network/networksecuritygroups",
    "microsoft.network/loadbalancers",
    "microsoft.compute/disks",
    "microsoft.storage/storageaccounts",
    "microsoft.keyvault/vaults",
    "microsoft.containerservice/managedclusters",
    "microsoft.web/sites",
    "microsoft.sql/servers",
    "microsoft.sql/servers/databases",
    "microsoft.cache/redis",
    "microsoft.eventhub/namespaces",
    "microsoft.servicebus/namespaces",
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TopologyRelationship(BaseModel):
    """A directed edge in the resource graph."""

    target_id: str = Field(..., description="ARM resource ID of the target node")
    rel_type: str = Field(
        ...,
        description=(
            "Relationship type: subnet_of | nic_of | disk_of | vnet_of | "
            "resource_group_member | connected_to | hosted_on | protected_by"
        ),
    )
    direction: str = Field(
        ...,
        description="Edge direction relative to the source node: outbound | inbound",
    )


class TopologyDocument(BaseModel):
    """A single node in the resource property graph (Cosmos DB document).

    The 'id' field doubles as the Cosmos document ID (ARM resource ID, lowercased).
    The 'resource_id' field is the Cosmos partition key — same value as 'id'.
    """

    id: str = Field(..., description="ARM resource ID (lowercased) — Cosmos document ID")
    resource_id: str = Field(..., description="Partition key — same as id")
    resource_type: str = Field(..., description="ARM resource type (lowercased)")
    resource_group: str = Field(..., description="Resource group name (lowercased)")
    subscription_id: str = Field(..., description="Azure subscription ID")
    name: str = Field(..., description="Resource display name")
    tags: Dict[str, str] = Field(default_factory=dict, description="ARM resource tags")
    relationships: List[TopologyRelationship] = Field(
        default_factory=list,
        description="Adjacency list: outbound and inbound edges from/to this node",
    )
    last_synced_at: str = Field(
        ...,
        description="ISO 8601 UTC timestamp of last sync from ARG",
    )


# ---------------------------------------------------------------------------
# Relationship extraction
# ---------------------------------------------------------------------------


def _extract_relationships(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract topology relationships from a raw ARG resource row.

    Parses well-known ARM properties to produce typed edges. Returns a list
    of relationship dicts (not TopologyRelationship objects — kept as plain
    dicts for Cosmos upsert performance).

    Supported relationship types:
    - nic_of: VM → NIC (networkInterfaces[*].id)
    - disk_of: VM → managed disk (storageProfile.osDisk.managedDisk.id + dataDisks)
    - subnet_of: NIC → subnet (ipConfigurations[0].properties.subnet.id)
    - vnet_of: subnet → VNet (derived from subnet resource_id path)
    - resource_group_member: any resource → its resource group pseudo-node
    """
    relationships: List[Dict[str, Any]] = []
    props = row.get("properties") or {}

    resource_type = (row.get("type") or "").lower()

    # VM: NIC relationships
    if resource_type == "microsoft.compute/virtualmachines":
        nics = []
        network_profile = props.get("networkProfile") or {}
        for nic_ref in network_profile.get("networkInterfaces") or []:
            nic_id = (nic_ref.get("id") or "").lower()
            if nic_id:
                nics.append(nic_id)
                relationships.append(
                    {"target_id": nic_id, "rel_type": "nic_of", "direction": "outbound"}
                )

        # VM: OS disk relationship
        storage_profile = props.get("storageProfile") or {}
        os_disk = storage_profile.get("osDisk") or {}
        managed_disk = os_disk.get("managedDisk") or {}
        disk_id = (managed_disk.get("id") or "").lower()
        if disk_id:
            relationships.append(
                {"target_id": disk_id, "rel_type": "disk_of", "direction": "outbound"}
            )

        # VM: data disk relationships
        for data_disk in storage_profile.get("dataDisks") or []:
            dd_managed = data_disk.get("managedDisk") or {}
            dd_id = (dd_managed.get("id") or "").lower()
            if dd_id:
                relationships.append(
                    {"target_id": dd_id, "rel_type": "disk_of", "direction": "outbound"}
                )

    # NIC: subnet relationship
    if resource_type == "microsoft.network/networkinterfaces":
        ip_configs = props.get("ipConfigurations") or []
        for ip_config in ip_configs:
            ip_props = ip_config.get("properties") or {}
            subnet_ref = ip_props.get("subnet") or {}
            subnet_id = (subnet_ref.get("id") or "").lower()
            if subnet_id:
                relationships.append(
                    {
                        "target_id": subnet_id,
                        "rel_type": "subnet_of",
                        "direction": "outbound",
                    }
                )
                break  # primary subnet only

    # Subnet: VNet relationship (derive from resource ID path)
    if resource_type == "microsoft.network/subnets":
        # Subnet ID format:
        # /subscriptions/{sub}/resourceGroups/{rg}/providers/
        #   Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}
        rid = (row.get("id") or "").lower()
        parts = rid.split("/")
        try:
            vnet_idx = parts.index("virtualnetworks")
            vnet_id = "/".join(parts[: vnet_idx + 2])
            relationships.append(
                {"target_id": vnet_id, "rel_type": "vnet_of", "direction": "outbound"}
            )
        except ValueError:
            pass

    # All resources: resource_group_member (lightweight containment edge)
    rg = (row.get("resourceGroup") or "").lower()
    sub_id = row.get("subscriptionId") or ""
    if rg and sub_id:
        rg_pseudo_id = f"/subscriptions/{sub_id}/resourcegroups/{rg}".lower()
        relationships.append(
            {
                "target_id": rg_pseudo_id,
                "rel_type": "resource_group_member",
                "direction": "outbound",
            }
        )

    return relationships


# ---------------------------------------------------------------------------
# ARG KQL queries
# ---------------------------------------------------------------------------

# Bootstrap KQL: fetch all topology-relevant resources with their properties.
# Results are large — pagination is handled by run_arg_query.
_BOOTSTRAP_KQL = """
Resources
| where type in~ ({type_list})
| project
    id         = tolower(id),
    type       = tolower(type),
    resourceGroup,
    subscriptionId,
    name,
    tags,
    properties
""".strip()

# Incremental sync KQL: fetch resources changed in the last N minutes.
# Uses ResourceChanges table to find recently modified resource IDs.
_INCREMENTAL_KQL = """
resourcechanges
| where properties.changeAttributes.timestamp > ago({interval_minutes}m)
| where properties.targetResourceType in~ ({type_list})
| project resource_id = tolower(properties.targetResourceId)
| distinct resource_id
""".strip()


def _build_bootstrap_kql() -> str:
    type_list = ", ".join(f"'{t}'" for t in _TOPOLOGY_RESOURCE_TYPES)
    return _BOOTSTRAP_KQL.format(type_list=type_list)


def _build_incremental_kql(interval_minutes: int = 16) -> str:
    """Build incremental sync KQL covering the last interval_minutes.

    Uses 16 minutes as default (slightly more than the 15-minute sync interval)
    to avoid missing changes at the boundary.
    """
    type_list = ", ".join(f"'{t}'" for t in _TOPOLOGY_RESOURCE_TYPES)
    return _INCREMENTAL_KQL.format(
        interval_minutes=interval_minutes,
        type_list=type_list,
    )


def _build_resource_fetch_kql(resource_ids: List[str]) -> str:
    """Build KQL to fetch specific resources by ID (for incremental refresh)."""
    id_list = ", ".join(f"'{rid}'" for rid in resource_ids)
    return f"""
Resources
| where tolower(id) in~ ({id_list})
| project
    id         = tolower(id),
    type       = tolower(type),
    resourceGroup,
    subscriptionId,
    name,
    tags,
    properties
""".strip()


# ---------------------------------------------------------------------------
# TopologyClient
# ---------------------------------------------------------------------------


class TopologyClient:
    """Manages the resource topology graph in Cosmos DB.

    Lifecycle:
    1. Call bootstrap() once at startup to load all resources via ARG.
    2. A background asyncio task calls sync_incremental() every 15 minutes.
    3. Route handlers call get_blast_radius(), get_path(), get_snapshot()
       to query the live graph.

    Thread safety: Cosmos SDK is not async-native; ARG and Cosmos calls run
    in asyncio executor (thread pool) from async entry points.
    """

    def __init__(self, cosmos_client: Any, credential: Any, subscription_ids: List[str]):
        """Initialise the TopologyClient.

        Args:
            cosmos_client: Initialized azure.cosmos.CosmosClient (from app.state).
            credential: DefaultAzureCredential (from app.state).
            subscription_ids: List of subscription IDs to scope ARG queries.
        """
        self._cosmos = cosmos_client
        self._credential = credential
        self._subscription_ids = subscription_ids
        self._container: Optional[Any] = None

    def get_cosmos_container(self) -> Any:
        """Return the Cosmos container client, initializing on first call."""
        if self._container is None:
            db = self._cosmos.get_database_client(COSMOS_DATABASE)
            self._container = db.get_container_client(TOPOLOGY_CONTAINER_NAME)
        return self._container

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def bootstrap(self) -> Dict[str, int]:
        """Full ARG bootstrap — load all topology resources into Cosmos.

        Fetches all resources matching _TOPOLOGY_RESOURCE_TYPES across all
        configured subscription IDs and upserts each as a TopologyDocument.

        Runs synchronously (designed to be called in run_in_executor).

        Returns:
            Dict with 'upserted' count and 'errors' count.
        """
        logger.info("topology: bootstrap starting | subscriptions=%d", len(self._subscription_ids))
        kql = _build_bootstrap_kql()
        try:
            rows = run_arg_query(self._credential, self._subscription_ids, kql)
        except Exception as exc:
            logger.error("topology: bootstrap ARG query failed | error=%s", exc)
            return {"upserted": 0, "errors": 1}

        upserted = 0
        errors = 0
        container = self.get_cosmos_container()
        now_iso = datetime.now(timezone.utc).isoformat()

        for row in rows:
            try:
                doc = self._row_to_document(row, now_iso)
                container.upsert_item(doc)
                upserted += 1
            except Exception as exc:
                logger.warning(
                    "topology: bootstrap upsert failed | resource=%s error=%s",
                    (row.get("id") or "")[:80],
                    exc,
                )
                errors += 1

        logger.info(
            "topology: bootstrap complete | upserted=%d errors=%d",
            upserted,
            errors,
        )
        return {"upserted": upserted, "errors": errors}

    # ------------------------------------------------------------------
    # Incremental sync
    # ------------------------------------------------------------------

    def sync_incremental(self) -> Dict[str, int]:
        """Incremental sync — refresh resources changed in the last ~16 minutes.

        1. Query resourcechanges ARG table for changed resource IDs.
        2. Fetch current state of those resources from the Resources table.
        3. Upsert each into Cosmos.

        Runs synchronously (designed to be called in run_in_executor).

        Returns:
            Dict with 'changed_ids', 'upserted', and 'errors' counts.
        """
        logger.info("topology: incremental sync starting")
        try:
            changed_rows = run_arg_query(
                self._credential,
                self._subscription_ids,
                _build_incremental_kql(),
            )
        except Exception as exc:
            logger.error("topology: incremental ARG change query failed | error=%s", exc)
            return {"changed_ids": 0, "upserted": 0, "errors": 1}

        changed_ids = [r.get("resource_id") for r in changed_rows if r.get("resource_id")]
        if not changed_ids:
            logger.info("topology: incremental sync — no changes detected")
            return {"changed_ids": 0, "upserted": 0, "errors": 0}

        try:
            resource_rows = run_arg_query(
                self._credential,
                self._subscription_ids,
                _build_resource_fetch_kql(changed_ids),
            )
        except Exception as exc:
            logger.error("topology: incremental resource fetch failed | error=%s", exc)
            return {"changed_ids": len(changed_ids), "upserted": 0, "errors": 1}

        upserted = 0
        errors = 0
        container = self.get_cosmos_container()
        now_iso = datetime.now(timezone.utc).isoformat()

        for row in resource_rows:
            try:
                doc = self._row_to_document(row, now_iso)
                container.upsert_item(doc)
                upserted += 1
            except Exception as exc:
                logger.warning(
                    "topology: incremental upsert failed | resource=%s error=%s",
                    (row.get("id") or "")[:80],
                    exc,
                )
                errors += 1

        logger.info(
            "topology: incremental sync complete | changed=%d upserted=%d errors=%d",
            len(changed_ids),
            upserted,
            errors,
        )
        return {"changed_ids": len(changed_ids), "upserted": upserted, "errors": errors}

    # ------------------------------------------------------------------
    # Graph queries
    # ------------------------------------------------------------------

    def get_blast_radius(
        self, resource_id: str, max_depth: int = 3
    ) -> Dict[str, Any]:
        """BFS from resource_id to find all resources within max_depth hops.

        Loads neighbor adjacency lists from Cosmos on demand (no full graph
        in memory — lazy per-node Cosmos reads during BFS).

        Args:
            resource_id: ARM resource ID of the origin node (case-insensitive).
            max_depth: Maximum BFS hop depth (default 3).

        Returns:
            Dict with:
                resource_id: str — the queried origin
                affected_resources: list[dict] — all reachable nodes (excluding origin)
                    Each dict: {resource_id, resource_type, resource_group,
                                subscription_id, name, hop_count}
                hop_counts: dict[resource_id, hop_count] — distance from origin
                total_affected: int — count of affected_resources
        """
        origin_id = resource_id.lower()
        container = self.get_cosmos_container()

        # BFS state
        visited: Set[str] = {origin_id}
        hop_counts: Dict[str, int] = {origin_id: 0}
        queue: deque = deque([(origin_id, 0)])
        affected_nodes: List[Dict[str, Any]] = []

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            # Fetch the current node's document from Cosmos
            try:
                doc = container.read_item(item=current_id, partition_key=current_id)
            except Exception as exc:
                logger.debug(
                    "topology: bfs read_item miss | node=%s depth=%d error=%s",
                    current_id[:80],
                    depth,
                    exc,
                )
                continue

            relationships = doc.get("relationships") or []
            for rel in relationships:
                neighbor_id = (rel.get("target_id") or "").lower()
                if not neighbor_id or neighbor_id in visited:
                    continue

                visited.add(neighbor_id)
                neighbor_depth = depth + 1
                hop_counts[neighbor_id] = neighbor_depth

                # Fetch neighbor metadata for the response
                try:
                    neighbor_doc = container.read_item(
                        item=neighbor_id, partition_key=neighbor_id
                    )
                    affected_nodes.append(
                        {
                            "resource_id": neighbor_id,
                            "resource_type": neighbor_doc.get("resource_type", ""),
                            "resource_group": neighbor_doc.get("resource_group", ""),
                            "subscription_id": neighbor_doc.get("subscription_id", ""),
                            "name": neighbor_doc.get("name", ""),
                            "hop_count": neighbor_depth,
                        }
                    )
                except Exception:
                    # Node exists in adjacency list but not in Cosmos — include with minimal data
                    affected_nodes.append(
                        {
                            "resource_id": neighbor_id,
                            "resource_type": "unknown",
                            "resource_group": "",
                            "subscription_id": "",
                            "name": neighbor_id.split("/")[-1],
                            "hop_count": neighbor_depth,
                        }
                    )

                if neighbor_depth < max_depth:
                    queue.append((neighbor_id, neighbor_depth))

        return {
            "resource_id": origin_id,
            "affected_resources": affected_nodes,
            "hop_counts": {k: v for k, v in hop_counts.items() if k != origin_id},
            "total_affected": len(affected_nodes),
        }

    def get_path(self, source_id: str, target_id: str) -> Dict[str, Any]:
        """Bidirectional BFS to find the shortest path between two resources.

        Args:
            source_id: ARM resource ID of the source node.
            target_id: ARM resource ID of the target node.

        Returns:
            Dict with:
                source: str
                target: str
                path: list[str] — ordered resource IDs from source to target (inclusive)
                hops: int — number of edges in the path (len(path) - 1)
                found: bool — False if no path exists within search depth
        """
        source = source_id.lower()
        target = target_id.lower()
        container = self.get_cosmos_container()

        if source == target:
            return {"source": source, "target": target, "path": [source], "hops": 0, "found": True}

        # Forward BFS from source; backward BFS from target
        # Each frontier maps node_id → predecessor_id (for path reconstruction)
        forward: Dict[str, Optional[str]] = {source: None}
        backward: Dict[str, Optional[str]] = {target: None}
        forward_queue: deque = deque([source])
        backward_queue: deque = deque([target])

        MAX_DEPTH = 6  # hard cap to keep query time bounded

        def _neighbors(node_id: str) -> List[str]:
            try:
                doc = container.read_item(item=node_id, partition_key=node_id)
                return [
                    (r.get("target_id") or "").lower()
                    for r in (doc.get("relationships") or [])
                    if r.get("target_id")
                ]
            except Exception:
                return []

        def _reconstruct(meeting: str) -> List[str]:
            # Forward path: source → meeting
            fwd_path: List[str] = []
            node: Optional[str] = meeting
            while node is not None:
                fwd_path.append(node)
                node = forward[node]
            fwd_path.reverse()
            # Backward path: meeting → target
            bwd_path: List[str] = []
            node = backward.get(meeting)
            while node is not None:
                bwd_path.append(node)
                node = backward[node]
            return fwd_path + bwd_path

        for _ in range(MAX_DEPTH // 2):
            # Expand forward frontier one level
            next_fwd: List[str] = []
            while forward_queue:
                current = forward_queue.popleft()
                for nb in _neighbors(current):
                    if nb not in forward:
                        forward[nb] = current
                        next_fwd.append(nb)
                    if nb in backward:
                        path = _reconstruct(nb)
                        return {
                            "source": source,
                            "target": target,
                            "path": path,
                            "hops": len(path) - 1,
                            "found": True,
                        }
            for n in next_fwd:
                forward_queue.append(n)

            # Expand backward frontier one level
            next_bwd: List[str] = []
            while backward_queue:
                current = backward_queue.popleft()
                for nb in _neighbors(current):
                    if nb not in backward:
                        backward[nb] = current
                        next_bwd.append(nb)
                    if nb in forward:
                        path = _reconstruct(nb)
                        return {
                            "source": source,
                            "target": target,
                            "path": path,
                            "hops": len(path) - 1,
                            "found": True,
                        }
            for n in next_bwd:
                backward_queue.append(n)

        return {"source": source, "target": target, "path": [], "hops": -1, "found": False}

    def get_snapshot(self, resource_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the full TopologyDocument for a single resource.

        Args:
            resource_id: ARM resource ID (case-insensitive).

        Returns:
            TopologyDocument as a dict, or None if not found.
        """
        rid = resource_id.lower()
        container = self.get_cosmos_container()
        try:
            doc = container.read_item(item=rid, partition_key=rid)
            # Strip Cosmos internal fields before returning
            return {k: v for k, v in doc.items() if not k.startswith("_")}
        except Exception as exc:
            logger.debug("topology: snapshot miss | resource=%s error=%s", rid[:80], exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_document(self, row: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
        """Convert a raw ARG resource row to a Cosmos topology document dict.

        Args:
            row: Raw ARG result row with id, type, resourceGroup, subscriptionId, name, tags, properties.
            now_iso: ISO 8601 UTC timestamp for last_synced_at.

        Returns:
            Dict ready to upsert into the topology container.
        """
        resource_id = (row.get("id") or "").lower()
        relationships = _extract_relationships(row)

        # Parse tags — ARG returns tags as dict or None
        tags = row.get("tags")
        if isinstance(tags, str):
            import json
            try:
                tags = json.loads(tags)
            except (ValueError, TypeError):
                tags = {}
        if not isinstance(tags, dict):
            tags = {}

        return {
            "id": resource_id,
            "resource_id": resource_id,
            "resource_type": (row.get("type") or "").lower(),
            "resource_group": (row.get("resourceGroup") or "").lower(),
            "subscription_id": row.get("subscriptionId") or "",
            "name": row.get("name") or "",
            "tags": tags,
            "relationships": relationships,
            "last_synced_at": now_iso,
        }


# ---------------------------------------------------------------------------
# Background asyncio sync task
# ---------------------------------------------------------------------------


async def run_topology_sync_loop(topology_client: TopologyClient) -> None:
    """Background asyncio task: run incremental sync every TOPOLOGY_SYNC_INTERVAL_SECONDS.

    Launched by the FastAPI lifespan (Plan 22-3). Runs indefinitely until the
    event loop is cancelled (on app shutdown).

    On first call, waits one full interval before syncing (bootstrap already
    ran at startup). Uses run_in_executor to avoid blocking the event loop.
    """
    logger.info(
        "topology: sync loop started | interval=%ds", TOPOLOGY_SYNC_INTERVAL_SECONDS
    )
    while True:
        await asyncio.sleep(TOPOLOGY_SYNC_INTERVAL_SECONDS)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, topology_client.sync_incremental)
            logger.info(
                "topology: sync loop tick | changed=%d upserted=%d errors=%d",
                result.get("changed_ids", 0),
                result.get("upserted", 0),
                result.get("errors", 0),
            )
        except asyncio.CancelledError:
            logger.info("topology: sync loop cancelled — shutting down")
            raise
        except Exception as exc:
            logger.error(
                "topology: sync loop unexpected error | error=%s", exc, exc_info=True
            )
            # Continue loop — transient ARG/Cosmos errors should not stop the background task
```
</action>

<acceptance_criteria>
```bash
# File exists and key classes are importable
python -c "
from services.api_gateway.topology import (
    TopologyDocument, TopologyRelationship, TopologyClient,
    run_topology_sync_loop, _extract_relationships,
    _build_bootstrap_kql, _build_incremental_kql
)
print('imports OK')
"

# TopologyDocument has all required fields
python -c "
from services.api_gateway.topology import TopologyDocument
fields = set(TopologyDocument.model_fields.keys())
required = {'id', 'resource_id', 'resource_type', 'resource_group',
            'subscription_id', 'name', 'tags', 'relationships', 'last_synced_at'}
assert required.issubset(fields), f'Missing fields: {required - fields}'
print('model fields OK')
"

# TopologyClient has all required methods
python -c "
from services.api_gateway.topology import TopologyClient
methods = dir(TopologyClient)
for m in ['bootstrap', 'sync_incremental', 'get_blast_radius', 'get_path', 'get_snapshot', 'get_cosmos_container']:
    assert m in methods, f'Missing method: {m}'
print('methods OK')
"

# Relationship extraction produces expected types for a VM row
python -c "
from services.api_gateway.topology import _extract_relationships
row = {
    'id': '/subscriptions/abc/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1',
    'type': 'microsoft.compute/virtualmachines',
    'resourceGroup': 'rg',
    'subscriptionId': 'abc',
    'properties': {
        'networkProfile': {'networkInterfaces': [{'id': '/subscriptions/abc/resourcegroups/rg/providers/microsoft.network/networkinterfaces/nic1'}]},
        'storageProfile': {'osDisk': {'managedDisk': {'id': '/subscriptions/abc/resourcegroups/rg/providers/microsoft.compute/disks/disk1'}}, 'dataDisks': []}
    }
}
rels = _extract_relationships(row)
rel_types = {r['rel_type'] for r in rels}
assert 'nic_of' in rel_types, 'missing nic_of'
assert 'disk_of' in rel_types, 'missing disk_of'
assert 'resource_group_member' in rel_types, 'missing resource_group_member'
print('extraction OK')
"
```
</acceptance_criteria>
</task>

---

<task id="22-2-03">
<title>Unit tests for topology service core</title>

<read_first>
- `services/api-gateway/tests/test_patch_endpoints.py` — test pattern for mocking ARG calls and Cosmos interactions
- `services/api-gateway/tests/conftest.py` — shared fixtures; check if there's a mock_cosmos_client fixture to reuse
- `services/api-gateway/topology.py` — the implementation just created
</read_first>

<action>
Create `services/api-gateway/tests/test_topology_service.py`:

```python
"""Unit tests for topology service core (topology.py).

Tests cover:
- _extract_relationships: VM/NIC/subnet/VNet/resource-group relationship extraction
- TopologyDocument: Pydantic model validation
- TopologyClient.get_blast_radius: BFS with mock Cosmos reads
- TopologyClient.get_path: bidirectional BFS path finding
- TopologyClient.get_snapshot: single document read
- TopologyClient._row_to_document: ARG row → Cosmos document conversion
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.topology import (
    TopologyClient,
    TopologyDocument,
    TopologyRelationship,
    _build_bootstrap_kql,
    _build_incremental_kql,
    _extract_relationships,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vm_row(vm_id: str = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1") -> Dict[str, Any]:
    return {
        "id": vm_id.lower(),
        "type": "microsoft.compute/virtualmachines",
        "resourceGroup": "rg1",
        "subscriptionId": "s1",
        "name": "vm1",
        "tags": {"env": "prod"},
        "properties": {
            "networkProfile": {
                "networkInterfaces": [
                    {"id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"}
                ]
            },
            "storageProfile": {
                "osDisk": {
                    "managedDisk": {
                        "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/disks/osdisk1"
                    }
                },
                "dataDisks": [
                    {
                        "managedDisk": {
                            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/disks/datadisk1"
                        }
                    }
                ],
            },
        },
    }


def _make_nic_row() -> Dict[str, Any]:
    return {
        "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1",
        "type": "microsoft.network/networkinterfaces",
        "resourceGroup": "rg1",
        "subscriptionId": "s1",
        "name": "nic1",
        "tags": {},
        "properties": {
            "ipConfigurations": [
                {
                    "properties": {
                        "subnet": {
                            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1/subnets/default"
                        }
                    }
                }
            ]
        },
    }


def _make_subnet_row() -> Dict[str, Any]:
    return {
        "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1/subnets/default",
        "type": "microsoft.network/subnets",
        "resourceGroup": "rg1",
        "subscriptionId": "s1",
        "name": "default",
        "tags": {},
        "properties": {},
    }


def _make_topology_client() -> TopologyClient:
    cosmos_mock = MagicMock()
    credential_mock = MagicMock()
    return TopologyClient(
        cosmos_client=cosmos_mock,
        credential=credential_mock,
        subscription_ids=["s1"],
    )


# ---------------------------------------------------------------------------
# _extract_relationships tests
# ---------------------------------------------------------------------------


class TestExtractRelationships:
    def test_vm_nic_relationship(self):
        row = _make_vm_row()
        rels = _extract_relationships(row)
        nic_rels = [r for r in rels if r["rel_type"] == "nic_of"]
        assert len(nic_rels) == 1
        assert "nic1" in nic_rels[0]["target_id"]
        assert nic_rels[0]["direction"] == "outbound"

    def test_vm_os_disk_relationship(self):
        row = _make_vm_row()
        rels = _extract_relationships(row)
        disk_rels = [r for r in rels if r["rel_type"] == "disk_of"]
        assert any("osdisk1" in r["target_id"] for r in disk_rels)

    def test_vm_data_disk_relationship(self):
        row = _make_vm_row()
        rels = _extract_relationships(row)
        disk_rels = [r for r in rels if r["rel_type"] == "disk_of"]
        assert any("datadisk1" in r["target_id"] for r in disk_rels)

    def test_vm_resource_group_member(self):
        row = _make_vm_row()
        rels = _extract_relationships(row)
        rg_rels = [r for r in rels if r["rel_type"] == "resource_group_member"]
        assert len(rg_rels) == 1
        assert "rg1" in rg_rels[0]["target_id"]

    def test_nic_subnet_relationship(self):
        row = _make_nic_row()
        rels = _extract_relationships(row)
        subnet_rels = [r for r in rels if r["rel_type"] == "subnet_of"]
        assert len(subnet_rels) == 1
        assert "default" in subnet_rels[0]["target_id"]

    def test_subnet_vnet_relationship(self):
        row = _make_subnet_row()
        rels = _extract_relationships(row)
        vnet_rels = [r for r in rels if r["rel_type"] == "vnet_of"]
        assert len(vnet_rels) == 1
        assert "vnet1" in vnet_rels[0]["target_id"]

    def test_empty_properties_no_crash(self):
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm2",
            "type": "microsoft.compute/virtualmachines",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "vm2",
            "tags": {},
            "properties": {},
        }
        rels = _extract_relationships(row)
        # Should still produce resource_group_member
        assert any(r["rel_type"] == "resource_group_member" for r in rels)

    def test_missing_properties_no_crash(self):
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.storage/storageaccounts/sa1",
            "type": "microsoft.storage/storageaccounts",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "sa1",
            "tags": {},
        }
        rels = _extract_relationships(row)
        assert isinstance(rels, list)


# ---------------------------------------------------------------------------
# TopologyDocument model tests
# ---------------------------------------------------------------------------


class TestTopologyDocument:
    def test_valid_document(self):
        doc = TopologyDocument(
            id="/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
            resource_id="/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
            resource_type="microsoft.compute/virtualmachines",
            resource_group="rg1",
            subscription_id="s1",
            name="vm1",
            tags={"env": "prod"},
            relationships=[
                TopologyRelationship(
                    target_id="/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1",
                    rel_type="nic_of",
                    direction="outbound",
                )
            ],
            last_synced_at="2026-04-03T10:00:00+00:00",
        )
        assert doc.resource_type == "microsoft.compute/virtualmachines"
        assert len(doc.relationships) == 1

    def test_empty_relationships_default(self):
        doc = TopologyDocument(
            id="test-id",
            resource_id="test-id",
            resource_type="microsoft.compute/virtualmachines",
            resource_group="rg",
            subscription_id="s1",
            name="vm1",
            last_synced_at="2026-04-03T10:00:00+00:00",
        )
        assert doc.relationships == []
        assert doc.tags == {}


# ---------------------------------------------------------------------------
# TopologyClient._row_to_document tests
# ---------------------------------------------------------------------------


class TestRowToDocument:
    def test_vm_row_conversion(self):
        client = _make_topology_client()
        row = _make_vm_row()
        doc = client._row_to_document(row, "2026-04-03T10:00:00+00:00")
        assert doc["id"] == row["id"].lower()
        assert doc["resource_id"] == doc["id"]
        assert doc["resource_type"] == "microsoft.compute/virtualmachines"
        assert doc["resource_group"] == "rg1"
        assert doc["subscription_id"] == "s1"
        assert doc["name"] == "vm1"
        assert doc["last_synced_at"] == "2026-04-03T10:00:00+00:00"
        assert isinstance(doc["relationships"], list)
        assert len(doc["relationships"]) > 0

    def test_tags_string_parsed_as_json(self):
        """Tags returned as JSON string from ARG should be parsed to dict."""
        import json
        client = _make_topology_client()
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.storage/storageaccounts/sa1",
            "type": "microsoft.storage/storageaccounts",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "sa1",
            "tags": json.dumps({"env": "prod", "team": "ops"}),
            "properties": {},
        }
        doc = client._row_to_document(row, "2026-04-03T10:00:00+00:00")
        assert doc["tags"] == {"env": "prod", "team": "ops"}

    def test_tags_none_becomes_empty_dict(self):
        client = _make_topology_client()
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.storage/storageaccounts/sa1",
            "type": "microsoft.storage/storageaccounts",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "sa1",
            "tags": None,
            "properties": {},
        }
        doc = client._row_to_document(row, "2026-04-03T10:00:00+00:00")
        assert doc["tags"] == {}


# ---------------------------------------------------------------------------
# TopologyClient.get_snapshot tests
# ---------------------------------------------------------------------------


class TestGetSnapshot:
    def test_returns_document_on_hit(self):
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_doc = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
            "resource_id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
            "resource_type": "microsoft.compute/virtualmachines",
            "resource_group": "rg1",
            "subscription_id": "s1",
            "name": "vm1",
            "tags": {},
            "relationships": [],
            "last_synced_at": "2026-04-03T10:00:00+00:00",
            "_rid": "cosmos-internal",
        }
        mock_container.read_item.return_value = mock_doc
        client._container = mock_container

        result = client.get_snapshot("/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1")
        assert result is not None
        assert "_rid" not in result
        assert result["name"] == "vm1"

    def test_returns_none_on_miss(self):
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_container.read_item.side_effect = Exception("NotFound")
        client._container = mock_container

        result = client.get_snapshot("/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/missing")
        assert result is None


# ---------------------------------------------------------------------------
# TopologyClient.get_blast_radius tests
# ---------------------------------------------------------------------------


class TestGetBlastRadius:
    def _make_doc(self, rid: str, neighbors: list[str]) -> Dict[str, Any]:
        return {
            "id": rid,
            "resource_id": rid,
            "resource_type": "microsoft.compute/virtualmachines",
            "resource_group": "rg1",
            "subscription_id": "s1",
            "name": rid.split("/")[-1],
            "tags": {},
            "relationships": [
                {"target_id": n, "rel_type": "nic_of", "direction": "outbound"}
                for n in neighbors
            ],
            "last_synced_at": "2026-04-03T10:00:00+00:00",
        }

    def test_blast_radius_single_hop(self):
        """Origin → NIC1 (1 hop)."""
        client = _make_topology_client()
        mock_container = MagicMock()

        origin = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"
        nic = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"

        docs = {
            origin: self._make_doc(origin, [nic]),
            nic: self._make_doc(nic, []),
        }

        def read_item(item, partition_key):
            rid = item.lower()
            if rid in docs:
                return docs[rid]
            raise Exception(f"NotFound: {rid}")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        result = client.get_blast_radius(origin, max_depth=3)
        assert result["resource_id"] == origin
        assert result["total_affected"] == 1
        affected_ids = [r["resource_id"] for r in result["affected_resources"]]
        assert nic in affected_ids

    def test_blast_radius_respects_max_depth(self):
        """With max_depth=1, should not traverse beyond direct neighbors."""
        client = _make_topology_client()
        mock_container = MagicMock()

        origin = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"
        nic = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"
        subnet = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1/subnets/default"

        docs = {
            origin: self._make_doc(origin, [nic]),
            nic: self._make_doc(nic, [subnet]),
            subnet: self._make_doc(subnet, []),
        }

        def read_item(item, partition_key):
            rid = item.lower()
            if rid in docs:
                return docs[rid]
            raise Exception("NotFound")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        result = client.get_blast_radius(origin, max_depth=1)
        affected_ids = [r["resource_id"] for r in result["affected_resources"]]
        assert nic in affected_ids
        assert subnet not in affected_ids

    def test_blast_radius_origin_not_found(self):
        """Returns empty result when origin node is not in Cosmos."""
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_container.read_item.side_effect = Exception("NotFound")
        client._container = mock_container

        result = client.get_blast_radius("/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/missing")
        assert result["total_affected"] == 0
        assert result["affected_resources"] == []


# ---------------------------------------------------------------------------
# TopologyClient.get_path tests
# ---------------------------------------------------------------------------


class TestGetPath:
    def test_path_same_node(self):
        client = _make_topology_client()
        result = client.get_path("resource-a", "resource-a")
        assert result["found"] is True
        assert result["hops"] == 0
        assert result["path"] == ["resource-a"]

    def test_path_direct_neighbor(self):
        client = _make_topology_client()
        mock_container = MagicMock()

        source = "node-a"
        target = "node-b"

        def read_item(item, partition_key):
            if item == "node-a":
                return {"relationships": [{"target_id": "node-b"}]}
            if item == "node-b":
                return {"relationships": []}
            raise Exception("NotFound")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        result = client.get_path(source, target)
        assert result["found"] is True
        assert result["hops"] == 1

    def test_path_not_found(self):
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_container.read_item.side_effect = Exception("NotFound")
        client._container = mock_container

        result = client.get_path("isolated-a", "isolated-b")
        assert result["found"] is False
        assert result["hops"] == -1


# ---------------------------------------------------------------------------
# KQL builder tests
# ---------------------------------------------------------------------------


class TestKQLBuilders:
    def test_bootstrap_kql_contains_resource_types(self):
        kql = _build_bootstrap_kql()
        assert "microsoft.compute/virtualmachines" in kql
        assert "microsoft.network/networkinterfaces" in kql
        assert "microsoft.storage/storageaccounts" in kql

    def test_incremental_kql_contains_interval(self):
        kql = _build_incremental_kql(interval_minutes=20)
        assert "ago(20m)" in kql

    def test_bootstrap_kql_projects_required_fields(self):
        kql = _build_bootstrap_kql()
        for field in ["id", "type", "resourceGroup", "subscriptionId", "name", "tags", "properties"]:
            assert field in kql
```
</action>

<acceptance_criteria>
```bash
# Tests pass (mocked — no real Azure dependencies)
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_topology_service.py -v 2>&1 | tail -20

# All test classes present
grep -c 'class Test' services/api-gateway/tests/test_topology_service.py | awk '$1 >= 7 {print "test classes OK"}'
```
</acceptance_criteria>
</task>

---

## must_haves

- [ ] `services/api-gateway/arg_helper.py` created with `run_arg_query(credential, subscription_ids, kql)` — exhaust pagination, debug-log row count
- [ ] `services/api-gateway/topology.py` created with `TopologyDocument`, `TopologyRelationship`, `TopologyClient`, `run_topology_sync_loop`
- [ ] `TopologyClient.bootstrap()` runs synchronously, upserts all resources, returns `{upserted, errors}` dict
- [ ] `TopologyClient.sync_incremental()` uses `resourcechanges` ARG table, then fetches changed resource rows, upserts only changed nodes
- [ ] `TopologyClient.get_blast_radius(resource_id, max_depth=3)` uses iterative BFS (no recursion), reads adjacency from Cosmos per-node, returns `{resource_id, affected_resources, hop_counts, total_affected}`
- [ ] `TopologyClient.get_path(source, target)` uses bidirectional BFS, hard-caps at depth 6, returns `{source, target, path, hops, found}`
- [ ] `TopologyClient.get_snapshot(resource_id)` returns full topology doc with Cosmos internal fields (`_*`) stripped, or `None` on miss
- [ ] `_extract_relationships` handles VM (NIC, OS disk, data disks), NIC (subnet), subnet (VNet), and all resources (resource_group_member); no crash on missing/None `properties`
- [ ] `run_topology_sync_loop` is `async`, sleeps `TOPOLOGY_SYNC_INTERVAL_SECONDS` between syncs, handles `CancelledError` cleanly for graceful shutdown
- [ ] No `networkx` or other external graph library dependency added
- [ ] `services/api-gateway/tests/test_topology_service.py` created with ≥20 unit tests covering all major code paths; all tests pass with mocked Cosmos/ARG
