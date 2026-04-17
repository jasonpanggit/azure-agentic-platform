from __future__ import annotations
"""Orphaned Disk & Snapshot Audit Service — Phase 100.

ARG scan for unattached managed disks and old snapshots (>30 days).
Persists findings to Cosmos DB container 'disk_audit'.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""
import os
import os

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL
_COSMOS_CONTAINER = "disk_audit"
_COSMOS_DB = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")

# Cost estimates per GB/month (USD)
_COST_PER_GB: Dict[str, float] = {
    "premium_lrs": 0.135,
    "premium_zrs": 0.135,
    "standardssd_lrs": 0.08,
    "standardssd_zrs": 0.08,
    "standard_lrs": 0.05,
    "ultrassd_lrs": 0.20,
}
_SNAPSHOT_COST_PER_GB = 0.05
_DEFAULT_DISK_COST_PER_GB = 0.05

_DISK_QUERY = """
Resources
| where type =~ "microsoft.compute/disks"
| extend diskState = tostring(properties.diskState)
| extend diskSizeGb = toint(properties.diskSizeGB)
| extend sku = tostring(sku.name)
| extend createdAt = tostring(properties.timeCreated)
| extend isOrphaned = (diskState =~ "Unattached")
| where isOrphaned == true
| project subscriptionId, resourceGroup, name, diskSizeGb, sku, createdAt, id
"""

_SNAPSHOT_QUERY = """
Resources
| where type =~ "microsoft.compute/snapshots"
| extend snapshotSizeGb = toint(properties.diskSizeGB)
| extend createdAt = tostring(properties.timeCreated)
| extend sourceResourceId = tostring(properties.creationData.sourceResourceId)
| extend daysOld = datetime_diff('day', now(), todatetime(createdAt))
| where daysOld > 30
| project subscriptionId, resourceGroup, name, snapshotSizeGb, createdAt, daysOld, sourceResourceId, id
"""


def _estimate_disk_cost(size_gb: int, sku: str) -> float:
    """Estimate monthly cost in USD for an orphaned disk."""
    sku_key = sku.lower().replace(" ", "_").replace("-", "_")
    cost_per_gb = _COST_PER_GB.get(sku_key, _DEFAULT_DISK_COST_PER_GB)
    return round(size_gb * cost_per_gb, 2)


def _estimate_snapshot_cost(size_gb: int) -> float:
    """Estimate monthly cost in USD for an old snapshot."""
    return round(size_gb * _SNAPSHOT_COST_PER_GB, 2)


def _days_old_from_created_at(created_at: str) -> int:
    """Compute days since creation from an ISO timestamp string."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = now - created
        return max(0, delta.days)
    except Exception:
        return 0


def _disk_severity(days_old: int) -> str:
    """All orphaned disks are high severity."""
    return "high"


def _snapshot_severity(days_old: int) -> str:
    """Snapshots >90d are medium, 30–90d are low."""
    if days_old > 90:
        return "medium"
    return "low"


def _build_disk_finding(row: Dict[str, Any], scanned_at: str) -> Dict[str, Any]:
    """Build a normalized disk finding from an ARG result row."""
    arm_id = row.get("id", "")
    finding_id = str(uuid.uuid5(_NAMESPACE, arm_id))

    size_gb = row.get("diskSizeGb") or 0
    sku = row.get("sku", "Standard_LRS")
    created_at = row.get("createdAt", "")
    days_old = _days_old_from_created_at(created_at)

    return {
        "id": finding_id,
        "subscription_id": row.get("subscriptionId", ""),
        "resource_group": row.get("resourceGroup", ""),
        "resource_name": row.get("name", ""),
        "resource_type": "disk",
        "size_gb": size_gb,
        "sku": sku,
        "days_old": days_old,
        "created_at": created_at,
        "estimated_monthly_cost_usd": _estimate_disk_cost(size_gb, sku),
        "severity": _disk_severity(days_old),
        "scanned_at": scanned_at,
    }


