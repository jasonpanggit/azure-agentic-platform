"""Resources inventory endpoint — flat listing of all Azure resources via ARG.

GET /api/v1/resources/inventory
  ?subscriptions=sub1,sub2   (optional, comma-separated; all accessible if omitted)

Response: { resources: [...], total: int, resourceTypes: [...] }

Each resource item: { id, name, type, location }

Uses run_arg_query() from arg_helper so counts match topology/tree exactly
(same ARG data source, no ARM pagination caps).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api_gateway.arg_helper import run_arg_query
from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])

# KQL: project only the fields needed by the Resources tab.
# No filter, no cap — full inventory across all resource types.
_RESOURCES_KQL = """
Resources
| project
    id       = tolower(id),
    name,
    type     = tolower(type),
    location,
    resourceGroup,
    subscriptionId
| order by type asc, name asc
"""


@router.get("/inventory")
async def list_resources(
    subscriptions: str = Query(
        default="",
        description="Comma-separated subscription IDs. All accessible if omitted.",
    ),
    credential: Any = Depends(get_credential),
    _token: dict = Depends(verify_token),
) -> Dict[str, Any]:
    """Return all Azure resources across the specified subscriptions.

    Uses ARG for cross-subscription inventory — no per-page caps.
    Counts here will always match GET /api/v1/topology/tree.
    """
    start = time.monotonic()
    subscription_ids: List[str] = (
        [s.strip() for s in subscriptions.split(",") if s.strip()]
        if subscriptions
        else []
    )

    logger.info(
        "resources_inventory: request | subscriptions=%d",
        len(subscription_ids),
    )

    loop = asyncio.get_running_loop()
    try:
        rows: List[Dict[str, Any]] = await loop.run_in_executor(
            None,
            run_arg_query,
            credential,
            subscription_ids,
            _RESOURCES_KQL,
        )
    except Exception as exc:
        logger.error("resources_inventory: ARG query failed | error=%s", exc)
        raise HTTPException(status_code=500, detail=f"ARG query failed: {exc}") from exc

    resources = [
        {
            "id": row.get("id", ""),
            "name": row.get("name", ""),
            "type": row.get("type", ""),
            "location": row.get("location", ""),
        }
        for row in rows
    ]

    resource_types = sorted({r["type"] for r in resources if r["type"]})

    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "resources_inventory: complete | count=%d duration_ms=%.0f",
        len(resources),
        duration_ms,
    )

    return {
        "resources": resources,
        "total": len(resources),
        "resourceTypes": resource_types,
    }
