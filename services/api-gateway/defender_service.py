from __future__ import annotations
"""Defender for Cloud Service — pull security alerts and recommendations via ARG.

Architecture:
- scan_defender_alerts: ARG query for active security alerts
- scan_defender_recommendations: ARG query for unhealthy assessments
- persist_defender_data: upsert to Cosmos defender_alerts container (TTL 48h)
- get_alerts / get_recommendations / get_defender_summary: query Cosmos
- All functions never raise — return [] or {} on error, log warning
"""

import logging
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK availability guard
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    _ARG_AVAILABLE = True
except Exception as _e:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    _ARG_AVAILABLE = False
    logger.warning("defender_service: azure-mgmt-resourcegraph unavailable: %s", _e)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFENDER_ALERTS_TTL: int = 172800  # 48 hours
_SEVERITY_NORM: Dict[str, str] = {
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "informational": "Informational",
    "critical": "High",  # map critical → high for consistent display
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DefenderAlert:
    alert_id: str
    subscription_id: str
    display_name: str
    description: str
    severity: str          # High/Medium/Low/Informational
    status: str            # Active
    resource_ids: List[str]
    generated_at: str      # ISO
    remediation_steps: List[str]
    captured_at: str
    ttl: int = DEFENDER_ALERTS_TTL


@dataclass
class DefenderRecommendation:
    rec_id: str
    subscription_id: str
    resource_group: str
    display_name: str
    severity: str          # High/Medium/Low
    description: str
    remediation: str
    resource_id: str
    category: str          # Compute/Networking/Data/Identity etc.
    captured_at: str
    ttl: int = DEFENDER_ALERTS_TTL


# ---------------------------------------------------------------------------
# KQL queries
# ---------------------------------------------------------------------------

_ALERTS_KQL = """
SecurityResources
| where type =~ 'microsoft.security/locations/alerts'
| project
    arm_id = tolower(id),
    subscription_id = subscriptionId,
    display_name = tostring(properties.alertDisplayName),
    description = tostring(properties.description),
    severity = tostring(properties.severity),
    status = tostring(properties.status),
    resource_identifiers = tostring(properties.resourceIdentifiers),
    generated_at = tostring(properties.timeGeneratedUtc),
    remediation_steps = tostring(properties.remediationSteps)
| where status =~ 'Active'
| order by generated_at desc
"""

_RECOMMENDATIONS_KQL = """
SecurityResources
| where type =~ 'microsoft.security/assessments'
| where properties.status.code =~ 'Unhealthy'
| project
    arm_id = tolower(id),
    subscription_id = subscriptionId,
    resource_group = resourceGroup,
    display_name = tostring(properties.displayName),
    severity = tostring(properties.metadata.severity),
    description = tostring(properties.metadata.description),
    remediation = tostring(properties.metadata.remediationDescription),
    resource_id = tostring(properties.resourceDetails.Id),
    category = tostring(properties.metadata.categories[0])
| order by severity asc
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_id(arm_id: str) -> str:
    """Return a stable UUID5 from an ARM resource ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, arm_id.lower()))


def _normalise_severity(raw: str) -> str:
    return _SEVERITY_NORM.get(raw.lower(), raw.capitalize())


def _parse_json_list(raw: str) -> List[Any]:
    """Try to parse a JSON list string; return [] on failure."""
    import json
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _extract_resource_ids(raw: str) -> List[str]:
    items = _parse_json_list(raw)
    result: List[str] = []
    for item in items:
        if isinstance(item, dict):
            rid = item.get("AzureResourceId") or item.get("id") or item.get("resourceId") or ""
            if rid:
                result.append(str(rid))
    return result


# ---------------------------------------------------------------------------
# Scan functions
# ---------------------------------------------------------------------------

def scan_defender_alerts(
    credential: Any,
    subscription_ids: List[str],
) -> List[DefenderAlert]:
    """Scan Defender security alerts across subscription_ids via ARG.

    Args:
        credential: Azure credential.
        subscription_ids: List of subscription IDs to query.

    Returns:
        List of DefenderAlert. Empty list on error.
    """
    start_time = time.monotonic()
    if not subscription_ids:
        return []
    try:
        from services.api_gateway.arg_helper import run_arg_query
        rows = run_arg_query(credential, subscription_ids, _ALERTS_KQL)
        captured_at = datetime.now(timezone.utc).isoformat()
        alerts: List[DefenderAlert] = []
        for row in rows:
            arm_id = row.get("arm_id", "") or ""
            alerts.append(DefenderAlert(
                alert_id=_stable_id(arm_id) if arm_id else str(uuid.uuid4()),
                subscription_id=row.get("subscription_id", ""),
                display_name=row.get("display_name", "Unknown Alert"),
                description=row.get("description", ""),
                severity=_normalise_severity(row.get("severity", "Medium")),
                status=row.get("status", "Active"),
                resource_ids=_extract_resource_ids(row.get("resource_identifiers", "")),
                generated_at=row.get("generated_at", captured_at),
                remediation_steps=_parse_json_list(row.get("remediation_steps", "")),
                captured_at=captured_at,
            ))
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "defender_service: scan_defender_alerts complete | count=%d duration_ms=%.1f",
            len(alerts), duration_ms,
        )
        return alerts
    except Exception as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.warning(
            "defender_service: scan_defender_alerts failed | error=%s duration_ms=%.1f",
            exc, duration_ms,
        )
        return []


