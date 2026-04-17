"""Pre-incident advisory service — z-score anomaly detection (Phase 73).

Detects anomaly precursors BEFORE incidents occur by comparing the latest
metric value against a rolling 7-day baseline using pure-Python z-score
analysis (no numpy/scipy).

Architecture:
- Pure functions: detect_anomaly, build_advisory
- AdvisoryRecord dataclass
- Cosmos helpers: get_advisories, dismiss_advisory, persist_advisory
- Container: pre_incident_advisories, partitionKey=/subscription_id, TTL 172800s
"""
from __future__ import annotations

import logging
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

ADVISORY_CONTAINER = "pre_incident_advisories"
ADVISORY_TTL_SECONDS = 172800  # 48 h


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class AdvisoryRecord:
    advisory_id: str           # "adv-<uuid8>"
    subscription_id: str
    resource_id: str
    resource_name: str
    metric_name: str           # "cpu_percentage", "disk_usage_pct", …
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    severity: str              # "warning" (2.5–3.5σ) or "critical" (>3.5σ)
    trend_direction: str       # "rising" | "falling" | "stable"
    estimated_breach_hours: Optional[float]
    message: str
    detected_at: str           # ISO-8601
    status: str                # "active" | "dismissed" | "resolved"
    pattern_match: Optional[str]


# ---------------------------------------------------------------------------
# Pure anomaly-detection helpers
# ---------------------------------------------------------------------------


def detect_anomaly(
    values: list[float],
    threshold_sigma: float = 2.5,
) -> tuple[bool, float]:
    """Return (is_anomaly, z_score).

    Requires at least 10 data points; returns (False, 0.0) otherwise.
    The latest element of *values* is the candidate; the rest form the
    baseline population.
    """
    if len(values) < 10:
        return False, 0.0

    baseline = values[:-1]
    latest = values[-1]

    mean = statistics.mean(baseline)
    try:
        stdev = statistics.stdev(baseline)
    except statistics.StatisticsError:
        return False, 0.0

    if stdev == 0.0:
        return False, 0.0

    z = (latest - mean) / stdev
    return abs(z) >= threshold_sigma, z


def _trend_direction(values: list[float]) -> str:
    """Classify direction from the last 3 values."""
    if len(values) < 3:
        return "stable"
    last3 = values[-3:]
    if last3[-1] > last3[0] * 1.02:
        return "rising"
    if last3[-1] < last3[0] * 0.98:
        return "falling"
    return "stable"


def _severity_from_z(z_score: float) -> str:
    abs_z = abs(z_score)
    if abs_z > 3.5:
        return "critical"
    return "warning"


def _build_message(
    *,
    resource_name: str,
    metric_name: str,
    current_value: float,
    baseline_mean: float,
    z_score: float,
    trend_direction: str,
    estimated_breach_hours: Optional[float],
    pattern_match: Optional[str],
) -> str:
    direction_phrase = {
        "rising": "rising",
        "falling": "falling",
        "stable": "stable",
    }.get(trend_direction, "stable")

    msg = (
        f"{resource_name}: {metric_name} is {current_value:.1f} "
        f"({abs(z_score):.1f}σ above baseline mean {baseline_mean:.1f}), "
        f"trend {direction_phrase}."
    )
    if estimated_breach_hours is not None:
        msg += f" Estimated breach in ~{estimated_breach_hours:.1f}h."
    if pattern_match:
        msg += f" Pattern: {pattern_match}."
    return msg


