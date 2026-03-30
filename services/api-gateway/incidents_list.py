"""Incident list endpoint for the alert feed (UI-006).

Returns incidents from Cosmos DB filtered by subscription, severity,
domain, and status. Supports polling from the Web UI alert feed.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from azure.cosmos import ContainerProxy, CosmosClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


def _get_incidents_container(cosmos_client: Optional[CosmosClient] = None) -> ContainerProxy:
    """Get the Cosmos DB incidents container.

    Uses the provided cosmos_client singleton when available; falls back to
    creating a per-call client for backward compatibility (e.g. direct calls
    in tests that do not go through the FastAPI lifespan).
    """
    if cosmos_client is None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            raise ValueError("COSMOS_ENDPOINT environment variable is required.")
        cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    database = cosmos_client.get_database_client(database_name)
    return database.get_container_client("incidents")


async def list_incidents(
    since: Optional[str] = None,
    subscription_ids: Optional[list[str]] = None,
    severity: Optional[str] = None,
    domain: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    cosmos_client: Optional[CosmosClient] = None,  # injected from app.state
) -> list[dict]:
    """List incidents from Cosmos DB with optional filters."""
    container = _get_incidents_container(cosmos_client=cosmos_client)

    conditions = []
    parameters = []

    if since:
        conditions.append("c.created_at >= @since")
        parameters.append({"name": "@since", "value": since})

    if severity:
        conditions.append("c.severity = @severity")
        parameters.append({"name": "@severity", "value": severity})

    if domain:
        conditions.append("c.domain = @domain")
        parameters.append({"name": "@domain", "value": domain})

    if status:
        conditions.append("c.status = @status")
        parameters.append({"name": "@status", "value": status})

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    query = (
        f"SELECT c.id, c.incident_id, c.severity, c.domain, c.status, "
        f"c.created_at, c.title, c.resource_id, c.subscription_id "
        f"FROM c WHERE {where_clause} "
        f"ORDER BY c.created_at DESC "
        f"OFFSET 0 LIMIT @limit"
    )
    parameters.append({"name": "@limit", "value": limit})

    items = container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
    )

    results = list(items)

    # Client-side subscription filter (cross-partition query can't filter on non-PK)
    if subscription_ids:
        results = [r for r in results if r.get("subscription_id") in subscription_ids]

    return results
