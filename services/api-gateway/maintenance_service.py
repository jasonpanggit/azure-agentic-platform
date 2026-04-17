from __future__ import annotations
"""Maintenance Window Intelligence Service — Phase 94.

Queries Azure Resource Health and Service Health via ARG for planned maintenance
and health advisory events across subscriptions.
"""

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from services.api_gateway.arg_helper import run_arg_query  # type: ignore[import]
except ImportError:
    run_arg_query = None  # type: ignore[assignment]

_ARG_RESOURCE_HEALTH_KQL = """
ResourceHealthResources
| where type =~ 'microsoft.resourcehealth/availabilitystatuses'
| where properties.availabilityState =~ 'Unavailable'
   or properties.availabilityState =~ 'Degraded'
   or tostring(properties.reasonType) has 'Planned'
| extend resource_base = tostring(split(id, '/providers/Microsoft.ResourceHealth')[0])
| extend parts = split(resource_base, '/')
| project
    health_id = tolower(id),
    resource_id = tolower(resource_base),
    resource_type = tolower(tostring(parts[7])),
    subscription_id = subscriptionId,
    resource_group = resourceGroup,
    availability_state = tostring(properties.availabilityState),
    reason_type = tostring(properties.reasonType),
    summary = tostring(properties.summary),
    reason_chronicity = tostring(properties.reasonChronicity),
    occurred_time = tostring(properties.occuredTime),
    reported_time = tostring(properties.reportedTime)
| where occurred_time > ago(7d)
| order by occurred_time desc
"""

_ARG_SERVICE_HEALTH_KQL = """
ServiceHealthResources
| where type =~ 'microsoft.resourcehealth/events'
| where properties.eventType in~ ('PlannedMaintenance', 'HealthAdvisory')
| project
    event_id = tolower(id),
    subscription_id = subscriptionId,
    title = tostring(properties.title),
    event_type = tostring(properties.eventType),
    status = tostring(properties.status),
    level = tostring(properties.level),
    impact_start_time = tostring(properties.impactStartTime),
    impact_mitigation_time = tostring(properties.impactMitigationTime),
    affected_regions = tostring(properties.impactedServices),
    description = tostring(properties.description)
| order by impact_start_time desc
| limit 50
"""


@dataclass
class MaintenanceEvent:
    event_id: str
    subscription_id: str
    resource_id: str
    resource_group: str
    event_type: str    # "planned_maintenance" | "health_advisory" | "resource_degraded"
    title: str
    status: str        # "Active" | "Resolved" | "InProgress"
    level: str         # "Information" | "Warning" | "Critical"
    impact_start: str  # ISO
    impact_end: str    # ISO or ""
    description: str
    severity: str      # "critical" | "high" | "medium"
    detected_at: str
    ttl: int = 172800  # 48h


def _stable_id(source_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, source_id))


def _map_level_to_severity(level: str, availability_state: str = "") -> str:
    lvl = (level or "").lower()
    state = (availability_state or "").lower()
    if lvl == "critical" or state == "unavailable":
        return "critical"
    if lvl == "warning" or state == "degraded":
        return "high"
    return "medium"


def _classify_event_type(raw_type: str, reason_type: str = "", availability_state: str = "") -> str:
    raw = (raw_type or "").lower()
    reason = (reason_type or "").lower()
    if "planned" in raw or "planned" in reason:
        return "planned_maintenance"
    if "advisory" in raw:
        return "health_advisory"
    return "resource_degraded"


