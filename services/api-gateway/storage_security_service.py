from __future__ import annotations
"""Storage Account Security Audit Service — Phase 98.

Scans storage accounts for security misconfigurations via Azure Resource Graph
and persists findings to Cosmos DB.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL

try:
    from services.api_gateway.arg_helper import run_arg_query  # type: ignore[import]
except ImportError:
    run_arg_query = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# KQL query
# ---------------------------------------------------------------------------

_KQL_STORAGE = """
Resources
| where type =~ "microsoft.storage/storageaccounts"
| extend props = parse_json(properties)
| extend https_only = tobool(props.supportsHttpsTrafficOnly)
| extend allow_blob_public = tobool(props.allowBlobPublicAccess)
| extend min_tls = tostring(props.minimumTlsVersion)
| extend allow_shared_key = tobool(props.allowSharedKeyAccess)
| extend network_default = tostring(props.networkAcls.defaultAction)
| extend pe_count = array_length(props.privateEndpointConnections)
| project subscriptionId, resourceGroup, name, id, https_only, allow_blob_public, min_tls, allow_shared_key, network_default, pe_count
"""

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_SCORE_BLOB_PUBLIC = 40       # critical
_SCORE_HTTPS_ONLY = 25        # high
_SCORE_TLS10 = 25             # high
_SCORE_NETWORK_OPEN = 20      # high (when no private endpoints)
_SCORE_SHARED_KEY = 10        # medium


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class StorageFinding:
    id: str
    subscription_id: str
    resource_group: str
    account_name: str
    arm_id: str
    https_only: bool
    allow_blob_public: bool
    min_tls_version: str
    allow_shared_key: bool
    network_default_action: str
    private_endpoint_count: int
    risk_score: int
    findings: List[str] = field(default_factory=list)
    severity: str = "low"
    scanned_at: str = ""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _stable_id(arm_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, arm_id.lower()))


def _score_and_findings(row: Dict[str, Any]) -> tuple[int, List[str], str]:
    """Compute risk_score, findings list, and severity for a storage account row."""
    score = 0
    findings: List[str] = []

    if row.get("allow_blob_public") is True:
        score += _SCORE_BLOB_PUBLIC
        findings.append("Blob public access is enabled — unauthenticated reads allowed")

    if row.get("https_only") is False:
        score += _SCORE_HTTPS_ONLY
        findings.append("HTTPS-only traffic not enforced — HTTP connections permitted")

    if (row.get("min_tls") or "").upper() == "TLS1_0":
        score += _SCORE_TLS10
        findings.append("Minimum TLS version is TLS 1.0 — outdated protocol allowed")

    pe_count = int(row.get("pe_count") or 0)
    if (row.get("network_default") or "").lower() == "allow" and pe_count == 0:
        score += _SCORE_NETWORK_OPEN
        findings.append(
            "Network firewall default action is Allow with no private endpoints — publicly accessible"
        )

    if row.get("allow_shared_key") is True:
        score += _SCORE_SHARED_KEY
        findings.append("Shared key (storage account key) access is enabled — prefer Entra ID auth")

    # Clamp to 0-100
    score = min(score, 100)

    if score >= 40:
        severity = "critical"
    elif score >= 25:
        severity = "high"
    elif score >= 10:
        severity = "medium"
    else:
        severity = "low"

    return score, findings, severity


def _row_to_finding(row: Dict[str, Any], scanned_at: str) -> StorageFinding:
    arm_id = row.get("id", "")
    score, finding_list, severity = _score_and_findings(row)
    return StorageFinding(
        id=_stable_id(arm_id),
        subscription_id=row.get("subscriptionId", ""),
        resource_group=row.get("resourceGroup", ""),
        account_name=row.get("name", ""),
        arm_id=arm_id,
        https_only=bool(row.get("https_only")),
        allow_blob_public=bool(row.get("allow_blob_public")),
        min_tls_version=row.get("min_tls") or "",
        allow_shared_key=bool(row.get("allow_shared_key")),
        network_default_action=row.get("network_default") or "",
        private_endpoint_count=int(row.get("pe_count") or 0),
        risk_score=score,
        findings=finding_list,
        severity=severity,
        scanned_at=scanned_at,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_storage_security(
    credential: Any,
    subscription_ids: List[str],
) -> List[Dict[str, Any]]:
    """Scan storage accounts for security misconfigurations via ARG. Never raises."""
    start = time.monotonic()
    scanned_at = datetime.now(tz=timezone.utc).isoformat()

    if run_arg_query is None:
        logger.warning("storage_security_service: arg_helper not available — skipping scan")
        return []

    findings: List[StorageFinding] = []
    try:
        rows = run_arg_query(credential, subscription_ids, _KQL_STORAGE)
        for row in rows:
            try:
                f = _row_to_finding(row, scanned_at)
                if f.findings:  # Only persist accounts with at least one finding
                    findings.append(f)
            except Exception as exc:
                logger.warning("storage_security_service: bad row: %s | row=%s", exc, row)
    except Exception as exc:
        logger.warning("storage_security_service: ARG query failed: %s", exc)

    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "storage_security_service: scan complete | accounts_with_findings=%d duration_ms=%.0f",
        len(findings),
        duration_ms,
    )
    return [asdict(f) for f in findings]


def persist_storage_findings(
    cosmos_client: Any,
    db_name: str,
    findings: List[Dict[str, Any]],
) -> None:
    """Upsert StorageFinding records into Cosmos DB 'storage_security' container. Never raises."""
    if not findings:
        return
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("storage_security")
        for finding in findings:
            container.upsert_item(finding)
        logger.info("storage_security_service: persisted %d findings", len(findings))
    except Exception as exc:
        logger.error("storage_security_service: persist_storage_findings failed: %s", exc)


def get_storage_findings(
    cosmos_client: Any,
    db_name: str,
    subscription_id: Optional[str] = None,
    severity: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch StorageFinding records from Cosmos DB with optional filters. Never raises."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("storage_security")

        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_id:
            conditions.append("c.subscription_id = @sub")
            params.append({"name": "@sub", "value": subscription_id})
        if severity:
            conditions.append("c.severity = @sev")
            params.append({"name": "@sev", "value": severity.lower()})

        where_clause = " AND ".join(conditions)
        query = f"SELECT * FROM c{' WHERE ' + where_clause if where_clause else ''}"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:
        logger.error("storage_security_service: get_storage_findings failed: %s", exc)
        return []


def get_storage_summary(
    cosmos_client: Any,
    db_name: str,
    subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return aggregate summary of storage security findings. Never raises."""
    findings = get_storage_findings(cosmos_client, db_name, subscription_id=subscription_id)

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    low = sum(1 for f in findings if f.get("severity") == "low")

    # Top risks: most common finding descriptions
    risk_counter: Dict[str, int] = {}
    for f in findings:
        for desc in f.get("findings", []):
            risk_counter[desc] = risk_counter.get(desc, 0) + 1
    top_risks = sorted(risk_counter.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total_accounts": len(findings),
        "critical_count": critical,
        "high_count": high,
        "medium_count": medium,
        "low_count": low,
        "top_risks": [{"description": r[0], "count": r[1]} for r in top_risks],
    }
