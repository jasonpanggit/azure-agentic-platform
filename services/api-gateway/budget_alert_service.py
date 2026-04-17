from __future__ import annotations
"""Subscription Budget & Spending Alerts Service — Phase 96.

Queries Azure Cost Management for budgets and current spend, persists
findings to Cosmos DB.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""
import os
import os

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    import requests  # noqa: F401
except ImportError:
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL
_COSMOS_CONTAINER = "budget_alerts"
_COSMOS_DB = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")

_CONSUMPTION_API_VERSION = "2023-11-01"


def _get_bearer_token() -> Optional[str]:
    """Obtain an ARM bearer token using DefaultAzureCredential."""
    try:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token = credential.get_token("https://management.azure.com/.default")
        return token.token
    except Exception as exc:
        logger.warning("budget_alert_service: failed to get bearer token: %s", exc)
        return None


def _classify_status(spend_pct: float, budget_amount: float) -> str:
    """Classify budget status from spend percentage."""
    if budget_amount <= 0:
        return "no_budget"
    if spend_pct >= 100:
        return "exceeded"
    if spend_pct >= 80:
        return "warning"
    return "on_track"


def _has_recent_spend(subscription_id: str, token: str) -> bool:
    """Check if subscription has recent spend data (last 30 days). Non-fatal."""
    try:
        import requests
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/providers/Microsoft.Consumption/usageDetails"
            f"?api-version={_CONSUMPTION_API_VERSION}"
            f"&$filter=properties/usageStart ge '{thirty_days_ago}'&$top=1"
        )
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.ok:
            data = resp.json()
            return len(data.get("value", [])) > 0
        return False
    except Exception as exc:
        logger.debug("budget_alert_service: recent-spend check failed: %s", exc)
        return False


def _fetch_budgets_for_subscription(
    subscription_id: str,
    token: str,
) -> List[Dict[str, Any]]:
    """Fetch budget status for one subscription. Returns [] on error."""
    try:
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/providers/Microsoft.Consumption/budgets"
            f"?api-version={_CONSUMPTION_API_VERSION}"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=30)

        scanned_at = datetime.now(timezone.utc).isoformat()

        if resp.status_code == 404 or resp.status_code == 204:
            # No budgets configured
            return [_no_budget_record(subscription_id, scanned_at)]

        if not resp.ok:
            logger.warning(
                "budget_alert_service: ARM API %d for sub=%s: %s",
                resp.status_code,
                subscription_id,
                resp.text[:200],
            )
            return []

        data = resp.json()
        items = data.get("value", [])

        if not items:
            return [_no_budget_record(subscription_id, scanned_at)]

        results: List[Dict[str, Any]] = []
        for item in items:
            props = item.get("properties", {})
            budget_id = item.get("id", f"{subscription_id}:budget")
            budget_name = item.get("name", "unknown")
            budget_amount = float(props.get("amount", 0))

            current_spend_data = props.get("currentSpend", {})
            current_spend = float(current_spend_data.get("amount", 0))

            forecast_data = props.get("forecastSpend", {})
            forecast_spend = float(forecast_data.get("amount", 0)) if forecast_data else current_spend

            if budget_amount > 0:
                spend_pct = round(current_spend / budget_amount * 100, 2)
            else:
                spend_pct = 0.0

            status = _classify_status(spend_pct, budget_amount)

            time_period = props.get("timePeriod", {})
            time_period_start = time_period.get("startDate", "")
            time_period_end = time_period.get("endDate", "")

            stable_key = budget_id
            item_id = str(uuid.uuid5(_NAMESPACE, stable_key))

            results.append({
                "id": item_id,
                "subscription_id": subscription_id,
                "budget_name": budget_name,
                "budget_amount": budget_amount,
                "current_spend": current_spend,
                "forecast_spend": forecast_spend,
                "spend_pct": spend_pct,
                "status": status,
                "time_period_start": time_period_start,
                "time_period_end": time_period_end,
                "scanned_at": scanned_at,
            })

        return results

    except Exception as exc:
        logger.warning(
            "budget_alert_service: error fetching budgets for sub=%s: %s",
            subscription_id,
            exc,
        )
        return []


def _no_budget_record(subscription_id: str, scanned_at: str) -> Dict[str, Any]:
    """Create a synthetic no_budget record for a subscription."""
    stable_key = f"{subscription_id}:no-budget"
    item_id = str(uuid.uuid5(_NAMESPACE, stable_key))
    return {
        "id": item_id,
        "subscription_id": subscription_id,
        "budget_name": "NO_BUDGET",
        "budget_amount": 0.0,
        "current_spend": 0.0,
        "forecast_spend": 0.0,
        "spend_pct": 0.0,
        "status": "no_budget",
        "time_period_start": "",
        "time_period_end": "",
        "scanned_at": scanned_at,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_budget_status(subscription_ids: List[str]) -> List[Dict[str, Any]]:
    """Scan budget status across subscriptions.

    Returns a flat list of budget findings.
    Never raises.
    """
    start_time = time.monotonic()

    if not subscription_ids:
        logger.warning("budget_alert_service: scan called with empty subscription list")
        return []

    token = _get_bearer_token()
    if not token:
        logger.warning("budget_alert_service: no bearer token — scan aborted")
        return []

    all_findings: List[Dict[str, Any]] = []
    for sub_id in subscription_ids:
        findings = _fetch_budgets_for_subscription(sub_id, token)
        all_findings.extend(findings)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "budget_alert_service: scan complete | subscriptions=%d findings=%d (%.0fms)",
        len(subscription_ids),
        len(all_findings),
        duration_ms,
    )
    return all_findings


def persist_budget_findings(
    findings: List[Dict[str, Any]],
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
) -> None:
    """Persist budget findings to Cosmos DB budget_alerts container.

    Never raises.
    """
    if not findings:
        return
    if cosmos_client is None:
        logger.warning("budget_alert_service: persist called without cosmos_client")
        return

    try:
        db = cosmos_client.get_database_client(cosmos_db)
        container = db.get_container_client(_COSMOS_CONTAINER)
        for finding in findings:
            container.upsert_item(finding)
        logger.info("budget_alert_service: persisted %d findings", len(findings))
    except Exception as exc:
        logger.warning("budget_alert_service: persist failed: %s", exc)


def get_budget_findings(
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
    subscription_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return budget findings from Cosmos DB with optional filters.

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
        if status:
            conditions.append("c.status = @status")
            params.append({"name": "@status", "value": status})

        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM c{where_clause} ORDER BY c.spend_pct DESC"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]

    except Exception as exc:
        logger.warning("budget_alert_service: get_budget_findings error: %s", exc)
        return []


def get_budget_summary(
    cosmos_client: Optional[Any] = None,
    cosmos_db: str = _COSMOS_DB,
    subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return budget summary: totals, exceeded, warning, no_budget counts.

    Never raises — returns zeroed summary on error.
    """
    empty: Dict[str, Any] = {
        "total_budgets": 0,
        "exceeded_count": 0,
        "warning_count": 0,
        "on_track_count": 0,
        "no_budget_count": 0,
    }

    findings = get_budget_findings(
        cosmos_client=cosmos_client,
        cosmos_db=cosmos_db,
        subscription_id=subscription_id,
    )

    if not findings:
        return empty

    status_counts: Dict[str, int] = {
        "exceeded": 0,
        "warning": 0,
        "on_track": 0,
        "no_budget": 0,
    }
    for f in findings:
        s = f.get("status", "no_budget")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "total_budgets": len(findings),
        "exceeded_count": status_counts.get("exceeded", 0),
        "warning_count": status_counts.get("warning", 0),
        "on_track_count": status_counts.get("on_track", 0),
        "no_budget_count": status_counts.get("no_budget", 0),
    }
