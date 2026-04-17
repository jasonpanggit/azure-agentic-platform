"""Resource lock audit service.

Scans Azure for high-value resources missing CanNotDelete / ReadOnly locks.
This is a governance gap finder — critical resources without delete protection
are a significant operational risk.

Never raises; all public functions return [] or {} on error.
"""
from __future__ import annotations

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
# Resource type display names
# ──────────────────────────────────────────────────────────────────────────────

_RESOURCE_TYPE_LABELS: Dict[str, str] = {
    "microsoft.compute/virtualmachines": "Virtual Machine",
    "microsoft.storage/storageaccounts": "Storage Account",
    "microsoft.keyvault/vaults": "Key Vault",
    "microsoft.documentdb/databaseaccounts": "Cosmos DB Account",
    "microsoft.dbforpostgresql/flexibleservers": "PostgreSQL Flexible Server",
    "microsoft.sql/servers": "SQL Server",
    "microsoft.network/virtualnetworks": "Virtual Network",
    "microsoft.recoveryservices/vaults": "Recovery Services Vault",
}

_HIGH_VALUE_TYPES = list(_RESOURCE_TYPE_LABELS.keys())

# ──────────────────────────────────────────────────────────────────────────────
# Dataclass
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class LockFinding:
    finding_id: str
    resource_id: str
    resource_name: str
    resource_type: str          # human label: "Virtual Machine"
    resource_type_raw: str      # raw ARG type lower: "microsoft.compute/virtualmachines"
    resource_group: str
    subscription_id: str
    location: str
    lock_status: str            # "no_lock" | "rg_lock_only" | "resource_lock"
    severity: str               # "high" | "medium"
    recommendation: str
    scanned_at: str
    ttl: int = 604800           # 7 days


# ──────────────────────────────────────────────────────────────────────────────
# KQL queries
# ──────────────────────────────────────────────────────────────────────────────

_HIGH_VALUE_RESOURCES_KQL = """
Resources
| where type in~ (
    'microsoft.compute/virtualmachines',
    'microsoft.storage/storageaccounts',
    'microsoft.keyvault/vaults',
    'microsoft.documentdb/databaseaccounts',
    'microsoft.dbforpostgresql/flexibleservers',
    'microsoft.sql/servers',
    'microsoft.network/virtualnetworks',
    'microsoft.recoveryservices/vaults'
  )
| project
    resource_id = tolower(id),
    name,
    resource_type = tolower(type),
    resourceGroup = tolower(resourceGroup),
    subscriptionId,
    location
"""

_LOCKS_KQL = """
Resources
| where type =~ 'microsoft.authorization/locks'
| project
    lock_id = tolower(id),
    lock_name = name,
    lock_level = tostring(properties.level),
    scope = tolower(tostring(split(id, '/providers/microsoft.authorization/locks')[0]))
"""


# ──────────────────────────────────────────────────────────────────────────────
# Core scan
# ──────────────────────────────────────────────────────────────────────────────


