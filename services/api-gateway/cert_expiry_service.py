"""TLS / Certificate Expiry Service — Phase 97.

Scans Azure Key Vault certificates and App Service certificates via ARG.
Reports any certs expiring within 90 days and persists findings to Cosmos DB.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass
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

_KQL_KV_CERTS = """
Resources
| where type =~ "microsoft.keyvault/vaults/certificates"
| extend props = parse_json(properties)
| extend expires_on = tostring(props.attributes.expires)
| extend enabled = tobool(props.attributes.enabled)
| where enabled == true
| extend days_until_expiry = datetime_diff('day', todatetime(expires_on), now())
| where days_until_expiry <= 90
| project subscriptionId, resourceGroup, name, vaultName = tostring(split(id, '/')[8]), expires_on, days_until_expiry, id
"""

_KQL_APPSVC_CERTS = """
Resources
| where type =~ "microsoft.web/certificates"
| extend expiry = tostring(properties.expirationDate)
| extend days_until_expiry = datetime_diff('day', todatetime(expiry), now())
| where days_until_expiry <= 90
| project subscriptionId, resourceGroup, name, expiry, days_until_expiry, id
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CertFinding:
    id: str
    subscription_id: str
    resource_group: str
    cert_name: str
    cert_type: str          # "keyvault" | "app_service"
    vault_or_app_name: str
    expires_on: str         # ISO
    days_until_expiry: int
    severity: str           # "critical" | "high" | "medium" | "low"
    scanned_at: str         # ISO
    arm_id: str


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _severity(days: int) -> str:
    if days <= 7:
        return "critical"
    if days <= 30:
        return "high"
    if days <= 60:
        return "medium"
    return "low"


def _stable_id(arm_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, arm_id.lower()))


def _row_to_kv_finding(row: Dict[str, Any], scanned_at: str) -> CertFinding:
    arm_id = row.get("id", "")
    days = int(row.get("days_until_expiry", 0))
    return CertFinding(
        id=_stable_id(arm_id),
        subscription_id=row.get("subscriptionId", ""),
        resource_group=row.get("resourceGroup", ""),
        cert_name=row.get("name", ""),
        cert_type="keyvault",
        vault_or_app_name=row.get("vaultName", ""),
        expires_on=row.get("expires_on", ""),
        days_until_expiry=days,
        severity=_severity(days),
        scanned_at=scanned_at,
        arm_id=arm_id,
    )


def _row_to_appsvc_finding(row: Dict[str, Any], scanned_at: str) -> CertFinding:
    arm_id = row.get("id", "")
    days = int(row.get("days_until_expiry", 0))
    # App name is the 8th segment of the ARM id: /subscriptions/.../resourceGroups/.../providers/.../certificates/<name>
    # We use the resourceGroup as the "app name" context since web/certificates is a
    # subscription-level resource; the name itself identifies the binding.
    parts = arm_id.split("/")
    app_name = parts[-3] if len(parts) >= 3 else row.get("resourceGroup", "")
    return CertFinding(
        id=_stable_id(arm_id),
        subscription_id=row.get("subscriptionId", ""),
        resource_group=row.get("resourceGroup", ""),
        cert_name=row.get("name", ""),
        cert_type="app_service",
        vault_or_app_name=app_name,
        expires_on=row.get("expiry", ""),
        days_until_expiry=days,
        severity=_severity(days),
        scanned_at=scanned_at,
        arm_id=arm_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_cert_expiry(
    credential: Any,
    subscription_ids: List[str],
) -> List[Dict[str, Any]]:
    """Scan Key Vault and App Service certificates expiring within 90 days.

    Returns a list of CertFinding dicts. Never raises.
    """
    start = time.monotonic()
    scanned_at = datetime.now(tz=timezone.utc).isoformat()

    if run_arg_query is None:
        logger.warning("cert_expiry_service: arg_helper not available — skipping scan")
        return []

    findings: List[CertFinding] = []

    # Key Vault certificates
    try:
        rows = run_arg_query(credential, subscription_ids, _KQL_KV_CERTS)
        for row in rows:
            try:
                findings.append(_row_to_kv_finding(row, scanned_at))
            except Exception as exc:
                logger.warning("cert_expiry_service: bad KV row: %s | row=%s", exc, row)
    except Exception as exc:
        logger.warning("cert_expiry_service: KV ARG query failed: %s", exc)

    # App Service certificates
    try:
        rows = run_arg_query(credential, subscription_ids, _KQL_APPSVC_CERTS)
        for row in rows:
            try:
                findings.append(_row_to_appsvc_finding(row, scanned_at))
            except Exception as exc:
                logger.warning("cert_expiry_service: bad AppSvc row: %s | row=%s", exc, row)
    except Exception as exc:
        logger.warning("cert_expiry_service: AppSvc ARG query failed: %s", exc)

    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "cert_expiry_service: scan complete | findings=%d duration_ms=%.0f",
        len(findings),
        duration_ms,
    )
    return [asdict(f) for f in findings]


def persist_cert_findings(
    cosmos_client: Any,
    db_name: str,
    findings: List[Dict[str, Any]],
) -> None:
    """Upsert CertFinding records into Cosmos DB 'cert_expiry' container. Never raises."""
    if not findings:
        return
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("cert_expiry")
        for finding in findings:
            container.upsert_item(finding)
        logger.info("cert_expiry_service: persisted %d findings", len(findings))
    except Exception as exc:
        logger.error("cert_expiry_service: persist_cert_findings failed: %s", exc)


def get_cert_findings(
    cosmos_client: Any,
    db_name: str,
    subscription_id: Optional[str] = None,
    severity: Optional[str] = None,
    cert_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch CertFinding records from Cosmos DB with optional filters. Never raises."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("cert_expiry")

        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_id:
            conditions.append("c.subscription_id = @sub")
            params.append({"name": "@sub", "value": subscription_id})
        if severity:
            conditions.append("c.severity = @sev")
            params.append({"name": "@sev", "value": severity.lower()})
        if cert_type:
            conditions.append("c.cert_type = @ct")
            params.append({"name": "@ct", "value": cert_type.lower()})

        where_clause = " AND ".join(conditions)
        query = f"SELECT * FROM c{' WHERE ' + where_clause if where_clause else ''}"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:
        logger.error("cert_expiry_service: get_cert_findings failed: %s", exc)
        return []


def get_cert_summary(
    cosmos_client: Any,
    db_name: str,
    subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return counts by severity and soonest expiry date. Never raises."""
    findings = get_cert_findings(cosmos_client, db_name, subscription_id=subscription_id)

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    low = sum(1 for f in findings if f.get("severity") == "low")

    soonest: Optional[str] = None
    min_days: Optional[int] = None
    for f in findings:
        d = f.get("days_until_expiry")
        if d is not None and (min_days is None or d < min_days):
            min_days = d
            soonest = f.get("expires_on")

    return {
        "total": len(findings),
        "critical_count": critical,
        "high_count": high,
        "medium_count": medium,
        "low_count": low,
        "soonest_expiry": soonest,
        "soonest_expiry_days": min_days,
    }
