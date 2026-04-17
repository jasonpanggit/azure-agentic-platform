from __future__ import annotations
"""Unit tests for alert_timeline_endpoints — Phase 72.

Covers:
- Happy path with full correlations
- Incident not found → 404
- Incident found but no top_changes → empty list (not 404)
- Suppressed incident → suppressed=true in response
- Reason chips for various score combinations
- _score_breakdown helper correctness
- Cosmos unavailable → 503 structured error
- Correlation summary happy path
- Correlation summary incident not found → 404
- Correlation summary Cosmos unavailable → 503
- Multiple changes sorted by correlation_score descending
- Missing optional fields default gracefully
"""
import os

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.alert_timeline_endpoints import (
    _build_reason_chips,
    _score_breakdown,
    _temporal_score_from_delta,
    get_alert_timeline,
    get_correlation_summary,
)
from fastapi.testclient import TestClient
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Minimal app fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    from services.api_gateway.alert_timeline_endpoints import router
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------

SAMPLE_CHANGE: dict[str, Any] = {
    "change_id": "evt-001",
    "operation_name": "microsoft.compute/virtualmachines/write",
    "resource_id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/my-vm-01",
    "resource_name": "my-vm-01",
    "caller": "operator@contoso.com",
    "changed_at": "2026-04-17T10:00:00Z",
    "delta_minutes": 2.0,
    "topology_distance": 0,
    "change_type_score": 0.9,
    "correlation_score": 0.87,
    "status": "Succeeded",
}

SAMPLE_INCIDENT: dict[str, Any] = {
    "incident_id": "inc-abc123",
    "title": "High CPU on my-vm-01",
    "severity": "Sev1",
    "composite_severity": "Sev0",
    "created_at": "2026-04-17T10:02:00Z",
    "suppressed": False,
    "blast_radius": 3,
    "top_changes": [SAMPLE_CHANGE],
}


def _make_cosmos(incident: dict[str, Any] | None):
    """Build a mock Cosmos client that returns the given incident doc."""
    container = MagicMock()
    if incident is None:
        container.query_items.return_value = []
    else:
        container.query_items.return_value = [incident]
    db = MagicMock()
    db.get_container_client.return_value = container
    cosmos = MagicMock()
    cosmos.get_database_client.return_value = db
    return cosmos


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestTemporalScore:
    def test_zero_delta_returns_zero(self):
        assert _temporal_score_from_delta(0) == 0.0

    def test_negative_delta_returns_zero(self):
        assert _temporal_score_from_delta(-5) == 0.0

    def test_2_minutes_high_score(self):
        score = _temporal_score_from_delta(2.0)
        assert score > 0.9

    def test_60_minutes_zero(self):
        score = _temporal_score_from_delta(60.0)
        assert score == pytest.approx(0.0)

    def test_30_minutes_midpoint(self):
        score = _temporal_score_from_delta(30.0)
        assert score == pytest.approx(0.5)


class TestScoreBreakdown:
    def test_fields_present(self):
        bd = _score_breakdown(SAMPLE_CHANGE)
        assert "temporal_score" in bd
        assert "topology_score" in bd
        assert "change_type_score" in bd
        assert "weighted_total" in bd

    def test_weighted_total_in_range(self):
        bd = _score_breakdown(SAMPLE_CHANGE)
        assert 0.0 <= bd["weighted_total"] <= 1.0

    def test_same_resource_topology_score_is_one(self):
        bd = _score_breakdown({**SAMPLE_CHANGE, "topology_distance": 0})
        assert bd["topology_score"] == pytest.approx(1.0)


