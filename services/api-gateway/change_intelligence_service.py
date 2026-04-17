from __future__ import annotations
"""Activity Log Change Intelligence service — Phase 81.

Scans Azure Activity Logs via the ARG ``resourcechanges`` table and surfaces
recent high-impact infrastructure changes, linking them to incidents.

Never raises from public functions; all return [] or {} on error.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from services.api_gateway.arg_helper import run_arg_query
except Exception:  # noqa: BLE001
    run_arg_query = None  # type: ignore[assignment]

# ──────────────────────────────────────────────────────────────────────────────
# Resource type — friendly display names
# ──────────────────────────────────────────────────────────────────────────────

_RESOURCE_TYPE_LABELS: Dict[str, str] = {
    "microsoft.compute/virtualmachines": "Virtual Machine",
    "microsoft.compute/virtualmachinescalesets": "VMSS",
    "microsoft.network/virtualnetworks": "Virtual Network",
    "microsoft.network/networksecuritygroups": "NSG",
    "microsoft.network/azurefirewalls": "Azure Firewall",
    "microsoft.network/loadbalancers": "Load Balancer",
    "microsoft.keyvault/vaults": "Key Vault",
    "microsoft.storage/storageaccounts": "Storage Account",
    "microsoft.containerservice/managedclusters": "AKS Cluster",
    "microsoft.documentdb/databaseaccounts": "Cosmos DB",
    "microsoft.dbforpostgresql/flexibleservers": "PostgreSQL Flexible Server",
    "microsoft.sql/servers": "SQL Server",
    "microsoft.web/sites": "App Service",
    "microsoft.recoveryservices/vaults": "Recovery Services Vault",
}

# Critical types where Delete is very high impact
_CRITICAL_DELETE_TYPES = {
    "microsoft.compute/virtualmachines",
    "microsoft.network/virtualnetworks",
    "microsoft.keyvault/vaults",
    "microsoft.storage/storageaccounts",
    "microsoft.containerservice/managedclusters",
    "microsoft.documentdb/databaseaccounts",
    "microsoft.recoveryservices/vaults",
}

# Types where Create/Update on security controls is high impact
_SECURITY_CONTROL_TYPES = {
    "microsoft.network/networksecuritygroups",
    "microsoft.network/azurefirewalls",
    "microsoft.network/applicationgateways",
}

# Types where update carries elevated risk
_ELEVATED_UPDATE_TYPES = {
    "microsoft.compute/virtualmachines",
    "microsoft.containerservice/managedclusters",
    "microsoft.compute/virtualmachinescalesets",
}

# ──────────────────────────────────────────────────────────────────────────────
# Dataclass
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ChangeRecord:
    change_id: str           # uuid5(NAMESPACE_URL, arm_change_id)
    subscription_id: str
    resource_id: str
    resource_name: str       # extracted from resource_id
    resource_type: str       # short friendly name
    change_type: str         # Create / Update / Delete
    changed_by: str          # UPN or service principal
    timestamp: str           # ISO
    resource_group: str
    impact_score: float      # 0.0–1.0
    impact_reason: str       # why it's scored high
    captured_at: str
    ttl: int = field(default=86400)  # 24 h


# ──────────────────────────────────────────────────────────────────────────────
# ARG KQL
# ──────────────────────────────────────────────────────────────────────────────

_CHANGES_KQL = """
resourcechanges
| where properties.changeType in~ ('Create', 'Update', 'Delete')
| where properties.targetResourceType !in~ (
    'microsoft.resources/deployments',
    'microsoft.resources/tags'
  )
| project
    change_id = tolower(id),
    subscription_id = subscriptionId,
    resource_id = tolower(tostring(properties.targetResourceId)),
    resource_type = tolower(tostring(properties.targetResourceType)),
    change_type = tostring(properties.changeType),
    changed_by = tostring(properties.changeAttributes.changedBy),
    timestamp = tostring(properties.changeAttributes.timestamp),
    resource_group = resourceGroup
