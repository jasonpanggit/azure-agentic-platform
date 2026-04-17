from __future__ import annotations
"""Load Balancer Health & Rule Audit Service — Phase 101.

Scans Azure Load Balancers via ARG for health probe / backend pool status.
Persists findings to Cosmos DB container ``lb_health``.
All functions follow the never-raise pattern: exceptions are caught, logged,
and callers receive [] or {}.
"""
import os

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ARG query
# ---------------------------------------------------------------------------

_LB_ARG_QUERY = """
Resources
| where type =~ "microsoft.network/loadbalancers"
| extend sku_name = tostring(sku.name)
| extend frontend_count = array_length(parse_json(properties).frontendIPConfigurations)
| extend backend_count = array_length(parse_json(properties).backendAddressPools)
| extend probe_count = array_length(parse_json(properties).probes)
| extend rule_count = array_length(parse_json(properties).loadBalancingRules)
| extend provisioning = tostring(properties.provisioningState)
| project subscriptionId, resourceGroup, name, sku_name, frontend_count, backend_count, probe_count, rule_count, provisioning, id, location
"""

# ---------------------------------------------------------------------------
# Cosmos container name
# ---------------------------------------------------------------------------

COSMOS_LB_HEALTH_CONTAINER = os.environ.get("COSMOS_LB_HEALTH_CONTAINER", "lb_health")
COSMOS_DATABASE = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")


# ---------------------------------------------------------------------------
# Risk classification helpers
# ---------------------------------------------------------------------------

def _classify(row: Dict[str, Any]) -> tuple[str, List[str]]:
    """Return (severity, findings) for a single LB ARG row."""
    findings: List[str] = []
    severity = "info"

    backend_count = int(row.get("backend_count") or 0)
    probe_count = int(row.get("probe_count") or 0)
    rule_count = int(row.get("rule_count") or 0)
    provisioning = str(row.get("provisioning") or "")
    sku_name = str(row.get("sku_name") or "")

    if backend_count == 0:
        findings.append("No backend address pools — load balancer is not serving traffic")
        severity = "critical"
    if probe_count == 0:
        findings.append("No health probes configured — unhealthy backends will not be detected")
        if severity not in ("critical",):
            severity = "high"
    if rule_count == 0:
        findings.append("No load balancing rules — traffic is not being routed")
        if severity not in ("critical",):
            severity = "high"
    if provisioning.lower() != "succeeded":
        findings.append(f"Provisioning state is '{provisioning}' (expected 'Succeeded')")
        if severity not in ("critical",):
            severity = "high"
    if sku_name.lower() == "basic":
        findings.append("Basic SKU is deprecated — migrate to Standard SKU")
        if severity == "info":
            severity = "medium"

    return severity, findings


def _stable_id(arm_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, arm_id))


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def scan_lb_health(subscription_ids: List[str]) -> List[Dict[str, Any]]:
    """Scan Azure Load Balancers via ARG and return classified findings.

    Args:
        subscription_ids: Azure subscription IDs to query.

    Returns:
        List of finding dicts. Empty list on error or when no LBs found.
    """
    start_time = time.monotonic()
    if not subscription_ids:
        logger.info("lb_health_scan: no subscription_ids provided")
        return []

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from services.api_gateway.arg_helper import run_arg_query

        credential = DefaultAzureCredential()
        rows = run_arg_query(credential, subscription_ids, _LB_ARG_QUERY)
        scanned_at = datetime.now(timezone.utc).isoformat()

        findings: List[Dict[str, Any]] = []
        for row in rows:
            arm_id = str(row.get("id", ""))
            severity, row_findings = _classify(row)
            findings.append({
                "id": _stable_id(arm_id) if arm_id else str(uuid.uuid4()),
                "subscription_id": str(row.get("subscriptionId", "")),
                "resource_group": str(row.get("resourceGroup", "")),
                "lb_name": str(row.get("name", "")),
                "sku": str(row.get("sku_name", "")),
                "location": str(row.get("location", "")),
                "frontend_count": int(row.get("frontend_count") or 0),
                "backend_count": int(row.get("backend_count") or 0),
                "probe_count": int(row.get("probe_count") or 0),
                "rule_count": int(row.get("rule_count") or 0),
                "provisioning_state": str(row.get("provisioning", "")),
                "findings": row_findings,
                "severity": severity,
                "scanned_at": scanned_at,
            })

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "lb_health_scan: complete | count=%d duration_ms=%.0f",
            len(findings), duration_ms,
        )
        return findings

    except Exception as exc:  # noqa: BLE001
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning("lb_health_scan: failed | error=%s duration_ms=%.0f", exc, duration_ms)
        return []


