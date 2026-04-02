"""SRE Agent tool functions — cross-domain monitoring and remediation proposal wrappers.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics, applicationinsights.query,
    advisor.list_recommendations, resourcehealth.get_availability_status,
    resourcehealth.list_events

Tools provided by this module:
    query_availability_metrics    — SLA/SLO availability % and downtime windows
    query_performance_baselines   — Historical baseline stats (avg, p95, p99)
    query_service_health          — Azure Service Health active events (preview SDK)
    query_advisor_recommendations — Azure Advisor recommendations with category filter
    query_change_analysis         — Recent ARM-tracked resource changes (preview SDK)
    correlate_cross_domain        — Pure-Python cross-domain RCA synthesiser
    propose_remediation           — Structured remediation proposal for operator review
"""
from __future__ import annotations

import logging
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

# Lazy import — azure-mgmt-servicehealth may not be installed in all envs
# Note: class is MicrosoftResourceHealth in this package (azure-mgmt-servicehealth),
# distinct from azure-mgmt-resourcehealth used by the compute agent.
try:
    from azure.mgmt.servicehealth import MicrosoftResourceHealth as ServiceHealthClient
except ImportError:
    ServiceHealthClient = None  # type: ignore[assignment,misc]

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
        "azure-mgmt-servicehealth": "azure.mgmt.servicehealth",
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
) -> Dict[str, Any]:
    """Query availability metrics for SLA/SLO assessment (MONITOR-001).

    Retrieves availability percentage and downtime windows for SLA breach
    assessment. Used for cross-domain SLA impact analysis.

    Calls azure-mgmt-monitor MonitorManagementClient.metrics.list() requesting
    the 'Availability' metric with PT5M granularity. Availability is computed
    as the average of all non-null average values. Downtime windows are
    consecutive intervals where the average drops below 99.9% (SLA threshold).

    Args:
        resource_id: Azure resource ID to query.
        timespan: ISO 8601 duration string (default: "PT24H" for daily SLA view).

    Returns:
        Dict with keys:
            resource_id (str): Resource queried.
            timespan (str): Time range applied.
            availability_percent (float | None): Availability percentage (0–100),
                or None if no data points are available.
            downtime_windows (list): Periods where availability dropped below SLA,
                each as {start (ISO str), end (ISO str)}.
            data_point_count (int): Number of data points used for calculation.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_id": resource_id, "timespan": timespan}

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
                interval="PT5M",
                aggregation="Average",
            )

            # Collect all non-null average datapoints across all timeseries
            values: List[float] = []
            timestamps: List[Optional[datetime]] = []
            for metric in response.value:
                for ts in metric.timeseries:
                    for dp in ts.data:
                        if dp.average is not None:
                            values.append(dp.average)
                            timestamps.append(
                                dp.time_stamp if hasattr(dp, "time_stamp") else None
                            )

            # Compute availability_percent
            availability_percent: Optional[float]
            if not values:
                availability_percent = None
            else:
                availability_percent = sum(values) / len(values)

            # Compute downtime_windows: consecutive intervals below 99.9% SLA
            SLA_THRESHOLD = 99.9
            downtime_windows: List[Dict[str, Any]] = []
            window_start: Optional[datetime] = None

            for i, (val, ts) in enumerate(zip(values, timestamps)):
                if val < SLA_THRESHOLD:
                    if window_start is None:
                        window_start = ts
                else:
                    if window_start is not None:
                        downtime_windows.append(
                            {
                                "start": window_start.isoformat() if window_start else None,
                                "end": ts.isoformat() if ts else None,
                            }
                        )
                        window_start = None

            # Close open window at end of timeseries
            if window_start is not None:
                downtime_windows.append(
                    {
                        "start": window_start.isoformat() if window_start else None,
                        "end": timestamps[-1].isoformat() if timestamps[-1] else None,
                    }
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_availability_metrics: complete | resource=%s availability=%.2f%% "
                "downtime_windows=%d duration_ms=%.0f",
                resource_id,
                availability_percent if availability_percent is not None else 0.0,
                len(downtime_windows),
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "timespan": timespan,
                "availability_percent": availability_percent,
                "downtime_windows": downtime_windows,
                "data_point_count": len(values),
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
                "availability_percent": None,
                "downtime_windows": [],
                "data_point_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_performance_baselines(
    resource_id: str,
    metric_names: List[str],
    baseline_period: str = "P7D",
) -> Dict[str, Any]:
    """Compare current metrics against historical baselines (MONITOR-001).

    Retrieves metric statistics over a historical baseline period for
    anomaly detection and SLO deviation analysis. For each metric, computes
    average, p95, p99, and max observed value from the timeseries data.

    Args:
        resource_id: Azure resource ID to query.
        metric_names: List of metric names to baseline.
        baseline_period: ISO 8601 duration for baseline window (default: "P7D").

    Returns:
        Dict with keys:
            resource_id (str): Resource queried.
            metric_names (list): Metrics analysed.
            baseline_period (str): Historical comparison window.
            baselines (list): Per-metric baseline statistics, each as:
                {metric_name, avg, p95, p99, max_observed, data_point_count}.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_id": resource_id,
        "metric_names": metric_names,
        "baseline_period": baseline_period,
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

            baselines: List[Dict[str, Any]] = []
            for metric_name in metric_names:
                response = client.metrics.list(
                    resource_uri=resource_id,
                    metricnames=metric_name,
                    timespan=baseline_period,
                    interval="PT5M",
                    aggregation="Average,Maximum,Minimum",
                )

                # Collect all non-null average and maximum values
                avg_values: List[float] = []
                max_values: List[float] = []

                for metric in response.value:
                    for ts in metric.timeseries:
                        for dp in ts.data:
                            if dp.average is not None:
                                avg_values.append(dp.average)
                            if dp.maximum is not None:
                                max_values.append(dp.maximum)

                if avg_values:
                    sorted_vals = sorted(avg_values)
                    n = len(sorted_vals)
                    p95_idx = int(n * 0.95)
                    p99_idx = int(n * 0.99)
                    # Clamp indices to valid range
                    p95_idx = min(p95_idx, n - 1)
                    p99_idx = min(p99_idx, n - 1)
                    avg_stat = sum(avg_values) / n
                    p95_stat = sorted_vals[p95_idx]
                    p99_stat = sorted_vals[p99_idx]
                    max_observed = max(max_values) if max_values else None
                else:
                    avg_stat = None
                    p95_stat = None
                    p99_stat = None
                    max_observed = None

                baselines.append(
                    {
                        "metric_name": metric_name,
                        "avg": avg_stat,
                        "p95": p95_stat,
                        "p99": p99_stat,
                        "max_observed": max_observed,
                        "data_point_count": len(avg_values),
                    }
                )

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
                "baselines": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_service_health(
    subscription_id: str,
    regions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Query Azure Service Health for active service issues (MONITOR-004).

    Retrieves active Service Health events for the given subscription, optionally
    filtered to specific Azure regions. Returns structured event data including
    impacted services and regions.

    NOTE: Uses azure-mgmt-servicehealth==1.0.0b4 (preview). The API may change
    before GA. The ServiceHealthClient here refers to MicrosoftResourceHealth from
    the azure-mgmt-servicehealth package (distinct from azure-mgmt-resourcehealth).

    Args:
        subscription_id: Azure subscription ID to query.
        regions: Optional list of Azure region names to filter events.
            If provided, only events impacting at least one of these regions
            are returned.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            region_filter (list | None): Region filter applied.
            events (list): Active service health events, each as:
                {id, event_type, status, title, start_time, impacted_services,
                 impacted_regions}.
            event_count (int): Number of events returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_id": subscription_id, "regions": regions}

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
            if ServiceHealthClient is None:
                raise ImportError("azure-mgmt-servicehealth is not installed")

            credential = get_credential()
            client = ServiceHealthClient(credential, subscription_id)

            base_filter = (
                "properties/EventType eq 'ServiceIssue' "
                "and properties/Status eq 'Active'"
            )
            events_iter = client.events.list_by_subscription_id(filter=base_filter)

            events_out: List[Dict[str, Any]] = []
            for event in events_iter:
                props = event.properties if hasattr(event, "properties") else event

                # Extract impacted regions for post-filtering
                impacted_region_names: List[str] = []
                if hasattr(props, "impacted_regions") and props.impacted_regions:
                    for region in props.impacted_regions:
                        rname = getattr(region, "region_name", None) or getattr(
                            region, "name", None
                        )
                        if rname:
                            impacted_region_names.append(rname)

                # Post-filter by regions if provided
                if regions:
                    regions_lower = [r.lower() for r in regions]
                    if not any(
                        r.lower() in regions_lower for r in impacted_region_names
                    ):
                        continue

                # Extract impacted services
                impacted_services: List[str] = []
                if hasattr(props, "impact") and props.impact:
                    for svc in props.impact:
                        svc_name = getattr(svc, "service_name", None)
                        if svc_name:
                            impacted_services.append(svc_name)

                # Extract activation time
                activation_time = getattr(props, "activation_time", None)
                start_time_iso = (
                    activation_time.isoformat() if activation_time else None
                )

                events_out.append(
                    {
                        "id": event.id if hasattr(event, "id") else None,
                        "event_type": str(getattr(props, "event_type", None)),
                        "status": str(getattr(props, "status", None)),
                        "title": getattr(props, "title", None),
                        "start_time": start_time_iso,
                        "impacted_services": impacted_services,
                        "impacted_regions": impacted_region_names,
                    }
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_service_health: complete | subscription=%s events=%d duration_ms=%.0f",
                subscription_id,
                len(events_out),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "region_filter": regions,
                "events": events_out,
                "event_count": len(events_out),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_service_health: failed | subscription=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "region_filter": regions,
                "events": [],
                "event_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_advisor_recommendations(
    subscription_id: str,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve Azure Advisor recommendations with optional category filtering.

    Supplements the MCP advisor.list_recommendations tool with direct SDK access
    and per-category filtering. Useful when the SRE agent needs targeted
    recommendations (e.g., only HighAvailability or Security) during incident triage.

    Valid categories: HighAvailability, Security, Performance, Cost,
    OperationalExcellence.

    Args:
        subscription_id: Azure subscription ID to query.
        category: Optional category filter. Must be one of: HighAvailability,
            Security, Performance, Cost, OperationalExcellence.
            If None, all recommendations are returned.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            category_filter (str | None): Category filter applied.
            recommendations (list): Advisor recommendations, each as:
                {id, resource_id, category, impact, short_description}.
            total_count (int): Total number of recommendations returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_id": subscription_id, "category": category}

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

            if category:
                recs_iter = client.recommendations.list(
                    filter=f"Category eq '{category}'"
                )
            else:
                recs_iter = client.recommendations.list()

            recs_out: List[Dict[str, Any]] = []
            for rec in recs_iter:
                props = rec.properties if hasattr(rec, "properties") else rec

                # Extract short description
                short_desc = None
                if hasattr(props, "short_description") and props.short_description:
                    short_desc = getattr(props.short_description, "problem", None)

                recs_out.append(
                    {
                        "id": rec.id if hasattr(rec, "id") else None,
                        "resource_id": rec.id if hasattr(rec, "id") else None,
                        "category": str(getattr(props, "category", None)),
                        "impact": str(getattr(props, "impact", None)),
                        "short_description": short_desc,
                    }
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_advisor_recommendations: complete | subscription=%s category=%s "
                "count=%d duration_ms=%.0f",
                subscription_id,
                category,
                len(recs_out),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "category_filter": category,
                "recommendations": recs_out,
                "total_count": len(recs_out),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_advisor_recommendations: failed | subscription=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "category_filter": category,
                "recommendations": [],
                "total_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_change_analysis(
    subscription_id: str,
    resource_group: str,
    timespan_hours: int = 24,
) -> Dict[str, Any]:
    """Query Azure Change Analysis for recent ARM-tracked resource changes.

    Retrieves changes to resources in the specified resource group over the
    given time window. ARM-tracked changes only (not OS-level changes).

    NOTE: Uses azure-mgmt-changeanalysis==1.0.0b2 (very early preview). The
    API may change before GA. The start_time and end_time parameters MUST be
    datetime objects (not ISO strings) — this is an SDK quirk of this version.
    The AzureChangeAnalysisManagementClient constructor does NOT accept a
    subscription_id argument (unlike most management clients).

    Args:
        subscription_id: Azure subscription ID (used for scoping, passed in result).
        resource_group: Resource group name to query changes for.
        timespan_hours: Look-back window in hours (default: 24).

    Returns:
        Dict with keys:
            subscription_id (str): Subscription context.
            resource_group (str): Resource group queried.
            timespan_hours (int): Look-back window.
            changes (list): Resource changes, each as:
                {resource_id, change_type, timestamp, changed_properties}.
            total_count (int): Number of changes returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "timespan_hours": timespan_hours,
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
        start_time_mono = time.monotonic()
        try:
            if AzureChangeAnalysisManagementClient is None:
                raise ImportError("azure-mgmt-changeanalysis is not installed")

            credential = get_credential()
            # Note: constructor does NOT take subscription_id (SDK quirk for this version)
            client = AzureChangeAnalysisManagementClient(credential)

            # Compute time range — must pass datetime objects, not ISO strings
            end_time = datetime.now(timezone.utc)
            start_time_dt = end_time - timedelta(hours=timespan_hours)

            changes_iter = client.changes.list_changes_by_resource_group(
                resource_group_name=resource_group,
                start_time=start_time_dt,
                end_time=end_time,
            )

            changes_out: List[Dict[str, Any]] = []
            for change in changes_iter:
                props = change.properties if hasattr(change, "properties") else change

                # Extract changed properties
                changed_props: List[Dict[str, Any]] = []
                if hasattr(props, "property_changes") and props.property_changes:
                    for pc in props.property_changes:
                        changed_props.append(
                            {
                                "property_name": getattr(pc, "property_name", None),
                                "old_value": getattr(pc, "old_value", None),
                                "new_value": getattr(pc, "new_value", None),
                            }
                        )

                # Extract timestamp
                ts = getattr(props, "time_stamp", None)
                ts_iso = ts.isoformat() if ts else None

                changes_out.append(
                    {
                        "resource_id": getattr(change, "resource_id", None),
                        "change_type": str(getattr(props, "change_type", None)),
                        "timestamp": ts_iso,
                        "changed_properties": changed_props,
                    }
                )

            duration_ms = (time.monotonic() - start_time_mono) * 1000
            logger.info(
                "query_change_analysis: complete | rg=%s changes=%d duration_ms=%.0f",
                resource_group,
                len(changes_out),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "timespan_hours": timespan_hours,
                "changes": changes_out,
                "total_count": len(changes_out),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time_mono) * 1000
            logger.error(
                "query_change_analysis: failed | rg=%s error=%s duration_ms=%.0f",
                resource_group,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "timespan_hours": timespan_hours,
                "changes": [],
                "total_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def correlate_cross_domain(
    incident_id: str,
    domain_findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Synthesise multi-domain findings into a structured RCA with scored hypotheses.

    This tool synthesises evidence from other domain agents (compute, network,
    storage, security, arc) into a cross-domain root cause analysis. No Azure SDK
    call is made — this is pure Python computation over the structured findings.

    Each finding is expected to have:
        domain (str): Agent domain (e.g., "compute", "network", "storage").
        finding_type (str): Type of finding (e.g., "cpu_spike", "nsg_block").
        severity (str): "Low", "Medium", "High", or "Critical".
        timestamp (str): ISO 8601 timestamp of the finding.
        description (str): Human-readable description.
        resource_id (str, optional): Azure resource ID affected.

    Confidence scoring per domain group:
        - Base: 0.3 per finding in the group (capped at 1.0).
        - +0.2 if any finding has severity in ["High", "Critical"].
        - +0.1 if any finding has a timestamp within the last hour.

    IMPORTANT: The requires_approval field is ALWAYS True (REMEDI-001).
    Correlation output must be reviewed before any remediation action is proposed.

    Args:
        incident_id: Unique incident identifier for correlation.
        domain_findings: List of structured findings from domain agents.

    Returns:
        Dict with keys:
            incident_id (str): Incident being correlated.
            correlation_summary (str): Brief summary of domains involved.
            top_hypotheses (list): Top 3 domain groups by confidence, each as:
                {domain, evidence (list of descriptions), confidence_score}.
            recommended_actions (list): Suggested investigation actions, each as:
                {domain, action}.
            finding_count (int): Total number of findings processed.
            requires_approval (bool): Always True (REMEDI-001).
    """
    # Group findings by domain
    domain_groups: Dict[str, List[Dict[str, Any]]] = {}
    for finding in domain_findings:
        domain = finding.get("domain", "unknown")
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(finding)

    # Compute confidence score per domain group
    now_utc = datetime.now(timezone.utc)
    domain_scores: List[Dict[str, Any]] = []

    for domain, findings in domain_groups.items():
        # Base score: 0.3 per finding, capped at 1.0
        score = min(len(findings) * 0.3, 1.0)

        # Bonus for high/critical severity
        has_high_severity = any(
            f.get("severity", "") in ("High", "Critical") for f in findings
        )
        if has_high_severity:
            score = min(score + 0.2, 1.0)

        # Bonus for recency (within last hour)
        has_recent = False
        for f in findings:
            ts_str = f.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    # Normalise to UTC if no timezone info
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if (now_utc - ts).total_seconds() < 3600:
                        has_recent = True
                        break
                except (ValueError, TypeError):
                    pass

        if has_recent:
            score = min(score + 0.1, 1.0)

        domain_scores.append(
            {
                "domain": domain,
                "findings": findings,
                "confidence_score": round(score, 4),
            }
        )

    # Sort by confidence descending, take top 3
    domain_scores.sort(key=lambda x: x["confidence_score"], reverse=True)
    top_3 = domain_scores[:3]

    # Build top_hypotheses
    top_hypotheses = [
        {
            "domain": ds["domain"],
            "evidence": [f.get("description", "") for f in ds["findings"]],
            "confidence_score": ds["confidence_score"],
        }
        for ds in top_3
    ]

    # Build recommended_actions
    recommended_actions: List[Dict[str, str]] = []
    for ds in top_3:
        domain = ds["domain"]
        # Use resource_id from first finding if available
        resource_id = None
        for f in ds["findings"]:
            resource_id = f.get("resource_id")
            if resource_id:
                break
        if resource_id:
            action = f"Investigate {domain} agent findings for resource {resource_id}"
        else:
            action = f"Investigate {domain} agent findings"
        recommended_actions.append({"domain": domain, "action": action})

    # Build correlation summary
    num_domains = len(domain_groups)
    if top_3:
        highest_domain = top_3[0]["domain"]
        correlation_summary = (
            f"{num_domains} domain(s) involved; highest confidence: {highest_domain} "
            f"({top_3[0]['confidence_score']:.2f})"
        )
    else:
        correlation_summary = "No findings to correlate."

    return {
        "incident_id": incident_id,
        "correlation_summary": correlation_summary,
        "top_hypotheses": top_hypotheses,
        "recommended_actions": recommended_actions,
        "finding_count": len(domain_findings),
        # REMEDI-001: Cross-domain correlation output MUST be reviewed before
        # any remediation action is proposed. Never set this to False.
        "requires_approval": True,
    }


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
