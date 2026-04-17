from __future__ import annotations
"""Cost anomaly detection service — Azure Cost Management REST API + z-score detection.

Calls the Azure Cost Management REST API directly (no SDK) to fetch daily cost
snapshots per service, runs pure-Python z-score analysis per service, and persists
results to Cosmos DB.

Containers:
  cost_snapshots  — TTL 7 days  (604800)
  cost_anomalies  — TTL 48 hours (172800)

Design rules:
  - Service functions NEVER raise; return [] or {} on error and log warning.
  - Python 3.9 compat: Optional[X] not X | None in signatures.
  - Pure-Python z-score via statistics.mean / statistics.stdev.
"""
import os

import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import — requests already in requirements
# ---------------------------------------------------------------------------
try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False
    logger.warning("cost_service: requests not available — fetch_daily_costs disabled")

# ---------------------------------------------------------------------------
# Cosmos container names
# ---------------------------------------------------------------------------
COST_SNAPSHOTS_CONTAINER = os.environ.get("COSMOS_COST_SNAPSHOTS_CONTAINER", "cost_snapshots")
COST_ANOMALIES_CONTAINER = os.environ.get("COSMOS_COST_ANOMALIES_CONTAINER", "cost_anomalies")
COSMOS_DATABASE = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DailyCostSnapshot:
    """One day's cost for a single service in a subscription."""

    snapshot_id: str          # uuid4
    subscription_id: str
    date: str                 # YYYY-MM-DD
    service_name: str
    cost_usd: float
    currency: str
    captured_at: str          # ISO 8601
    ttl: int = 604800         # 7 days


@dataclass
class CostAnomaly:
    """A detected cost spike relative to the rolling 7-day baseline."""

    anomaly_id: str           # uuid4
    subscription_id: str
    service_name: str
    date: str                 # date of spike  YYYY-MM-DD
    cost_usd: float           # actual spend
    baseline_usd: float       # rolling 7-day average
    z_score: float
    severity: str             # "warning" (2.5–3.5σ) | "critical" (>3.5σ)
    pct_change: float         # (cost − baseline) / baseline * 100
    description: str
    detected_at: str          # ISO 8601
    ttl: int = 172800         # 48 hours


# ---------------------------------------------------------------------------
# Cost Management API fetch
# ---------------------------------------------------------------------------

_COST_MGMT_API_VERSION = "2023-11-01"
_COST_MGMT_SCOPE = "https://management.azure.com/.default"


def _get_bearer_token(credential: Any) -> str:
    """Obtain an ARM bearer token from DefaultAzureCredential."""
    token = credential.get_token(_COST_MGMT_SCOPE)
    return token.token


