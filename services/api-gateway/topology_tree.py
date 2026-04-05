"""Topology tree endpoint — hierarchical subscription → RG → resource view via ARG.

GET /api/v1/topology/tree
  ?subscriptions=sub1,sub2   (optional, comma-separated; all accessible if omitted)

Response: { nodes: [...], edges: [...] }

Node shapes:
  subscription: { id, label, kind="subscription", parentId=null }
  resourceGroup: { id, label, kind="resourceGroup", location, parentId, resourceCount }
  resource:      { id, label, kind="resource", type, location, parentId }

Uses run_arg_query() so counts are identical to /api/v1/resources/inventory.
No per-RG cap, no global resource cap.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api_gateway.arg_helper import run_arg_query
from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/topology", tags=["topology"])

# KQL: subscription display names
_SUBSCRIPTIONS_KQL = """
ResourceContainers
| where type =~ 'microsoft.resources/subscriptions'
| project subscriptionId, displayName = name
"""

# KQL: all resources with group + location. No type filter — full inventory.
_TREE_RESOURCES_KQL = """
Resources
| project
    id            = tolower(id),
    name,
    type          = tolower(type),
    resourceGroup,
    subscriptionId,
    location
"""


@router.get("/tree")
async def get_topology_tree(
    subscriptions: str = Query(
        default="",
        description="Comma-separated subscription IDs. All accessible if omitted.",
    ),
    credential: Any = Depends(get_credential),
    _token: dict = Depends(verify_token),
) -> Dict[str, Any]:
    """Return a three-tier resource tree: subscriptions → resource groups → resources.

    Counts are accurate — backed by ARG with full pagination, no caps.
    Matches counts from GET /api/v1/resources/inventory exactly.
    """
    start = time.monotonic()
    subscription_ids: List[str] = (
        [s.strip() for s in subscriptions.split(",") if s.strip()]
        if subscriptions
        else []
    )

    logger.info(
        "topology_tree: request | subscriptions=%d",
        len(subscription_ids),
    )

    loop = asyncio.get_running_loop()

    # Step 1: resolve subscription display names (best-effort — never raises)
    try:
        sub_rows: List[Dict[str, Any]] = await loop.run_in_executor(
            None,
            run_arg_query,
            credential,
            subscription_ids,
            _SUBSCRIPTIONS_KQL,
        )
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.warning(
            "topology_tree: subscription name query failed | error=%s duration_ms=%.0f",
            exc,
            duration_ms,
        )
        sub_rows = []

    sub_names: Dict[str, str] = {
        row["subscriptionId"]: row.get("displayName", row["subscriptionId"])
        for row in sub_rows
        if row.get("subscriptionId")
    }

    # Step 2: fetch all resources
    try:
        resource_rows: List[Dict[str, Any]] = await loop.run_in_executor(
            None,
            run_arg_query,
            credential,
            subscription_ids,
            _TREE_RESOURCES_KQL,
        )
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "topology_tree: ARG resource query failed | error=%s duration_ms=%.0f",
            exc,
            duration_ms,
        )
        raise HTTPException(status_code=500, detail=f"ARG query failed: {exc}") from exc

    # Step 3: group resources by subscription → resource group
    rg_resources: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    rg_locations: Dict[str, Dict[str, str]] = defaultdict(dict)

    for row in resource_rows:
        sub_id: str = row.get("subscriptionId", "")
        rg_name: str = (row.get("resourceGroup") or "").lower()
        loc: str = row.get("location", "")
        if sub_id and rg_name:
            rg_resources[sub_id][rg_name].append(row)
            if rg_name not in rg_locations[sub_id]:
                rg_locations[sub_id][rg_name] = loc

    # Step 4: build node + edge lists
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []

    all_sub_ids = set(subscription_ids) | set(rg_resources.keys())

    for sub_id in sorted(all_sub_ids):
        sub_node_id = f"sub:{sub_id}"
        nodes.append({
            "id": sub_node_id,
            "label": sub_names.get(sub_id, sub_id),
            "kind": "subscription",
            "parentId": None,
        })

        for rg_name, resources in sorted(rg_resources[sub_id].items()):
            rg_node_id = f"rg:{sub_id}:{rg_name}"
            rg_loc = rg_locations[sub_id].get(rg_name, "")
            nodes.append({
                "id": rg_node_id,
                "label": rg_name,
                "kind": "resourceGroup",
                "location": rg_loc,
                "parentId": sub_node_id,
                "resourceCount": len(resources),
            })
            edges.append({"source": sub_node_id, "target": rg_node_id})

            for resource in resources:
                res_node_id = f"res:{resource['id']}"
                nodes.append({
                    "id": res_node_id,
                    "label": resource.get("name", ""),
                    "kind": "resource",
                    "type": resource.get("type", ""),
                    "location": resource.get("location", ""),
                    "parentId": rg_node_id,
                })
                edges.append({"source": rg_node_id, "target": res_node_id})

    duration_ms = (time.monotonic() - start) * 1000
    resource_count = sum(1 for n in nodes if n["kind"] == "resource")
    logger.info(
        "topology_tree: complete | nodes=%d resources=%d duration_ms=%.0f",
        len(nodes),
        resource_count,
        duration_ms,
    )

    return {"nodes": nodes, "edges": edges}
