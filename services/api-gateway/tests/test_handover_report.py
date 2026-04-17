"""Tests for Operator Shift Handover Report — Phase 74.

12+ tests covering:
  Group A — generate_handover_report (cosmos available)
  Group B — generate_handover_report (cosmos unavailable / partial data)
  Group C — incident counting helpers
  Group D — SLO status / pattern integration
  Group E — render_markdown / render_teams_card
  Group F — POST endpoint
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_gateway.handover_report import (
    HandoverReport,
    _age_hours,
    _build_focus,
    _is_open,
    _severity_rank,
    generate_handover_report,
    render_markdown,
    render_teams_card,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_incident(
    incident_id: str = "inc-001",
    title: str = "Test incident",
    severity: str = "Sev1",
    status: str = "open",
    detected_at: str = "2026-04-17T08:00:00+00:00",
    resolved_at: str | None = None,
) -> dict:
    doc: dict = {
        "id": incident_id,
        "incident_id": incident_id,
        "title": title,
        "severity": severity,
        "status": status,
        "detected_at": detected_at,
    }
    if resolved_at:
        doc["resolved_at"] = resolved_at
    return doc


def _make_approval(
    approval_id: str = "appr-001",
    title: str = "Restart VM?",
    severity: str = "Sev1",
    status: str = "pending",
) -> dict:
    return {
        "id": approval_id,
        "approval_id": approval_id,
        "title": title,
        "severity": severity,
        "status": status,
    }


def _mock_cosmos_client(incidents: list[dict], approvals: list[dict]) -> MagicMock:
    """Build a mock CosmosClient returning the given incidents + approvals."""
    client = MagicMock()

    def _get_container(name: str):
        container = MagicMock()
        if name == "incidents":
            container.query_items.return_value = incidents
        elif name == "approvals":
            container.query_items.return_value = approvals
        else:
            container.query_items.return_value = []
        container.upsert_item = MagicMock()
        return container

    db = MagicMock()
    db.get_container_client.side_effect = _get_container
    client.get_database_client.return_value = db
    return client


# ---------------------------------------------------------------------------
# Group A — full report (cosmos available)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_full_report_returns_handover_report():
    """When cosmos has data, generate_handover_report returns a HandoverReport."""
    now = datetime.now(timezone.utc)
    shift_start = (now - timedelta(hours=8)).isoformat()

    incidents = [
        _make_incident("i1", "CPU spike", "Sev0", "open", shift_start),
        _make_incident("i2", "Disk full", "Sev1", "open", shift_start),
        _make_incident("i3", "Resolved issue", "Sev2", "resolved",
                       shift_start, resolved_at=now.isoformat()),
    ]
    approvals = [_make_approval()]
    cosmos = _mock_cosmos_client(incidents, approvals)

    report = await generate_handover_report(cosmos, "aap", shift_hours=8)

    assert isinstance(report, HandoverReport)
    assert report.report_id.startswith("handover-")


@pytest.mark.asyncio
async def test_open_incidents_count():
    """open_incidents counts non-resolved, non-dismissed docs."""
    now = datetime.now(timezone.utc)
    shift_start = (now - timedelta(hours=8)).isoformat()
    incidents = [
        _make_incident("i1", status="open", detected_at=shift_start),
        _make_incident("i2", status="investigating", detected_at=shift_start),
        _make_incident("i3", status="resolved", detected_at=shift_start,
                       resolved_at=now.isoformat()),
        _make_incident("i4", status="dismissed", detected_at=shift_start),
    ]
    cosmos = _mock_cosmos_client(incidents, [])
    report = await generate_handover_report(cosmos, "aap")
    assert report.open_incidents == 2


@pytest.mark.asyncio
async def test_resolved_this_shift_count():
    """resolved_this_shift only counts resolved docs whose resolved_at >= shift_start."""
    now = datetime.now(timezone.utc)
    shift_start = now - timedelta(hours=8)
    old = (shift_start - timedelta(hours=1)).isoformat()
    recent = (shift_start + timedelta(minutes=30)).isoformat()

    incidents = [
        _make_incident("i1", status="resolved", detected_at=old, resolved_at=recent),
        _make_incident("i2", status="resolved", detected_at=old, resolved_at=old),
    ]
    cosmos = _mock_cosmos_client(incidents, [])
    report = await generate_handover_report(cosmos, "aap")
    assert report.resolved_this_shift == 1


@pytest.mark.asyncio
async def test_new_this_shift_count():
    """new_this_shift counts incidents detected during the shift window."""
    now = datetime.now(timezone.utc)
    shift_start = now - timedelta(hours=8)
    old = (shift_start - timedelta(hours=1)).isoformat()
    recent = (shift_start + timedelta(minutes=10)).isoformat()

    incidents = [
        _make_incident("i1", status="open", detected_at=recent),
        _make_incident("i2", status="open", detected_at=old),
        _make_incident("i3", status="open", detected_at=recent),
    ]
    cosmos = _mock_cosmos_client(incidents, [])
    report = await generate_handover_report(cosmos, "aap")
    assert report.new_this_shift == 2


@pytest.mark.asyncio
async def test_sev0_sev1_open_counts():
    """sev0_open and sev1_open count correctly among open docs."""
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    incidents = [
        _make_incident("i1", severity="Sev0", status="open", detected_at=ts),
        _make_incident("i2", severity="Sev0", status="open", detected_at=ts),
        _make_incident("i3", severity="Sev1", status="open", detected_at=ts),
        _make_incident("i4", severity="Sev2", status="open", detected_at=ts),
        _make_incident("i5", severity="Sev0", status="resolved", detected_at=ts,
                       resolved_at=ts),
    ]
    cosmos = _mock_cosmos_client(incidents, [])
    report = await generate_handover_report(cosmos, "aap")
    assert report.sev0_open == 2
    assert report.sev1_open == 1


@pytest.mark.asyncio
async def test_top_open_incidents_ordered_by_severity():
    """top_open_incidents lists max 5 open incidents sorted Sev0 first."""
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    incidents = [
        _make_incident(f"i{i}", severity=sev, status="open", detected_at=ts)
        for i, sev in enumerate(["Sev2", "Sev3", "Sev0", "Sev1", "Sev2", "Sev1"])
    ]
    cosmos = _mock_cosmos_client(incidents, [])
    report = await generate_handover_report(cosmos, "aap")

    assert len(report.top_open_incidents) == 5
    assert report.top_open_incidents[0]["severity"] == "Sev0"
    assert report.top_open_incidents[1]["severity"] == "Sev1"


@pytest.mark.asyncio
async def test_pending_approvals_count():
    """pending_approvals reflects number of pending approval docs."""
    approvals = [_make_approval(f"a{i}") for i in range(3)]
    cosmos = _mock_cosmos_client([], approvals)
    report = await generate_handover_report(cosmos, "aap")
    assert report.pending_approvals == 3


@pytest.mark.asyncio
async def test_urgent_approvals_only_sev0_sev1():
    """urgent_approvals includes only Sev0/Sev1 approvals."""
    approvals = [
        _make_approval("a1", severity="Sev0"),
        _make_approval("a2", severity="Sev1"),
        _make_approval("a3", severity="Sev2"),
    ]
    cosmos = _mock_cosmos_client([], approvals)
    report = await generate_handover_report(cosmos, "aap")
    assert report.pending_approvals == 3
    assert len(report.urgent_approvals) == 2
    sevs = {a["severity"] for a in report.urgent_approvals}
    assert sevs == {"Sev0", "Sev1"}


# ---------------------------------------------------------------------------
# Group B — cosmos unavailable / partial data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cosmos_unavailable_returns_zeros_no_raise():
    """When cosmos raises, generate_handover_report returns zeros without raising."""
    bad_client = MagicMock()
    bad_client.get_database_client.side_effect = Exception("Connection refused")

    report = await generate_handover_report(bad_client, "aap")

    assert isinstance(report, HandoverReport)
    assert report.open_incidents == 0
    assert report.pending_approvals == 0


@pytest.mark.asyncio
async def test_none_cosmos_client_returns_partial_report():
    """None cosmos_client produces a partial report with zeros and no exception."""
    report = await generate_handover_report(None, "aap")
    assert isinstance(report, HandoverReport)
    assert report.open_incidents == 0
    assert report.slo_status == "unknown"


# ---------------------------------------------------------------------------
# Group C — pattern integration (graceful fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pattern_fetch_failure_is_graceful():
    """If pattern_analysis container throws, top_patterns is empty, no raise."""
    client = MagicMock()

    def _get_container(name: str):
        container = MagicMock()
        if name == "pattern_analysis":
            container.query_items.side_effect = Exception("timeout")
        else:
            container.query_items.return_value = []
        container.upsert_item = MagicMock()
        return container

    db = MagicMock()
    db.get_container_client.side_effect = _get_container
    client.get_database_client.return_value = db

    report = await generate_handover_report(client, "aap")
    assert report.top_patterns == []


# ---------------------------------------------------------------------------
# Group D — recommended_focus
# ---------------------------------------------------------------------------

def test_recommended_focus_includes_sev0_warning():
    """_build_focus emits Sev0 warning when sev0_open > 0."""
    focus = _build_focus(sev0_open=2, sev1_open=0, pending_approvals=0,
                         top_patterns=[], slo_status="healthy")
    assert any("Sev0" in item for item in focus)


def test_recommended_focus_includes_approvals():
    """_build_focus emits approval reminder when pending > 0."""
    focus = _build_focus(sev0_open=0, sev1_open=0, pending_approvals=3,
                         top_patterns=[], slo_status="healthy")
    assert any("approval" in item.lower() for item in focus)


def test_recommended_focus_slo_breached():
    """_build_focus flags SLO breach."""
    focus = _build_focus(sev0_open=0, sev1_open=0, pending_approvals=0,
                         top_patterns=[], slo_status="breached")
    assert any("breach" in item.lower() for item in focus)


# ---------------------------------------------------------------------------
# Group E — render_markdown / render_teams_card
# ---------------------------------------------------------------------------

def _sample_report() -> HandoverReport:
    return HandoverReport(
        report_id="handover-abc12345",
        shift_start="2026-04-17T04:00:00+00:00",
        shift_end="2026-04-17T12:00:00+00:00",
        generated_at="2026-04-17T12:00:01+00:00",
        open_incidents=3,
        resolved_this_shift=2,
        new_this_shift=4,
        sev0_open=1,
        sev1_open=1,
        top_open_incidents=[
            {"incident_id": "i1", "title": "CPU spike", "severity": "Sev0",
             "status": "open", "age_hours": 2.5},
        ],
        slo_status="at_risk",
        slo_burn_rate=1.8,
        top_patterns=[
            {"pattern_id": "p1", "description": "compute / VM / cpu_spike",
             "frequency": 5, "last_seen": "2026-04-17T11:00:00+00:00"},
        ],
        pending_approvals=2,
        urgent_approvals=[
            {"approval_id": "a1", "title": "Restart VM?", "severity": "Sev0"},
        ],
        recommended_focus=["🚨 Immediate: resolve 1 open Sev0 incident(s)"],
        markdown="",
    )


def test_render_markdown_returns_non_empty_string():
    report = _sample_report()
    md = render_markdown(report)
    assert isinstance(md, str)
    assert len(md) > 100


def test_render_markdown_contains_key_sections():
    report = _sample_report()
    md = render_markdown(report)
    assert "Incident Summary" in md
    assert "SLO Status" in md
    assert "Recommended Focus" in md
    assert "handover-abc12345" in md


def test_render_teams_card_returns_adaptive_card():
    report = _sample_report()
    card = render_teams_card(report)
    assert isinstance(card, dict)
    assert card.get("type") == "AdaptiveCard"
    assert "body" in card
    assert "actions" in card


def test_render_teams_card_has_open_url_action():
    report = _sample_report()
    card = render_teams_card(report)
    actions = card.get("actions", [])
    assert any(a.get("type") == "Action.OpenUrl" for a in actions)


# ---------------------------------------------------------------------------
# Group F — POST endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_endpoint_returns_200():
    """POST /api/v1/reports/shift-handover returns 200 with a HandoverReport payload."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from services.api_gateway.handover_endpoints import router

    app = FastAPI()
    app.include_router(router)
    # Seed app state so get_optional_cosmos_client dependency resolves
    app.state.cosmos_client = None

    with patch(
        "services.api_gateway.handover_endpoints.generate_handover_report",
        new_callable=AsyncMock,
        return_value=_sample_report(),
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/reports/shift-handover",
            json={"shift_hours": 8, "format": "json"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["report_id"] == "handover-abc12345"
    assert "open_incidents" in data
