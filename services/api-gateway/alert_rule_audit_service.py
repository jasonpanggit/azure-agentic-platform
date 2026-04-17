from __future__ import annotations
"""Alert Rule Coverage Audit service (Phase 90).

Identifies Azure resource types with no Monitor Alert Rules configured,
exposing governance blind spots across subscriptions.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.api_gateway.arg_helper import run_arg_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resource type criticality map
# ---------------------------------------------------------------------------

CRITICAL_RESOURCE_TYPES: Dict[str, Dict[str, str]] = {
    "microsoft.compute/virtualmachines": {
        "friendly": "Virtual Machines",
        "severity": "critical",
        "recommendation": "Add metric alerts for CPU, memory, and disk. Enable VM health alerts.",
    },
    "microsoft.containerservice/managedclusters": {
        "friendly": "AKS Clusters",
        "severity": "critical",
        "recommendation": "Add alerts for node CPU/memory, pod failures, and cluster health.",
    },
    "microsoft.keyvault/vaults": {
        "friendly": "Key Vaults",
        "severity": "critical",
        "recommendation": "Add alerts for availability, latency, and failed requests.",
    },
    "microsoft.storage/storageaccounts": {
        "friendly": "Storage Accounts",
        "severity": "critical",
        "recommendation": "Add alerts for availability, transactions errors, and latency.",
    },
    "microsoft.network/networksecuritygroups": {
        "friendly": "Network Security Groups",
        "severity": "high",
        "recommendation": "Add activity log alerts for NSG rule changes.",
    },
    "microsoft.network/virtualnetworks": {
        "friendly": "Virtual Networks",
        "severity": "high",
        "recommendation": "Add alerts for VNet peering state and DDoS attacks.",
    },
    "microsoft.documentdb/databaseaccounts": {
        "friendly": "Cosmos DB",
        "severity": "high",
        "recommendation": "Add alerts for RU consumption, availability, and throttled requests.",
    },
    "microsoft.dbforpostgresql/flexibleservers": {
        "friendly": "PostgreSQL Flexible Servers",
        "severity": "high",
        "recommendation": "Add alerts for CPU, storage, and connection failures.",
    },
    "microsoft.web/sites": {
        "friendly": "App Services",
        "severity": "medium",
        "recommendation": "Add alerts for HTTP 5xx errors, response time, and availability.",
    },
    "microsoft.servicebus/namespaces": {
        "friendly": "Service Bus",
        "severity": "medium",
        "recommendation": "Add alerts for dead-lettered messages and server errors.",
    },
    "microsoft.eventhub/namespaces": {
        "friendly": "Event Hubs",
        "severity": "medium",
        "recommendation": "Add alerts for throttled requests and incoming/outgoing bytes.",
    },
}

# ---------------------------------------------------------------------------
# ARG KQL templates
# ---------------------------------------------------------------------------

_KQL_METRIC_ALERTS = """
Resources
| where type =~ 'microsoft.insights/metricalerts'
| project
    rule_id = tolower(id),
    rule_name = name,
    subscription_id = subscriptionId,
    resource_group = resourceGroup,
    severity = toint(properties.severity),
    enabled = tobool(properties.enabled),
    target_resource_type = tolower(tostring(properties.targetResourceType)),
    target_resource_ids = properties.scopes,
    description = tostring(properties.description)
"""

_KQL_ACTIVITY_ALERTS = """
Resources
| where type =~ 'microsoft.insights/activitylogalerts'
| project
    rule_id = tolower(id),
    rule_name = name,
    subscription_id = subscriptionId,
    resource_group = resourceGroup,
    enabled = tobool(properties.enabled),
    conditions = properties.condition.allOf
"""

_KQL_RESOURCES = """
Resources
| where type in~ ({type_list})
| summarize resource_count = count() by type = tolower(type), subscription_id = subscriptionId
"""

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class AlertCoverageGap:
    gap_id: str
    subscription_id: str
    resource_type: str
    resource_count: int
    alert_rule_count: int
    severity: str
    recommendation: str
    scanned_at: str
    ttl: int = 86400

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.gap_id,
            "gap_id": self.gap_id,
            "subscription_id": self.subscription_id,
            "resource_type": self.resource_type,
            "resource_count": self.resource_count,
            "alert_rule_count": self.alert_rule_count,
            "severity": self.severity,
            "recommendation": self.recommendation,
            "scanned_at": self.scanned_at,
            "ttl": self.ttl,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_alert_coverage(
    credential: Any,
    subscription_ids: List[str],
) -> List[AlertCoverageGap]:
    """Scan subscriptions for resource types with no alert rules.

    Never raises — returns empty list on error.
    """
    start = time.monotonic()
    try:
        metric_rows = run_arg_query(credential, subscription_ids, _KQL_METRIC_ALERTS)
        activity_rows = run_arg_query(credential, subscription_ids, _KQL_ACTIVITY_ALERTS)

        type_list = ", ".join(f"'{t}'" for t in CRITICAL_RESOURCE_TYPES)
        resource_kql = f"""