def scan_maintenance_events(
    credential: Any,
    subscription_ids: List[str],
) -> List[MaintenanceEvent]:
    """Scan Resource Health and Service Health events via ARG.

    Never raises; returns [] on any failure.
    """
    if not subscription_ids:
        return []

    detected_at = datetime.now(tz=timezone.utc).isoformat()
    events: List[MaintenanceEvent] = []

    if run_arg_query is None:
        logger.warning("maintenance_service: arg_helper not available")
        return []

    # --- Resource Health ---
    try:
        rows = run_arg_query(credential, subscription_ids, _ARG_RESOURCE_HEALTH_KQL)
        for row in rows:
            health_id = row.get("health_id", "")
            events.append(MaintenanceEvent(
                event_id=_stable_id(health_id),
                subscription_id=row.get("subscription_id", ""),
                resource_id=row.get("resource_id", ""),
                resource_group=row.get("resource_group", ""),
                event_type=_classify_event_type(
                    row.get("reason_type", ""),
                    availability_state=row.get("availability_state", ""),
                ),
                title=row.get("summary", "") or f"Resource {row.get('availability_state', 'Degraded')}",
                status="Active",
                level=row.get("availability_state", "Warning"),
                impact_start=row.get("occurred_time", detected_at),
                impact_end=row.get("reported_time", ""),
                description=row.get("summary", ""),
                severity=_map_level_to_severity(
                    row.get("availability_state", ""),
                    availability_state=row.get("availability_state", ""),
                ),
                detected_at=detected_at,
            ))
    except Exception as exc:
        logger.warning("maintenance_service: resource health ARG query failed: %s", exc)

    # --- Service Health ---
    try:
        rows = run_arg_query(credential, subscription_ids, _ARG_SERVICE_HEALTH_KQL)
        for row in rows:
            event_id = row.get("event_id", "")
            raw_type = row.get("event_type", "")
            events.append(MaintenanceEvent(
                event_id=_stable_id(event_id),
                subscription_id=row.get("subscription_id", ""),
                resource_id="",
                resource_group="",
                event_type=_classify_event_type(raw_type),
                title=row.get("title", "Service Health Event"),
                status=row.get("status", "Active"),
                level=row.get("level", "Information"),
                impact_start=row.get("impact_start_time", detected_at),
                impact_end=row.get("impact_mitigation_time", ""),
                description=row.get("description", ""),
                severity=_map_level_to_severity(row.get("level", "Information")),
                detected_at=detected_at,
            ))
    except Exception as exc:
        logger.warning("maintenance_service: service health ARG query failed: %s", exc)

    logger.info("maintenance_service: scan complete | events=%d", len(events))
    return events


def persist_events(
    cosmos_client: Any,
    db_name: str,
    events: List[MaintenanceEvent],
) -> None:
    """Upsert MaintenanceEvent records into Cosmos DB 'maintenance_events'. Never raises."""
    if not events:
        return
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("maintenance_events")
        for event in events:
            item = asdict(event)
            item["id"] = event.event_id
            container.upsert_item(item)
        logger.info("maintenance_service: persisted %d events", len(events))
    except Exception as exc:
        logger.error("maintenance_service: persist_events failed: %s", exc)


def get_events(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
) -> List[MaintenanceEvent]:
    """Fetch MaintenanceEvent records from Cosmos DB. Never raises."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("maintenance_events")
        clauses: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            clauses.append(f"c.subscription_id IN ({placeholders})")
            for i, sid in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sid})

        if event_type:
            clauses.append("c.event_type = @event_type")
            params.append({"name": "@event_type", "value": event_type})

        if status:
            clauses.append("c.status = @status")
            params.append({"name": "@status", "value": status})

        where_clause = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"SELECT * FROM c{where_clause}"

        items = list(container.query_items(query=query, parameters=params or None, enable_cross_partition_query=True))
        return [
            MaintenanceEvent(
                event_id=i.get("event_id", i.get("id", "")),
                subscription_id=i.get("subscription_id", ""),
                resource_id=i.get("resource_id", ""),
                resource_group=i.get("resource_group", ""),
                event_type=i.get("event_type", ""),
                title=i.get("title", ""),
                status=i.get("status", ""),
                level=i.get("level", ""),
                impact_start=i.get("impact_start", ""),
                impact_end=i.get("impact_end", ""),
                description=i.get("description", ""),
                severity=i.get("severity", ""),
                detected_at=i.get("detected_at", ""),
                ttl=i.get("ttl", 172800),
            )
            for i in items
        ]
    except Exception as exc:
        logger.error("maintenance_service: get_events failed: %s", exc)
        return []


def get_maintenance_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregated maintenance event summary. Never raises."""
    events = get_events(cosmos_client, db_name)
    active = [e for e in events if e.status.lower() in ("active", "inprogress")]
    planned = [e for e in events if e.event_type == "planned_maintenance"]
    advisories = [e for e in events if e.event_type == "health_advisory"]
    affected_subs = len({e.subscription_id for e in active if e.subscription_id})
    critical = sum(1 for e in events if e.severity == "critical")
    return {
        "active_events": len(active),
        "planned_upcoming": len(planned),
        "health_advisories": len(advisories),
        "affected_subscriptions": affected_subs,
        "critical_count": critical,
    }
