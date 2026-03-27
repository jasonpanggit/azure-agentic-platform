"""Two-layer alert deduplication (DETECT-005).

Layer 1 (D-11): Time-window collapse — multiple alerts for the same
    resource_id + detection_rule within a 5-minute window collapse
    into a single Cosmos DB incident record.

Layer 2 (D-12): Open-incident correlation — a new distinct alert for
    a resource_id that already has an open incident is appended to
    the existing incident's correlated_alerts array.

ETag optimistic concurrency (same pattern as agents/shared/budget.py):
    read -> mutate -> replace_item(etag=, match_condition="IfMatch")
    On 412 Precondition Failed, retry with fresh read.

Execution order: Layer 1 first, then Layer 2, then create new.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from azure.cosmos import ContainerProxy
from azure.cosmos.exceptions import CosmosResourceExistsError

from models import (
    AlertStatus,
    CorrelatedAlert,
    IncidentRecord,
    StatusHistoryEntry,
)

logger = logging.getLogger(__name__)

DEFAULT_DEDUP_WINDOW_MINUTES = 5
MAX_DEDUP_RETRIES = 3

# Cosmos DB container name for incidents
INCIDENTS_CONTAINER_NAME = "incidents"


class DedupResult:
    """Result of deduplication check."""

    def __init__(
        self,
        is_duplicate: bool,
        existing_record: Optional[dict[str, Any]] = None,
        layer: Optional[str] = None,
    ):
        self.is_duplicate = is_duplicate
        self.existing_record = existing_record
        self.layer = layer  # "layer1" | "layer2" | None


async def dedup_layer1(
    resource_id: str,
    detection_rule: str,
    container: ContainerProxy,
    window_minutes: int = DEFAULT_DEDUP_WINDOW_MINUTES,
) -> DedupResult:
    """Layer 1: Time-window collapse (D-11).

    Check for an existing incident with the same resource_id + detection_rule
    within the configured time window.

    Args:
        resource_id: ARM resource ID (partition key).
        detection_rule: Name of the detection rule.
        container: Cosmos DB incidents container proxy.
        window_minutes: Dedup window in minutes (default 5).

    Returns:
        DedupResult with is_duplicate=True if a match was found.
    """
    window_start = (
        datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    ).isoformat()

    query = (
        "SELECT * FROM incidents c "
        "WHERE c.resource_id = @resource_id "
        "AND c.detection_rule = @detection_rule "
        "AND c.created_at >= @window_start "
        "AND c.status != 'closed' "
        "ORDER BY c.created_at DESC "
        "OFFSET 0 LIMIT 1"
    )
    params = [
        {"name": "@resource_id", "value": resource_id},
        {"name": "@detection_rule", "value": detection_rule},
        {"name": "@window_start", "value": window_start},
    ]

    results = list(
        container.query_items(
            query=query,
            parameters=params,
            partition_key=resource_id,
        )
    )

    if results:
        return DedupResult(is_duplicate=True, existing_record=results[0], layer="layer1")
    return DedupResult(is_duplicate=False)


async def dedup_layer2(
    resource_id: str,
    container: ContainerProxy,
) -> DedupResult:
    """Layer 2: Open-incident correlation (D-12).

    Check for any open incident for the same resource_id.

    Args:
        resource_id: ARM resource ID (partition key).
        container: Cosmos DB incidents container proxy.

    Returns:
        DedupResult with is_duplicate=True if an open incident exists.
    """
    query = (
        "SELECT * FROM incidents c "
        "WHERE c.resource_id = @resource_id "
        "AND c.status IN ('new', 'acknowledged') "
        "ORDER BY c.created_at DESC "
        "OFFSET 0 LIMIT 1"
    )
    params = [{"name": "@resource_id", "value": resource_id}]

    results = list(
        container.query_items(
            query=query,
            parameters=params,
            partition_key=resource_id,
        )
    )

    if results:
        return DedupResult(is_duplicate=True, existing_record=results[0], layer="layer2")
    return DedupResult(is_duplicate=False)


async def collapse_duplicate(
    existing_record: dict[str, Any],
    container: ContainerProxy,
) -> dict[str, Any]:
    """Collapse a Layer 1 duplicate into the existing record.

    Increments duplicate_count with ETag optimistic concurrency.

    Args:
        existing_record: The existing Cosmos DB incident record.
        container: Cosmos DB incidents container proxy.

    Returns:
        Updated Cosmos DB record.

    Raises:
        Exception: If all retry attempts fail.
    """
    for attempt in range(MAX_DEDUP_RETRIES):
        record = existing_record if attempt == 0 else container.read_item(
            item=existing_record["id"],
            partition_key=existing_record["resource_id"],
        )
        etag = record["_etag"]

        updated = {
            **record,
            "duplicate_count": record.get("duplicate_count", 0) + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            return container.replace_item(
                item=record["id"],
                body=updated,
                etag=etag,
                match_condition="IfMatch",
            )
        except Exception as exc:
            if "412" in str(exc) or "Precondition Failed" in str(exc):
                logger.warning(
                    "ETag conflict on dedup collapse (attempt %d/%d)",
                    attempt + 1,
                    MAX_DEDUP_RETRIES,
                )
                if attempt == MAX_DEDUP_RETRIES - 1:
                    raise
                continue
            raise


async def correlate_alert(
    existing_record: dict[str, Any],
    alert_id: str,
    severity: str,
    detection_rule: str,
    container: ContainerProxy,
) -> dict[str, Any]:
    """Correlate a new alert to an existing open incident (Layer 2, D-12).

    Appends to correlated_alerts array with ETag optimistic concurrency.

    Args:
        existing_record: The existing Cosmos DB incident record.
        alert_id: ID of the new alert being correlated.
        severity: Severity of the new alert.
        detection_rule: Detection rule of the new alert.
        container: Cosmos DB incidents container proxy.

    Returns:
        Updated Cosmos DB record.
    """
    for attempt in range(MAX_DEDUP_RETRIES):
        record = existing_record if attempt == 0 else container.read_item(
            item=existing_record["id"],
            partition_key=existing_record["resource_id"],
        )
        etag = record["_etag"]

        correlated = CorrelatedAlert(
            alert_id=alert_id,
            severity=severity,
            detection_rule=detection_rule,
        )
        new_correlated = [
            *record.get("correlated_alerts", []),
            correlated.model_dump(),
        ]

        updated = {
            **record,
            "correlated_alerts": new_correlated,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            return container.replace_item(
                item=record["id"],
                body=updated,
                etag=etag,
                match_condition="IfMatch",
            )
        except Exception as exc:
            if "412" in str(exc) or "Precondition Failed" in str(exc):
                logger.warning(
                    "ETag conflict on alert correlation (attempt %d/%d)",
                    attempt + 1,
                    MAX_DEDUP_RETRIES,
                )
                if attempt == MAX_DEDUP_RETRIES - 1:
                    raise
                continue
            raise


async def create_incident_record(
    incident_id: str,
    resource_id: str,
    severity: str,
    domain: str,
    detection_rule: str,
    affected_resources: list[dict],
    container: ContainerProxy,
    kql_evidence: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new incident record in Cosmos DB.

    Args:
        incident_id: Unique incident identifier.
        resource_id: ARM resource ID (partition key).
        severity: Sev0-Sev3.
        domain: Agent domain (compute/network/storage/security/arc/sre).
        detection_rule: Name of the detection rule.
        affected_resources: List of affected resource dicts.
        container: Cosmos DB incidents container proxy.
        kql_evidence: Optional KQL evidence string.
        title: Optional human-readable title.
        description: Optional description.

    Returns:
        Created Cosmos DB record.
    """
    now = datetime.now(timezone.utc).isoformat()
    record = IncidentRecord(
        id=incident_id,
        resource_id=resource_id,
        incident_id=incident_id,
        severity=severity,
        domain=domain,
        detection_rule=detection_rule,
        kql_evidence=kql_evidence,
        status=AlertStatus.NEW,
        status_history=[
            StatusHistoryEntry(status=AlertStatus.NEW, actor="system", timestamp=now),
        ],
        affected_resources=affected_resources,
        title=title,
        description=description,
        created_at=now,
        updated_at=now,
    )

    return container.create_item(body=record.model_dump())
