"""Availability Zone Coverage Audit Service — Phase 102.

Scans VMs and VMSS instances via ARG to determine if they are deployed
across Availability Zones. Only flags resources in regions that support AZs.
All functions follow the never-raise pattern.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regions that support Availability Zones
# ---------------------------------------------------------------------------

AZ_SUPPORTED_REGIONS = {
    "eastus",
    "eastus2",
    "westus2",
    "westeurope",
    "northeurope",
    "southeastasia",
    "australiaeast",
    "uksouth",
    "japaneast",
    "canadacentral",
}

# ---------------------------------------------------------------------------
# ARG queries
# ---------------------------------------------------------------------------

_VM_ARG_QUERY = """
Resources
| where type =~ "microsoft.compute/virtualmachines"
| extend zone_list = tostring(zones)
| extend has_zones = (array_length(zones) > 0)
| extend vm_size = tostring(properties.hardwareProfile.vmSize)
| project subscriptionId, resourceGroup, name, zone_list, has_zones, vm_size, id, location
"""

_VMSS_ARG_QUERY = """
Resources
| where type =~ "microsoft.compute/virtualmachinescalesets"
| extend zone_list = tostring(zones)
| extend has_zones = (array_length(zones) > 0)
| extend sku_name = tostring(sku.name)
| extend capacity = toint(sku.capacity)
| project subscriptionId, resourceGroup, name, zone_list, has_zones, sku_name, capacity, id, location
"""

# ---------------------------------------------------------------------------
# Cosmos
# ---------------------------------------------------------------------------

COSMOS_AZ_COVERAGE_CONTAINER = os.environ.get("COSMOS_AZ_COVERAGE_CONTAINER", "az_coverage")
COSMOS_DATABASE = os.environ.get("COSMOS_DATABASE", "aap")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_id(arm_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, arm_id))


def _parse_zones(zone_list_str: Optional[str]) -> List[str]:
    """Parse ARG zone_list string (e.g. '["1","2","3"]' or '[]') to list of strings."""
    if not zone_list_str or zone_list_str in ("[]", ""):
        return []
    try:
        import json
        parsed = json.loads(zone_list_str)
        if isinstance(parsed, list):
            return [str(z) for z in parsed]
    except Exception:  # noqa: BLE001
        pass
    return []


def _build_finding(
    row: Dict[str, Any],
    resource_type: str,
    scanned_at: str,
) -> Dict[str, Any]:
    """Build a normalised az_coverage finding dict from an ARG row."""
    arm_id = str(row.get("id", ""))
    location = str(row.get("location", "")).lower()
    zones = _parse_zones(row.get("zone_list"))
    has_zone_redundancy = len(zones) > 1
    az_supported = location in AZ_SUPPORTED_REGIONS

    severity = "high" if (az_supported and not has_zone_redundancy) else "info"
    recommendation = (
        "Deploy across 3 availability zones for HA"
        if not has_zone_redundancy
        else "Zone-redundant"
    )

    return {
        "id": _stable_id(arm_id) if arm_id else str(uuid.uuid4()),
        "subscription_id": str(row.get("subscriptionId", "")),
        "resource_group": str(row.get("resourceGroup", "")),
        "resource_name": str(row.get("name", "")),
        "resource_type": resource_type,
        "location": location,
        "zones": zones,
        "has_zone_redundancy": has_zone_redundancy,
        "zone_count": len(zones),
        "severity": severity,
        "recommendation": recommendation,
        "scanned_at": scanned_at,
    }


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def scan_az_coverage(subscription_ids: List[str]) -> List[Dict[str, Any]]:
    """Scan VMs and VMSS instances for AZ coverage via ARG.

    Args:
        subscription_ids: Azure subscription IDs to query.

    Returns:
        List of az_coverage finding dicts. Empty list on error.
    """
    start_time = time.monotonic()
    if not subscription_ids:
        logger.info("az_coverage_scan: no subscription_ids provided")
        return []

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from services.api_gateway.arg_helper import run_arg_query

        credential = DefaultAzureCredential()
        scanned_at = datetime.now(timezone.utc).isoformat()
        findings: List[Dict[str, Any]] = []

        for query, resource_type in (
            (_VM_ARG_QUERY, "vm"),
            (_VMSS_ARG_QUERY, "vmss"),
        ):
            try:
                rows = run_arg_query(credential, subscription_ids, query)
                for row in rows:
                    findings.append(_build_finding(row, resource_type, scanned_at))
            except Exception as query_exc:  # noqa: BLE001
                logger.warning(
                    "az_coverage_scan: query failed | resource_type=%s error=%s",
                    resource_type, query_exc,
                )

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "az_coverage_scan: complete | count=%d duration_ms=%.0f",
            len(findings), duration_ms,
        )
        return findings

    except Exception as exc:  # noqa: BLE001
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning("az_coverage_scan: failed | error=%s duration_ms=%.0f", exc, duration_ms)
        return []


def persist_az_findings(findings: List[Dict[str, Any]]) -> None:
    """Upsert AZ coverage findings into Cosmos DB container ``az_coverage``.

    Args:
        findings: List returned by ``scan_az_coverage``.
    """
    if not findings:
        return

    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    if not cosmos_endpoint:
        logger.warning("persist_az_findings: COSMOS_ENDPOINT not set — skipping")
        return

    try:
        from azure.cosmos import CosmosClient  # type: ignore[import]
        from azure.identity import DefaultAzureCredential  # type: ignore[import]

        credential = DefaultAzureCredential()
        client = CosmosClient(url=cosmos_endpoint, credential=credential)
        db = client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(COSMOS_AZ_COVERAGE_CONTAINER)

        upserted = 0
        for finding in findings:
            try:
                container.upsert_item(finding)
                upserted += 1
            except Exception as item_exc:  # noqa: BLE001
                logger.warning(
                    "persist_az_findings: upsert failed | id=%s error=%s",
                    finding.get("id"), item_exc,
                )
        logger.info("persist_az_findings: upserted=%d / total=%d", upserted, len(findings))
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_az_findings: cosmos error | error=%s", exc)


def get_az_findings(
    subscription_id: Optional[str] = None,
    has_zone_redundancy: Optional[bool] = None,
    resource_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve AZ coverage findings from Cosmos DB.

    Args:
        subscription_id: Optional filter by subscription.
        has_zone_redundancy: Optional boolean filter.
        resource_type: Optional filter: "vm" or "vmss".

    Returns:
        List of finding dicts. Empty list on error.
    """
    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    if not cosmos_endpoint:
        logger.warning("get_az_findings: COSMOS_ENDPOINT not set")
        return []

    try:
        from azure.cosmos import CosmosClient  # type: ignore[import]
        from azure.identity import DefaultAzureCredential  # type: ignore[import]

        credential = DefaultAzureCredential()
        client = CosmosClient(url=cosmos_endpoint, credential=credential)
        db = client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(COSMOS_AZ_COVERAGE_CONTAINER)

        clauses: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_id:
            clauses.append("c.subscription_id = @subscription_id")
            params.append({"name": "@subscription_id", "value": subscription_id})
        if has_zone_redundancy is not None:
            clauses.append("c.has_zone_redundancy = @has_zone_redundancy")
            params.append({"name": "@has_zone_redundancy", "value": has_zone_redundancy})
        if resource_type:
            clauses.append("c.resource_type = @resource_type")
            params.append({"name": "@resource_type", "value": resource_type})

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"SELECT * FROM c {where} ORDER BY c.scanned_at DESC"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]

    except Exception as exc:  # noqa: BLE001
        logger.warning("get_az_findings: error | error=%s", exc)
        return []


def get_az_summary(subscription_id: Optional[str] = None) -> Dict[str, Any]:
    """Return aggregate summary of AZ coverage findings.

    Args:
        subscription_id: Optional filter by subscription.

    Returns:
        Dict with total, zone_redundant, non_redundant, coverage_pct.
    """
    try:
        findings = get_az_findings(subscription_id=subscription_id)
        total = len(findings)
        zone_redundant = sum(1 for f in findings if f.get("has_zone_redundancy"))
        non_redundant = total - zone_redundant
        coverage_pct = round(zone_redundant / total * 100, 1) if total > 0 else 0.0

        return {
            "total": total,
            "zone_redundant": zone_redundant,
            "non_redundant": non_redundant,
            "coverage_pct": coverage_pct,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_az_summary: error | error=%s", exc)
        return {
            "total": 0,
            "zone_redundant": 0,
            "non_redundant": 0,
            "coverage_pct": 0.0,
        }