def _build_snapshot_finding(row: Dict[str, Any], scanned_at: str) -> Dict[str, Any]:
    """Build a normalized snapshot finding from an ARG result row."""
    arm_id = row.get("id", "")
    finding_id = str(uuid.uuid5(_NAMESPACE, arm_id))

    size_gb = row.get("snapshotSizeGb") or 0
    created_at = row.get("createdAt", "")
    days_old = row.get("daysOld") or _days_old_from_created_at(created_at)

    return {
        "id": finding_id,
        "subscription_id": row.get("subscriptionId", ""),
        "resource_group": row.get("resourceGroup", ""),
        "resource_name": row.get("name", ""),
        "resource_type": "snapshot",
        "size_gb": size_gb,
        "sku": "",
        "days_old": days_old,
        "created_at": created_at,
        "estimated_monthly_cost_usd": _estimate_snapshot_cost(size_gb),
        "severity": _snapshot_severity(days_old),
        "scanned_at": scanned_at,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_orphaned_disks(subscription_ids: List[str]) -> List[Dict[str, Any]]:
    """ARG scan for orphaned disks and old snapshots across the given subscriptions.

    Returns a flat list of findings (disks + snapshots combined).
    Never raises.
    """
    start_time = time.monotonic()

    if not subscription_ids:
        logger.warning("disk_audit_service: scan called with empty subscription list")
        return []

    try:
        from arg_helper import run_arg_query  # type: ignore[import]
    except ImportError:
        logger.warning("disk_audit_service: arg_helper not available — scan skipped")
        return []

    scanned_at = datetime.now(timezone.utc).isoformat()
    findings: List[Dict[str, Any]] = []

    # Scan orphaned disks
    try:
        disk_rows = run_arg_query(
            query=_DISK_QUERY,
            subscription_ids=subscription_ids,
        )
        for row in disk_rows:
            try:
                findings.append(_build_disk_finding(row, scanned_at))
            except Exception as row_exc:
                logger.warning(
                    "disk_audit_service: failed to process disk row | error=%s", row_exc
                )
    except Exception as exc:
        logger.warning("disk_audit_service: disk ARG query failed | error=%s", exc)

    # Scan old snapshots
    try:
        snapshot_rows = run_arg_query(
            query=_SNAPSHOT_QUERY,
            subscription_ids=subscription_ids,
        )
        for row in snapshot_rows:
            try:
                findings.append(_build_snapshot_finding(row, scanned_at))
            except Exception as row_exc:
                logger.warning(
                    "disk_audit_service: failed to process snapshot row | error=%s", row_exc
                )
    except Exception as exc:
        logger.warning("disk_audit_service: snapshot ARG query failed | error=%s", exc)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "disk_audit_service: scan complete | subscriptions=%d findings=%d (%.0fms)",
        len(subscription_ids),
        len(findings),
        duration_ms,
    )
    return findings


def persist_disk_findings(
    findings: List[Dict[str, Any]],
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
) -> None:
    """Persist disk audit findings to Cosmos DB disk_audit container.

    Never raises.
    """
    if not findings:
        return
    if cosmos_client is None:
        logger.warning("disk_audit_service: persist called without cosmos_client")
        return

    try:
        db = cosmos_client.get_database_client(cosmos_db)
        container = db.get_container_client(_COSMOS_CONTAINER)
        for finding in findings:
            container.upsert_item(finding)
        logger.info("disk_audit_service: persisted %d findings", len(findings))
    except Exception as exc:
        logger.warning("disk_audit_service: persist failed | error=%s", exc)


def get_disk_findings(
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
    subscription_id: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return disk audit findings from Cosmos DB with optional filters.

    Never raises — returns [] on error.
    """
    if cosmos_client is None:
        return []

    try:
        db = cosmos_client.get_database_client(cosmos_db)
        container = db.get_container_client(_COSMOS_CONTAINER)

        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_id:
            conditions.append("c.subscription_id = @subscription_id")
            params.append({"name": "@subscription_id", "value": subscription_id})
        if resource_type:
            conditions.append("c.resource_type = @resource_type")
            params.append({"name": "@resource_type", "value": resource_type})

        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (
            f"SELECT * FROM c{where_clause} "
            "ORDER BY c.estimated_monthly_cost_usd DESC"
        )

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]

    except Exception as exc:
        logger.warning("disk_audit_service: get_disk_findings error | error=%s", exc)
        return []


def get_disk_summary(
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
    subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return aggregated disk waste summary.

    Returns: total orphaned disks, old snapshots, total wasted GB,
    estimated total monthly cost USD.
    Never raises — returns zeroed summary on error.
    """
    empty: Dict[str, Any] = {
        "orphaned_disks": 0,
        "old_snapshots": 0,
        "total_wasted_gb": 0,
        "estimated_monthly_cost_usd": 0.0,
    }

    findings = get_disk_findings(
        cosmos_client=cosmos_client,
        cosmos_db=cosmos_db,
        subscription_id=subscription_id,
    )

    if not findings:
        return empty

    orphaned_disks = sum(1 for f in findings if f.get("resource_type") == "disk")
    old_snapshots = sum(1 for f in findings if f.get("resource_type") == "snapshot")
    total_wasted_gb = sum(f.get("size_gb", 0) for f in findings)
    estimated_monthly_cost_usd = round(
        sum(f.get("estimated_monthly_cost_usd", 0.0) for f in findings), 2
    )

    return {
        "orphaned_disks": orphaned_disks,
        "old_snapshots": old_snapshots,
        "total_wasted_gb": total_wasted_gb,
        "estimated_monthly_cost_usd": estimated_monthly_cost_usd,
    }
