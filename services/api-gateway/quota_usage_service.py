from __future__ import annotations
"""Azure Compute Quota Utilisation Service — Phase 95.

Queries Compute quota usage per subscription using Azure Resource Manager REST API
and persists findings to Cosmos DB.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""
import os

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import requests  # noqa: F401
except ImportError:
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL

_DEFAULT_LOCATIONS = ["eastus", "eastus2", "westus2", "westeurope", "southeastasia"]

_COSMOS_CONTAINER = "quota_usage"
_COSMOS_DB = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")

_ARM_API_VERSION = "2024-03-01"


def _get_locations() -> List[str]:
    """Return list of locations to scan from env var or default."""
    raw = os.environ.get("QUOTA_SCAN_LOCATIONS", "")
    if raw.strip():
        return [loc.strip() for loc in raw.split(",") if loc.strip()]
    return list(_DEFAULT_LOCATIONS)


def _get_bearer_token() -> Optional[str]:
    """Obtain an ARM bearer token using DefaultAzureCredential."""
    try:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token = credential.get_token("https://management.azure.com/.default")
        return token.token
    except Exception as exc:
        logger.warning("quota_usage_service: failed to get bearer token: %s", exc)
        return None


def _compute_severity(pct: float) -> str:
    if pct >= 90:
        return "critical"
    if pct >= 75:
        return "high"
    if pct >= 50:
        return "medium"
    return "low"


def _fetch_quota_for_location(
    subscription_id: str,
    location: str,
    token: str,
) -> List[Dict[str, Any]]:
    """Fetch quota usage for one subscription + location. Returns [] on error."""
    try:
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/providers/Microsoft.Compute/locations/{location}"
            f"/usages?api-version={_ARM_API_VERSION}"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 404:
            # Location not available for this subscription — not an error
            logger.debug(
                "quota_usage_service: location %s not available for sub %s",
                location,
                subscription_id,
            )
            return []
        if not resp.ok:
            logger.warning(
                "quota_usage_service: ARM API %d for sub=%s loc=%s: %s",
                resp.status_code,
                subscription_id,
                location,
                resp.text[:200],
            )
            return []

        data = resp.json()
        items = data.get("value", [])
        results: List[Dict[str, Any]] = []
        scanned_at = datetime.now(timezone.utc).isoformat()

        for item in items:
            name = item.get("name", {}).get("localizedValue") or item.get("name", {}).get("value", "")
            current_value = int(item.get("currentValue", 0))
            limit = int(item.get("limit", 0))

            if limit <= 0:
                utilisation_pct = 0.0
            else:
                utilisation_pct = round(current_value / limit * 100, 2)

            # Filter noise — only persist >= 25%
            if utilisation_pct < 25:
                continue

            severity = _compute_severity(utilisation_pct)
            stable_key = f"{subscription_id}:{location}:{name}"
            item_id = str(uuid.uuid5(_NAMESPACE, stable_key))

            results.append({
                "id": item_id,
                "subscription_id": subscription_id,
                "location": location,
                "quota_name": name,
                "current_value": current_value,
                "limit": limit,
                "utilisation_pct": utilisation_pct,
                "severity": severity,
                "scanned_at": scanned_at,
            })

        return results

    except Exception as exc:
        logger.warning(
            "quota_usage_service: error fetching loc=%s sub=%s: %s",
            location,
            subscription_id,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_quota_usage(subscription_ids: List[str]) -> List[Dict[str, Any]]:
    """Scan Compute quota usage across subscriptions and locations.

    Returns a flat list of quota findings (utilisation_pct >= 25 only).
    Never raises.
    """
    start_time = time.monotonic()

    if not subscription_ids:
        logger.warning("quota_usage_service: scan called with empty subscription list")
        return []

    token = _get_bearer_token()
    if not token:
        logger.warning("quota_usage_service: no bearer token — scan aborted")
        return []

    locations = _get_locations()
    all_findings: List[Dict[str, Any]] = []

    for sub_id in subscription_ids:
        for location in locations:
            findings = _fetch_quota_for_location(sub_id, location, token)
            all_findings.extend(findings)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "quota_usage_service: scan complete | subscriptions=%d locations=%d findings=%d (%.0fms)",
        len(subscription_ids),
        len(locations),
        len(all_findings),
        duration_ms,
    )
    return all_findings


def persist_quota_findings(
    findings: List[Dict[str, Any]],
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
) -> None:
    """Persist quota findings to Cosmos DB quota_usage container.

    Never raises.
    """
    if not findings:
        return
    if cosmos_client is None:
        logger.warning("quota_usage_service: persist called without cosmos_client")
        return

    try:
        db = cosmos_client.get_database_client(cosmos_db)
        container = db.get_container_client(_COSMOS_CONTAINER)
        for finding in findings:
            container.upsert_item(finding)
        logger.info("quota_usage_service: persisted %d findings", len(findings))
    except Exception as exc:
        logger.warning("quota_usage_service: persist failed: %s", exc)


def get_quota_findings(
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
    subscription_id: Optional[str] = None,
    severity: Optional[str] = None,
    location: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return quota findings from Cosmos DB with optional filters.

    Never raises — returns [] on error.
    """
    if cosmos_client is None:
        return []

    try:
        db = cosmos_client.get_database_client(cosmos_db)
        container = db.get_container_client(_COSMOS_CONTAINER)

        conditions = []
        params: List[Dict[str, Any]] = []

        if subscription_id:
            conditions.append("c.subscription_id = @subscription_id")
            params.append({"name": "@subscription_id", "value": subscription_id})
        if severity:
            conditions.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity})
        if location:
            conditions.append("c.location = @location")
            params.append({"name": "@location", "value": location})

        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM c{where_clause} ORDER BY c.utilisation_pct DESC"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]

    except Exception as exc:
        logger.warning("quota_usage_service: get_quota_findings error: %s", exc)
        return []


def get_quota_summary(
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
    subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return quota summary: counts by severity and most constrained quotas.

    Never raises — returns zeroed summary on error.
    """
    empty: Dict[str, Any] = {
        "critical_count": 0,
        "high_count": 0,
        "medium_count": 0,
        "low_count": 0,
        "total_count": 0,
        "most_constrained": [],
    }

    findings = get_quota_findings(
        cosmos_client=cosmos_client,
        cosmos_db=cosmos_db,
        subscription_id=subscription_id,
    )

    if not findings:
        return empty

    severity_counts: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "low")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    # Top 5 most constrained
    sorted_findings = sorted(findings, key=lambda x: x.get("utilisation_pct", 0), reverse=True)
    most_constrained = [
        {
            "quota_name": f.get("quota_name"),
            "location": f.get("location"),
            "subscription_id": f.get("subscription_id"),
            "utilisation_pct": f.get("utilisation_pct"),
            "current_value": f.get("current_value"),
            "limit": f.get("limit"),
            "severity": f.get("severity"),
        }
        for f in sorted_findings[:5]
    ]

    return {
        "critical_count": severity_counts.get("critical", 0),
        "high_count": severity_counts.get("high", 0),
        "medium_count": severity_counts.get("medium", 0),
        "low_count": severity_counts.get("low", 0),
        "total_count": len(findings),
        "most_constrained": most_constrained,
    }
