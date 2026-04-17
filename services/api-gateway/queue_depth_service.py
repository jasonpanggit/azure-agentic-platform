"""Service Bus / Event Hub queue depth monitoring service.

Scans namespaces via ARG then enriches with Azure Monitor Metrics REST API
for active and dead-letter message counts.  Persists to Cosmos DB container
'queue_health' (TTL 30 min).

Never raises — all exceptions are caught and logged.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ARG KQL
# ---------------------------------------------------------------------------

_ARG_KQL = """
Resources
| where type in~ (
    'microsoft.servicebus/namespaces',
    'microsoft.eventhub/namespaces'
  )
| project
    resource_id = tolower(id),
    name,
    type = tolower(type),
    resource_group = resourceGroup,
    subscription_id = subscriptionId,
    location,
    sku_name = tostring(sku.name),
    sku_tier = tostring(sku.tier),
    status = tostring(properties.status),
    created_at = tostring(properties.createdAt),
    tags
"""

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class QueueNamespace:
    namespace_id: str     # uuid5(NAMESPACE_URL, arm_id)
    arm_id: str
    name: str
    namespace_type: str   # "service_bus" | "event_hub"
    resource_group: str
    subscription_id: str
    location: str
    sku_name: str
    status: str           # Active/Disabled
    active_messages: Optional[int]       # from metrics (None if unavailable)
    dead_letter_messages: Optional[int]
    health_status: str    # "healthy"/"warning"/"critical"/"unknown"
    health_reason: str
    scanned_at: str = ""
    ttl: int = 1800       # 30 min


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_namespace_type(resource_type: str) -> str:
    if "servicebus" in resource_type:
        return "service_bus"
    return "event_hub"


def _classify_health(
    active: Optional[int],
    dead_letter: Optional[int],
) -> tuple:
    """Return (health_status, health_reason)."""
    if active is None and dead_letter is None:
        return "unknown", "metrics unavailable"

    dlq = dead_letter or 0
    am = active or 0

    if dlq > 100:
        return "critical", f"dead_letter_messages={dlq} > 100"
    if am > 10000:
        return "critical", f"active_messages={am} > 10000"
    if dlq > 10:
        return "warning", f"dead_letter_messages={dlq} > 10"
    if am > 1000:
        return "warning", f"active_messages={am} > 1000"
    return "healthy", "within thresholds"


def _fetch_metrics(
    arm_id: str,
    token: str,
) -> tuple:
    """Fetch ActiveMessages and DeadletteredMessages from Azure Monitor Metrics REST API.

    Returns (active_messages, dead_letter_messages).  Both values are None on error.
    Best-effort: never raises.
    """
    try:
        url = (
            f"https://management.azure.com{arm_id}"
            "/providers/Microsoft.Insights/metrics"
        )
        params = {
            "api-version": "2018-01-01",
            "metricnames": "ActiveMessages,DeadletteredMessages",
            "aggregation": "Maximum",
            "timespan": "PT1H",
        }
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.debug("queue_metrics: non-200 status=%d arm_id=%s", resp.status_code, arm_id[:60])
            return None, None

        data = resp.json()
        active: Optional[int] = None
        dead_letter: Optional[int] = None

        for metric in data.get("value", []):
            name = (metric.get("name") or {}).get("value", "")
            timeseries = metric.get("timeseries") or []
            max_val: Optional[float] = None
            for ts in timeseries:
                for dp in ts.get("data") or []:
                    v = dp.get("maximum")
                    if v is not None:
                        max_val = max(max_val, v) if max_val is not None else v
            int_val = int(max_val) if max_val is not None else None
            if name == "ActiveMessages":
                active = int_val
            elif name == "DeadletteredMessages":
                dead_letter = int_val

        return active, dead_letter
    except Exception as exc:
        logger.debug("queue_metrics: fetch failed arm_id=%s error=%s", arm_id[:60], exc)
        return None, None


def _get_bearer_token(credential: Any) -> Optional[str]:
    """Obtain a bearer token for the ARM audience.  Never raises."""
    try:
        token = credential.get_token("https://management.azure.com/.default")
        return token.token
    except Exception as exc:
        logger.warning("queue_metrics: token fetch failed error=%s", exc)
        return None


def _row_to_namespace(
    row: Dict[str, Any],
    active: Optional[int],
    dead_letter: Optional[int],
) -> QueueNamespace:
    arm_id = str(row.get("resource_id") or "")
    namespace_id = str(uuid.uuid5(uuid.NAMESPACE_URL, arm_id))
    resource_type = str(row.get("type") or "")
    ns_type = _classify_namespace_type(resource_type)
    health_status, health_reason = _classify_health(active, dead_letter)

    return QueueNamespace(
        namespace_id=namespace_id,
        arm_id=arm_id,
        name=str(row.get("name") or ""),
        namespace_type=ns_type,
        resource_group=str(row.get("resource_group") or ""),
        subscription_id=str(row.get("subscription_id") or ""),
        location=str(row.get("location") or ""),
        sku_name=str(row.get("sku_name") or ""),
        status=str(row.get("status") or "Unknown"),
        active_messages=active,
        dead_letter_messages=dead_letter,
        health_status=health_status,
        health_reason=health_reason,
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_queue_namespaces(
    credential: Any,
    subscription_ids: List[str],
) -> List[QueueNamespace]:
    """Scan Service Bus and Event Hub namespaces via ARG then enrich with metrics.

    Metrics fetch is best-effort — namespaces with unavailable metrics are
    returned with health_status='unknown'.  Never raises.
    """
    start_time = time.monotonic()
    if not subscription_ids:
        logger.info("queue_scan: no subscriptions provided")
        return []

    try:
        from services.api_gateway.arg_helper import run_arg_query
        rows = run_arg_query(credential, subscription_ids, _ARG_KQL)
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("queue_scan: arg_query failed error=%s duration_ms=%.1f", exc, duration_ms)
        return []

    # Obtain bearer token once; reuse for all metric calls
    token = _get_bearer_token(credential)

    namespaces: List[QueueNamespace] = []
    for row in rows:
        try:
            arm_id = str(row.get("resource_id") or "")
            if token and arm_id:
                active, dead_letter = _fetch_metrics(arm_id, token)
            else:
                active, dead_letter = None, None
            namespaces.append(_row_to_namespace(row, active, dead_letter))
        except Exception as exc:
            logger.warning("queue_scan: row processing failed row=%s error=%s", row.get("resource_id"), exc)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "queue_scan: complete total=%d duration_ms=%.1f",
        len(namespaces), duration_ms,
    )
    return namespaces


def persist_namespaces(
    cosmos_client: Any,
    db_name: str,
    namespaces: List[QueueNamespace],
) -> None:
    """Upsert QueueNamespace records into Cosmos DB container 'queue_health'.

    Container TTL is configured at the container level (30 min).  Never raises.
    """
    if not namespaces:
        return
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("queue_health")
        for ns in namespaces:
            doc = asdict(ns)
            doc["id"] = ns.namespace_id
            try:
                container.upsert_item(doc)
            except Exception as exc:
                logger.warning("queue_persist: upsert failed namespace_id=%s error=%s", ns.namespace_id, exc)
        logger.info("queue_persist: upserted %d items", len(namespaces))
    except Exception as exc:
        logger.error("queue_persist: container error=%s", exc)


def get_namespaces(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    health_status: Optional[str] = None,
    namespace_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query persisted queue namespace health records from Cosmos DB.

    Filters by subscription_ids, health_status, namespace_type (all optional).
    Never raises.
    """
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("queue_health")

        conditions = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sub in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sub})

        if health_status:
            conditions.append("c.health_status = @health_status")
            params.append({"name": "@health_status", "value": health_status})

        if namespace_type:
            conditions.append("c.namespace_type = @namespace_type")
            params.append({"name": "@namespace_type", "value": namespace_type})

        where_clause = " AND ".join(conditions)
        query = f"SELECT * FROM c WHERE {where_clause}" if where_clause else "SELECT * FROM c"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:
        logger.error("queue_get: cosmos error=%s", exc)
        return []


def get_queue_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregate counts for the Queue Depth dashboard strip.

    Returns dict with: total, critical, warning, healthy,
    total_dead_letter, total_active_messages.
    Never raises.
    """
    try:
        items = get_namespaces(cosmos_client, db_name)
        total = len(items)
        critical = sum(1 for i in items if i.get("health_status") == "critical")
        warning = sum(1 for i in items if i.get("health_status") == "warning")
        healthy = sum(1 for i in items if i.get("health_status") == "healthy")
        total_dead_letter = sum(i.get("dead_letter_messages") or 0 for i in items)
        total_active = sum(i.get("active_messages") or 0 for i in items)
        return {
            "total": total,
            "critical": critical,
            "warning": warning,
            "healthy": healthy,
            "total_dead_letter": total_dead_letter,
            "total_active_messages": total_active,
        }
    except Exception as exc:
        logger.error("queue_summary: error=%s", exc)
        return {
            "total": 0,
            "critical": 0,
            "warning": 0,
            "healthy": 0,
            "total_dead_letter": 0,
            "total_active_messages": 0,
        }
