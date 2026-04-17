"""Backup Compliance Service — ARG-based scan for VM backup coverage (Phase 91).

Scans Recovery Services Vaults and protected items via Azure Resource Graph,
identifies unprotected VMs, and persists findings to Cosmos DB.

Never raises from public functions — errors are logged and empty/partial results
returned to keep the API gateway fault-tolerant.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL

try:
    from services.api_gateway.arg_helper import run_arg_query  # type: ignore[import]
except ImportError:
    run_arg_query = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# KQL queries
# ---------------------------------------------------------------------------

_KQL_VAULTS = """
Resources
| where type =~ 'microsoft.recoveryservices/vaults'
| project
    vault_id = tolower(id),
    vault_name = name,
    resource_group = resourceGroup,
    subscription_id = subscriptionId,
    location,
    sku_name = tostring(sku.name),
    provisioning_state = tostring(properties.provisioningState)
"""

_KQL_PROTECTED_ITEMS = """
RecoveryServicesResources
| where type =~ 'microsoft.recoveryservices/vaults/backupfabrics/protectioncontainers/protecteditems'
| where properties.protectionState =~ 'Protected'
| project
    item_id = tolower(id),
    vault_id = tolower(tostring(split(id, '/backupFabrics/')[0])),
    resource_id = tolower(tostring(properties.sourceResourceId)),
    item_name = tostring(properties.friendlyName),
    backup_policy = tostring(properties.policyName),
    last_backup_time = tostring(properties.lastBackupTime),
    last_backup_status = tostring(properties.lastBackupStatus),
    health_status = tostring(properties.healthStatus),
    subscription_id = subscriptionId
"""

_KQL_VMS = """
Resources
| where type =~ 'microsoft.compute/virtualmachines'
| project
    vm_id = tolower(id),
    vm_name = name,
    resource_group = resourceGroup,
    subscription_id = subscriptionId,
    location