def scan_lock_compliance(
    credential: Any,
    subscription_ids: List[str],
) -> List[LockFinding]:
    """Scan all high-value resources and identify those missing resource-level locks.

    Returns a LockFinding for every resource that lacks a resource-level lock.
    Severity is 'medium' if a resource-group lock covers it, 'high' otherwise.
    """
    if not subscription_ids:
        logger.warning("lock_audit: no subscription_ids provided; skipping scan")
        return []

    start = time.monotonic()
    try:
        # 1. Fetch high-value resources
        resources = run_arg_query(credential, subscription_ids, _HIGH_VALUE_RESOURCES_KQL)

        # 2. Fetch all lock scopes
        locks_raw = run_arg_query(credential, subscription_ids, _LOCKS_KQL)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "lock_audit: ARG queries complete | resources=%d locks=%d duration_ms=%d",
            len(resources),
            len(locks_raw),
            duration_ms,
        )

        # Build a set of locked scopes (resource IDs and resource-group IDs)
        resource_locked_scopes: set[str] = set()
        rg_locked_scopes: set[str] = set()

        for lock in locks_raw:
            scope = (lock.get("scope") or "").lower().rstrip("/")
            if not scope:
                continue
            # Resource group scope: ends with /resourcegroups/<name> and has no further path
            parts = scope.split("/")
            # A resource group scope looks like: /subscriptions/.../resourcegroups/rg-name  (6 parts after split on '/')
            # A resource scope has more segments
            if len(parts) <= 6:
                rg_locked_scopes.add(scope)
            else:
                resource_locked_scopes.add(scope)

        findings: List[LockFinding] = []
        scanned_at = datetime.now(timezone.utc).isoformat()

        for row in resources:
            resource_id = (row.get("resource_id") or "").lower()
            resource_name = row.get("name") or ""
            resource_type_raw = (row.get("resource_type") or "").lower()
            resource_group = (row.get("resourceGroup") or "").lower()
            subscription_id = row.get("subscriptionId") or ""
            location = row.get("location") or ""

            if not resource_id:
                continue

            # Check resource-level lock
            has_resource_lock = resource_id in resource_locked_scopes

            if has_resource_lock:
                # Fully protected — not a finding
                continue

            # Check resource-group-level lock
            rg_scope = f"/subscriptions/{subscription_id.lower()}/resourcegroups/{resource_group}"
            has_rg_lock = rg_scope in rg_locked_scopes

            lock_status = "rg_lock_only" if has_rg_lock else "no_lock"
            severity = "medium" if has_rg_lock else "high"
            resource_type_label = _RESOURCE_TYPE_LABELS.get(resource_type_raw, resource_type_raw)
            recommendation = (
                f"Add CanNotDelete lock directly on {resource_type_label} '{resource_name}' "
                "to prevent accidental deletion. Resource-group locks can be bypassed by moving "
                "the resource out of the group."
                if has_rg_lock
                else f"Add CanNotDelete lock to {resource_type_label} '{resource_name}' "
                "to prevent accidental deletion. This resource has no lock protection."
            )

            finding_id = str(uuid.uuid5(uuid.NAMESPACE_URL, resource_id))

            findings.append(
                LockFinding(
                    finding_id=finding_id,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    resource_type=resource_type_label,
                    resource_type_raw=resource_type_raw,
                    resource_group=resource_group,
                    subscription_id=subscription_id,
                    location=location,
                    lock_status=lock_status,
                    severity=severity,
                    recommendation=recommendation,
                    scanned_at=scanned_at,
                )
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "lock_audit: scan complete | findings=%d duration_ms=%d",
            len(findings),
            duration_ms,
        )
        return findings

    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "lock_audit: scan failed | error=%s duration_ms=%d",
            exc,
            duration_ms,
        )
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Cosmos persistence
# ──────────────────────────────────────────────────────────────────────────────

_CONTAINER_NAME = "lock_findings"


def _to_cosmos_doc(finding: LockFinding) -> Dict[str, Any]:
    return {
        "id": finding.finding_id,
        "finding_id": finding.finding_id,
        "resource_id": finding.resource_id,
        "resource_name": finding.resource_name,
        "resource_type": finding.resource_type,
        "resource_type_raw": finding.resource_type_raw,
        "resource_group": finding.resource_group,
        "subscription_id": finding.subscription_id,
        "location": finding.location,
        "lock_status": finding.lock_status,
        "severity": finding.severity,
        "recommendation": finding.recommendation,
        "scanned_at": finding.scanned_at,
        "ttl": finding.ttl,
    }


def _from_cosmos_doc(doc: Dict[str, Any]) -> LockFinding:
    return LockFinding(
        finding_id=doc.get("finding_id", doc.get("id", "")),
        resource_id=doc.get("resource_id", ""),
        resource_name=doc.get("resource_name", ""),
        resource_type=doc.get("resource_type", ""),
        resource_type_raw=doc.get("resource_type_raw", ""),
        resource_group=doc.get("resource_group", ""),
        subscription_id=doc.get("subscription_id", ""),
        location=doc.get("location", ""),
        lock_status=doc.get("lock_status", "no_lock"),
        severity=doc.get("severity", "high"),
        recommendation=doc.get("recommendation", ""),
        scanned_at=doc.get("scanned_at", ""),
        ttl=doc.get("ttl", 604800),
    )


def persist_lock_findings(
    cosmos_client: Any,
    db_name: str,
    findings: List[LockFinding],
) -> None:
    """Upsert lock findings into Cosmos DB. Never raises."""
    if not findings:
        return
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client(_CONTAINER_NAME)
        for finding in findings:
            doc = _to_cosmos_doc(finding)
            container.upsert_item(doc)
        logger.info("lock_audit: persisted %d findings", len(findings))
    except Exception as exc:  # noqa: BLE001
        logger.warning("lock_audit: persist failed | error=%s", exc)


