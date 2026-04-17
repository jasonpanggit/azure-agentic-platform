"""VNet Peering Health Audit Service — Phase 99.

ARG scan for all VNet peerings and their health status. Persists findings
to Cosmos DB container 'vnet_peerings'.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL
_COSMOS_CONTAINER = "vnet_peerings"
_COSMOS_DB = "aap"

_ARG_QUERY = """
Resources
| where type =~ "microsoft.network/virtualnetworks"
| mv-expand peering = parse_json(properties).virtualNetworkPeerings
| extend peeringName = tostring(peering.name)
| extend peeringState = tostring(peering.properties.peeringState)
| extend provisioningState = tostring(peering.properties.provisioningState)
| extend remoteVnetId = tolower(tostring(peering.properties.remoteVirtualNetwork.id))
| extend allowGatewayTransit = tobool(peering.properties.allowGatewayTransit)
| extend useRemoteGateways = tobool(peering.properties.useRemoteGateways)
| project subscriptionId, resourceGroup, vnetName = name, peeringName, peeringState, provisioningState, remoteVnetId, allowGatewayTransit, useRemoteGateways, id
"""


def _compute_severity(peering_state: str, provisioning_state: str) -> str:
    """Classify severity from peering and provisioning state."""
    if peering_state.lower() == "disconnected":
        return "critical"
    if provisioning_state.lower() != "succeeded":
        return "high"
    return "info"


def _build_finding(row: Dict[str, Any], scanned_at: str) -> Dict[str, Any]:
    """Build a normalized peering finding dict from an ARG result row."""
    vnet_arm_id = row.get("id", "")
    peering_name = row.get("peeringName", "")
    stable_key = f"{vnet_arm_id}:{peering_name}"
    finding_id = str(uuid.uuid5(_NAMESPACE, stable_key))

    peering_state = row.get("peeringState", "")
    provisioning_state = row.get("provisioningState", "")

    is_healthy = (
        peering_state.lower() == "connected"
        and provisioning_state.lower() == "succeeded"
    )

    return {
        "id": finding_id,
        "subscription_id": row.get("subscriptionId", ""),
        "resource_group": row.get("resourceGroup", ""),
        "vnet_name": row.get("vnetName", ""),
        "peering_name": peering_name,
        "peering_state": peering_state,
        "provisioning_state": provisioning_state,
        "remote_vnet_id": row.get("remoteVnetId", ""),
        "allow_gateway_transit": bool(row.get("allowGatewayTransit", False)),
        "use_remote_gateways": bool(row.get("useRemoteGateways", False)),
        "is_healthy": is_healthy,
        "severity": _compute_severity(peering_state, provisioning_state),
        "scanned_at": scanned_at,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_vnet_peerings(subscription_ids: List[str]) -> List[Dict[str, Any]]:
    """ARG scan for all VNet peerings across the given subscriptions.

    Returns a flat list of peering findings.
    Never raises.
    """
    start_time = time.monotonic()

    if not subscription_ids:
        logger.warning("vnet_peering_service: scan called with empty subscription list")
        return []

    try:
        from arg_helper import run_arg_query  # type: ignore[import]
    except ImportError:
        logger.warning("vnet_peering_service: arg_helper not available — scan skipped")
        return []

    scanned_at = datetime.now(timezone.utc).isoformat()
    findings: List[Dict[str, Any]] = []

    try:
        rows = run_arg_query(
            query=_ARG_QUERY,
            subscription_ids=subscription_ids,
        )
        for row in rows:
            try:
                finding = _build_finding(row, scanned_at)
                findings.append(finding)
            except Exception as row_exc:
                logger.warning(
                    "vnet_peering_service: failed to process row | error=%s row=%s",
                    row_exc,
                    row,
                )
    except Exception as exc:
        logger.warning("vnet_peering_service: ARG query failed | error=%s", exc)
        return []

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "vnet_peering_service: scan complete | subscriptions=%d findings=%d (%.0fms)",
        len(subscription_ids),
        len(findings),
        duration_ms,
    )
    return findings


def persist_peering_findings(
    findings: List[Dict[str, Any]],
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
) -> None:
    """Persist peering findings to Cosmos DB vnet_peerings container.

    Never raises.
    """
    if not findings:
        return
    if cosmos_client is None:
        logger.warning("vnet_peering_service: persist called without cosmos_client")
        return

    try:
        db = cosmos_client.get_database_client(cosmos_db)
        container = db.get_container_client(_COSMOS_CONTAINER)
        for finding in findings:
            container.upsert_item(finding)
        logger.info("vnet_peering_service: persisted %d findings", len(findings))
    except Exception as exc:
        logger.warning("vnet_peering_service: persist failed | error=%s", exc)


def get_peering_findings(
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
    subscription_id: Optional[str] = None,
    is_healthy: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Return peering findings from Cosmos DB with optional filters.

    Never raises — returns [] on error.
    """
    if cosmos_client is None:
        return []

    try:
        db = cosmos_client.get_database_client(cosmos_db)
        container = db.get_container_client(_COSMOS_CONTAINER)

        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_id:
            conditions.append("c.subscription_id = @subscription_id")
            params.append({"name": "@subscription_id", "value": subscription_id})
        if is_healthy is not None:
            conditions.append("c.is_healthy = @is_healthy")
            params.append({"name": "@is_healthy", "value": is_healthy})

        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM c{where_clause} ORDER BY c.severity ASC, c.vnet_name ASC"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]

    except Exception as exc:
        logger.warning("vnet_peering_service: get_peering_findings error | error=%s", exc)
        return []


def get_peering_summary(
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
    subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return aggregated peering health summary.

    Returns totals: total, healthy, unhealthy, disconnected count.
    Never raises — returns zeroed summary on error.
    """
    empty: Dict[str, Any] = {
        "total": 0,
        "healthy": 0,
        "unhealthy": 0,
        "disconnected": 0,
    }

    findings = get_peering_findings(
        cosmos_client=cosmos_client,
        cosmos_db=cosmos_db,
        subscription_id=subscription_id,
    )

    if not findings:
        return empty

    total = len(findings)
    healthy = sum(1 for f in findings if f.get("is_healthy"))
    unhealthy = total - healthy
    disconnected = sum(
        1 for f in findings
        if f.get("peering_state", "").lower() == "disconnected"
    )

    return {
        "total": total,
        "healthy": healthy,
        "unhealthy": unhealthy,
        "disconnected": disconnected,
    }
