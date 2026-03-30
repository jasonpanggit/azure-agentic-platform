"""SRE Agent tool functions — cross-domain monitoring and remediation proposal wrappers.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics, applicationinsights.query,
    advisor.list_recommendations, resourcehealth.get_availability_status,
    resourcehealth.list_events
"""
from __future__ import annotations

from typing import Any, Dict, List

from agent_framework import tool

from shared.auth import get_agent_identity
from shared.otel import instrument_tool_call, setup_telemetry

tracer = setup_telemetry("aiops-sre-agent")

# Explicit MCP tool allowlist — no wildcards permitted.
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "applicationinsights.query",
    "advisor.list_recommendations",
    "resourcehealth.get_availability_status",
    "resourcehealth.list_events",
]


@tool
def query_availability_metrics(
    resource_id: str,
    timespan: str = "PT24H",
) -> Dict[str, Any]:
    """Query availability metrics for SLA/SLO assessment (MONITOR-001).

    Retrieves availability percentage and downtime windows for SLA breach
    assessment. Used for cross-domain SLA impact analysis.

    Args:
        resource_id: Azure resource ID to query.
        timespan: ISO 8601 duration string (default: "PT24H" for daily SLA view).

    Returns:
        Dict with keys:
            resource_id (str): Resource queried.
            timespan (str): Time range applied.
            availability_percent (float | None): Availability percentage.
            downtime_windows (list): Periods where availability dropped below SLA.
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
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "availability_percent": None,
            "downtime_windows": [],
            "query_status": "success",
        }


@tool
def query_performance_baselines(
    resource_id: str,
    metric_names: List[str],
    baseline_period: str = "P7D",
) -> Dict[str, Any]:
    """Compare current metrics against historical baselines (MONITOR-001).

    Retrieves metric statistics over a historical baseline period for
    anomaly detection and SLO deviation analysis.

    Args:
        resource_id: Azure resource ID to query.
        metric_names: List of metric names to baseline.
        baseline_period: ISO 8601 duration for baseline window (default: "P7D").

    Returns:
        Dict with keys:
            resource_id (str): Resource queried.
            metric_names (list): Metrics analysed.
            baseline_period (str): Historical comparison window.
            baselines (list): Per-metric baseline statistics (avg, p95, p99).
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
        return {
            "resource_id": resource_id,
            "metric_names": metric_names,
            "baseline_period": baseline_period,
            "baselines": [],
            "query_status": "success",
        }


@tool
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