| where timestamp > ago({hours}h)
| order by timestamp desc
| limit 200
"""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _extract_resource_name(resource_id: str) -> str:
    """Return the last non-empty path segment of an ARM resource ID."""
    parts = [p for p in resource_id.split("/") if p]
    return parts[-1] if parts else resource_id


def _friendly_type(raw_type: str) -> str:
    return _RESOURCE_TYPE_LABELS.get(raw_type.lower(), raw_type.lower())


def _score_impact(
    resource_type: str,
    change_type: str,
) -> tuple[float, str]:
    """Return (impact_score, impact_reason) for a change record."""
    rt = resource_type.lower()
    ct = change_type.lower()

    if ct == "delete" and rt in _CRITICAL_DELETE_TYPES:
        label = _RESOURCE_TYPE_LABELS.get(rt, rt)
        return 0.9, f"Delete on critical resource type: {label}"

    if ct in ("create", "update") and rt in _SECURITY_CONTROL_TYPES:
        label = _RESOURCE_TYPE_LABELS.get(rt, rt)
        return 0.8, f"{change_type} on security control: {label}"

    if ct == "update" and rt in _ELEVATED_UPDATE_TYPES:
        label = _RESOURCE_TYPE_LABELS.get(rt, rt)
        return 0.7, f"Update on production workload: {label}"

    if ct == "create":
        return 0.6, "New resource created"

    return 0.3, "Routine change"


def _build_record(row: Dict[str, Any], captured_at: str) -> Optional[ChangeRecord]:
    """Convert an ARG result row to a ChangeRecord. Returns None on missing data."""
    arm_change_id = row.get("change_id") or ""
    resource_id = (row.get("resource_id") or "").lower()
    if not resource_id:
        return None

    resource_type_raw = (row.get("resource_type") or "").lower()
    change_type = row.get("change_type") or "Update"
    impact_score, impact_reason = _score_impact(resource_type_raw, change_type)

    stable_id = str(uuid.uuid5(uuid.NAMESPACE_URL, arm_change_id or resource_id))

    return ChangeRecord(
        change_id=stable_id,
        subscription_id=row.get("subscription_id") or "",
        resource_id=resource_id,
        resource_name=_extract_resource_name(resource_id),
        resource_type=_friendly_type(resource_type_raw),
        change_type=change_type,
        changed_by=row.get("changed_by") or "unknown",
        timestamp=row.get("timestamp") or captured_at,
        resource_group=(row.get("resource_group") or "").lower(),
        impact_score=impact_score,
        impact_reason=impact_reason,
        captured_at=captured_at,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def scan_recent_changes(
    credential: Any,
    subscription_ids: List[str],
    hours: int = 24,
) -> List[ChangeRecord]:
    """Query ARG for recent resource changes. Never raises."""
    if not subscription_ids:
        logger.warning("change_intelligence: no subscription_ids provided; skipping scan")
        return []
    if run_arg_query is None:
        logger.warning("change_intelligence: arg_helper not available; skipping scan")
        return []

    start = time.monotonic()
    captured_at = datetime.now(timezone.utc).isoformat()

    try:
        kql = _CHANGES_KQL.replace("{hours}", str(max(1, hours)))
        rows = run_arg_query(credential, subscription_ids, kql)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "change_intelligence: ARG query complete | rows=%d duration_ms=%d",
            len(rows),
            duration_ms,
        )

        records: List[ChangeRecord] = []
        for row in rows:
            record = _build_record(row, captured_at)
            if record:
                records.append(record)

        logger.info(
            "change_intelligence: scan complete | records=%d duration_ms=%d",
            len(records),
            int((time.monotonic() - start) * 1000),
        )
        return records

    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "change_intelligence: scan failed | error=%s duration_ms=%d",
            exc,
            duration_ms,
        )
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Cosmos persistence
# ──────────────────────────────────────────────────────────────────────────────

_CONTAINER_NAME = "change_records"


def _to_cosmos_doc(record: ChangeRecord) -> Dict[str, Any]:
    return {
        "id": record.change_id,
        "change_id": record.change_id,
        "subscription_id": record.subscription_id,
        "resource_id": record.resource_id,
        "resource_name": record.resource_name,
        "resource_type": record.resource_type,
        "change_type": record.change_type,
        "changed_by": record.changed_by,
        "timestamp": record.timestamp,
        "resource_group": record.resource_group,
        "impact_score": record.impact_score,
        "impact_reason": record.impact_reason,
        "captured_at": record.captured_at,
        "ttl": record.ttl,
    }


def _from_cosmos_doc(doc: Dict[str, Any]) -> ChangeRecord:
    return ChangeRecord(
        change_id=doc.get("change_id", doc.get("id", "")),
        subscription_id=doc.get("subscription_id", ""),
        resource_id=doc.get("resource_id", ""),
        resource_name=doc.get("resource_name", ""),
        resource_type=doc.get("resource_type", ""),
        change_type=doc.get("change_type", "Update"),
        changed_by=doc.get("changed_by", "unknown"),
        timestamp=doc.get("timestamp", ""),
        resource_group=doc.get("resource_group", ""),
        impact_score=float(doc.get("impact_score", 0.3)),
        impact_reason=doc.get("impact_reason", ""),
        captured_at=doc.get("captured_at", ""),
        ttl=int(doc.get("ttl", 86400)),
    )


def persist_changes(
    cosmos_client: Any,
    db_name: str,
    changes: List[ChangeRecord],
) -> None:
    """Upsert change records into Cosmos DB. Never raises."""
    if not changes:
        return
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client(_CONTAINER_NAME)
        for record in changes:
            container.upsert_item(_to_cosmos_doc(record))
        logger.info("change_intelligence: persisted %d records", len(changes))
    except Exception as exc:  # noqa: BLE001
        logger.warning("change_intelligence: persist failed | error=%s", exc)


def get_changes(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    min_impact: float = 0.0,
    change_type: Optional[str] = None,
) -> List[ChangeRecord]:
    """Query change records from Cosmos. Never raises."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client(_CONTAINER_NAME)

        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sub in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sub})

        if min_impact > 0.0:
            conditions.append("c.impact_score >= @min_impact")
            params.append({"name": "@min_impact", "value": min_impact})

        if change_type:
            conditions.append("LOWER(c.change_type) = @change_type")
            params.append({"name": "@change_type", "value": change_type.lower()})

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT * FROM c {where} ORDER BY c.timestamp DESC"

        items = list(
            container.query_items(
                query=query,
                parameters=params if params else None,
                enable_cross_partition_query=True,
            )
        )
        return [_from_cosmos_doc(doc) for doc in items]
    except Exception as exc:  # noqa: BLE001
        logger.warning("change_intelligence: get_changes failed | error=%s", exc)
        return []


def get_change_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregate stats for the change intelligence dashboard. Never raises."""
    try:
        records = get_changes(cosmos_client, db_name)

        deletes = [r for r in records if r.change_type.lower() == "delete"]
        creates = [r for r in records if r.change_type.lower() == "create"]
        updates = [r for r in records if r.change_type.lower() == "update"]
        high_impact = [r for r in records if r.impact_score >= 0.7]

        changer_counts: Dict[str, int] = {}
        for r in records:
            changer_counts[r.changed_by] = changer_counts.get(r.changed_by, 0) + 1
        top_changers = sorted(changer_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "total": len(records),
            "deletes": len(deletes),
            "creates": len(creates),
            "updates": len(updates),
            "high_impact_count": len(high_impact),
            "top_changers": [
                {"changed_by": changer, "count": cnt} for changer, cnt in top_changers
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("change_intelligence: get_summary failed | error=%s", exc)
        return {
            "total": 0,
            "deletes": 0,
            "creates": 0,
            "updates": 0,
            "high_impact_count": 0,
            "top_changers": [],
        }
