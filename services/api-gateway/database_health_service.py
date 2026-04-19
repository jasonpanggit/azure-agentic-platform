from __future__ import annotations
"""Database Health Service — Phase 105.

Scans Cosmos DB accounts, PostgreSQL Flexible Servers, and Azure SQL databases
via Azure Resource Graph. Returns a unified list of database health records.

Never raises — all exceptions caught, logged, caller receives [].
Data queried live from ARG (15-minute TTL cache).
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ARG query — returns Cosmos, PG, SQL resources in one call
# ---------------------------------------------------------------------------

_DB_ARG_QUERY = """
Resources
| where type in~ (
    'microsoft.documentdb/databaseaccounts',
    'microsoft.dbforpostgresql/flexibleservers',
    'microsoft.sql/servers/databases'
  )
| extend db_type = case(
    type =~ 'microsoft.documentdb/databaseaccounts', 'cosmos',
    type =~ 'microsoft.dbforpostgresql/flexibleservers', 'postgresql',
    type =~ 'microsoft.sql/servers/databases', 'sql',
    'unknown'
  )
| extend state = coalesce(
    tostring(properties.provisioningState),
    tostring(properties.state),
    'Unknown'
  )
| extend sku_name = coalesce(
    tostring(sku.name),
    tostring(properties.sku.name),
    ''
  )
| extend version = tostring(properties.version)
| extend location = location
| project
    resource_id = tolower(id),
    name,
    db_type,
    resource_group = resourceGroup,
    subscription_id = subscriptionId,
    location,
    state,
    sku_name,
    version,
    tags
| order by db_type asc, name asc
"""

# ---------------------------------------------------------------------------
# Health classification
# ---------------------------------------------------------------------------

def _classify(row: Dict[str, Any]) -> tuple[str, List[str]]:
    """Return (health_status, findings) for a single DB ARG row."""
    findings: List[str] = []
    state = str(row.get("state") or "Unknown").lower()

    if state in ("creating", "updating", "unknown", "provisioning"):
        health_status = "provisioning"
        findings.append(f"Resource is in transitional state: {state}")
    elif state in ("deleting", "disabled", "stopped", "offline"):
        health_status = "stopped"
        findings.append(f"Resource is not serving traffic: {state}")
    elif state in ("failed", "error"):
        health_status = "failed"
        findings.append(f"Resource is in failed state: {state}")
    else:
        health_status = "healthy"

    return health_status, findings


# ---------------------------------------------------------------------------
# Public scan function
# ---------------------------------------------------------------------------

def scan_database_health(subscription_ids: List[str]) -> List[Dict[str, Any]]:
    """Scan all database resources across subscriptions via ARG.

    Returns list of health records. Never raises.
    """
    start_time = time.monotonic()
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from services.api_gateway.arg_helper import run_arg_query

        credential = DefaultAzureCredential()
        rows = run_arg_query(credential, subscription_ids, _DB_ARG_QUERY)
    except Exception as exc:  # noqa: BLE001
        logger.error("database_health_service.scan: arg_error=%s", exc)
        return []

    results: List[Dict[str, Any]] = []
    for row in rows:
        health_status, findings = _classify(row)
        results.append({
            **row,
            "health_status": health_status,
            "findings": findings,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        })

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "database_health_service.scan: total=%d duration_ms=%.1f",
        len(results), duration_ms,
    )
    return results
