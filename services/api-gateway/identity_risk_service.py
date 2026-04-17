"""Identity Risk Service — Phase 93.

Scans service principal credential expiry via Microsoft Graph API.
Falls back gracefully (returns []) if Graph permissions are not available.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import requests  # type: ignore[import]
except ImportError:
    requests = None  # type: ignore[assignment]


@dataclass
class CredentialRisk:
    risk_id: str
    service_principal_id: str
    service_principal_name: str
    credential_type: str   # "password" | "certificate"
    credential_name: str
    expiry_date: str       # ISO date
    days_until_expiry: int # negative = already expired
    severity: str          # "critical" | "high" | "medium"
    detected_at: str
    ttl: int = 86400       # 24h


def _days_until(expiry_iso: str) -> int:
    """Return days from now until expiry_iso. Negative = already expired."""
    try:
        expiry = datetime.fromisoformat(expiry_iso.rstrip("Z")).replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        return (expiry.date() - now.date()).days
    except Exception:
        return 0


def _severity(days: int) -> str:
    if days < 0:
        return "critical"
    if days < 30:
        return "high"
    return "medium"


def _stable_id(sp_id: str, key_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{sp_id}:{key_id}"))


def _build_risks_from_sp(sp: Dict[str, Any], detected_at: str) -> List[CredentialRisk]:
    """Parse a Graph servicePrincipal response into CredentialRisk records."""
    risks: List[CredentialRisk] = []
    sp_id = sp.get("id", "")
    sp_name = sp.get("displayName", sp_id)

    for cred in sp.get("passwordCredentials", []) or []:
        end_date: Optional[str] = cred.get("endDateTime")
        if not end_date:
            continue
        key_id = cred.get("keyId", "")
        days = _days_until(end_date)
        if days >= 90:
            continue  # Only report within 90 days
        risks.append(CredentialRisk(
            risk_id=_stable_id(sp_id, key_id),
            service_principal_id=sp_id,
            service_principal_name=sp_name,
            credential_type="password",
            credential_name=cred.get("displayName") or key_id or "password",
            expiry_date=end_date,
            days_until_expiry=days,
            severity=_severity(days),
            detected_at=detected_at,
        ))

    for cred in sp.get("keyCredentials", []) or []:
        end_date = cred.get("endDateTime")
        if not end_date:
            continue
        key_id = cred.get("keyId", "")
        days = _days_until(end_date)
        if days >= 90:
            continue
        risks.append(CredentialRisk(
            risk_id=_stable_id(sp_id, key_id),
            service_principal_id=sp_id,
            service_principal_name=sp_name,
            credential_type="certificate",
            credential_name=cred.get("displayName") or key_id or "certificate",
            expiry_date=end_date,
            days_until_expiry=days,
            severity=_severity(days),
            detected_at=detected_at,
        ))

    return risks


def scan_credential_risks(
    credential: Any,
    tenant_id: Optional[str] = None,
) -> List[CredentialRisk]:
    """Scan service principals via Microsoft Graph API for expiring credentials.

    Returns [] gracefully if Graph API is inaccessible (401/403) or SDK missing.
    Never raises.
    """
    detected_at = datetime.now(tz=timezone.utc).isoformat()
    risks: List[CredentialRisk] = []

    if requests is None:
        logger.warning("identity_risk_service: requests not installed — skipping Graph scan")
        return []

    # Acquire Graph token via DefaultAzureCredential
    try:
        token_obj = credential.get_token("https://graph.microsoft.com/.default")
        token = token_obj.token
    except Exception as exc:
        logger.warning("identity_risk_service: failed to acquire Graph token: %s", exc)
        return []

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = (
        "https://graph.microsoft.com/v1.0/servicePrincipals"
        "?$select=id,displayName,passwordCredentials,keyCredentials&$top=100"
    )

    pages = 0
    while url and pages < 20:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except Exception as exc:
            logger.warning("identity_risk_service: Graph request failed: %s", exc)
            break

        if resp.status_code in (401, 403):
            logger.warning(
                "identity_risk_service: Graph API returned %d — "
                "Microsoft Graph permissions not configured",
                resp.status_code,
            )
            return []

        if not resp.ok:
            logger.warning("identity_risk_service: Graph API error %d: %s", resp.status_code, resp.text[:200])
            break

        data = resp.json()
        for sp in data.get("value", []):
            risks.extend(_build_risks_from_sp(sp, detected_at))

        url = data.get("@odata.nextLink")
        pages += 1

    logger.info(
        "identity_risk_service: scan complete | sps_checked=%d risks=%d",
        pages * 100,
        len(risks),
    )
    return risks


def persist_risks(
    cosmos_client: Any,
    db_name: str,
    risks: List[CredentialRisk],
) -> None:
    """Upsert CredentialRisk records into Cosmos DB 'identity_risks' container.

    Never raises.
    """
    if not risks:
        return
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("identity_risks")
        for risk in risks:
            item = asdict(risk)
            item["id"] = risk.risk_id
            container.upsert_item(item)
        logger.info("identity_risk_service: persisted %d risks", len(risks))
    except Exception as exc:
        logger.error("identity_risk_service: persist_risks failed: %s", exc)


def get_risks(
    cosmos_client: Any,
    db_name: str,
    severity: Optional[str] = None,
) -> List[CredentialRisk]:
    """Fetch CredentialRisk records from Cosmos DB. Never raises."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("identity_risks")
        if severity:
            query = "SELECT * FROM c WHERE c.severity = @sev"
            params: List[Dict[str, Any]] = [{"name": "@sev", "value": severity.lower()}]
            items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        else:
            items = list(container.read_all_items())

        return [
            CredentialRisk(
                risk_id=i.get("risk_id", i.get("id", "")),
                service_principal_id=i.get("service_principal_id", ""),
                service_principal_name=i.get("service_principal_name", ""),
                credential_type=i.get("credential_type", ""),
                credential_name=i.get("credential_name", ""),
                expiry_date=i.get("expiry_date", ""),
                days_until_expiry=i.get("days_until_expiry", 0),
                severity=i.get("severity", ""),
                detected_at=i.get("detected_at", ""),
                ttl=i.get("ttl", 86400),
            )
            for i in items
        ]
    except Exception as exc:
        logger.error("identity_risk_service: get_risks failed: %s", exc)
        return []


def get_identity_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return summary counts for identity risks. Never raises."""
    risks = get_risks(cosmos_client, db_name)
    total_sps = len({r.service_principal_id for r in risks})
    critical = sum(1 for r in risks if r.severity == "critical")
    high = sum(1 for r in risks if r.severity == "high")
    medium = sum(1 for r in risks if r.severity == "medium")
    expired = sum(1 for r in risks if r.days_until_expiry < 0)
    expiring_30d = sum(1 for r in risks if 0 <= r.days_until_expiry < 30)
    return {
        "total_sps_checked": total_sps,
        "critical_count": critical,
        "high_count": high,
        "medium_count": medium,
        "expired_count": expired,
        "expiring_30d_count": expiring_30d,
    }
