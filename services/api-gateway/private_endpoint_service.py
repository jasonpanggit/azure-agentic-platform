"""Private Endpoint Compliance Service — ARG-based public network access audit (Phase 92).

Scans PaaS resources that should use Private Endpoints and identifies those with
public network access enabled. Persists findings to Cosmos DB.

Never raises from public functions.
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
# Resource type → friendly label
# ---------------------------------------------------------------------------

_TYPE_LABELS: Dict[str, str] = {
    "microsoft.storage/storageaccounts": "Storage Account",
    "microsoft.keyvault/vaults": "Key Vault",
    "microsoft.documentdb/databaseaccounts": "Cosmos DB",
    "microsoft.dbforpostgresql/flexibleservers": "PostgreSQL Flexible Server",
    "microsoft.sql/servers": "SQL Server",
    "microsoft.cognitiveservices/accounts": "Cognitive Services",
    "microsoft.containerregistry/registries": "Container Registry",
}

# ---------------------------------------------------------------------------
# KQL query
# ---------------------------------------------------------------------------

_KQL_PE = """
Resources
| where type in~ (
    'microsoft.storage/storageaccounts',
    'microsoft.keyvault/vaults',
    'microsoft.documentdb/databaseaccounts',
    'microsoft.dbforpostgresql/flexibleservers',
    'microsoft.sql/servers',
    'microsoft.cognitiveservices/accounts',
    'microsoft.containerregistry/registries'
  )
| project
    resource_id = tolower(id),
    name,
    type = tolower(type),
    resource_group = resourceGroup,
    subscription_id = subscriptionId,
    location,
    public_network_access = tostring(
        coalesce(
            properties.publicNetworkAccess,
            properties.networkAcls.defaultAction
        )
    ),
    private_endpoint_connections = array_length(properties.privateEndpointConnections)
