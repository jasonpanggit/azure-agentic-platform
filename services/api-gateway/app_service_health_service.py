from __future__ import annotations
"""App Service / Function App health scanning service.

Scans Azure App Service Plans and Web Apps (including Function Apps and Logic Apps)
via Azure Resource Graph.  Detects configuration issues (no HTTPS, weak TLS, free
tier) and persists results to Cosmos DB container 'app_service_health'.

Never raises — all exceptions are caught and logged.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ARG KQL
# ---------------------------------------------------------------------------

_ARG_KQL = """
Resources
| where type in~ ('microsoft.web/sites', 'microsoft.web/serverfarms')
| project
    resource_id = tolower(id),
    name,
    type = tolower(type),
    resource_group = resourceGroup,
    subscription_id = subscriptionId,
    location,
    sku_name = tostring(properties.sku.name),
    sku_tier = tostring(sku.tier),
    state = tostring(properties.state),
    kind = tostring(kind),
    enabled = tobool(properties.enabled),
    https_only = tobool(properties.httpsOnly),
    min_tls_version = tostring(properties.siteConfig.minTlsVersion),
    worker_count = toint(properties.numberOfWorkers),
    reserved = tobool(properties.reserved),
    tags
| order by type asc, name asc
"""

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class AppServiceApp:
    app_id: str           # uuid5(NAMESPACE_URL, arm_id)
    arm_id: str
    name: str
    app_type: str         # "web_app" | "function_app" | "logic_app" | "app_service_plan"
    resource_group: str
    subscription_id: str
    location: str
    state: str            # Running/Stopped/Unknown
    enabled: bool
    https_only: bool
    min_tls_version: str  # "1.0"/"1.1"/"1.2"/"1.3"
    sku_name: str         # F1/D1/B1/B2/S1/P1v2 etc
    health_status: str    # "healthy"/"degraded"/"stopped"/"misconfigured"
    issues: List[str] = field(default_factory=list)
    scanned_at: str = ""
    ttl: int = 3600       # 1h


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_app_type(kind: str, resource_type: str) -> str:
    kind_lower = (kind or "").lower()
    if "functionapp" in kind_lower:
        return "function_app"
    if "workflowapp" in kind_lower or "logicapp" in kind_lower:
        return "logic_app"
    if "app" in kind_lower or resource_type.endswith("sites"):
        return "web_app"
    if "serverfarrm" in resource_type or "serverfarms" in resource_type:
        return "app_service_plan"
    return "web_app"


def _classify_health(row: Dict[str, Any]) -> tuple:
    """Return (health_status, issues_list)."""
    state = str(row.get("state") or "Unknown")
    enabled = row.get("enabled")
    https_only = row.get("https_only")
    min_tls = str(row.get("min_tls_version") or "")
    sku_name = str(row.get("sku_name") or "")
    resource_type = str(row.get("type") or "")

    # App Service Plans don't have the same runtime config checks
    if "serverfarrm" in resource_type or "serverfarms" in resource_type:
        if sku_name in ("F1", "D1"):
            return "misconfigured", ["Free/Shared tier — no SLA"]
        return "healthy", []

    issues: List[str] = []

    if state != "Running" and enabled is False:
        return "stopped", []

    if https_only is False:
        issues.append("HTTP allowed (should be HTTPS-only)")

    if min_tls in ("1.0", "1.1"):
        issues.append("TLS version below 1.2")

    if sku_name in ("F1", "D1"):
        issues.append("Free/Shared tier — no SLA")

    if issues:
        return "misconfigured", issues

    return "healthy", []


def _row_to_app(row: Dict[str, Any]) -> AppServiceApp:
    arm_id = str(row.get("resource_id") or "")
    app_id = str(uuid.uuid5(uuid.NAMESPACE_URL, arm_id))
    resource_type = str(row.get("type") or "")
    kind = str(row.get("kind") or "")
    app_type = _classify_app_type(kind, resource_type)
    health_status, issues = _classify_health(row)

    return AppServiceApp(
        app_id=app_id,
        arm_id=arm_id,
        name=str(row.get("name") or ""),
        app_type=app_type,
        resource_group=str(row.get("resource_group") or ""),
        subscription_id=str(row.get("subscription_id") or ""),
        location=str(row.get("location") or ""),
        state=str(row.get("state") or "Unknown"),
        enabled=bool(row.get("enabled") if row.get("enabled") is not None else True),
        https_only=bool(row.get("https_only") if row.get("https_only") is not None else False),
        min_tls_version=str(row.get("min_tls_version") or ""),
        sku_name=str(row.get("sku_name") or ""),
        health_status=health_status,
        issues=issues,
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_app_services(
    credential: Any,
    subscription_ids: List[str],
) -> List[AppServiceApp]:
    """Scan all App Service apps across subscription_ids via ARG.

    Returns a list of AppServiceApp objects.  Never raises.
    """
    start_time = time.monotonic()
    if not subscription_ids:
        logger.info("app_service_scan: no subscriptions provided")
        return []

    try:
        from services.api_gateway.arg_helper import run_arg_query
        rows = run_arg_query(credential, subscription_ids, _ARG_KQL)
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("app_service_scan: arg_query failed error=%s duration_ms=%.1f", exc, duration_ms)
        return []

    apps: List[AppServiceApp] = []
    for row in rows:
        try:
            apps.append(_row_to_app(row))
        except Exception as exc:
            logger.warning("app_service_scan: row_to_app failed row=%s error=%s", row.get("resource_id"), exc)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "app_service_scan: complete total=%d duration_ms=%.1f",
        len(apps), duration_ms,
    )
    return apps


def persist_app_services(
    cosmos_client: Any,
    db_name: str,
    apps: List[AppServiceApp],
) -> None:
    """Upsert AppServiceApp records into Cosmos DB container 'app_service_health'.

    Container TTL is configured at the container level (1h).  Never raises.
    """
    if not apps:
        return
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("app_service_health")
        for app in apps:
            doc = asdict(app)
            doc["id"] = app.app_id
            try:
                container.upsert_item(doc)
            except Exception as exc:
                logger.warning("app_service_persist: upsert failed app_id=%s error=%s", app.app_id, exc)
        logger.info("app_service_persist: upserted %d items", len(apps))
    except Exception as exc:
        logger.error("app_service_persist: container error=%s", exc)


def get_app_services(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    health_status: Optional[str] = None,
    app_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query persisted app service health records from Cosmos DB.

    Filters by subscription_ids, health_status, and app_type (all optional).
    Never raises.
    """
    try:
        db = cosmos_client.get_database_client(db_name)
        container = db.get_container_client("app_service_health")

        conditions = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sub in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sub})

        if health_status:
            conditions.append("c.health_status = @health_status")
            params.append({"name": "@health_status", "value": health_status})

        if app_type:
            conditions.append("c.app_type = @app_type")
            params.append({"name": "@app_type", "value": app_type})

        where_clause = " AND ".join(conditions)
        query = f"SELECT * FROM c WHERE {where_clause}" if where_clause else "SELECT * FROM c"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:
        logger.error("app_service_get: cosmos error=%s", exc)
        return []