def scan_defender_recommendations(
    credential: Any,
    subscription_ids: List[str],
) -> List[DefenderRecommendation]:
    """Scan Defender recommendations (unhealthy assessments) via ARG.

    Args:
        credential: Azure credential.
        subscription_ids: List of subscription IDs to query.

    Returns:
        List of DefenderRecommendation. Empty list on error.
    """
    start_time = time.monotonic()
    if not subscription_ids:
        return []
    try:
        from services.api_gateway.arg_helper import run_arg_query
        rows = run_arg_query(credential, subscription_ids, _RECOMMENDATIONS_KQL)
        captured_at = datetime.now(timezone.utc).isoformat()
        recs: List[DefenderRecommendation] = []
        for row in rows:
            arm_id = row.get("arm_id", "") or ""
            recs.append(DefenderRecommendation(
                rec_id=_stable_id(arm_id) if arm_id else str(uuid.uuid4()),
                subscription_id=row.get("subscription_id", ""),
                resource_group=row.get("resource_group", ""),
                display_name=row.get("display_name", "Unknown Recommendation"),
                severity=_normalise_severity(row.get("severity", "Medium")),
                description=row.get("description", ""),
                remediation=row.get("remediation", ""),
                resource_id=row.get("resource_id", ""),
                category=row.get("category", "General"),
                captured_at=captured_at,
            ))
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "defender_service: scan_defender_recommendations complete | count=%d duration_ms=%.1f",
            len(recs), duration_ms,
        )
        return recs
    except Exception as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.warning(
            "defender_service: scan_defender_recommendations failed | error=%s duration_ms=%.1f",
            exc, duration_ms,
        )
        return []


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def persist_defender_data(
    cosmos_client: Any,
    db_name: str,
    alerts: List[DefenderAlert],
    recommendations: List[DefenderRecommendation],
) -> None:
    """Upsert Defender alerts and recommendations into Cosmos.

    Args:
        cosmos_client: azure.cosmos.CosmosClient instance.
        db_name: Cosmos database name.
        alerts: List of DefenderAlert to persist.
        recommendations: List of DefenderRecommendation to persist.
    """
    if cosmos_client is None:
        logger.debug("defender_service: persist_defender_data skipped — no cosmos client")
        return
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("defender_alerts")
        upserted = 0
        for alert in alerts:
            doc = {**asdict(alert), "id": alert.alert_id, "record_type": "alert"}
            try:
                container.upsert_item(doc)
                upserted += 1
            except Exception as exc:
                logger.warning("defender_service: upsert alert failed | id=%s error=%s", alert.alert_id, exc)
        for rec in recommendations:
            doc = {**asdict(rec), "id": rec.rec_id, "record_type": "recommendation"}
            try:
                container.upsert_item(doc)
                upserted += 1
            except Exception as exc:
                logger.warning("defender_service: upsert rec failed | id=%s error=%s", rec.rec_id, exc)
        logger.info("defender_service: persist_defender_data | upserted=%d", upserted)
    except Exception as exc:
        logger.warning("defender_service: persist_defender_data failed | error=%s", exc)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _query_container(
    cosmos_client: Any,
    db_name: str,
    query: str,
    params: List[Dict[str, Any]],
    partition_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Run a Cosmos query and return results. Never raises."""
    if cosmos_client is None:
        return []
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("defender_alerts")
        kwargs: Dict[str, Any] = {
            "query": query,
            "parameters": params,
            "enable_cross_partition_query": partition_key is None,
        }
        if partition_key is not None:
            kwargs["partition_key"] = partition_key
        return list(container.query_items(**kwargs))
    except Exception as exc:
        logger.warning("defender_service: _query_container failed | error=%s", exc)
        return []


def get_alerts(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    severity: Optional[str] = None,
    limit: int = 50,
) -> List[DefenderAlert]:
    """Return Defender alerts from Cosmos.

    Args:
        cosmos_client: Cosmos client.
        db_name: Database name.
        subscription_ids: Optional filter by subscription.
        severity: Optional filter by severity (High/Medium/Low/Informational).
        limit: Max results (default 50).

    Returns:
        List of DefenderAlert. Empty on error.
    """
    try:
        conditions = ["c.record_type = 'alert'"]
        params: List[Dict[str, Any]] = []
        if severity:
            conditions.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity})
        where = " AND ".join(conditions)
        query = f"SELECT TOP {limit} * FROM c WHERE {where} ORDER BY c.generated_at DESC"
        items = _query_container(cosmos_client, db_name, query, params)
        if subscription_ids:
            sub_set = set(subscription_ids)
            items = [i for i in items if i.get("subscription_id") in sub_set]
        results: List[DefenderAlert] = []
        for item in items:
            try:
                results.append(DefenderAlert(
                    alert_id=item.get("alert_id", item.get("id", "")),
                    subscription_id=item.get("subscription_id", ""),
                    display_name=item.get("display_name", ""),
                    description=item.get("description", ""),
                    severity=item.get("severity", "Medium"),
                    status=item.get("status", "Active"),
                    resource_ids=item.get("resource_ids", []),
                    generated_at=item.get("generated_at", ""),
                    remediation_steps=item.get("remediation_steps", []),
                    captured_at=item.get("captured_at", ""),
                    ttl=item.get("ttl", DEFENDER_ALERTS_TTL),
                ))
            except Exception as exc:
                logger.warning("defender_service: get_alerts row parse error | error=%s", exc)
        return results
    except Exception as exc:
        logger.warning("defender_service: get_alerts failed | error=%s", exc)
        return []


def get_recommendations(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
) -> List[DefenderRecommendation]:
    """Return Defender recommendations from Cosmos.

    Args:
        cosmos_client: Cosmos client.
        db_name: Database name.
        subscription_ids: Optional filter by subscription.
        category: Optional filter by category.
        severity: Optional filter by severity.

    Returns:
        List of DefenderRecommendation. Empty on error.
    """
    try:
        conditions = ["c.record_type = 'recommendation'"]
        params: List[Dict[str, Any]] = []
        if category:
            conditions.append("c.category = @category")
            params.append({"name": "@category", "value": category})
        if severity:
            conditions.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity})
        where = " AND ".join(conditions)
        query = f"SELECT * FROM c WHERE {where} ORDER BY c.severity ASC"
        items = _query_container(cosmos_client, db_name, query, params)
        if subscription_ids:
            sub_set = set(subscription_ids)
            items = [i for i in items if i.get("subscription_id") in sub_set]
        results: List[DefenderRecommendation] = []
        for item in items:
            try:
                results.append(DefenderRecommendation(
                    rec_id=item.get("rec_id", item.get("id", "")),
                    subscription_id=item.get("subscription_id", ""),
                    resource_group=item.get("resource_group", ""),
                    display_name=item.get("display_name", ""),
                    severity=item.get("severity", "Medium"),
                    description=item.get("description", ""),
                    remediation=item.get("remediation", ""),
                    resource_id=item.get("resource_id", ""),
                    category=item.get("category", "General"),
                    captured_at=item.get("captured_at", ""),
                    ttl=item.get("ttl", DEFENDER_ALERTS_TTL),
                ))
            except Exception as exc:
                logger.warning("defender_service: get_recommendations row parse error | error=%s", exc)
        return results
    except Exception as exc:
        logger.warning("defender_service: get_recommendations failed | error=%s", exc)
        return []


def get_defender_summary(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return summary counts for alerts and recommendations.

    Args:
        cosmos_client: Cosmos client.
        db_name: Database name.
        subscription_ids: Optional filter by subscription.

    Returns:
        Dict with alert_counts_by_severity, recommendation_counts_by_severity,
        secure_score_estimate (null), top_affected_resources, total_alerts, total_recommendations.
        Never raises.
    """
    try:
        alerts = get_alerts(cosmos_client, db_name, subscription_ids, limit=500)
        recs = get_recommendations(cosmos_client, db_name, subscription_ids)

        alert_counts: Dict[str, int] = {"High": 0, "Medium": 0, "Low": 0, "Informational": 0}
        for a in alerts:
            sev = a.severity if a.severity in alert_counts else "Informational"
            alert_counts[sev] = alert_counts.get(sev, 0) + 1

        rec_counts: Dict[str, int] = {"High": 0, "Medium": 0, "Low": 0}
        for r in recs:
            sev = r.severity if r.severity in rec_counts else "Medium"
            rec_counts[sev] = rec_counts.get(sev, 0) + 1

        # Top affected resources (up to 10) from alert resource_ids
        resource_counter: Dict[str, int] = {}
        for a in alerts:
            for rid in a.resource_ids:
                if rid:
                    resource_counter[rid] = resource_counter.get(rid, 0) + 1
        top_resources = sorted(resource_counter.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "alert_counts_by_severity": alert_counts,
            "recommendation_counts_by_severity": rec_counts,
            "secure_score_estimate": None,
            "top_affected_resources": [{"resource_id": r, "alert_count": c} for r, c in top_resources],
            "total_alerts": len(alerts),
            "total_recommendations": len(recs),
        }
    except Exception as exc:
        logger.warning("defender_service: get_defender_summary failed | error=%s", exc)
        return {
            "alert_counts_by_severity": {"High": 0, "Medium": 0, "Low": 0, "Informational": 0},
            "recommendation_counts_by_severity": {"High": 0, "Medium": 0, "Low": 0},
            "secure_score_estimate": None,
            "top_affected_resources": [],
            "total_alerts": 0,
            "total_recommendations": 0,
            "error": str(exc),
        }
