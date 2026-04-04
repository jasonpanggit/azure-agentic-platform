"""Unit tests for Platform Intelligence endpoints (PLATINT-001, PLATINT-002, PLATINT-003, PLATINT-004).

Tests cover:
- GET /api/v1/intelligence/patterns 200 with PatternAnalysisResult shape (test 1)
- GET /api/v1/intelligence/patterns 404 when no analysis exists (test 2)
- GET /api/v1/intelligence/patterns 503 when Cosmos not configured (test 3)
- GET /api/v1/intelligence/platform-health 200 with all fields (test 4)
- GET /api/v1/intelligence/platform-health 200 when Cosmos not available (test 5)
- POST /api/v1/admin/business-tiers 200 with upsert (test 6)
- GET /api/v1/admin/business-tiers 200 with list (test 7)
- POST /api/v1/admin/business-tiers 503 when Cosmos not configured (test 8)
- POST .../approve passes feedback_text (backward compat) (test 9)
- POST .../reject passes feedback_tags (backward compat) (test 10)
- GET /api/v1/intelligence/patterns 500 on Cosmos error (test 11)
- GET /api/v1/admin/business-tiers 503 when Cosmos not configured (test 12)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from fastapi.testclient import TestClient

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_optional_cosmos_client
from services.api_gateway.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW_ISO = datetime.now(timezone.utc).isoformat()

_SAMPLE_PATTERN_DOC = {
    "id": "pattern-2026-04-04",
    "analysis_id": "pattern-2026-04-04",
    "analysis_date": "2026-04-04",
    "period_days": 30,
    "total_incidents_analyzed": 42,
    "top_patterns": [
        {
            "pattern_id": "pat-001",
            "domain": "compute",
            "resource_type": "microsoft.compute/virtualmachines",
            "detection_rule": "high_cpu",
            "incident_count": 10,
            "frequency_per_week": 2.5,
            "avg_severity_score": 2.8,
            "top_title_words": ["high", "cpu", "vm", "threshold"],
            "first_seen": "2026-03-01T00:00:00Z",
            "last_seen": "2026-04-04T00:00:00Z",
            "operator_flagged": False,
            "common_feedback": [],
        }
    ],
    "finops_summary": {
        "wasted_compute_usd": 12.50,
        "automation_savings_usd": 5.00,
        "complete_remediations": 3,
        "compute_incidents_30min": 5,
    },
    "generated_at": _NOW_ISO,
}

_SAMPLE_TIER_DOC = {
    "id": "gold",
    "tier_name": "gold",
    "monthly_revenue_usd": 50000.0,
    "resource_tags": {"env": "prod"},
    "created_at": _NOW_ISO,
    "updated_at": _NOW_ISO,
}


def _mock_token():
    return {"sub": "test-user"}


def _make_cosmos_mock(query_items_return=None, upsert_item_return=None):
    """Build a layered Cosmos mock: client → database → container."""
    container = MagicMock()
    container.query_items.return_value = iter(query_items_return or [])
    container.upsert_item.return_value = upsert_item_return

    database = MagicMock()
    database.get_container_client.return_value = container

    cosmos = MagicMock()
    cosmos.get_database_client.return_value = database
    return cosmos, container


# ---------------------------------------------------------------------------
# Test 1: GET /api/v1/intelligence/patterns — 200 with PatternAnalysisResult
# ---------------------------------------------------------------------------


def test_get_patterns_200():
    """Returns 200 with PatternAnalysisResult shape when analysis exists."""
    cosmos, _ = _make_cosmos_mock(query_items_return=[_SAMPLE_PATTERN_DOC])

    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/intelligence/patterns")
        assert resp.status_code == 200
        data = resp.json()
        assert "analysis_id" in data
        assert "analysis_date" in data
        assert "top_patterns" in data
        assert "finops_summary" in data
        assert data["total_incidents_analyzed"] == 42
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 2: GET /api/v1/intelligence/patterns — 404 when no analysis
# ---------------------------------------------------------------------------


def test_get_patterns_404_no_analysis():
    """Returns 404 when pattern_analysis container is empty."""
    cosmos, _ = _make_cosmos_mock(query_items_return=[])

    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/intelligence/patterns")
        assert resp.status_code == 404
        assert "No pattern analysis" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 3: GET /api/v1/intelligence/patterns — 503 when Cosmos not configured
# ---------------------------------------------------------------------------


def test_get_patterns_503_no_cosmos():
    """Returns 503 when Cosmos client is not configured."""
    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: None

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/intelligence/patterns")
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 4: GET /api/v1/intelligence/platform-health — 200 with all fields
# ---------------------------------------------------------------------------


def test_get_platform_health_200():
    """Returns 200 with PlatformHealth containing populated Cosmos-sourced fields."""
    # Incidents container: one det- incident
    _det_incident = {"created_at": "2026-04-04T10:00:00+00:00"}
    # Remediation container: 2 complete, 1 failed records
    _rem_items = [
        {"status": "complete"},
        {"status": "complete"},
        {"status": "failed"},
    ]
    # Savings: 1 complete in 30d
    _savings_items = [{"id": "exec-001"}]

    container = MagicMock()
    # Sequence of query_items calls:
    # 1. detection lag (det- incidents)
    # 2. remediation rate (7d)
    # 3. noise reduction (24h)
    # 4. savings count (30d)
    container.query_items.side_effect = [
        iter([_det_incident]),        # detection lag
        iter(_rem_items),             # remediation rate
        iter([{"status": "active"}]), # noise reduction (1 active, 0 suppressed)
        iter(_savings_items),         # savings count
    ]

    database = MagicMock()
    database.get_container_client.return_value = container

    cosmos = MagicMock()
    cosmos.get_database_client.return_value = database

    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos

    try:
        with patch(
            "services.api_gateway.main.list_slos",
            new=AsyncMock(return_value=[
                {"id": "slo-1", "status": "healthy", "error_budget_pct": 95.0},
                {"id": "slo-2", "status": "burn_rate_alert", "error_budget_pct": 40.0},
            ]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/intelligence/platform-health")
        assert resp.status_code == 200
        data = resp.json()
        assert "detection_pipeline_lag_seconds" in data
        assert "auto_remediation_success_rate" in data
        assert "generated_at" in data
        assert data["auto_remediation_success_rate"] == pytest.approx(66.7, abs=0.2)
        assert data["automation_savings_count"] == 1
        assert "slo_compliance_pct" in data
        assert data["slo_compliance_pct"] == 50.0
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 5: GET /api/v1/intelligence/platform-health — 200 when Cosmos unavailable
# ---------------------------------------------------------------------------


def test_get_platform_health_200_no_cosmos():
    """Returns 200 with null Cosmos fields when Cosmos is not configured."""
    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: None

    try:
        with patch(
            "services.api_gateway.main.list_slos",
            new=AsyncMock(return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/intelligence/platform-health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["detection_pipeline_lag_seconds"] is None
        assert data["auto_remediation_success_rate"] is None
        assert data["automation_savings_count"] == 0
        assert "generated_at" in data
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 6: POST /api/v1/admin/business-tiers — 200 with upsert
# ---------------------------------------------------------------------------


def test_post_business_tier_200():
    """Returns 200 with BusinessTier after upsert."""
    cosmos, container = _make_cosmos_mock()

    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/admin/business-tiers",
            json=_SAMPLE_TIER_DOC,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier_name"] == "gold"
        assert data["monthly_revenue_usd"] == 50000.0
        container.upsert_item.assert_called_once()
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 7: GET /api/v1/admin/business-tiers — 200 with list
# ---------------------------------------------------------------------------


def test_get_business_tiers_200():
    """Returns 200 with BusinessTiersResponse containing tiers list."""
    cosmos, _ = _make_cosmos_mock(query_items_return=[_SAMPLE_TIER_DOC])

    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/business-tiers")
        assert resp.status_code == 200
        data = resp.json()
        assert "tiers" in data
        assert len(data["tiers"]) == 1
        assert data["tiers"][0]["tier_name"] == "gold"
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 8: POST /api/v1/admin/business-tiers — 503 when Cosmos not configured
# ---------------------------------------------------------------------------


def test_post_business_tier_503_no_cosmos():
    """Returns 503 when Cosmos is not configured."""
    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: None

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/admin/business-tiers",
            json=_SAMPLE_TIER_DOC,
        )
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 9: POST .../approve passes feedback_text through (PLATINT-003)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_with_feedback_text():
    """Verifies feedback_text is passed to process_approval_decision on approve."""
    from datetime import timedelta

    future_expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    approval_record = {
        "id": "appr-test-001",
        "action_id": "act-001",
        "thread_id": "thread-001",
        "incident_id": "inc-001",
        "agent_name": "compute",
        "status": "pending",
        "risk_level": "low",
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": future_expires,
        "decided_at": None,
        "decided_by": None,
        "executed_at": None,
        "abort_reason": None,
        "resource_snapshot": None,
        "proposal": {"description": "Restart VM"},
        "_etag": '"etag-001"',
    }

    mock_container = MagicMock()
    mock_container.read_item.return_value = approval_record
    mock_container.replace_item.return_value = approval_record

    captured_kwargs: dict = {}

    async def _fake_process_decision(**kwargs):
        captured_kwargs.update(kwargs)

    app.state.credential = MagicMock()
    app.state.cosmos_client = MagicMock()

    with patch(
        "services.api_gateway.approvals._get_approvals_container",
        return_value=mock_container,
    ), patch(
        "services.api_gateway.main.process_approval_decision",
        side_effect=_fake_process_decision,
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/approvals/appr-test-001/approve?thread_id=thread-001",
            json={
                "decided_by": "user@test.com",
                "feedback_text": "Good suggestion",
            },
        )

    # 200 or whatever the endpoint returns, but the key assertion is feedback_text
    assert captured_kwargs.get("feedback_text") == "Good suggestion"


# ---------------------------------------------------------------------------
# Test 10: POST .../reject passes feedback_tags through (PLATINT-003)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_with_feedback_tags():
    """Verifies feedback_tags is passed to process_approval_decision on reject."""
    from datetime import timedelta

    future_expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    approval_record = {
        "id": "appr-test-002",
        "action_id": "act-002",
        "thread_id": "thread-002",
        "incident_id": "inc-002",
        "agent_name": "compute",
        "status": "pending",
        "risk_level": "low",
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": future_expires,
        "decided_at": None,
        "decided_by": None,
        "executed_at": None,
        "abort_reason": None,
        "resource_snapshot": None,
        "proposal": {"description": "Deallocate VM"},
        "_etag": '"etag-002"',
    }

    mock_container = MagicMock()
    mock_container.read_item.return_value = approval_record
    mock_container.replace_item.return_value = approval_record

    captured_kwargs: dict = {}

    async def _fake_process_decision(**kwargs):
        captured_kwargs.update(kwargs)

    app.state.credential = MagicMock()
    app.state.cosmos_client = MagicMock()

    with patch(
        "services.api_gateway.approvals._get_approvals_container",
        return_value=mock_container,
    ), patch(
        "services.api_gateway.main.process_approval_decision",
        side_effect=_fake_process_decision,
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/approvals/appr-test-002/reject?thread_id=thread-002",
            json={
                "decided_by": "user@test.com",
                "feedback_tags": ["false_positive"],
            },
        )

    assert captured_kwargs.get("feedback_tags") == ["false_positive"]


# ---------------------------------------------------------------------------
# Test 11: GET /api/v1/intelligence/patterns — 500 on Cosmos exception
# ---------------------------------------------------------------------------


def test_get_patterns_500_cosmos_error():
    """Returns 500 when Cosmos query throws an unexpected exception."""
    container = MagicMock()
    container.query_items.side_effect = RuntimeError("Cosmos connection refused")

    database = MagicMock()
    database.get_container_client.return_value = container

    cosmos = MagicMock()
    cosmos.get_database_client.return_value = database

    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/intelligence/patterns")
        assert resp.status_code == 500
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)


# ---------------------------------------------------------------------------
# Test 12: GET /api/v1/admin/business-tiers — 503 when Cosmos not configured
# ---------------------------------------------------------------------------


def test_get_business_tiers_503_no_cosmos():
    """Returns 503 when Cosmos is not configured for GET /admin/business-tiers."""
    app.dependency_overrides[verify_token] = _mock_token
    app.dependency_overrides[get_optional_cosmos_client] = lambda: None

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/business-tiers")
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(get_optional_cosmos_client, None)
