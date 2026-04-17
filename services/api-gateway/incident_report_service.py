"""Incident Report Service — Phase 82.

Generates structured Markdown + JSON reports for any incident, including
agent conversation transcript, timeline, findings, and remediation steps.

Generated on-demand; no Cosmos persistence for reports themselves.
Never raises from public functions.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Dataclass
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class IncidentReport:
    report_id: str
    incident_id: str
    title: str
    severity: str
    status: str
    created_at: str
    resolved_at: Optional[str]
    duration_minutes: Optional[int]
    affected_resources: List[str]
    domain: str
    classification: str
    agent_summary: str
    thread_id: Optional[str]
    timeline: List[Dict[str, Any]]    # [{timestamp, event, actor}]
    findings: List[Dict[str, Any]]    # [{title, description, severity}]
    remediation_steps: List[str]
    generated_at: str


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _parse_duration(created_at: str, resolved_at: Optional[str]) -> Optional[int]:
    """Return duration in minutes between two ISO timestamps, or None on error."""
    if not resolved_at:
        return None
    try:
        start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
        delta = end - start
        return max(0, int(delta.total_seconds() / 60))
    except (ValueError, TypeError):
        return None


def _extract_timeline(incident: Dict[str, Any], traces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build a chronological timeline from incident + agent trace records."""
    timeline: List[Dict[str, Any]] = []

    created_at = incident.get("created_at") or incident.get("createdAt") or ""
    if created_at:
        timeline.append({
            "timestamp": created_at,
            "event": "Incident created",
            "actor": incident.get("source", "system"),
        })

    for trace in traces:
        ts = trace.get("timestamp") or trace.get("created_at") or ""
        event = trace.get("event") or trace.get("message") or trace.get("type") or "Agent interaction"
        actor = trace.get("actor") or trace.get("agent") or "agent"
        if ts:
            timeline.append({"timestamp": ts, "event": event, "actor": actor})

    resolved_at = incident.get("resolved_at") or incident.get("resolvedAt")
    if resolved_at:
        timeline.append({
            "timestamp": resolved_at,
            "event": "Incident resolved",
            "actor": incident.get("resolved_by", "system"),
        })

    # Sort by timestamp, treating missing timestamps as very early
    timeline.sort(key=lambda x: x.get("timestamp") or "")
    return timeline