def persist_lb_findings(findings: List[Dict[str, Any]]) -> None:
    """Upsert LB health findings into Cosmos DB container ``lb_health``.

    Args:
        findings: List returned by ``scan_lb_health``.
    """
    if not findings:
        return

    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    if not cosmos_endpoint:
        logger.warning("persist_lb_findings: COSMOS_ENDPOINT not set — skipping")
        return

    try:
        from azure.cosmos import CosmosClient  # type: ignore[import]
        from azure.identity import DefaultAzureCredential  # type: ignore[import]

        credential = DefaultAzureCredential()
        client = CosmosClient(url=cosmos_endpoint, credential=credential)
        db = client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(COSMOS_LB_HEALTH_CONTAINER)

        upserted = 0
        for finding in findings:
            try:
                container.upsert_item(finding)
                upserted += 1
            except Exception as item_exc:  # noqa: BLE001
                logger.warning(
                    "persist_lb_findings: upsert failed | id=%s error=%s",
                    finding.get("id"), item_exc,
                )
        logger.info("persist_lb_findings: upserted=%d / total=%d", upserted, len(findings))
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_lb_findings: cosmos error | error=%s", exc)


def get_lb_findings(
    subscription_id: Optional[str] = None,
    severity: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve LB health findings from Cosmos DB.

    Args:
        subscription_id: Optional filter by subscription.
        severity: Optional filter by severity (critical, high, medium, info).

    Returns:
        List of finding dicts. Empty list on error or when Cosmos is unavailable.
    """
    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    if not cosmos_endpoint:
        logger.warning("get_lb_findings: COSMOS_ENDPOINT not set")
        return []

    try:
        from azure.cosmos import CosmosClient  # type: ignore[import]
        from azure.identity import DefaultAzureCredential  # type: ignore[import]

        credential = DefaultAzureCredential()
        client = CosmosClient(url=cosmos_endpoint, credential=credential)
        db = client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(COSMOS_LB_HEALTH_CONTAINER)

        clauses: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_id:
            clauses.append("c.subscription_id = @subscription_id")
            params.append({"name": "@subscription_id", "value": subscription_id})
        if severity:
            clauses.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity})

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"SELECT * FROM c {where} ORDER BY c.scanned_at DESC"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]

    except Exception as exc:  # noqa: BLE001
        logger.warning("get_lb_findings: error | error=%s", exc)
        return []


def get_lb_summary(subscription_id: Optional[str] = None) -> Dict[str, Any]:
    """Return aggregate summary of LB health findings.

    Args:
        subscription_id: Optional filter by subscription.

    Returns:
        Dict with total, by_severity, basic_sku_count. Empty counts on error.
    """
    empty: Dict[str, Any] = {
        "total": 0,
        "by_severity": {"critical": 0, "high": 0, "medium": 0, "info": 0},
        "basic_sku_count": 0,
    }

    try:
        findings = get_lb_findings(subscription_id=subscription_id)
        by_severity: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "info": 0}
        basic_count = 0

        for f in findings:
            sev = f.get("severity", "info")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if str(f.get("sku", "")).lower() == "basic":
                basic_count += 1

        return {
            "total": len(findings),
            "by_severity": by_severity,
            "basic_sku_count": basic_count,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_lb_summary: error | error=%s", exc)
        return empty