def build_advisory(
    *,
    subscription_id: str,
    resource_id: str,
    resource_name: str,
    metric_name: str,
    values: list[float],
    threshold_sigma: float = 2.5,
    estimated_breach_hours: Optional[float] = None,
    pattern_match: Optional[str] = None,
) -> Optional[AdvisoryRecord]:
    """Build an AdvisoryRecord if an anomaly is detected; returns None otherwise."""
    is_anomaly, z_score = detect_anomaly(values, threshold_sigma)
    if not is_anomaly:
        return None

    baseline = values[:-1]
    mean = statistics.mean(baseline)
    try:
        stdev = statistics.stdev(baseline)
    except statistics.StatisticsError:
        stdev = 0.0

    current_value = values[-1]
    trend = _trend_direction(values)
    severity = _severity_from_z(z_score)
    advisory_id = f"adv-{uuid.uuid4().hex[:8]}"
    detected_at = datetime.now(timezone.utc).isoformat()

    message = _build_message(
        resource_name=resource_name,
        metric_name=metric_name,
        current_value=current_value,
        baseline_mean=mean,
        z_score=z_score,
        trend_direction=trend,
        estimated_breach_hours=estimated_breach_hours,
        pattern_match=pattern_match,
    )

    return AdvisoryRecord(
        advisory_id=advisory_id,
        subscription_id=subscription_id,
        resource_id=resource_id,
        resource_name=resource_name,
        metric_name=metric_name,
        current_value=current_value,
        baseline_mean=mean,
        baseline_stddev=stdev,
        z_score=z_score,
        severity=severity,
        trend_direction=trend,
        estimated_breach_hours=estimated_breach_hours,
        message=message,
        detected_at=detected_at,
        status="active",
        pattern_match=pattern_match,
    )


# ---------------------------------------------------------------------------
# Cosmos helpers
# ---------------------------------------------------------------------------


async def get_advisories(
    cosmos_client: Any,
    cosmos_database_name: str,
    *,
    subscription_id: Optional[str] = None,
    status: str = "active",
    limit: int = 50,
) -> list[dict]:
    """Query active advisories from Cosmos pre_incident_advisories container."""
    if cosmos_client is None:
        return []

    try:
        db = cosmos_client.get_database_client(cosmos_database_name)
        container = db.get_container_client(ADVISORY_CONTAINER)

        params: list[dict] = [{"name": "@status", "value": status}]
        conditions = ["c.status = @status"]

        if subscription_id:
            conditions.append("c.subscription_id = @subscription_id")
            params.append({"name": "@subscription_id", "value": subscription_id})

        query = (
            f"SELECT TOP {limit} * FROM c "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY c.detected_at DESC"
        )

        items = list(
            container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
        return items
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_advisories failed: %s", exc)
        return []


async def dismiss_advisory(
    cosmos_client: Any,
    cosmos_database_name: str,
    advisory_id: str,
) -> bool:
    """Set advisory status to dismissed. Returns True if found+updated."""
    if cosmos_client is None:
        return False

    try:
        db = cosmos_client.get_database_client(cosmos_database_name)
        container = db.get_container_client(ADVISORY_CONTAINER)

        query = "SELECT * FROM c WHERE c.advisory_id = @advisory_id"
        params = [{"name": "@advisory_id", "value": advisory_id}]
        items = list(
            container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )

        if not items:
            return False

        doc = items[0]
        doc["status"] = "dismissed"
        container.upsert_item(doc)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("dismiss_advisory failed: %s", exc)
        return False


async def persist_advisory(
    cosmos_client: Any,
    cosmos_database_name: str,
    record: AdvisoryRecord,
) -> None:
    """Upsert advisory to Cosmos. No-op if cosmos_client is None."""
    if cosmos_client is None:
        return

    try:
        db = cosmos_client.get_database_client(cosmos_database_name)
        container = db.get_container_client(ADVISORY_CONTAINER)

        doc: dict[str, Any] = {
            "id": record.advisory_id,
            "advisory_id": record.advisory_id,
            "subscription_id": record.subscription_id,
            "resource_id": record.resource_id,
            "resource_name": record.resource_name,
            "metric_name": record.metric_name,
            "current_value": record.current_value,
            "baseline_mean": record.baseline_mean,
            "baseline_stddev": record.baseline_stddev,
            "z_score": record.z_score,
            "severity": record.severity,
            "trend_direction": record.trend_direction,
            "estimated_breach_hours": record.estimated_breach_hours,
            "message": record.message,
            "detected_at": record.detected_at,
            "status": record.status,
            "pattern_match": record.pattern_match,
            "ttl": ADVISORY_TTL_SECONDS,
        }
        container.upsert_item(doc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_advisory failed: %s", exc)
