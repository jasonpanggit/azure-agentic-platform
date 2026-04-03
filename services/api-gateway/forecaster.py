"""Capacity exhaustion forecaster — double exponential smoothing (INTEL-005).

Implements Holt's method (double exponential smoothing) in pure Python
(no numpy/statsmodels) to forecast when Azure resource metrics will breach
capacity thresholds. Runs as a 15-minute background sweep.

Architecture:
- Pure functions: _holt_smooth, _compute_mape, _compute_time_to_breach
- ForecasterClient: collects metrics, stores baselines in Cosmos, emits alerts
- run_forecast_sweep_loop: asyncio background task (mirrors topology.py pattern)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FORECAST_ENABLED: bool = os.environ.get("FORECAST_ENABLED", "true").lower() == "true"
FORECAST_SWEEP_INTERVAL_SECONDS: int = int(
    os.environ.get("FORECAST_SWEEP_INTERVAL_SECONDS", "900")
)
FORECAST_BREACH_ALERT_MINUTES: float = float(
    os.environ.get("FORECAST_BREACH_ALERT_MINUTES", "60")
)
COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")
BASELINES_CONTAINER: str = "baselines"
# Number of data points to use for Holt smoothing (2h at 5-min intervals)
_DATA_WINDOW = 24
# Points used for hold-out MAPE validation (fit on first 18, predict last 6)
_HOLDOUT_POINTS = 6
_FIT_POINTS = _DATA_WINDOW - _HOLDOUT_POINTS  # 18

# Metrics to forecast, keyed by ARM resource type (lowercased).
# Each entry: name, threshold, unit, and optional invert flag.
# invert=True means breach occurs when metric goes LOW (e.g. Available Memory).
FORECAST_METRICS: Dict[str, List[Dict[str, Any]]] = {
    "microsoft.compute/virtualmachines": [
        {"name": "Percentage CPU",         "threshold": 90.0, "unit": "%"},
        {"name": "Available Memory Bytes", "threshold": 0.1,  "unit": "GB", "invert": True},
        {"name": "OS Disk Queue Depth",    "threshold": 10.0, "unit": "count"},
    ],
    "microsoft.sql/servers/databases": [
        {"name": "dtu_consumption_percent", "threshold": 90.0, "unit": "%"},
        {"name": "storage_percent",          "threshold": 85.0, "unit": "%"},
    ],
    "microsoft.storage/storageaccounts": [
        {"name": "UsedCapacity", "threshold": 90.0, "unit": "%_of_quota"},
    ],
}


@dataclass
class _ForecastBaseline:
    """Internal state for a single metric baseline document."""

    resource_id: str
    metric_name: str
    resource_type: str
    data_points: List[Dict[str, Any]]   # [{"timestamp": str, "value": float}, ...]
    level: float
    trend: float
    threshold: float
    invert: bool
    time_to_breach_minutes: Optional[float]
    confidence: str                      # high | medium | low
    mape: float
    last_updated: str


def _holt_smooth(
    values: List[float], alpha: float = 0.3, beta: float = 0.1
) -> tuple[float, float]:
    """Double exponential smoothing (Holt's method).

    Returns (level, trend) after processing all values.
    Requires at least 2 data points; returns (values[-1], 0.0) for a single
    point and (0.0, 0.0) for an empty list.

    Algorithm:
        level[0]  = values[0]
        trend[0]  = values[1] - values[0]
        level[t]  = α * values[t] + (1 − α) * (level[t-1] + trend[t-1])
        trend[t]  = β * (level[t] − level[t-1]) + (1 − β) * trend[t-1]

    Args:
        values: Ordered time-series values (oldest first).
        alpha:  Smoothing factor for level (0 < α < 1). Default 0.3.
        beta:   Smoothing factor for trend (0 < β < 1). Default 0.1.

    Returns:
        Tuple of (level, trend) at the last data point.
    """
    if not values:
        return 0.0, 0.0
    if len(values) < 2:
        return float(values[-1]), 0.0
    level = float(values[0])
    trend = float(values[1]) - float(values[0])
    for v in values[1:]:
        prev_level = level
        level = alpha * float(v) + (1.0 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1.0 - beta) * trend
    return level, trend


def _compute_mape(actual: List[float], predicted: List[float]) -> float:
    """Mean Absolute Percentage Error (MAPE) between actual and predicted.

    Skips zero-value actuals to avoid division by zero.
    Returns 0.0 if no valid pairs exist.

    Args:
        actual:    Ground-truth values.
        predicted: Model-predicted values (same length as actual).

    Returns:
        MAPE as a percentage (e.g. 12.5 means 12.5% error).
    """
    if not actual or len(actual) != len(predicted):
        return 0.0
    errors = []
    for a, p in zip(actual, predicted):
        if a != 0.0:
            errors.append(abs((a - p) / a) * 100.0)
    return sum(errors) / len(errors) if errors else 0.0


def _compute_time_to_breach(
    level: float,
    trend: float,
    threshold: float,
    invert: bool = False,
) -> Optional[float]:
    """Estimate minutes until the metric breaches the threshold.

    Uses linear projection from current level at rate of `trend` per interval.
    One interval = 5 minutes (PT5M Azure Monitor resolution).

    For normal metrics (invert=False):   breach when level + h*trend >= threshold
    For inverted metrics (invert=True):  breach when level + h*trend <= threshold
                                          (e.g. Available Memory going to zero)

    Returns None when:
    - Trend is flat or moving away from threshold (no imminent breach)
    - Level has already breached threshold

    Args:
        level:     Current smoothed value.
        trend:     Trend per 5-minute interval from Holt smoothing.
        threshold: Capacity threshold value.
        invert:    True for metrics where low value = breach.

    Returns:
        Time to breach in minutes, or None if not breaching.
    """
    _INTERVAL_MINUTES = 5.0

    if not invert:
        # Normal: breach when value rises above threshold
        if level >= threshold:
            return None  # already breached
        if trend <= 0:
            return None  # stable or declining — no breach
        intervals = (threshold - level) / trend
    else:
        # Inverted: breach when value falls below threshold
        if level <= threshold:
            return None  # already breached
        if trend >= 0:
            return None  # stable or rising — no breach
        intervals = (level - threshold) / abs(trend)

    minutes = intervals * _INTERVAL_MINUTES
    # Cap at 24 hours — beyond that, forecast confidence is too low to be useful
    if minutes > 1440:
        return None
    return round(minutes, 1)


def _domain_for_resource_type(resource_type: str) -> str:
    """Map ARM resource type to incident domain for FORECAST_ALERT incidents."""
    _rtype = resource_type.lower()
    if "compute" in _rtype or "virtualmachine" in _rtype:
        return "compute"
    if "sql" in _rtype or "database" in _rtype:
        return "storage"
    if "storage" in _rtype:
        return "storage"
    return "sre"


def _emit_forecast_alert(
    incident_id: str,
    resource_id: str,
    resource_type: str,
    metric_name: str,
    threshold: float,
    ttb: float,
    confidence: str,
) -> Dict[str, Any]:
    """Build a synthetic FORECAST_ALERT incident payload dict.

    The caller is responsible for posting this to POST /api/v1/incidents
    or calling ingest_incident() directly. This function only constructs
    the payload — it does not perform any I/O.

    Args:
        incident_id:   Pre-generated unique incident ID.
        resource_id:   ARM resource ID of the affected resource.
        resource_type: ARM resource type (lowercased).
        metric_name:   Name of the metric that will breach.
        threshold:     Threshold value that will be breached.
        ttb:           Estimated minutes until breach.
        confidence:    Forecast confidence: high | medium | low.

    Returns:
        Dict matching the IncidentPayload schema.
    """
    domain = _domain_for_resource_type(resource_type)
    # Extract subscription_id from ARM resource ID
    _parts = resource_id.lower().split("/")
    try:
        _sub_idx = _parts.index("subscriptions")
        subscription_id = resource_id.split("/")[_sub_idx + 1]
    except (ValueError, IndexError):
        subscription_id = "unknown"

    metric_slug = re.sub(r"[^a-z0-9]+", "_", metric_name.lower()).strip("_")

    return {
        "incident_id": incident_id,
        "severity": "Sev2",
        "domain": domain,
        "affected_resources": [
            {
                "resource_id": resource_id,
                "subscription_id": subscription_id,
                "resource_type": resource_type,
            }
        ],
        "detection_rule": "forecast_capacity_exhaustion",
        "title": f"Capacity forecast alert: {metric_name} breach in {ttb:.0f}m",
        "description": (
            f"Forecast: {metric_name} will breach {threshold}% threshold in "
            f"{ttb:.0f} minutes (confidence: {confidence})"
        ),
    }


class ForecasterClient:
    """Manages capacity forecasting baselines in Cosmos DB.

    Lifecycle:
    1. ForecasterClient is instantiated in lifespan startup (Plan 26-3).
    2. run_forecast_sweep_loop calls sweep() every 15 minutes.
    3. Forecast API endpoints call get_forecasts() and get_all_imminent().

    All Cosmos and Azure Monitor calls run in run_in_executor to avoid
    blocking the asyncio event loop (same pattern as TopologyClient).
    """

    def __init__(self, cosmos_client: Any, credential: Any):
        self._cosmos = cosmos_client
        self._credential = credential
        self._container: Optional[Any] = None

    def _get_container(self) -> Any:
        """Return Cosmos baselines container client (lazy init)."""
        if self._container is None:
            db = self._cosmos.get_database_client(COSMOS_DATABASE)
            self._container = db.get_container_client(BASELINES_CONTAINER)
        return self._container

    def collect_metrics(
        self,
        resource_id: str,
        metric_name: str,
        credential: Any,
    ) -> List[Dict[str, Any]]:
        """Collect last 2h of Azure Monitor metrics for a single metric.

        Runs synchronously (designed to be called in run_in_executor).

        Returns list of {"timestamp": str, "value": float} dicts,
        capped at _DATA_WINDOW (24) most recent points.
        Returns empty list on any error (non-fatal).
        """
        try:
            from azure.mgmt.monitor import MonitorManagementClient

            parts = resource_id.lower().split("/")
            sub_idx = parts.index("subscriptions")
            sub_id = resource_id.split("/")[sub_idx + 1]

            now = datetime.now(timezone.utc)
            start = now - timedelta(hours=2)
            timespan = f"{start.isoformat()}/{now.isoformat()}"

            client = MonitorManagementClient(credential, sub_id)
            result = client.metrics.list(
                resource_uri=resource_id,
                timespan=timespan,
                interval="PT5M",
                metricnames=metric_name,
                aggregation="Average",
            )
            data_points: List[Dict[str, Any]] = []
            for metric in result.value:
                for ts in metric.timeseries:
                    for dp in ts.data:
                        if dp.average is not None:
                            data_points.append({
                                "timestamp": dp.time_stamp.isoformat(),
                                "value": dp.average,
                            })
            # Sort ascending by timestamp, keep last _DATA_WINDOW points
            data_points.sort(key=lambda x: x["timestamp"])
            return data_points[-_DATA_WINDOW:]
        except Exception as exc:
            logger.debug(
                "forecaster: collect_metrics failed | resource=%s metric=%s error=%s",
                resource_id[:80], metric_name, exc,
            )
            return []

    def update_baseline(
        self,
        resource_id: str,
        resource_type: str,
        metric_name: str,
        data_points: List[Dict[str, Any]],
        threshold: float,
        invert: bool = False,
    ) -> Optional[_ForecastBaseline]:
        """Compute Holt smoothing + MAPE and upsert baseline doc in Cosmos.

        Runs synchronously (designed to be called in run_in_executor).
        Returns the computed baseline, or None if fewer than 2 data points.
        Never raises — returns None on Cosmos write failure (non-fatal).
        """
        if len(data_points) < 2:
            logger.debug(
                "forecaster: insufficient data | resource=%s metric=%s points=%d",
                resource_id[:80], metric_name, len(data_points),
            )
            return None

        values = [dp["value"] for dp in data_points]

        # Hold-out MAPE validation (only when enough points available)
        mape = 0.0
        if len(values) >= _DATA_WINDOW:
            fit_values = values[:_FIT_POINTS]
            holdout_actual = values[_FIT_POINTS:]
            fit_level, fit_trend = _holt_smooth(fit_values)
            holdout_predicted = [
                fit_level + (i + 1) * fit_trend
                for i in range(len(holdout_actual))
            ]
            mape = _compute_mape(holdout_actual, holdout_predicted)

        # Final smoothing on all points
        level, trend = _holt_smooth(values)
        ttb = _compute_time_to_breach(level, trend, threshold, invert)

        # Confidence from MAPE
        if mape < 15.0:
            confidence = "high"
        elif mape < 30.0:
            confidence = "medium"
        else:
            confidence = "low"

        now_iso = datetime.now(timezone.utc).isoformat()
        doc_id = f"{resource_id}:{metric_name}"

        baseline = _ForecastBaseline(
            resource_id=resource_id,
            metric_name=metric_name,
            resource_type=resource_type.lower(),
            data_points=data_points,
            level=level,
            trend=trend,
            threshold=threshold,
            invert=invert,
            time_to_breach_minutes=ttb,
            confidence=confidence,
            mape=mape,
            last_updated=now_iso,
        )

        if self._cosmos is not None:
            try:
                container = self._get_container()
                container.upsert_item({
                    "id": doc_id,
                    "resource_id": resource_id,
                    "metric_name": metric_name,
                    "resource_type": resource_type.lower(),
                    "data_points": data_points,
                    "level": level,
                    "trend": trend,
                    "threshold": threshold,
                    "invert": invert,
                    "time_to_breach_minutes": ttb,
                    "confidence": confidence,
                    "mape": mape,
                    "last_updated": now_iso,
                })
            except Exception as exc:
                logger.warning(
                    "forecaster: cosmos upsert failed (non-fatal) | "
                    "resource=%s metric=%s error=%s",
                    resource_id[:80], metric_name, exc,
                )
        return baseline

    def get_forecasts(self, resource_id: str) -> List[Dict[str, Any]]:
        """Return all baseline documents for a given resource_id.

        Runs synchronously. Returns empty list if Cosmos unavailable or
        resource not found (non-fatal).
        """
        if self._cosmos is None:
            return []
        try:
            container = self._get_container()
            query = "SELECT * FROM c WHERE c.resource_id = @rid"
            params = [{"name": "@rid", "value": resource_id}]
            items = list(container.query_items(
                query=query,
                parameters=params,
                partition_key=resource_id,
            ))
            return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]
        except Exception as exc:
            logger.debug(
                "forecaster: get_forecasts error | resource=%s error=%s",
                resource_id[:80], exc,
            )
            return []

    def get_all_imminent(self) -> List[Dict[str, Any]]:
        """Return all baseline documents where time_to_breach < FORECAST_BREACH_ALERT_MINUTES.

        Cross-partition query — used by GET /api/v1/forecasts (no resource_id param).
        Returns empty list if Cosmos unavailable (non-fatal).
        """
        if self._cosmos is None:
            return []
        try:
            container = self._get_container()
            query = (
                "SELECT * FROM c "
                "WHERE c.time_to_breach_minutes != null "
                "AND c.time_to_breach_minutes < @threshold"
            )
            params = [{"name": "@threshold", "value": FORECAST_BREACH_ALERT_MINUTES}]
            items = list(container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            ))
            return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]
        except Exception as exc:
            logger.warning("forecaster: get_all_imminent error | error=%s", exc)
            return []


async def run_forecast_sweep_loop(
    cosmos_client: Any,
    credential: Any,
    topology_client: Any,
    interval_seconds: int = FORECAST_SWEEP_INTERVAL_SECONDS,
) -> None:
    """Background asyncio task: sweep all resources and refresh forecasts.

    Follows the same pattern as run_topology_sync_loop in topology.py:
    - Waits one full interval before first sweep (topology bootstrap runs first).
    - Uses run_in_executor for blocking Cosmos + Azure Monitor calls.
    - Handles CancelledError cleanly for graceful shutdown.
    - Logs but does not raise on transient errors (sweep continues).

    If FORECAST_ENABLED=false, logs and exits immediately.

    Args:
        cosmos_client:    CosmosClient instance (from app.state).
        credential:       DefaultAzureCredential (from app.state).
        topology_client:  TopologyClient for resource discovery.
        interval_seconds: Sweep interval (default 900 — 15 minutes).
    """
    if not FORECAST_ENABLED:
        logger.info("forecaster: sweep loop disabled (FORECAST_ENABLED=false)")
        return

    forecaster = ForecasterClient(cosmos_client, credential)
    logger.info("forecaster: sweep loop started | interval=%ds", interval_seconds)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, _run_sweep_sync, forecaster, cosmos_client, credential, topology_client
            )
            logger.info(
                "forecaster: sweep complete | resources=%d forecasts=%d alerts=%d",
                result.get("resources", 0),
                result.get("forecasts", 0),
                result.get("alerts_emitted", 0),
            )
        except asyncio.CancelledError:
            logger.info("forecaster: sweep loop cancelled — shutting down")
            raise
        except Exception as exc:
            logger.error(
                "forecaster: sweep loop unexpected error | error=%s", exc, exc_info=True
            )
            # Continue loop — transient errors must not stop the background task


def _run_sweep_sync(
    forecaster: ForecasterClient,
    cosmos_client: Any,
    credential: Any,
    topology_client: Any,
) -> Dict[str, int]:
    """Synchronous sweep body — runs in executor thread.

    1. Queries the topology container for all resource IDs and types.
    2. For each resource with a known type in FORECAST_METRICS:
       a. Collect last 2h of metrics for each configured metric.
       b. Compute forecast and upsert to Cosmos baselines container.
       c. If time_to_breach < FORECAST_BREACH_ALERT_MINUTES, emit alert.
    3. Returns summary counts.

    Non-fatal: individual resource failures are logged and skipped.
    """
    resources_processed = 0
    forecasts_updated = 0
    alerts_emitted = 0

    # Discover resources via topology container
    resource_items: List[Dict[str, Any]] = []
    if topology_client is not None:
        try:
            db = cosmos_client.get_database_client(COSMOS_DATABASE)
            topo_container = db.get_container_client("topology")
            resource_items = list(topo_container.query_items(
                "SELECT c.resource_id, c.resource_type FROM c",
                enable_cross_partition_query=True,
            ))
        except Exception as exc:
            logger.warning("forecaster: topology query failed | error=%s", exc)

    for item in resource_items:
        resource_id = item.get("resource_id", "")
        resource_type = (item.get("resource_type") or "").lower()
        if not resource_id or resource_type not in FORECAST_METRICS:
            continue

        resources_processed += 1
        metrics_config = FORECAST_METRICS[resource_type]

        for metric_cfg in metrics_config:
            metric_name = metric_cfg["name"]
            threshold = metric_cfg["threshold"]
            invert = metric_cfg.get("invert", False)

            data_points = forecaster.collect_metrics(resource_id, metric_name, credential)
            if not data_points:
                continue

            baseline = forecaster.update_baseline(
                resource_id=resource_id,
                resource_type=resource_type,
                metric_name=metric_name,
                data_points=data_points,
                threshold=threshold,
                invert=invert,
            )
            if baseline is not None:
                forecasts_updated += 1

                ttb = baseline.time_to_breach_minutes
                if ttb is not None and ttb < FORECAST_BREACH_ALERT_MINUTES:
                    # Emit synthetic FORECAST_ALERT incident
                    from datetime import datetime as _dt, timezone as _tz
                    metric_slug = re.sub(
                        r"[^a-z0-9]+", "_", metric_name.lower()
                    ).strip("_")
                    ts_compact = _dt.now(_tz.utc).strftime("%Y%m%dT%H%M%S")
                    incident_id = (
                        f"forecast-{resource_id[-8:]}-{metric_slug[:20]}-{ts_compact}"
                    )
                    alert_payload = _emit_forecast_alert(
                        incident_id=incident_id,
                        resource_id=resource_id,
                        resource_type=resource_type,
                        metric_name=metric_name,
                        threshold=threshold,
                        ttb=ttb,
                        confidence=baseline.confidence,
                    )
                    _post_forecast_alert(cosmos_client, alert_payload)
                    alerts_emitted += 1

    return {
        "resources": resources_processed,
        "forecasts": forecasts_updated,
        "alerts_emitted": alerts_emitted,
    }


def _post_forecast_alert(cosmos_client: Any, payload: Dict[str, Any]) -> None:
    """Write a synthetic FORECAST_ALERT incident directly to Cosmos incidents container.

    Avoids an HTTP self-call to POST /api/v1/incidents — writes the minimal
    incident doc directly. The diagnostic pipeline BackgroundTask is NOT
    queued here (forecast alerts carry their own evidence in the description).

    Non-fatal: logs warning and returns on any error.
    """
    if cosmos_client is None:
        logger.debug("forecaster: _post_forecast_alert skipped (no cosmos_client)")
        return
    try:
        from datetime import datetime as _dt, timezone as _tz

        now_iso = _dt.now(_tz.utc).isoformat()
        incident_id = payload["incident_id"]
        primary_resource = payload["affected_resources"][0] if payload["affected_resources"] else {}

        doc = {
            "id": incident_id,
            "incident_id": incident_id,
            "resource_id": primary_resource.get("resource_id", ""),
            "severity": payload["severity"],
            "domain": payload["domain"],
            "status": "new",
            "detection_rule": payload["detection_rule"],
            "title": payload.get("title", ""),
            "description": payload.get("description", ""),
            "affected_resources": payload["affected_resources"],
            "created_at": now_iso,
            "investigation_status": "pending",
        }
        db = cosmos_client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client("incidents")
        container.upsert_item(doc)
        logger.info(
            "forecaster: FORECAST_ALERT emitted | incident_id=%s", incident_id
        )
    except Exception as exc:
        logger.warning(
            "forecaster: _post_forecast_alert failed (non-fatal) | "
            "incident=%s error=%s",
            payload.get("incident_id", "?"), exc,
        )