def fetch_daily_costs(
    credential: Any,
    subscription_id: str,
    days: int = 14,
) -> List[DailyCostSnapshot]:
    """Fetch daily costs per service from the Azure Cost Management REST API.

    Args:
        credential: DefaultAzureCredential instance.
        subscription_id: Azure subscription ID.
        days: Number of days of history to retrieve (default 14).

    Returns:
        List of DailyCostSnapshot objects; empty list on any error.
    """
    if not _REQUESTS_AVAILABLE:
        logger.warning("cost_service: requests unavailable; returning empty snapshots")
        return []

    start_time = time.monotonic()
    captured_at = datetime.now(timezone.utc).isoformat()

    try:
        token = _get_bearer_token(credential)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cost_service: failed to obtain bearer token | sub=%s error=%s",
            subscription_id, exc,
        )
        return []

    today = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=days)).isoformat()
    to_date = today.isoformat()

    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/providers/Microsoft.CostManagement/query"
        f"?api-version={_COST_MGMT_API_VERSION}"
    )
    body = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": from_date, "to": to_date},
        "dataset": {
            "granularity": "Daily",
            "aggregation": {
                "totalCost": {"name": "Cost", "function": "Sum"},
            },
            "grouping": [
                {"type": "Dimension", "name": "ServiceName"},
            ],
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = _requests.post(url, json=body, headers=headers, timeout=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cost_service: HTTP request failed | sub=%s error=%s",
            subscription_id, exc,
        )
        return []

    duration_ms = (time.monotonic() - start_time) * 1000

    if resp.status_code == 403:
        logger.warning(
            "cost_service: 403 Forbidden — no Billing Reader role | sub=%s duration_ms=%.0f",
            subscription_id, duration_ms,
        )
        return []
    if resp.status_code == 404:
        logger.warning(
            "cost_service: 404 Not Found — subscription not found | sub=%s duration_ms=%.0f",
            subscription_id, duration_ms,
        )
        return []
    if resp.status_code == 429:
        logger.warning(
            "cost_service: 429 Rate Limited — Cost Management throttled | sub=%s duration_ms=%.0f",
            subscription_id, duration_ms,
        )
        return []
    if not resp.ok:
        logger.warning(
            "cost_service: unexpected HTTP %d | sub=%s duration_ms=%.0f body=%s",
            resp.status_code, subscription_id, duration_ms, resp.text[:200],
        )
        return []

    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cost_service: JSON parse error | sub=%s error=%s duration_ms=%.0f",
            subscription_id, exc, duration_ms,
        )
        return []

    # Parse response columns: Cost, UsageDate, ServiceName, Currency
    columns = [col.get("name", "") for col in data.get("properties", {}).get("columns", [])]
    rows = data.get("properties", {}).get("rows", [])

    try:
        cost_idx = columns.index("Cost")
        date_idx = columns.index("UsageDate")
        service_idx = columns.index("ServiceName")
        currency_idx = columns.index("Currency") if "Currency" in columns else None
    except ValueError as exc:
        logger.warning(
            "cost_service: unexpected column layout | sub=%s columns=%s error=%s",
            subscription_id, columns, exc,
        )
        return []

    snapshots: List[DailyCostSnapshot] = []
    for row in rows:
        try:
            raw_date = str(row[date_idx])
            # UsageDate comes back as "20240101" or "2024-01-01"
            if len(raw_date) == 8:
                date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            else:
                date_str = raw_date[:10]

            currency = str(row[currency_idx]) if currency_idx is not None else "USD"
            snapshots.append(
                DailyCostSnapshot(
                    snapshot_id=str(uuid.uuid4()),
                    subscription_id=subscription_id,
                    date=date_str,
                    service_name=str(row[service_idx]) or "Unknown",
                    cost_usd=float(row[cost_idx]),
                    currency=currency,
                    captured_at=captured_at,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cost_service: row parse error | sub=%s row=%s error=%s",
                subscription_id, row, exc,
            )

    logger.info(
        "cost_service: fetched %d snapshots | sub=%s days=%d duration_ms=%.0f",
        len(snapshots), subscription_id, days, duration_ms,
    )
    return snapshots


# ---------------------------------------------------------------------------
# Anomaly detection — pure Python z-score per service
# ---------------------------------------------------------------------------

_WARNING_SIGMA = 2.5
_CRITICAL_SIGMA = 3.5
_MIN_DATA_POINTS = 7  # need at least 7 days to compute a meaningful baseline


def detect_cost_anomalies(snapshots: List[DailyCostSnapshot]) -> List[CostAnomaly]:
    """Run z-score anomaly detection per service over daily cost snapshots.

    Uses a rolling 7-day baseline (mean of the 7 days preceding each point).
    Requires at least MIN_DATA_POINTS (7) days of data per service.

    Args:
        snapshots: All snapshots (may span multiple subscriptions/services).

    Returns:
        List of CostAnomaly; empty list if no anomalies found or data is insufficient.
    """
    if not snapshots:
        return []

    # Group by (subscription_id, service_name) → sorted list by date
    groups: Dict[tuple, List[DailyCostSnapshot]] = {}
    for snap in snapshots:
        key = (snap.subscription_id, snap.service_name)
        groups.setdefault(key, []).append(snap)

    for key in groups:
        groups[key].sort(key=lambda s: s.date)

    anomalies: List[CostAnomaly] = []
    detected_at = datetime.now(timezone.utc).isoformat()

    for (sub_id, service_name), series in groups.items():
        if len(series) < _MIN_DATA_POINTS:
            continue  # not enough data for a stable baseline

        costs = [s.cost_usd for s in series]

        # Compute population mean/stdev for z-score across all points
        mu = mean(costs)
        if len(costs) < 2:
            continue
        try:
            sigma = stdev(costs)
        except Exception:  # noqa: BLE001
            continue
        if sigma == 0.0:
            continue  # all values identical — no anomaly possible

        for i, snap in enumerate(series):
            # Only evaluate points that have at least 7 prior data points
            if i < _MIN_DATA_POINTS:
                continue

            # Rolling 7-day baseline = mean of the 7 days preceding this point
            baseline_window = series[i - 7 : i]
            baseline_usd = mean(s.cost_usd for s in baseline_window)

            z = (snap.cost_usd - mu) / sigma

            # Only flag positive spikes (spend increase)
            if z < _WARNING_SIGMA:
                continue

            severity = "critical" if z > _CRITICAL_SIGMA else "warning"
            pct_change = (
                (snap.cost_usd - baseline_usd) / baseline_usd * 100
                if baseline_usd > 0
                else 0.0
            )
            description = (
                f"{service_name} spend on {snap.date} was ${snap.cost_usd:.2f} "
                f"(+{pct_change:.1f}% vs 7-day baseline of ${baseline_usd:.2f}). "
                f"Z-score: {z:.2f}σ."
            )
            anomalies.append(
                CostAnomaly(
                    anomaly_id=str(uuid.uuid4()),
                    subscription_id=sub_id,
                    service_name=service_name,
                    date=snap.date,
                    cost_usd=snap.cost_usd,
                    baseline_usd=round(baseline_usd, 4),
                    z_score=round(z, 4),
                    severity=severity,
                    pct_change=round(pct_change, 2),
                    description=description,
                    detected_at=detected_at,
                )
            )

    logger.info("cost_service: detected %d anomalies from %d snapshots", len(anomalies), len(snapshots))
    return anomalies


# ---------------------------------------------------------------------------
# Cosmos persistence helpers
# ---------------------------------------------------------------------------


def _cosmos_container(cosmos_client: Any, db_name: str, container_name: str) -> Any:
    return cosmos_client.get_database_client(db_name).get_container_client(container_name)


def persist_snapshots(
    cosmos_client: Any,
    db_name: str,
    snapshots: List[DailyCostSnapshot],
) -> None:
    """Upsert daily cost snapshots into Cosmos DB.

    Non-fatal: logs warning on any error.
    """
    if cosmos_client is None or not snapshots:
        return
    start_time = time.monotonic()
    container = _cosmos_container(cosmos_client, db_name, COST_SNAPSHOTS_CONTAINER)
    errors = 0
    for snap in snapshots:
        try:
            doc = asdict(snap)
            doc["id"] = snap.snapshot_id
            container.upsert_item(doc)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning("cost_service: snapshot upsert failed | id=%s error=%s", snap.snapshot_id, exc)
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "cost_service: persisted %d/%d snapshots | errors=%d duration_ms=%.0f",
        len(snapshots) - errors, len(snapshots), errors, duration_ms,
    )