"""


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class BackupFinding:
    finding_id: str
    resource_id: str
    resource_name: str
    resource_group: str
    subscription_id: str
    location: str
    backup_status: str        # "protected" | "unprotected" | "unhealthy"
    backup_policy: str
    last_backup_time: str
    last_backup_status: str   # "Completed" | "Failed" | ""
    severity: str             # "critical" | "high" | "info"
    scanned_at: str
    ttl: int = field(default=86400)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_finding_id(resource_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, resource_id.lower()))


def _derive_severity(backup_status: str, last_backup_status: str) -> str:
    if backup_status == "unprotected":
        return "critical"
    if backup_status == "unhealthy" or last_backup_status == "Failed":
        return "high"
    return "info"


def _classify_health(
    health_status: str,
    last_backup_status: str,
) -> str:
    hs = (health_status or "").lower()
    lbs = (last_backup_status or "").lower()
    if hs in ("actionrequired", "actionsuggested") or lbs == "failed":
        return "unhealthy"
    return "protected"


# ---------------------------------------------------------------------------
# Public scan function
# ---------------------------------------------------------------------------

def scan_backup_compliance(
    credential: Any,
    subscription_ids: List[str],
) -> List[BackupFinding]:
    """Scan Azure subscriptions for VM backup compliance via ARG.

    Returns list of BackupFinding — one per VM. Never raises.
    """
    if not subscription_ids:
        logger.warning("backup_compliance: no subscription_ids provided")
        return []

    start_time = time.monotonic()
    try:
        vms_rows = run_arg_query(credential, subscription_ids, _KQL_VMS)
        protected_rows = run_arg_query(credential, subscription_ids, _KQL_PROTECTED_ITEMS)
    except Exception as exc:  # noqa: BLE001
        logger.error("backup_compliance: ARG query failed | error=%s", exc)
        return []

    scanned_at = datetime.now(timezone.utc).isoformat()

    # Build lookup: vm_id (lower) → protected-item row
    protected_map: Dict[str, Dict[str, Any]] = {}
    for row in protected_rows:
        rid = (row.get("resource_id") or "").lower()
        if rid:
            protected_map[rid] = row

    findings: List[BackupFinding] = []
    for vm in vms_rows:
        vm_id = (vm.get("vm_id") or "").lower()
        vm_name = vm.get("vm_name") or ""
        resource_group = vm.get("resource_group") or ""
        subscription_id = vm.get("subscription_id") or ""
        location = vm.get("location") or ""

        if not vm_id:
            continue

        protected_item = protected_map.get(vm_id)

        if protected_item is None:
            backup_status = "unprotected"
            backup_policy = ""
            last_backup_time = ""
            last_backup_status_val = ""
        else:
            raw_lbs = protected_item.get("last_backup_status") or ""
            raw_hs = protected_item.get("health_status") or ""
            backup_status = _classify_health(raw_hs, raw_lbs)
            backup_policy = protected_item.get("backup_policy") or ""
            last_backup_time = protected_item.get("last_backup_time") or ""
            last_backup_status_val = raw_lbs

        severity = _derive_severity(backup_status, last_backup_status_val)

        findings.append(BackupFinding(
            finding_id=_make_finding_id(vm_id),
            resource_id=vm_id,
            resource_name=vm_name,
            resource_group=resource_group,
            subscription_id=subscription_id,
            location=location,
            backup_status=backup_status,
            backup_policy=backup_policy,
            last_backup_time=last_backup_time,
            last_backup_status=last_backup_status_val,
            severity=severity,
            scanned_at=scanned_at,
        ))

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "backup_compliance: scan complete | vms=%d protected=%d duration_ms=%.0f",
        len(vms_rows),
        len(protected_map),
        duration_ms,
    )
    return findings


# ---------------------------------------------------------------------------
# Cosmos DB persistence
# ---------------------------------------------------------------------------

def persist_findings(
    cosmos_client: Any,
    db_name: str,
    findings: List[BackupFinding],
) -> None:
    """Upsert backup compliance findings into Cosmos DB. Never raises."""
    if not findings:
        return
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("backup_compliance")
        for finding in findings:
            doc = asdict(finding)
            doc["id"] = finding.finding_id
            container.upsert_item(doc)
        logger.info("backup_compliance: persisted %d findings", len(findings))
    except Exception as exc:  # noqa: BLE001
        logger.error("backup_compliance: persist failed | error=%s", exc)


def get_findings(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    backup_status: Optional[str] = None,
) -> List[BackupFinding]:
    """Query backup compliance findings from Cosmos DB. Never raises."""
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("backup_compliance")

        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sid in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sid})

        if backup_status:
            conditions.append("c.backup_status = @backup_status")
            params.append({"name": "@backup_status", "value": backup_status})

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT * FROM c {where_clause} ORDER BY c._ts DESC"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))

        results: List[BackupFinding] = []
        for item in items:
            try:
                results.append(BackupFinding(
                    finding_id=item.get("finding_id", item.get("id", "")),
                    resource_id=item.get("resource_id", ""),
                    resource_name=item.get("resource_name", ""),
                    resource_group=item.get("resource_group", ""),
                    subscription_id=item.get("subscription_id", ""),
                    location=item.get("location", ""),
                    backup_status=item.get("backup_status", ""),
                    backup_policy=item.get("backup_policy", ""),
                    last_backup_time=item.get("last_backup_time", ""),
                    last_backup_status=item.get("last_backup_status", ""),
                    severity=item.get("severity", ""),
                    scanned_at=item.get("scanned_at", ""),
                    ttl=item.get("ttl", 86400),
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("backup_compliance: skip malformed item | error=%s", exc)

        return results
    except Exception as exc:  # noqa: BLE001
        logger.error("backup_compliance: get_findings failed | error=%s", exc)
        return []


def get_backup_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregate backup compliance summary. Never raises."""
    findings = get_findings(cosmos_client, db_name)

    total_vms = len(findings)
    protected = sum(1 for f in findings if f.backup_status == "protected")
    unprotected = sum(1 for f in findings if f.backup_status == "unprotected")
    unhealthy = sum(1 for f in findings if f.backup_status == "unhealthy")
    recent_failures = sum(1 for f in findings if f.last_backup_status == "Failed")
    protection_rate = round(protected / total_vms * 100, 1) if total_vms > 0 else 0.0

    return {
        "total_vms": total_vms,
        "protected": protected,
        "unprotected": unprotected,
        "unhealthy": unhealthy,
        "protection_rate": protection_rate,
        "recent_failures": recent_failures,
    }