class TestBuildReasonChips:
    def test_temporal_chip_for_recent_change(self):
        chips = _build_reason_chips(SAMPLE_CHANGE)
        assert any("Temporal" in c for c in chips)

    def test_same_resource_chip(self):
        chips = _build_reason_chips(SAMPLE_CHANGE)
        assert "Same resource" in chips

    def test_write_operation_chip(self):
        chips = _build_reason_chips(SAMPLE_CHANGE)
        assert "Write operation" in chips

    def test_caller_chip_present(self):
        chips = _build_reason_chips(SAMPLE_CHANGE)
        assert any("operator@contoso.com" in c for c in chips)

    def test_topology_neighbor_chip(self):
        change = {**SAMPLE_CHANGE, "topology_distance": 1}
        chips = _build_reason_chips(change)
        assert "Topology neighbor" in chips

    def test_low_temporal_score_no_temporal_chip(self):
        # delta_minutes=90 → temporal_score ≈ 0 → no Temporal chip
        change = {**SAMPLE_CHANGE, "delta_minutes": 90.0}
        chips = _build_reason_chips(change)
        assert not any("Temporal" in c for c in chips)

    def test_fallback_chip_when_nothing_matches(self):
        change = {
            "operation_name": "microsoft.resources/read",
            "resource_name": "res",
            "caller": None,
            "delta_minutes": 90.0,
            "topology_distance": 99,
            "change_type_score": 0.0,
            "correlation_score": 0.1,
        }
        chips = _build_reason_chips(change)
        assert chips == ["Correlated"]


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestAlertTimelineEndpoint:
    def test_happy_path_with_correlations(self):
        cosmos = _make_cosmos(SAMPLE_INCIDENT)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-abc123/alert-timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_id"] == "inc-abc123"
        assert data["severity"] == "Sev1"
        assert data["composite_severity"] == "Sev0"
        assert data["blast_radius"] == 3
        assert len(data["change_correlations"]) == 1
        cc = data["change_correlations"][0]
        assert cc["resource_name"] == "my-vm-01"
        assert cc["correlation_score"] == pytest.approx(0.87, abs=0.01)
        assert "reason_chips" in cc
        assert "score_breakdown" in cc

    def test_incident_not_found_returns_404(self, client):
        cosmos = _make_cosmos(None)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-missing/alert-timeline")
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"].lower()

    def test_no_top_changes_returns_empty_list_not_404(self):
        incident = {**SAMPLE_INCIDENT, "top_changes": None}
        cosmos = _make_cosmos(incident)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-abc123/alert-timeline")
        assert resp.status_code == 200
        assert resp.json()["change_correlations"] == []

    def test_suppressed_incident_returns_suppressed_true(self):
        incident = {**SAMPLE_INCIDENT, "suppressed": True, "suppressed_by": "inc-parent-001"}
        cosmos = _make_cosmos(incident)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-abc123/alert-timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["suppressed"] is True
        assert data["parent_incident_id"] == "inc-parent-001"

    def test_cosmos_unavailable_returns_503(self):
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: None
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-abc123/alert-timeline")
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["error"].lower()

    def test_changes_sorted_by_score_descending(self):
        change_low = {**SAMPLE_CHANGE, "correlation_score": 0.3, "resource_name": "low-score"}
        change_high = {**SAMPLE_CHANGE, "correlation_score": 0.95, "resource_name": "high-score"}
        incident = {**SAMPLE_INCIDENT, "top_changes": [change_low, change_high]}
        cosmos = _make_cosmos(incident)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-abc123/alert-timeline")
        assert resp.status_code == 200
        correlations = resp.json()["change_correlations"]
        assert correlations[0]["resource_name"] == "high-score"
        assert correlations[1]["resource_name"] == "low-score"

    def test_missing_optional_fields_default_gracefully(self):
        incident = {
            "incident_id": "inc-minimal",
            "severity": "Sev2",
        }
        cosmos = _make_cosmos(incident)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-minimal/alert-timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["blast_radius"] is None
        assert data["composite_severity"] is None
        assert data["suppressed"] is False
        assert data["change_correlations"] == []


class TestCorrelationSummaryEndpoint:
    def test_happy_path(self):
        cosmos = _make_cosmos(SAMPLE_INCIDENT)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-abc123/correlation-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_id"] == "inc-abc123"
        assert data["has_correlations"] is True
        assert data["correlation_count"] == 1
        assert data["blast_radius"] == 3
        assert data["top_change"] is not None

    def test_incident_not_found_returns_404(self):
        cosmos = _make_cosmos(None)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-missing/correlation-summary")
        assert resp.status_code == 404

    def test_cosmos_unavailable_returns_503(self):
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: None
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-abc123/correlation-summary")
        assert resp.status_code == 503

    def test_no_changes_returns_has_correlations_false(self):
        incident = {**SAMPLE_INCIDENT, "top_changes": []}
        cosmos = _make_cosmos(incident)
        from services.api_gateway import alert_timeline_endpoints as mod
        app2 = FastAPI()
        app2.include_router(mod.router)
        app2.dependency_overrides[mod.get_optional_cosmos_client] = lambda: cosmos
        tc = TestClient(app2)
        resp = tc.get("/api/v1/incidents/inc-abc123/correlation-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_correlations"] is False
        assert data["correlation_count"] == 0
        assert data["top_change"] is None