def get_lock_findings(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    severity: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> List[LockFinding]:
    """Query lock findings from Cosmos. Never raises."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client(_CONTAINER_NAME)

        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sub in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sub})

        if severity:
            conditions.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity.lower()})

        if resource_type:
            conditions.append("CONTAINS(LOWER(c.resource_type), @resource_type)")
            params.append({"name": "@resource_type", "value": resource_type.lower()})

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT * FROM c {where} ORDER BY c.scanned_at DESC"

        items = list(
            container.query_items(
                query=query,
                parameters=params if params else None,
                enable_cross_partition_query=True,
            )
        )
        return [_from_cosmos_doc(doc) for doc in items]
    except Exception as exc:  # noqa: BLE001
        logger.warning("lock_audit: get_findings failed | error=%s", exc)
        return []


def get_lock_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregate stats for the lock audit dashboard. Never raises."""
    try:
        findings = get_lock_findings(cosmos_client, db_name)
        high = [f for f in findings if f.severity == "high"]
        medium = [f for f in findings if f.severity == "medium"]

        by_type: Dict[str, int] = {}
        for f in findings:
            by_type[f.resource_type] = by_type.get(f.resource_type, 0) + 1

        sub_counts: Dict[str, int] = {}
        for f in findings:
            sub_counts[f.subscription_id] = sub_counts.get(f.subscription_id, 0) + 1
        top_subscriptions = sorted(sub_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "total_unprotected": len(findings),
            "high_count": len(high),
            "medium_count": len(medium),
            "by_resource_type": by_type,
            "top_subscriptions": [
                {"subscription_id": sub, "count": cnt} for sub, cnt in top_subscriptions
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("lock_audit: get_summary failed | error=%s", exc)
        return {
            "total_unprotected": 0,
            "high_count": 0,
            "medium_count": 0,
            "by_resource_type": {},
            "top_subscriptions": [],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Remediation script generator
# ──────────────────────────────────────────────────────────────────────────────

# Map raw ARG type → az resource type argument
_AZ_RESOURCE_TYPE_MAP: Dict[str, str] = {
    "microsoft.compute/virtualmachines": "Microsoft.Compute/virtualMachines",
    "microsoft.storage/storageaccounts": "Microsoft.Storage/storageAccounts",
    "microsoft.keyvault/vaults": "Microsoft.KeyVault/vaults",
    "microsoft.documentdb/databaseaccounts": "Microsoft.DocumentDB/databaseAccounts",
    "microsoft.dbforpostgresql/flexibleservers": "Microsoft.DBforPostgreSQL/flexibleServers",
    "microsoft.sql/servers": "Microsoft.Sql/servers",
    "microsoft.network/virtualnetworks": "Microsoft.Network/virtualNetworks",
    "microsoft.recoveryservices/vaults": "Microsoft.RecoveryServices/vaults",
}


def generate_lock_remediation_script(findings: List[LockFinding]) -> str:
    """Generate an az CLI script to add CanNotDelete locks for each finding.

    Returns a shell script string. Never raises.
    """
    try:
        lines: List[str] = [
            "#!/bin/bash",
            "# Resource Lock Remediation Script",
            "# Generated by Azure Agentic Platform — Lock Audit Service",
            "# Run this script to add CanNotDelete locks to unprotected resources.",
            "# Review each command before executing in production.",
            "",
            "set -euo pipefail",
            "",
        ]

        high_findings = [f for f in findings if f.severity == "high"]
        medium_findings = [f for f in findings if f.severity == "medium"]

        if high_findings:
            lines.append("# ── HIGH SEVERITY: No lock protection ─────────────────────────────")
            for f in high_findings:
                az_type = _AZ_RESOURCE_TYPE_MAP.get(f.resource_type_raw, f.resource_type_raw)
                lines.append(
                    f"az lock create"
                    f' --name "NoDelete-{f.resource_name}"'
                    f' --resource-group "{f.resource_group}"'
                    f' --resource-name "{f.resource_name}"'
                    f' --resource-type "{az_type}"'
                    f' --lock-type CanNotDelete'
                    f' --subscription "{f.subscription_id}"'
                )
            lines.append("")

        if medium_findings:
            lines.append(
                "# ── MEDIUM SEVERITY: RG lock exists but no resource-level lock ─────────"
            )
            for f in medium_findings:
                az_type = _AZ_RESOURCE_TYPE_MAP.get(f.resource_type_raw, f.resource_type_raw)
                lines.append(
                    f"az lock create"
                    f' --name "NoDelete-{f.resource_name}"'
                    f' --resource-group "{f.resource_group}"'
                    f' --resource-name "{f.resource_name}"'
                    f' --resource-type "{az_type}"'
                    f' --lock-type CanNotDelete'
                    f' --subscription "{f.subscription_id}"'
                )
            lines.append("")

        if not findings:
            lines.append("# No findings to remediate.")

        lines.append("echo 'Lock remediation complete.'")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        logger.warning("lock_audit: remediation script generation failed | error=%s", exc)
        return "#!/bin/bash\n# Error generating remediation script.\n"