def _build_findings(incident: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract findings from the incident record."""
    raw = incident.get("findings") or []
    if isinstance(raw, list) and raw:
        return [
            {
                "title": f.get("title", "Finding"),
                "description": f.get("description", ""),
                "severity": f.get("severity", "medium"),
            }
            for f in raw
            if isinstance(f, dict)
        ]

    # Build a synthetic finding from agent_summary if no structured findings
    summary = incident.get("agent_summary") or incident.get("summary") or ""
    if summary:
        return [{
            "title": "Agent analysis",
            "description": summary,
            "severity": incident.get("severity", "medium").lower(),
        }]
    return []


def _build_remediation_steps(incident: Dict[str, Any]) -> List[str]:
    """Extract or synthesise remediation steps from the incident record."""
    raw = incident.get("remediation_steps") or incident.get("remediationSteps") or []
    if isinstance(raw, list) and raw:
        return [str(s) for s in raw]

    # Fall back to action items if present
    actions = incident.get("action_items") or []
    if isinstance(actions, list) and actions:
        return [str(a) for a in actions]

    return ["Review agent findings and apply recommended configuration changes.",
            "Verify affected resources are in a healthy state after remediation.",
            "Update runbook with lessons learned."]


def _fetch_incident(
    cosmos_client: Any,
    db_name: str,
    incident_id: str,
) -> Optional[Dict[str, Any]]:
    """Read a single incident from Cosmos. Returns None on error/not-found."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
        items = list(
            container.query_items(
                query="SELECT * FROM c WHERE c.incident_id = @id OR c.id = @id",
                parameters=[{"name": "@id", "value": incident_id}],
                enable_cross_partition_query=True,
            )
        )
        return items[0] if items else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("incident_report: fetch_incident failed | id=%s error=%s", incident_id, exc)
        return None


def _fetch_traces(
    cosmos_client: Any,
    db_name: str,
    thread_id: str,
) -> List[Dict[str, Any]]:
    """Read agent traces for a Foundry thread. Returns [] on error/not-found."""
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client("agent_traces")
        items = list(
            container.query_items(
                query="SELECT * FROM c WHERE c.thread_id = @thread_id ORDER BY c.timestamp ASC",
                parameters=[{"name": "@thread_id", "value": thread_id}],
                enable_cross_partition_query=True,
            )
        )
        return items
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "incident_report: fetch_traces failed | thread_id=%s error=%s", thread_id, exc
        )
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def generate_incident_report(
    cosmos_client: Any,
    db_name: str,
    incident_id: str,
) -> Optional[IncidentReport]:
    """Build an IncidentReport for the given incident_id. Never raises.

    Returns None if the incident cannot be found.
    """
    try:
        incident = _fetch_incident(cosmos_client, db_name, incident_id)
        if not incident:
            logger.warning("incident_report: incident not found | id=%s", incident_id)
            return None

        thread_id = incident.get("thread_id") or incident.get("foundry_thread_id")
        traces: List[Dict[str, Any]] = []
        if thread_id:
            traces = _fetch_traces(cosmos_client, db_name, thread_id)

        created_at = incident.get("created_at") or incident.get("createdAt") or ""
        resolved_at = incident.get("resolved_at") or incident.get("resolvedAt")
        duration_minutes = _parse_duration(created_at, resolved_at)

        affected_resources = incident.get("affected_resources") or []
        if not affected_resources:
            resource_id = incident.get("resource_id") or incident.get("resourceId")
            if resource_id:
                affected_resources = [resource_id]

        return IncidentReport(
            report_id=str(uuid.uuid4()),
            incident_id=incident_id,
            title=incident.get("title") or incident.get("summary") or f"Incident {incident_id}",
            severity=incident.get("severity") or "unknown",
            status=incident.get("status") or "unknown",
            created_at=created_at,
            resolved_at=resolved_at,
            duration_minutes=duration_minutes,
            affected_resources=affected_resources,
            domain=incident.get("domain") or "unknown",
            classification=incident.get("classification") or incident.get("alert_type") or "unknown",
            agent_summary=incident.get("agent_summary") or incident.get("summary") or "",
            thread_id=thread_id,
            timeline=_extract_timeline(incident, traces),
            findings=_build_findings(incident),
            remediation_steps=_build_remediation_steps(incident),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("incident_report: generate failed | id=%s error=%s", incident_id, exc)
        return None


def render_markdown(report: IncidentReport) -> str:
    """Render an IncidentReport as a structured Markdown document. Never raises."""
    try:
        lines: List[str] = []

        lines += [
            f"# Incident Report: {report.title}",
            "",
            "## Summary",
            "",
            f"| Field | Value |",
            f"|---|---|",
            f"| **Incident ID** | `{report.incident_id}` |",
            f"| **Report ID** | `{report.report_id}` |",
            f"| **Severity** | {report.severity.upper()} |",
            f"| **Status** | {report.status} |",
            f"| **Domain** | {report.domain} |",
            f"| **Classification** | {report.classification} |",
            f"| **Created** | {report.created_at} |",
            f"| **Resolved** | {report.resolved_at or 'N/A'} |",
            f"| **Duration** | {f'{report.duration_minutes} minutes' if report.duration_minutes is not None else 'N/A'} |",
            f"| **Generated** | {report.generated_at} |",
            "",
        ]

        if report.affected_resources:
            lines += ["## Affected Resources", ""]
            for r in report.affected_resources:
                lines.append(f"- `{r}`")
            lines.append("")

        if report.agent_summary:
            lines += ["## Agent Summary", "", report.agent_summary, ""]

        if report.timeline:
            lines += ["## Timeline", ""]
            lines += ["| Timestamp | Event | Actor |", "|---|---|---|"]
            for entry in report.timeline:
                ts = entry.get("timestamp", "")
                event = entry.get("event", "")
                actor = entry.get("actor", "")
                lines.append(f"| {ts} | {event} | {actor} |")
            lines.append("")

        if report.findings:
            lines += ["## Findings", ""]
            for i, finding in enumerate(report.findings, 1):
                sev = finding.get("severity", "").upper()
                title = finding.get("title", f"Finding {i}")
                desc = finding.get("description", "")
                lines += [
                    f"### {i}. {title} ({sev})",
                    "",
                    desc,
                    "",
                ]

        if report.remediation_steps:
            lines += ["## Remediation Steps", ""]
            for i, step in enumerate(report.remediation_steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        if report.thread_id:
            lines += [
                "## Agent Thread",
                "",
                f"Foundry thread ID: `{report.thread_id}`",
                "",
            ]

        lines += [
            "---",
            "",
            f"*Report generated by Azure Agentic Platform at {report.generated_at}*",
        ]

        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        logger.warning("incident_report: render_markdown failed | error=%s", exc)
        return f"# Incident Report\n\nError rendering report: {exc}\n"


def render_json(report: IncidentReport) -> Dict[str, Any]:
    """Return a JSON-serializable dict for the report. Never raises."""
    try:
        return {
            "report_id": report.report_id,
            "incident_id": report.incident_id,
            "title": report.title,
            "severity": report.severity,
            "status": report.status,
            "created_at": report.created_at,
            "resolved_at": report.resolved_at,
            "duration_minutes": report.duration_minutes,
            "affected_resources": report.affected_resources,
            "domain": report.domain,
            "classification": report.classification,
            "agent_summary": report.agent_summary,
            "thread_id": report.thread_id,
            "timeline": report.timeline,
            "findings": report.findings,
            "remediation_steps": report.remediation_steps,
            "generated_at": report.generated_at,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("incident_report: render_json failed | error=%s", exc)
        return {"error": str(exc)}