| order by type asc, name asc
"""

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class PrivateEndpointFinding:
    finding_id: str
    resource_id: str
    resource_name: str
    resource_type: str          # friendly label
    resource_group: str
    subscription_id: str
    location: str
    public_access: str          # "enabled" | "disabled" | "unknown"
    has_private_endpoint: bool
    private_endpoint_count: int
    severity: str               # "high" | "medium" | "info"
    recommendation: str
    scanned_at: str
    ttl: int = field(default=86400)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_finding_id(resource_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, resource_id.lower()))


def _normalise_public_access(raw: str) -> str:
    val = (raw or "").lower().strip()
    if val in ("enabled", "allow"):
        return "enabled"
    if val in ("disabled", "deny"):
        return "disabled"
    return "unknown"


def _derive_severity(public_access: str, pe_count: int) -> str:
    if public_access == "enabled" and pe_count == 0:
        return "high"
    if public_access == "enabled" and pe_count > 0:
        return "medium"
    return "info"


def _make_recommendation(public_access: str, pe_count: int, resource_type: str) -> str:
    if public_access == "enabled" and pe_count == 0:
        return f"Configure a Private Endpoint for this {resource_type} and disable public network access."
    if public_access == "enabled" and pe_count > 0:
        return f"Private Endpoint exists but public network access is still enabled on this {resource_type}. Disable public access to enforce private-only connectivity."
    return "Resource is compliant — public network access is disabled."


# ---------------------------------------------------------------------------
# Public scan function
# ---------------------------------------------------------------------------

def scan_private_endpoint_compliance(
    credential: Any,
    subscription_ids: List[str],
) -> List[PrivateEndpointFinding]:
    """Scan Azure subscriptions for Private Endpoint compliance via ARG.

    Returns list of PrivateEndpointFinding. Never raises.
    """
    if not subscription_ids:
        logger.warning("pe_compliance: no subscription_ids provided")
        return []

    start_time = time.monotonic()
    try:
        rows = run_arg_query(credential, subscription_ids, _KQL_PE)
    except Exception as exc:  # noqa: BLE001
        logger.error("pe_compliance: ARG query failed | error=%s", exc)
        return []

    scanned_at = datetime.now(timezone.utc).isoformat()
    findings: List[PrivateEndpointFinding] = []

    for row in rows:
        resource_id = (row.get("resource_id") or "").lower()
        resource_name = row.get("name") or ""
        raw_type = (row.get("type") or "").lower()
        resource_group = row.get("resource_group") or ""
        subscription_id = row.get("subscription_id") or ""
        location = row.get("location") or ""
        raw_public = row.get("public_network_access") or ""
        raw_pe_count = row.get("private_endpoint_connections")

        if not resource_id:
            continue

        public_access = _normalise_public_access(raw_public)
        try:
            pe_count = int(raw_pe_count) if raw_pe_count is not None else 0
        except (ValueError, TypeError):
            pe_count = 0

        resource_type = _TYPE_LABELS.get(raw_type, raw_type)
        severity = _derive_severity(public_access, pe_count)
        recommendation = _make_recommendation(public_access, pe_count, resource_type)

        findings.append(PrivateEndpointFinding(
            finding_id=_make_finding_id(resource_id),
            resource_id=resource_id,
            resource_name=resource_name,
            resource_type=resource_type,
            resource_group=resource_group,
            subscription_id=subscription_id,
            location=location,
            public_access=public_access,
            has_private_endpoint=pe_count > 0,
            private_endpoint_count=pe_count,
            severity=severity,
            recommendation=recommendation,
            scanned_at=scanned_at,
        ))

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "pe_compliance: scan complete | resources=%d high=%d medium=%d duration_ms=%.0f",
        len(findings),
        sum(1 for f in findings if f.severity == "high"),
        sum(1 for f in findings if f.severity == "medium"),
        duration_ms,
    )
    return findings


# ---------------------------------------------------------------------------
# Cosmos DB persistence
# ---------------------------------------------------------------------------

def persist_findings(
    cosmos_client: Any,
    db_name: str,
    findings: List[PrivateEndpointFinding],
) -> None:
    """Upsert PE compliance findings into Cosmos DB. Never raises."""
    if not findings:
        return
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("pe_compliance")
        for finding in findings:
            doc = asdict(finding)
            doc["id"] = finding.finding_id
            container.upsert_item(doc)
        logger.info("pe_compliance: persisted %d findings", len(findings))
    except Exception as exc:  # noqa: BLE001
        logger.error("pe_compliance: persist failed | error=%s", exc)


def get_findings(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    severity: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> List[PrivateEndpointFinding]:
    """Query PE compliance findings from Cosmos DB. Never raises."""
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("pe_compliance")

        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sid in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sid})

        if severity:
            conditions.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity})

        if resource_type:
            conditions.append("c.resource_type = @resource_type")
            params.append({"name": "@resource_type", "value": resource_type})

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT * FROM c {where_clause} ORDER BY c._ts DESC"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))

        results: List[PrivateEndpointFinding] = []
        for item in items:
            try:
                results.append(PrivateEndpointFinding(
                    finding_id=item.get("finding_id", item.get("id", "")),
                    resource_id=item.get("resource_id", ""),
                    resource_name=item.get("resource_name", ""),
                    resource_type=item.get("resource_type", ""),
                    resource_group=item.get("resource_group", ""),
                    subscription_id=item.get("subscription_id", ""),
                    location=item.get("location", ""),
                    public_access=item.get("public_access", "unknown"),
                    has_private_endpoint=item.get("has_private_endpoint", False),
                    private_endpoint_count=item.get("private_endpoint_count", 0),
                    severity=item.get("severity", ""),
                    recommendation=item.get("recommendation", ""),
                    scanned_at=item.get("scanned_at", ""),
                    ttl=item.get("ttl", 86400),
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("pe_compliance: skip malformed item | error=%s", exc)

        return results
    except Exception as exc:  # noqa: BLE001
        logger.error("pe_compliance: get_findings failed | error=%s", exc)
        return []


def get_pe_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregate PE compliance summary. Never raises."""
    findings = get_findings(cosmos_client, db_name)

    total = len(findings)
    high_count = sum(1 for f in findings if f.severity == "high")
    medium_count = sum(1 for f in findings if f.severity == "medium")
    info_count = sum(1 for f in findings if f.severity == "info")
    pe_coverage_pct = round(info_count / total * 100, 1) if total > 0 else 0.0

    # Group by resource_type
    by_type: Dict[str, Dict[str, int]] = {}
    for f in findings:
        rt = f.resource_type or "Unknown"
        if rt not in by_type:
            by_type[rt] = {"total": 0, "high": 0, "medium": 0, "info": 0}
        by_type[rt]["total"] += 1
        by_type[rt][f.severity] += 1

    return {
        "total_resources": total,
        "high_count": high_count,
        "medium_count": medium_count,
        "info_count": info_count,
        "pe_coverage_pct": pe_coverage_pct,
        "by_resource_type": by_type,
    }
