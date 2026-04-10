"""SRE Agent tool functions — cross-domain monitoring and remediation proposal wrappers.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics, applicationinsights.query,
    advisor.list_recommendations, resourcehealth.get_availability_status,
    resourcehealth.list_events
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

# Lazy import — azure-mgmt-monitor may not be installed in all envs
try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-resourcehealth may not be installed in all envs
try:
    from azure.mgmt.resourcehealth import ResourceHealthMgmtClient
except ImportError:
    ResourceHealthMgmtClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-advisor may not be installed in all envs
try:
    from azure.mgmt.advisor import AdvisorManagementClient
except ImportError:
    AdvisorManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-changeanalysis may not be installed in all envs
try:
    from azure.mgmt.changeanalysis import AzureChangeAnalysisManagementClient
except ImportError:
    AzureChangeAnalysisManagementClient = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-sre-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — no wildcards permitted.
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "applicationinsights.query",
    "advisor.list_recommendations",
    "resourcehealth.get_availability_status",
    "resourcehealth.list_events",
]


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-monitor": "azure.mgmt.monitor",
        "azure-mgmt-resourcehealth": "azure.mgmt.resourcehealth",
        "azure-mgmt-advisor": "azure.mgmt.advisor",
        "azure-mgmt-changeanalysis": "azure.mgmt.changeanalysis",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("sre_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "sre_tools: sdk_missing | package=%s — tool will return error", pkg
            )


_log_sdk_availability()


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an Azure resource ID.

    Args:
        resource_id: Azure resource ID in the form
            /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}

    Returns:
        Subscription ID string (lowercase).

    Raises:
        ValueError: If the subscription segment cannot be found.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot extract subscription_id from resource_id: {resource_id}"
        )


@ai_function
def query_availability_metrics(
    resource_id: str,
    timespan: str = "PT24H",
    interval: str = "PT1H",
) -> Dict[str, Any]:
    """Query availability metrics for SLA/SLO assessment (MONITOR-001).

    Retrieves availability percentage and downtime windows for SLA breach
    assessment. Used for cross-domain SLA impact analysis.

    Args:
        resource_id: Azure resource ID to query.
        timespan: ISO 8601 duration string (default: "PT24H" for daily SLA view).
        interval: ISO 8601 duration for metric granularity (default: "PT1H").

    Returns:
        Dict with keys:
            resource_id (str): Resource queried.
            timespan (str): Time range applied.
            interval (str): Granularity applied.
            availability_percent (float | None): Availability percentage.
            downtime_windows (list): Periods where availability dropped below 99.9%.
            data_points (list): Raw metric data points.
            data_point_count (int): Number of data points returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_id": resource_id,
        "timespan": timespan,
        "interval": interval,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="sre-agent",
        agent_id=agent_id,
        tool_name="query_availability_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(resource_id)
            client = MonitorManagementClient(credential, sub_id)

            response = client.metrics.list(
                resource_uri=resource_id,
                metricnames="Availability",
                timespan=timespan,
                interval=interval,
                aggregation="Average,Minimum",
            )

            data_points: List[Dict[str, Any]] = []
            all_averages: List[float] = []
            downtime_windows: List[Dict[str, Any]] = []

            for metric in response.value:
                for ts in metric.timeseries:
                    for dp in ts.data:
                        point = {
                            "timestamp": (
                                dp.time_stamp.isoformat()
                                if dp.time_stamp
                                else None
                            ),
                            "average": dp.average,
                            "minimum": dp.minimum,
                        }
                        data_points.append(point)

                        if dp.average is not None:
                            all_averages.append(dp.average)

                        if dp.minimum is not None and dp.minimum < 99.9:
                            downtime_windows.append({
                                "timestamp": point["timestamp"],
                                "minimum": dp.minimum,
                                "average": dp.average,
                            })

            availability_percent: Optional[float] = None
            if all_averages:
                availability_percent = sum(all_averages) / len(all_averages)

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_availability_metrics: complete | resource=%s points=%d avail=%.2f%% duration_ms=%.0f",
                resource_id,
                len(data_points),
                availability_percent if availability_percent is not None else 0.0,
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "timespan": timespan,
                "interval": interval,
                "availability_percent": availability_percent,
                "downtime_windows": downtime_windows,
                "data_points": data_points,
                "data_point_count": len(data_points),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_availability_metrics: failed | resource=%s error=%s duration_ms=%.0f",
                resource_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_id": resource_id,
                "timespan": timespan,
                "interval": interval,
                "availability_percent": None,
                "downtime_windows": [],
                "data_points": [],
                "data_point_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_performance_baselines(
    resource_id: str,
    metric_names: List[str],
    baseline_period: str = "P7D",
    interval: str = "PT1H",
) -> Dict[str, Any]:
    """Compare current metrics against historical baselines (MONITOR-001).

    Retrieves metric statistics over a historical baseline period for
    anomaly detection and SLO deviation analysis. Computes avg, p95, p99,
    min, and max for each requested metric.

    Args:
        resource_id: Azure resource ID to query.
        metric_names: List of metric names to baseline.
        baseline_period: ISO 8601 duration for baseline window (default: "P7D").
        interval: ISO 8601 duration for metric granularity (default: "PT1H").

    Returns:
        Dict with keys:
            resource_id (str): Resource queried.
            metric_names (list): Metrics analysed.
            baseline_period (str): Historical comparison window.
            interval (str): Granularity applied.
            baselines (list): Per-metric baseline statistics (avg, p95, p99, min, max).
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_id": resource_id,
        "metric_names": metric_names,
        "baseline_period": baseline_period,
        "interval": interval,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="sre-agent",
        agent_id=agent_id,
        tool_name="query_performance_baselines",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(resource_id)
            client = MonitorManagementClient(credential, sub_id)

            response = client.metrics.list(
                resource_uri=resource_id,
                metricnames=",".join(metric_names),
                timespan=baseline_period,
                interval=interval,
                aggregation="Average,Maximum,Minimum",
            )

            baselines: List[Dict[str, Any]] = []
            for metric in response.value:
                averages: List[float] = []
                minimums: List[float] = []
                maximums: List[float] = []

                for ts in metric.timeseries:
                    for dp in ts.data:
                        if dp.average is not None:
                            averages.append(dp.average)
                        if dp.minimum is not None:
                            minimums.append(dp.minimum)
                        if dp.maximum is not None:
                            maximums.append(dp.maximum)

                # Compute percentiles using sort + index-based approach
                sorted_avg = sorted(averages) if averages else []
                p95 = _percentile(sorted_avg, 0.95) if sorted_avg else None
                p99 = _percentile(sorted_avg, 0.99) if sorted_avg else None

                baseline_entry = {
                    "metric_name": metric.name.value if metric.name else None,
                    "avg": (
                        sum(averages) / len(averages) if averages else None
                    ),
                    "p95": p95,
                    "p99": p99,
                    "min": min(minimums) if minimums else None,
                    "max": max(maximums) if maximums else None,
                    "data_point_count": len(averages),
                }
                baselines.append(baseline_entry)

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_performance_baselines: complete | resource=%s metrics=%d duration_ms=%.0f",
                resource_id,
                len(baselines),
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "metric_names": metric_names,
                "baseline_period": baseline_period,
                "interval": interval,
                "baselines": baselines,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_performance_baselines: failed | resource=%s error=%s duration_ms=%.0f",
                resource_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_id": resource_id,
                "metric_names": metric_names,
                "baseline_period": baseline_period,
                "interval": interval,
                "baselines": [],
                "query_status": "error",
                "error": str(e),
            }


def _percentile(sorted_data: List[float], pct: float) -> Optional[float]:
    """Compute percentile from a pre-sorted list using index-based approach.

    Args:
        sorted_data: Pre-sorted list of float values.
        pct: Percentile as a decimal (e.g. 0.95 for 95th percentile).

    Returns:
        Percentile value, or None if the list is empty.
    """
    if not sorted_data:
        return None
    n = len(sorted_data)
    idx = int(pct * (n - 1))
    idx = min(idx, n - 1)
    return sorted_data[idx]


@ai_function
def propose_remediation(
    incident_id: str,
    hypothesis: str,
    affected_resources: List[str],
    action_type: str,
    description: str,
    risk_level: str,
    reversibility: str,
) -> Dict[str, Any]:
    """Produce a structured remediation proposal for operator review (REMEDI-001).

    This tool generates a remediation proposal that MUST be reviewed and
    approved by a human operator before any action is taken. The SRE Agent
    MUST NOT execute any remediation action — proposals only (REMEDI-001).

    Args:
        incident_id: Unique incident identifier for correlation.
        hypothesis: Root-cause hypothesis the proposal addresses.
        affected_resources: List of Azure resource IDs to be affected.
        action_type: Machine-readable action category
            (e.g., "scale_up", "restart", "rollback", "escalate", "failover").
        description: Human-readable description of the proposed action.
        risk_level: One of "low", "medium", "high", "critical".
        reversibility: Human-readable reversibility description.

    Returns:
        Dict with mandatory requires_approval=True (REMEDI-001) and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "incident_id": incident_id,
        "hypothesis": hypothesis,
        "affected_resources": affected_resources,
        "action_type": action_type,
        "description": description,
        "risk_level": risk_level,
        "reversibility": reversibility,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="sre-agent",
        agent_id=agent_id,
        tool_name="propose_remediation",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "incident_id": incident_id,
            "hypothesis": hypothesis,
            "affected_resources": affected_resources,
            "action_type": action_type,
            "description": description,
            "risk_level": risk_level,
            "reversibility": reversibility,
            # REMEDI-001: All remediation proposals require explicit human approval.
            # The SRE Agent MUST NOT execute any action without operator confirmation.
            "requires_approval": True,
        }