def persist_anomalies(
    cosmos_client: Any,
    db_name: str,
    anomalies: List[CostAnomaly],
) -> None:
    """Upsert cost anomalies into Cosmos DB.

    Non-fatal: logs warning on any error.
    """
    if cosmos_client is None or not anomalies:
        return
    start_time = time.monotonic()
    container = _cosmos_container(cosmos_client, db_name, COST_ANOMALIES_CONTAINER)
    errors = 0
    for anomaly in anomalies:
        try:
            doc = asdict(anomaly)
            doc["id"] = anomaly.anomaly_id
            container.upsert_item(doc)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning("cost_service: anomaly upsert failed | id=%s error=%s", anomaly.anomaly_id, exc)
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "cost_service: persisted %d/%d anomalies | errors=%d duration_ms=%.0f",
        len(anomalies) - errors, len(anomalies), errors, duration_ms,
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_anomalies(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    severity: Optional[str] = None,
) -> List[CostAnomaly]:
    """Retrieve cost anomalies from Cosmos DB.

    Args:
        cosmos_client: Shared CosmosClient (may be None).
        db_name: Cosmos database name.
        subscription_ids: Optional list to filter by subscription.
        severity: Optional "warning" or "critical" filter.

    Returns:
        List of CostAnomaly; empty list on error or missing Cosmos.
    """
    if cosmos_client is None:
        return []
    start_time = time.monotonic()
    try:
        container = _cosmos_container(cosmos_client, db_name, COST_ANOMALIES_CONTAINER)
        query = "SELECT * FROM c"
        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sub in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sub})

        if severity:
            conditions.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity})

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "cost_service: get_anomalies returned %d items | duration_ms=%.0f",
            len(items), duration_ms,
        )
        return [
            CostAnomaly(**{k: v for k, v in item.items() if not k.startswith("_") and k != "id"})
            for item in items
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("cost_service: get_anomalies failed | error=%s", exc)
        return []


def get_cost_summary(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Aggregate cost anomaly summary across subscriptions.

    Returns:
        {
          total_anomalies: int,
          critical_count: int,
          warning_count: int,
          top_spenders: [{service, cost, change_pct}],
        }
    """
    anomalies = get_anomalies(cosmos_client, db_name, subscription_ids=subscription_ids)

    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")

    # Top spenders by cost_usd, deduplicated by service name (keep highest)
    service_max: Dict[str, CostAnomaly] = {}
    for a in anomalies:
        existing = service_max.get(a.service_name)
        if existing is None or a.cost_usd > existing.cost_usd:
            service_max[a.service_name] = a

    top_spenders = sorted(service_max.values(), key=lambda a: a.cost_usd, reverse=True)[:5]

    return {
        "total_anomalies": len(anomalies),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "top_spenders": [
            {
                "service": a.service_name,
                "cost": a.cost_usd,
                "change_pct": a.pct_change,
            }
            for a in top_spenders
        ],
    }


def get_cost_snapshots(
    cosmos_client: Any,
    db_name: str,
    subscription_id: Optional[str] = None,
    service_name: Optional[str] = None,
    days: int = 14,
) -> List[DailyCostSnapshot]:
    """Retrieve daily cost snapshots for sparkline rendering.

    Args:
        cosmos_client: Shared CosmosClient (may be None).
        db_name: Cosmos database name.
        subscription_id: Optional subscription filter.
        service_name: Optional service name filter.
        days: How many days back to look (default 14).

    Returns:
        List of DailyCostSnapshot; empty list on error.
    """
    if cosmos_client is None:
        return []
    start_time = time.monotonic()
    try:
        container = _cosmos_container(cosmos_client, db_name, COST_SNAPSHOTS_CONTAINER)
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        query = "SELECT * FROM c WHERE c.date >= @cutoff"
        params: List[Dict[str, Any]] = [{"name": "@cutoff", "value": cutoff_date}]

        if subscription_id:
            query += " AND c.subscription_id = @sub_id"
            params.append({"name": "@sub_id", "value": subscription_id})

        if service_name:
            query += " AND c.service_name = @service_name"
            params.append({"name": "@service_name", "value": service_name})

        items = list(container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        ))
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "cost_service: get_cost_snapshots returned %d items | duration_ms=%.0f",
            len(items), duration_ms,
        )
        return [
            DailyCostSnapshot(**{k: v for k, v in item.items() if not k.startswith("_") and k != "id"})
            for item in items
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("cost_service: get_cost_snapshots failed | error=%s", exc)
        return []


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_cost_scan(
    credential: Any,
    cosmos_client: Any,
    db_name: str,
    subscription_ids: List[str],
) -> Dict[str, Any]:
    """Orchestrate: fetch → detect → persist for all subscriptions.

    Args:
        credential: DefaultAzureCredential.
        cosmos_client: Shared CosmosClient (may be None).
        db_name: Cosmos database name.
        subscription_ids: List of Azure subscription IDs to scan.

    Returns:
        Summary dict with scan stats; never raises.
    """
    start_time = time.monotonic()
    all_snapshots: List[DailyCostSnapshot] = []
    fetch_errors = 0

    for sub_id in subscription_ids:
        snaps = fetch_daily_costs(credential, sub_id)
        if snaps:
            all_snapshots.extend(snaps)
        else:
            fetch_errors += 1

    anomalies = detect_cost_anomalies(all_snapshots)
    persist_snapshots(cosmos_client, db_name, all_snapshots)
    persist_anomalies(cosmos_client, db_name, anomalies)

    duration_ms = (time.monotonic() - start_time) * 1000
    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")

    logger.info(
        "cost_service: scan complete | subs=%d snapshots=%d anomalies=%d "
        "critical=%d warning=%d fetch_errors=%d duration_ms=%.0f",
        len(subscription_ids), len(all_snapshots), len(anomalies),
        critical_count, warning_count, fetch_errors, duration_ms,
    )

    return {
        "subscriptions_scanned": len(subscription_ids),
        "snapshots_fetched": len(all_snapshots),
        "anomalies_detected": len(anomalies),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "fetch_errors": fetch_errors,
        "duration_ms": round(duration_ms, 0),
    }
