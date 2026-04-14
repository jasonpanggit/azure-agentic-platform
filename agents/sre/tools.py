"""SRE Agent tool functions — cross-domain monitoring and remediation proposal wrappers.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics, applicationinsights.query,
    advisor.list_recommendations, resourcehealth.get_availability_status,
    resourcehealth.list_events,
    containerapps (list_apps, get_app, list_revisions)
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
    "containerapps.list_apps",
    "containerapps.get_app",
    "containerapps.list_revisions",
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


@ai_function
def query_service_health(
    subscription_id: str,
    event_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Azure Service Health events for platform-level incidents (MONITOR-003).

    Retrieves active and recent Service Health events (service issues,
    planned maintenance, health advisories, security advisories) that may
    impact resources in the given subscription.

    Args:
        subscription_id: Azure subscription ID to query.
        event_type: Optional filter — one of "ServiceIssue", "PlannedMaintenance",
            "HealthAdvisory", "SecurityAdvisory". If None, returns all types.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            event_type_filter (str | None): Applied filter.
            events (list): Service Health events (max 50).
            event_count (int): Total events returned.
            active_count (int): Events with status "Active".
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "event_type": event_type,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="sre-agent",
        agent_id=agent_id,
        tool_name="query_service_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if ResourceHealthMgmtClient is None:
                raise ImportError("azure-mgmt-resourcehealth is not installed")

            credential = get_credential()
            client = ResourceHealthMgmtClient(credential, subscription_id)

            raw_events = client.events.list_by_subscription_id()

            events: List[Dict[str, Any]] = []
            active_count = 0

            for event in raw_events:
                # Filter by event_type if specified
                evt_type = getattr(event, "event_type", None)
                if event_type is not None and str(evt_type) != event_type:
                    continue

                status = getattr(event, "status", None)
                status_str = str(status) if status is not None else None

                impact_start = getattr(event, "impact_start_time", None)
                last_update = getattr(event, "last_update_time", None)

                entry = {
                    "event_type": str(evt_type) if evt_type is not None else None,
                    "summary": getattr(event, "summary", None),
                    "status": status_str,
                    "impact_start_time": (
                        impact_start.isoformat() if impact_start else None
                    ),
                    "last_update_time": (
                        last_update.isoformat() if last_update else None
                    ),
                    "header": getattr(event, "header", None),
                    "level": str(getattr(event, "level", None)),
                }
                events.append(entry)

                if status_str == "Active":
                    active_count += 1

                if len(events) >= 50:
                    break

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_service_health: complete | sub=%s events=%d active=%d duration_ms=%.0f",
                subscription_id,
                len(events),
                active_count,
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "event_type_filter": event_type,
                "events": events,
                "event_count": len(events),
                "active_count": active_count,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_service_health: failed | sub=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "event_type_filter": event_type,
                "events": [],
                "event_count": 0,
                "active_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_advisor_recommendations(
    subscription_id: str,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Azure Advisor recommendations for reliability and performance insights.

    Retrieves Advisor recommendations filtered by category. Useful for
    identifying proactive improvements and correlating with active incidents.

    Args:
        subscription_id: Azure subscription ID to query.
        category: Optional filter — one of "HighAvailability", "Security",
            "Performance", "Cost", "OperationalExcellence". If None, returns all.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            category_filter (str | None): Applied filter.
            recommendations (list): Advisor recommendations (max 100).
            recommendation_count (int): Total recommendations returned.
            high_impact_count (int): Recommendations with impact "High".
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "category": category,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="sre-agent",
        agent_id=agent_id,
        tool_name="query_advisor_recommendations",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if AdvisorManagementClient is None:
                raise ImportError("azure-mgmt-advisor is not installed")

            credential = get_credential()
            client = AdvisorManagementClient(credential, subscription_id)

            raw_recs = client.recommendations.list()

            recommendations: List[Dict[str, Any]] = []
            high_impact_count = 0

            for rec in raw_recs:
                rec_category = getattr(rec, "category", None)
                if category is not None and str(rec_category) != category:
                    continue

                impact = getattr(rec, "impact", None)
                impact_str = str(impact) if impact is not None else None

                # Extract short description fields safely
                short_desc = getattr(rec, "short_description", None)
                problem = (
                    getattr(short_desc, "problem", None)
                    if short_desc is not None
                    else None
                )
                solution = (
                    getattr(short_desc, "solution", None)
                    if short_desc is not None
                    else None
                )

                # Extract resource metadata safely
                res_meta = getattr(rec, "resource_metadata", None)
                rec_resource_id = (
                    getattr(res_meta, "resource_id", None)
                    if res_meta is not None
                    else None
                )

                entry = {
                    "category": str(rec_category) if rec_category is not None else None,
                    "impact": impact_str,
                    "impacted_field": getattr(rec, "impacted_field", None),
                    "impacted_value": getattr(rec, "impacted_value", None),
                    "problem": problem,
                    "solution": solution,
                    "resource_id": rec_resource_id,
                }
                recommendations.append(entry)

                if impact_str == "High":
                    high_impact_count += 1

                if len(recommendations) >= 100:
                    break

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_advisor_recommendations: complete | sub=%s recs=%d high=%d duration_ms=%.0f",
                subscription_id,
                len(recommendations),
                high_impact_count,
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "category_filter": category,
                "recommendations": recommendations,
                "recommendation_count": len(recommendations),
                "high_impact_count": high_impact_count,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_advisor_recommendations: failed | sub=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "category_filter": category,
                "recommendations": [],
                "recommendation_count": 0,
                "high_impact_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_change_analysis(
    subscription_id: str,
    timespan_hours: int = 2,
    resource_group: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Azure Change Analysis for recent infrastructure changes.

    Retrieves property-level change diffs detected by the Change Analysis
    service. Supplements Activity Log with deeper change visibility.

    Args:
        subscription_id: Azure subscription ID to query.
        timespan_hours: Look-back window in hours (default: 2).
        resource_group: Optional resource group filter. If None, queries
            the entire subscription.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            timespan_hours (int): Look-back window applied.
            resource_group_filter (str | None): Applied filter.
            changes (list): Detected changes (max 100).
            change_count (int): Total changes returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "timespan_hours": timespan_hours,
        "resource_group": resource_group,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="sre-agent",
        agent_id=agent_id,
        tool_name="query_change_analysis",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if AzureChangeAnalysisManagementClient is None:
                raise ImportError("azure-mgmt-changeanalysis is not installed")

            credential = get_credential()
            client = AzureChangeAnalysisManagementClient(credential, subscription_id)

            end_time_dt = datetime.now(timezone.utc)
            start_time_dt = end_time_dt - timedelta(hours=timespan_hours)

            if resource_group is not None:
                raw_changes = client.changes.list_changes_by_resource_group(
                    resource_group, start_time_dt, end_time_dt
                )
            else:
                raw_changes = client.changes.list_changes_by_subscription(
                    start_time_dt, end_time_dt
                )

            changes: List[Dict[str, Any]] = []
            for change in raw_changes:
                # Extract property changes (cap at 10 per change)
                prop_changes_raw = getattr(change, "property_changes", None) or []
                property_changes: List[Dict[str, Any]] = []
                for pc in prop_changes_raw[:10]:
                    property_changes.append({
                        "property_name": getattr(pc, "property_name", None),
                        "old_value": getattr(pc, "old_value", None),
                        "new_value": getattr(pc, "new_value", None),
                    })

                # Extract initiated-by list safely
                initiated_raw = getattr(change, "initiated_by_list", None) or []
                initiated_by = [str(i) for i in initiated_raw]

                ts = getattr(change, "time_stamp", None)

                entry = {
                    "resource_id": getattr(change, "resource_id", None),
                    "change_type": str(getattr(change, "change_type", None)),
                    "time_stamp": ts.isoformat() if ts else None,
                    "initiated_by_list": initiated_by,
                    "property_changes": property_changes,
                }
                changes.append(entry)

                if len(changes) >= 100:
                    break

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_change_analysis: complete | sub=%s changes=%d duration_ms=%.0f",
                subscription_id,
                len(changes),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "timespan_hours": timespan_hours,
                "resource_group_filter": resource_group,
                "changes": changes,
                "change_count": len(changes),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_change_analysis: failed | sub=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "timespan_hours": timespan_hours,
                "resource_group_filter": resource_group,
                "changes": [],
                "change_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def correlate_cross_domain(
    subscription_id: str,
    resource_id: str,
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Build a unified cross-domain correlation view for incident investigation.

    Composite tool that aggregates platform events, recent changes, availability
    metrics, and advisor recommendations into a single correlation view. Each
    sub-call is independently fault-tolerant — partial failures are captured
    but do not prevent the overall correlation from completing.

    Args:
        subscription_id: Azure subscription ID to query.
        resource_id: Azure resource ID to correlate around.
        timespan_hours: Look-back window in hours (default: 2).

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            resource_id (str): Resource correlated around.
            timespan_hours (int): Look-back window applied.
            platform_events (list): Active service health events.
            recent_changes (list): Changes in timespan, sorted by timestamp.
            availability_impact (dict): Availability data for the resource.
            relevant_recommendations (list): Advisor recs for the resource.
            correlation_summary (str): Human-readable summary.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "resource_id": resource_id,
        "timespan_hours": timespan_hours,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="sre-agent",
        agent_id=agent_id,
        tool_name="correlate_cross_domain",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            # 1. Service Health — check for active platform events
            platform_events: List[Dict[str, Any]] = []
            health_error: Optional[str] = None
            try:
                health_result = query_service_health(subscription_id)
                if health_result.get("query_status") == "success":
                    platform_events = [
                        evt for evt in health_result.get("events", [])
                        if evt.get("status") == "Active"
                    ]
                else:
                    health_error = health_result.get("error", "unknown")
            except Exception as e:
                health_error = str(e)
                logger.warning(
                    "correlate_cross_domain: service_health sub-call failed | error=%s",
                    e,
                )

            # 2. Change Analysis — find recent changes
            recent_changes: List[Dict[str, Any]] = []
            changes_error: Optional[str] = None
            try:
                changes_result = query_change_analysis(subscription_id, timespan_hours)
                if changes_result.get("query_status") == "success":
                    recent_changes = sorted(
                        changes_result.get("changes", []),
                        key=lambda c: c.get("time_stamp") or "",
                    )
                else:
                    changes_error = changes_result.get("error", "unknown")
            except Exception as e:
                changes_error = str(e)
                logger.warning(
                    "correlate_cross_domain: change_analysis sub-call failed | error=%s",
                    e,
                )

            # 3. Availability metrics — check resource availability
            availability_impact: Dict[str, Any] = {}
            avail_error: Optional[str] = None
            try:
                avail_result = query_availability_metrics(
                    resource_id, f"PT{timespan_hours}H"
                )
                if avail_result.get("query_status") == "success":
                    availability_impact = {
                        "availability_percent": avail_result.get("availability_percent"),
                        "downtime_windows": avail_result.get("downtime_windows", []),
                        "data_point_count": avail_result.get("data_point_count", 0),
                    }
                else:
                    avail_error = avail_result.get("error", "unknown")
            except Exception as e:
                avail_error = str(e)
                logger.warning(
                    "correlate_cross_domain: availability_metrics sub-call failed | error=%s",
                    e,
                )

            # 4. Advisor recommendations — filter to those affecting the resource
            relevant_recommendations: List[Dict[str, Any]] = []
            advisor_error: Optional[str] = None
            try:
                advisor_result = query_advisor_recommendations(subscription_id)
                if advisor_result.get("query_status") == "success":
                    resource_id_lower = resource_id.lower()
                    relevant_recommendations = [
                        rec for rec in advisor_result.get("recommendations", [])
                        if rec.get("resource_id")
                        and rec["resource_id"].lower() == resource_id_lower
                    ]
                else:
                    advisor_error = advisor_result.get("error", "unknown")
            except Exception as e:
                advisor_error = str(e)
                logger.warning(
                    "correlate_cross_domain: advisor_recommendations sub-call failed | error=%s",
                    e,
                )

            # Build correlation summary
            avail_pct = availability_impact.get("availability_percent")
            avail_str = f"{avail_pct:.2f}%" if avail_pct is not None else "unknown"

            sub_errors = []
            if health_error:
                sub_errors.append(f"service_health: {health_error}")
            if changes_error:
                sub_errors.append(f"change_analysis: {changes_error}")
            if avail_error:
                sub_errors.append(f"availability: {avail_error}")
            if advisor_error:
                sub_errors.append(f"advisor: {advisor_error}")

            correlation_summary = (
                f"Found {len(platform_events)} platform events, "
                f"{len(recent_changes)} changes in last {timespan_hours}h, "
                f"availability at {avail_str}"
            )
            if relevant_recommendations:
                correlation_summary += (
                    f", {len(relevant_recommendations)} relevant advisor recommendations"
                )
            if sub_errors:
                correlation_summary += (
                    f" (partial failures: {'; '.join(sub_errors)})"
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "correlate_cross_domain: complete | sub=%s resource=%s events=%d changes=%d duration_ms=%.0f",
                subscription_id,
                resource_id,
                len(platform_events),
                len(recent_changes),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "resource_id": resource_id,
                "timespan_hours": timespan_hours,
                "platform_events": platform_events,
                "recent_changes": recent_changes,
                "availability_impact": availability_impact,
                "relevant_recommendations": relevant_recommendations,
                "correlation_summary": correlation_summary,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "correlate_cross_domain: failed | sub=%s resource=%s error=%s duration_ms=%.0f",
                subscription_id,
                resource_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "resource_id": resource_id,
                "timespan_hours": timespan_hours,
                "platform_events": [],
                "recent_changes": [],
                "availability_impact": {},
                "relevant_recommendations": [],
                "correlation_summary": f"Correlation failed: {e}",
                "query_status": "error",
                "error": str(e),
            }
