from __future__ import annotations
"""Azure Policy Compliance Drill-Down service (Phase 84).

Scans non-compliant policy states via Azure Resource Graph, classifies severity,
persists to Cosmos DB (container: policy_violations, TTL 24h), and returns
structured summary data.

Never raises — all exceptions are caught and logged.
"""

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy SDK imports
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions  # type: ignore[import]
    _ARG_AVAILABLE = True
except Exception as _e:  # noqa: BLE001
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    QueryRequestOptions = None  # type: ignore[assignment,misc]
    _ARG_AVAILABLE = False
    logger.warning("azure-mgmt-resourcegraph unavailable — policy compliance scan disabled: %s", _e)


def _log_sdk_availability() -> None:
    logger.info("policy_compliance_service: resourcegraph_available=%s", _ARG_AVAILABLE)


_log_sdk_availability()

# ---------------------------------------------------------------------------
# KQL query
# ---------------------------------------------------------------------------

_POLICY_STATES_KQL = """
PolicyResources
| where type =~ 'microsoft.policyinsights/policystates'
| where properties.complianceState =~ 'NonCompliant'
| project
    state_id = tolower(id),
    subscription_id = subscriptionId,
    resource_id = tolower(tostring(properties.resourceId)),
    resource_type = tolower(tostring(properties.resourceType)),
    resource_group = tostring(properties.resourceGroup),
    policy_definition_id = tostring(properties.policyDefinitionId),
    policy_name = tostring(properties.policyDefinitionName),
    policy_display_name = tostring(properties.policyDefinitionDisplayName),
    initiative_name = tostring(properties.policySetDefinitionName),
    effect = tostring(properties.policyDefinitionEffect),
    timestamp = tostring(properties.timestamp)
| order by timestamp desc
| limit 500
"""

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PolicyViolation:
    violation_id: str          # uuid5(NAMESPACE_URL, state_id)
    subscription_id: str
    resource_id: str
    resource_name: str         # extracted from resource_id
    resource_type: str         # short friendly name
    resource_group: str
    policy_definition_id: str
    policy_name: str
    policy_display_name: str
    initiative_name: str       # empty if standalone policy
    effect: str                # Deny/Audit/AuditIfNotExists/DeployIfNotExists
    severity: str              # high (Deny) / medium (Audit) / low (others)
    timestamp: str
    captured_at: str
    ttl: int = 86400           # 24h


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _stable_id(state_id: str) -> str:
    """Derive a stable UUID from the policy state ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, state_id.lower()))


def _extract_resource_name(resource_id: str) -> str:
    """Extract the last segment of an ARM resource ID as resource name."""
    if not resource_id:
        return ""
    return resource_id.rstrip("/").split("/")[-1]


def _friendly_resource_type(resource_type: str) -> str:
    """Return last two segments of resource type as short friendly name."""
    if not resource_type:
        return ""
    parts = resource_type.split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else resource_type


def _classify_severity(effect: str) -> str:
    """Map policy effect to severity level."""
    effect_lower = effect.lower()
    if effect_lower == "deny":
        return "high"
    if effect_lower in ("audit", "auditifnotexists"):
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Core scan function
# ---------------------------------------------------------------------------


def scan_policy_compliance(
    credential: Any,
    subscription_ids: List[str],
) -> List[PolicyViolation]:
    """Scan non-compliant policy states via ARG. Never raises."""
    start_time = time.monotonic()

    if not _ARG_AVAILABLE:
        logger.warning("policy_compliance_service.scan: ARG SDK unavailable — returning empty")
        return []

    if not subscription_ids:
        logger.info("policy_compliance_service.scan: no subscription_ids provided")
        return []

    try:
        client = ResourceGraphClient(credential)
        rows: List[Dict[str, Any]] = []
        skip_token: Optional[str] = None

        while True:
            options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
            req = QueryRequest(subscriptions=subscription_ids, query=_POLICY_STATES_KQL, options=options)
            resp = client.resources(req)
            rows.extend(resp.data or [])
            skip_token = resp.skip_token
            if not skip_token:
                break

        captured_at = datetime.now(tz=timezone.utc).isoformat()
        violations: List[PolicyViolation] = []

        for row in rows:
            state_id = str(row.get("state_id", ""))
            resource_id = str(row.get("resource_id", ""))
            resource_type = str(row.get("resource_type", ""))
            effect = str(row.get("effect", ""))

            violations.append(PolicyViolation(
                violation_id=_stable_id(state_id) if state_id else _stable_id(resource_id + str(row.get("policy_name", ""))),
                subscription_id=str(row.get("subscription_id", "")),
                resource_id=resource_id,
                resource_name=_extract_resource_name(resource_id),
                resource_type=_friendly_resource_type(resource_type),
                resource_group=str(row.get("resource_group", "")),
                policy_definition_id=str(row.get("policy_definition_id", "")),
                policy_name=str(row.get("policy_name", "")),
                policy_display_name=str(row.get("policy_display_name", "")),
                initiative_name=str(row.get("initiative_name", "") or ""),
                effect=effect,
                severity=_classify_severity(effect),
                timestamp=str(row.get("timestamp", "")),
                captured_at=captured_at,
            ))

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "policy_compliance_service.scan: violations=%d duration_ms=%.1f",
            len(violations), duration_ms,
        )
        return violations

    except Exception as exc:  # noqa: BLE001
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("policy_compliance_service.scan: error=%s duration_ms=%.1f", exc, duration_ms)
        return []


# ---------------------------------------------------------------------------
# Cosmos DB persistence
# ---------------------------------------------------------------------------


def persist_violations(
    cosmos_client: Any,
    db_name: str,
    violations: List[PolicyViolation],
) -> None:
    """Upsert policy violation records into Cosmos DB. Never raises."""
    if not violations:
        return

    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("policy_violations")
        for violation in violations:
            doc = asdict(violation)
            doc["id"] = violation.violation_id
            container.upsert_item(doc)
        logger.info("policy_compliance_service.persist: upserted %d violations", len(violations))
    except Exception as exc:  # noqa: BLE001
        logger.error("policy_compliance_service.persist: error=%s", exc)


# ---------------------------------------------------------------------------
# Cosmos DB reads
# ---------------------------------------------------------------------------


def get_violations(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    severity: Optional[str] = None,
    policy_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query policy violation records from Cosmos DB. Never raises."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("policy_violations")
        conditions: List[str] = []
        parameters: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = [f"@sub{i}" for i in range(len(subscription_ids))]
            conditions.append(f"c.subscription_id IN ({', '.join(placeholders)})")
            for i, sid in enumerate(subscription_ids):
                parameters.append({"name": f"@sub{i}", "value": sid})

        if severity:
            conditions.append("c.severity = @severity")
            parameters.append({"name": "@severity", "value": severity})

        if policy_name:
            conditions.append("CONTAINS(LOWER(c.policy_display_name), LOWER(@policy_name))")
            parameters.append({"name": "@policy_name", "value": policy_name})

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM c {where_clause} ORDER BY c.timestamp DESC"

        items = list(container.query_items(
            query=query,
            parameters=parameters if parameters else None,
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("policy_compliance_service.get_violations: error=%s", exc)
        return []


def get_policy_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Compute policy compliance summary from Cosmos DB records. Never raises."""
    try:
        violations = get_violations(cosmos_client, db_name)
        total = len(violations)

        by_severity: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        policy_counts: Dict[str, int] = {}
        sub_counts: Dict[str, int] = {}

        for v in violations:
            sev = v.get("severity", "low")
            by_severity[sev] = by_severity.get(sev, 0) + 1

            pname = v.get("policy_display_name") or v.get("policy_name", "Unknown")
            policy_counts[pname] = policy_counts.get(pname, 0) + 1

            sid = v.get("subscription_id", "Unknown")
            sub_counts[sid] = sub_counts.get(sid, 0) + 1

        top_policies = sorted(
            [{"policy_name": k, "count": c} for k, c in policy_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:10]

        top_subs = sorted(
            [{"subscription_id": k, "count": c} for k, c in sub_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:10]

        return {
            "total_violations": total,
            "by_severity": by_severity,
            "top_violated_policies": top_policies,
            "top_affected_subscriptions": top_subs,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("policy_compliance_service.get_summary: error=%s", exc)
        return {
            "total_violations": 0,
            "by_severity": {"high": 0, "medium": 0, "low": 0},
            "top_violated_policies": [],
            "top_affected_subscriptions": [],
        }
