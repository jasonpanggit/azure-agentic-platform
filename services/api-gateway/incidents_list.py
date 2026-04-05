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


def _parse_resource_id(resource_id: Optional[str]) -> dict:
    """Extract name, resource_group, resource_type, subscription_id from ARM resource ID.

    ARM resource ID format:
    /subscriptions/{sub}/resourceGroups/{rg}/providers/{namespace}/{type}/{name}

    Returns dict with keys: resource_name, resource_group, resource_type, subscription_id.
    All values are None if resource_id is None or malformed.
    """
    if not resource_id:
        return {"resource_name": None, "resource_group": None, "resource_type": None, "subscription_id": None}

    parts = resource_id.split("/")
    # Normalize to lowercase for comparison, but extract original-case values
    lower = resource_id.lower().split("/")

    result: dict = {"resource_name": None, "resource_group": None, "resource_type": None, "subscription_id": None}

    try:
        if "subscriptions" in lower:
            idx = lower.index("subscriptions")
            result["subscription_id"] = parts[idx + 1]
        if "resourcegroups" in lower:
            idx = lower.index("resourcegroups")
            result["resource_group"] = parts[idx + 1]
        if "providers" in lower:
            idx = lower.index("providers")
            # type = namespace/type, name = parts[idx+3]
            if idx + 3 < len(parts):
                result["resource_type"] = f"{lower[idx + 1]}/{lower[idx + 2]}"
                result["resource_name"] = parts[idx + 3]
            elif idx + 2 < len(parts):
                result["resource_type"] = lower[idx + 1]
        # Fallback: last non-empty segment is the resource name
        if not result["resource_name"]:
            non_empty = [p for p in parts if p]
            if non_empty:
                result["resource_name"] = non_empty[-1]
    except (IndexError, ValueError):
        pass

    return result


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
        f"c.created_at, c.title, c.resource_id, c.subscription_id, "
        f"c.affected_resources, c.investigation_status, c.evidence_collected_at, "
        f"c.top_changes, c.composite_severity, c.suppressed, c.parent_incident_id, "
        f"c.historical_matches, c.slo_escalated "
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

    # Enrich each result with parsed resource metadata and investigation status.
    # NOTE: subscription_id is derived from the ARM resource_id during enrichment,
    # so the subscription filter must run AFTER enrichment (not before).
    enriched = []
    for doc in results:
        resource_id = doc.get("resource_id") or (
            doc.get("affected_resources", [{}])[0].get("resource_id")
            if doc.get("affected_resources")
            else None
        )
        parsed = _parse_resource_id(resource_id)
        enriched_doc = {
            **doc,
            "resource_id": resource_id,
            "resource_name": parsed["resource_name"],
            "resource_group": parsed["resource_group"],
            "resource_type": parsed["resource_type"],
            "subscription_id": parsed["subscription_id"] or doc.get("subscription_id"),
            "investigation_status": doc.get("investigation_status", "pending"),
            "evidence_collected_at": doc.get("evidence_collected_at"),
            "top_changes": doc.get("top_changes"),
            "composite_severity": doc.get("composite_severity"),
            "suppressed": doc.get("suppressed"),
            "parent_incident_id": doc.get("parent_incident_id"),
            "historical_matches": doc.get("historical_matches"),
            "slo_escalated": doc.get("slo_escalated"),
        }
        enriched.append(enriched_doc)

    # Client-side subscription filter — runs after enrichment because subscription_id
    # is parsed from the ARM resource_id and is not a raw field in the Cosmos document.
    if subscription_ids:
        enriched = [r for r in enriched if r.get("subscription_id") in subscription_ids]

    return enriched