Resources
| where type in~ ({type_list})
| summarize resource_count = count() by type = tolower(type), subscription_id = subscriptionId
"""
        resource_rows = run_arg_query(credential, subscription_ids, resource_kql)
    except Exception as exc:  # noqa: BLE001
        logger.error("alert_rule_audit: ARG query failed | error=%s", exc)
        return []

    # Build set of (subscription_id, resource_type) pairs that have alert rules
    covered: Dict[tuple, int] = {}
    for row in metric_rows:
        rtype = str(row.get("target_resource_type", "")).lower()
        sub = str(row.get("subscription_id", "")).lower()
        if rtype and sub:
            key = (sub, rtype)
            covered[key] = covered.get(key, 0) + 1

    # Activity log alerts count towards subscription-level coverage (they target activity)
    # Track per subscription
    activity_subs: Dict[str, int] = {}
    for row in activity_rows:
        sub = str(row.get("subscription_id", "")).lower()
        if sub:
            activity_subs[sub] = activity_subs.get(sub, 0) + 1

    scanned_at = datetime.now(timezone.utc).isoformat()
    gaps: List[AlertCoverageGap] = []

    for row in resource_rows:
        rtype = str(row.get("type", "")).lower()
        sub = str(row.get("subscription_id", "")).lower()
        count = int(row.get("resource_count", 0))

        meta = CRITICAL_RESOURCE_TYPES.get(rtype)
        if not meta:
            continue

        rule_count = covered.get((sub, rtype), 0)
        if rule_count > 0:
            continue  # already covered

        gap_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{sub}:{rtype}"))
        gaps.append(AlertCoverageGap(
            gap_id=gap_id,
            subscription_id=sub,
            resource_type=meta["friendly"],
            resource_count=count,
            alert_rule_count=0,
            severity=meta["severity"],
            recommendation=meta["recommendation"],
            scanned_at=scanned_at,
        ))

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "alert_rule_audit: scan complete | gaps=%d duration_ms=%d",
        len(gaps), duration_ms,
    )
    return gaps


def persist_gaps(
    cosmos_client: Any,
    db_name: str,
    gaps: List[AlertCoverageGap],
) -> None:
    """Upsert gaps into Cosmos DB container 'alert_coverage_gaps'.

    Never raises.
    """
    if not gaps:
        return
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client(
            "alert_coverage_gaps"
        )
        for g in gaps:
            container.upsert_item(g.to_dict())
        logger.info("alert_rule_audit: persisted %d gaps", len(gaps))
    except Exception as exc:  # noqa: BLE001
        logger.error("alert_rule_audit: persist failed | error=%s", exc)


def get_gaps(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    severity: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query coverage gaps from Cosmos DB.

    Never raises — returns empty list on error.
    """
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client(
            "alert_coverage_gaps"
        )
        conditions = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sid in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sid})

        if severity:
            conditions.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity})

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM c {where}"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("alert_rule_audit: get_gaps failed | error=%s", exc)
        return []


def get_alert_coverage_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregate summary of alert coverage gaps.

    Never raises.
    """
    try:
        gaps = get_gaps(cosmos_client, db_name)
        total = len(gaps)

        sev_counts: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0}
        sub_set: set = set()

        for g in gaps:
            sev = g.get("severity", "medium")
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
            sub = g.get("subscription_id", "")
            if sub:
                sub_set.add(sub)

        # Total possible (one gap per type per subscription, 11 types)
        possible = len(CRITICAL_RESOURCE_TYPES)
        if possible > 0 and total >= 0:
            overall_coverage_pct = max(0.0, round((1 - total / max(total + possible, 1)) * 100, 1))
        else:
            overall_coverage_pct = 100.0

        return {
            "total_gaps": total,
            "critical_gaps": sev_counts.get("critical", 0),
            "high_gaps": sev_counts.get("high", 0),
            "medium_gaps": sev_counts.get("medium", 0),
            "subscriptions_with_gaps": len(sub_set),
            "overall_coverage_pct": overall_coverage_pct,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("alert_rule_audit: summary failed | error=%s", exc)
        return {
            "total_gaps": 0,
            "critical_gaps": 0,
            "high_gaps": 0,
            "medium_gaps": 0,
            "subscriptions_with_gaps": 0,
            "overall_coverage_pct": 0.0,
        }