def get_app_service_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregate counts for the App Service Health dashboard strip.

    Returns dict with: total, healthy, stopped, misconfigured,
    https_only_violations, tls_violations, free_tier_count.
    Never raises.
    """
    try:
        items = get_app_services(cosmos_client, db_name)
        total = len(items)
        healthy = sum(1 for i in items if i.get("health_status") == "healthy")
        stopped = sum(1 for i in items if i.get("health_status") == "stopped")
        misconfigured = sum(1 for i in items if i.get("health_status") == "misconfigured")
        https_violations = sum(
            1 for i in items if not i.get("https_only") and i.get("app_type") != "app_service_plan"
        )
        tls_violations = sum(
            1 for i in items if i.get("min_tls_version") in ("1.0", "1.1")
        )
        free_tier = sum(1 for i in items if i.get("sku_name") in ("F1", "D1"))
        return {
            "total": total,
            "healthy": healthy,
            "stopped": stopped,
            "misconfigured": misconfigured,
            "https_only_violations": https_violations,
            "tls_violations": tls_violations,
            "free_tier_count": free_tier,
        }
    except Exception as exc:
        logger.error("app_service_summary: error=%s", exc)
        return {
            "total": 0,
            "healthy": 0,
            "stopped": 0,
            "misconfigured": 0,
            "https_only_violations": 0,
            "tls_violations": 0,
            "free_tier_count": 0,
        }
