"""Tests for incident_report_service — Phase 82."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from services.api_gateway.incident_report_service import (
    IncidentReport,
    _build_findings,
    _build_remediation_steps,
    _extract_timeline,
    _parse_duration,
    generate_incident_report,
    render_json,
    render_markdown,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc).isoformat()
RESOLVED = "2026-04-17T15:30:00+00:00"
CREATED = "2026-04-17T14:00:00+00:00"

SAMPLE_INCIDENT: Dict[str, Any] = {
    "id": "inc-001",
    "incident_id": "inc-001",
    "title": "VM CPU spike on vm-web-01",
    "severity": "sev2",
    "status": "resolved",
    "domain": "compute",
    "classification": "performance",
    "created_at": CREATED,
    "resolved_at": RESOLVED,
    "agent_summary": "High CPU utilisation detected. Root cause: runaway process.",
    "thread_id": "thread-abc-123",
    "affected_resources": ["/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-web-01"],
    "findings": [
        {"title": "CPU at 98%", "description": "CPU pegged for 15+ minutes.", "severity": "high"}
    ],
    "remediation_steps": ["Restart the runaway process.", "Scale out VMSS if recurrence."],
}

SAMPLE_REPORT = IncidentReport(
    report_id=str(uuid.uuid4()),
    incident_id="inc-001",
    title="VM CPU spike on vm-web-01",
    severity="sev2",
    status="resolved",
    created_at=CREATED,
    resolved_at=RESOLVED,
    duration_minutes=90,
    affected_resources=["/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-web-01"],
    domain="compute",
    classification="performance",
    agent_summary="High CPU utilisation detected.",
    thread_id="thread-abc-123",
    timeline=[
        {"timestamp": CREATED, "event": "Incident created", "actor": "system"},
        {"timestamp": RESOLVED, "event": "Incident resolved", "actor": "system"},
    ],
    findings=[{"title": "CPU at 98%", "description": "CPU pegged.", "severity": "high"}],
    remediation_steps=["Restart the process.", "Scale out if needed."],
    generated_at=NOW,
)


def _make_cosmos_mock(
    incidents: List[Dict[str, Any]],
    traces: List[Dict[str, Any]] = [],
) -> MagicMock:
    def get_container_client(name: str) -> MagicMock:
        container = MagicMock()
        if name == "incidents":
            container.query_items.return_value = iter(incidents)
        else:
            container.query_items.return_value = iter(traces)
        return container

    db = MagicMock()
    db.get_container_client.side_effect = get_container_client
    client = MagicMock()
    client.get_database_client.return_value = db
    return client


# ---------------------------------------------------------------------------
# _parse_duration
# ---------------------------------------------------------------------------


def test_parse_duration_happy_path():
    minutes = _parse_duration(CREATED, RESOLVED)
    assert minutes == 90


def test_parse_duration_no_resolved():
    assert _parse_duration(CREATED, None) is None


def test_parse_duration_invalid_timestamps():
    assert _parse_duration("not-a-date", "also-bad") is None


def test_parse_duration_zero_delta():
    assert _parse_duration(CREATED, CREATED) == 0


# ---------------------------------------------------------------------------
# _extract_timeline
# ---------------------------------------------------------------------------


def test_extract_timeline_basic():
    incident = {"created_at": CREATED, "resolved_at": RESOLVED, "source": "monitor"}
    timeline = _extract_timeline(incident, [])
    assert len(timeline) == 2
    assert timeline[0]["event"] == "Incident created"
    assert timeline[-1]["event"] == "Incident resolved"


def test_extract_timeline_with_traces():
    incident = {"created_at": CREATED}
    trace_ts = "2026-04-17T14:30:00+00:00"
    traces = [{"timestamp": trace_ts, "event": "Agent queried ARG", "actor": "compute-agent"}]
    timeline = _extract_timeline(incident, traces)
    assert len(timeline) == 2
    events = [e["event"] for e in timeline]
    assert "Agent queried ARG" in events


def test_extract_timeline_sorted():
    incident = {"created_at": CREATED, "resolved_at": RESOLVED}
    traces = [{"timestamp": "2026-04-17T14:45:00+00:00", "event": "Midpoint", "actor": "agent"}]
    timeline = _extract_timeline(incident, traces)
    timestamps = [e["timestamp"] for e in timeline]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# _build_findings
# ---------------------------------------------------------------------------


def test_build_findings_structured():
    findings = _build_findings(SAMPLE_INCIDENT)
    assert len(findings) == 1
    assert findings[0]["title"] == "CPU at 98%"


def test_build_findings_fallback_to_summary():
    incident = {"agent_summary": "Some summary", "severity": "high"}
    findings = _build_findings(incident)
    assert len(findings) == 1
    assert findings[0]["description"] == "Some summary"


def test_build_findings_empty():
    findings = _build_findings({})
    assert findings == []


# ---------------------------------------------------------------------------
# _build_remediation_steps
# ---------------------------------------------------------------------------


def test_build_remediation_steps_structured():
    steps = _build_remediation_steps(SAMPLE_INCIDENT)
    assert len(steps) == 2
    assert "Restart" in steps[0]


def test_build_remediation_steps_defaults():
    steps = _build_remediation_steps({})
    assert len(steps) > 0
    assert all(isinstance(s, str) for s in steps)


# ---------------------------------------------------------------------------
# generate_incident_report
# ---------------------------------------------------------------------------


def test_generate_report_happy_path():
    cosmos = _make_cosmos_mock([SAMPLE_INCIDENT])
    report = generate_incident_report(cosmos, "aap-db", "inc-001")
    assert report is not None
    assert report.incident_id == "inc-001"
    assert report.title == "VM CPU spike on vm-web-01"
    assert report.severity == "sev2"
    assert report.duration_minutes == 90


def test_generate_report_not_found():
    cosmos = _make_cosmos_mock([])
    report = generate_incident_report(cosmos, "aap-db", "inc-missing")
    assert report is None


def test_generate_report_cosmos_error_returns_none():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = RuntimeError("Cosmos down")
    report = generate_incident_report(cosmos, "aap-db", "inc-001")
    assert report is None


def test_generate_report_with_traces():
    traces = [{"timestamp": "2026-04-17T14:20:00+00:00", "event": "ARG query", "actor": "agent"}]
    cosmos = _make_cosmos_mock([SAMPLE_INCIDENT], traces)
    report = generate_incident_report(cosmos, "aap-db", "inc-001")
    assert report is not None
    assert any("ARG query" in e["event"] for e in report.timeline)


def test_generate_report_no_thread_id():
    incident = {**SAMPLE_INCIDENT, "thread_id": None}
    cosmos = _make_cosmos_mock([incident])
    report = generate_incident_report(cosmos, "aap-db", "inc-001")
    assert report is not None
    assert report.thread_id is None


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def test_render_markdown_contains_title():
    md = render_markdown(SAMPLE_REPORT)
    assert "# Incident Report:" in md
    assert SAMPLE_REPORT.title in md


def test_render_markdown_contains_summary_table():
    md = render_markdown(SAMPLE_REPORT)
    assert "| **Incident ID**" in md
    assert SAMPLE_REPORT.incident_id in md


def test_render_markdown_contains_timeline():
    md = render_markdown(SAMPLE_REPORT)
    assert "## Timeline" in md
    assert "Incident created" in md


def test_render_markdown_contains_findings():
    md = render_markdown(SAMPLE_REPORT)
    assert "## Findings" in md
    assert "CPU at 98%" in md


def test_render_markdown_contains_remediation():
    md = render_markdown(SAMPLE_REPORT)
    assert "## Remediation Steps" in md
    assert "Restart" in md


def test_render_markdown_contains_footer():
    md = render_markdown(SAMPLE_REPORT)
    assert "Azure Agentic Platform" in md


# ---------------------------------------------------------------------------
# render_json
# ---------------------------------------------------------------------------


def test_render_json_all_keys():
    data = render_json(SAMPLE_REPORT)
    expected_keys = {
        "report_id", "incident_id", "title", "severity", "status",
        "created_at", "resolved_at", "duration_minutes", "affected_resources",
        "domain", "classification", "agent_summary", "thread_id",
        "timeline", "findings", "remediation_steps", "generated_at",
    }
    assert expected_keys.issubset(data.keys())


def test_render_json_values():
    data = render_json(SAMPLE_REPORT)
    assert data["incident_id"] == "inc-001"
    assert data["duration_minutes"] == 90
    assert isinstance(data["timeline"], list)
    assert isinstance(data["findings"], list)
    assert isinstance(data["remediation_steps"], list)
