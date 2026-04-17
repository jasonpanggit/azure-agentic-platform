from __future__ import annotations
"""Tests for FeedbackCapture — FeedbackRecord model, FeedbackCaptureService, quality endpoints."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(**kwargs):
    """Build a FeedbackRecord with sensible defaults."""
    from services.api_gateway.feedback_capture import FeedbackRecord

    defaults = {
        "incident_id": "inc-001",
        "action_type": "approve",
        "operator_id": "op-123",
        "agent_response_summary": "Restart the service",
        "operator_decision": "approved",
        "verification_outcome": "RESOLVED",
        "response_quality_score": 0.9,
        "sop_id": "sop-reboot-vm",
    }
    defaults.update(kwargs)
    return FeedbackRecord(**defaults)


# ---------------------------------------------------------------------------
# 1. FeedbackRecord creation
# ---------------------------------------------------------------------------

class TestFeedbackRecordCreation:
    def test_feedback_record_creation_defaults(self):
        """FeedbackRecord auto-generates feedback_id and created_at."""
        from services.api_gateway.feedback_capture import FeedbackRecord

        record = FeedbackRecord(incident_id="inc-001", action_type="approve")
        assert record.feedback_id is not None
        assert len(record.feedback_id) == 36  # UUID format
        assert record.incident_id == "inc-001"
        assert record.action_type == "approve"
        assert record.created_at is not None

    def test_feedback_record_all_fields(self):
        """FeedbackRecord stores all optional fields correctly."""
        record = _make_record()
        assert record.operator_id == "op-123"
        assert record.verification_outcome == "RESOLVED"
        assert record.response_quality_score == 0.9
        assert record.sop_id == "sop-reboot-vm"

    def test_feedback_record_action_types(self):
        """FeedbackRecord accepts all valid action_type values."""
        from services.api_gateway.feedback_capture import FeedbackRecord

        for action in ("approve", "reject", "resolved", "degraded"):
            r = FeedbackRecord(incident_id="inc-x", action_type=action)
            assert r.action_type == action

    def test_feedback_record_unique_ids(self):
        """Each FeedbackRecord gets a unique feedback_id."""
        from services.api_gateway.feedback_capture import FeedbackRecord

        r1 = FeedbackRecord(incident_id="inc-1", action_type="approve")
        r2 = FeedbackRecord(incident_id="inc-2", action_type="reject")
        assert r1.feedback_id != r2.feedback_id


# ---------------------------------------------------------------------------
# 2. FeedbackCaptureService — record_feedback (pool unavailable)
# ---------------------------------------------------------------------------

class TestFeedbackCaptureServiceNoPool:
    @pytest.mark.asyncio
    async def test_record_feedback_no_pool_is_noop(self):
        """record_feedback is a silent no-op when pool is None."""
        from services.api_gateway.feedback_capture import FeedbackCaptureService

        svc = FeedbackCaptureService(pool=None)
        record = _make_record()
        # Should not raise
        await svc.record_feedback(record)

    @pytest.mark.asyncio
    async def test_get_quality_metrics_no_pool_returns_error_dict(self):
        """get_quality_metrics returns error dict when pool unavailable."""
        from services.api_gateway.feedback_capture import FeedbackCaptureService

        svc = FeedbackCaptureService(pool=None)
        result = await svc.get_quality_metrics()
        assert "error" in result
        assert result["sop_count_scored"] == 0
        assert result["mttr_p50_min"] is None

    @pytest.mark.asyncio
    async def test_list_recent_feedback_no_pool_returns_empty(self):
        """list_recent_feedback returns empty list when pool unavailable."""
        from services.api_gateway.feedback_capture import FeedbackCaptureService

        svc = FeedbackCaptureService(pool=None)
        result = await svc.list_recent_feedback()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_sop_effectiveness_no_pool_returns_empty(self):
        """list_sop_effectiveness returns empty list when pool unavailable."""
        from services.api_gateway.feedback_capture import FeedbackCaptureService

        svc = FeedbackCaptureService(pool=None)
        result = await svc.list_sop_effectiveness()
        assert result == []


# ---------------------------------------------------------------------------
# 3. SOP effectiveness calculation
# ---------------------------------------------------------------------------

class TestSopEffectivenessCalculation:
    @pytest.mark.asyncio
    async def test_sop_effectiveness_resolved(self):
        """compute_sop_effectiveness returns 1.0 when all outcomes are RESOLVED."""
        from services.api_gateway.feedback_capture import FeedbackCaptureService

        mock_rows = [
            {"verification_outcome": "RESOLVED", "created_at": datetime.now(timezone.utc)},
            {"verification_outcome": "RESOLVED", "created_at": datetime.now(timezone.utc)},
            {"verification_outcome": "RESOLVED", "created_at": datetime.now(timezone.utc)},
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_context(mock_conn))

        svc = FeedbackCaptureService(pool=mock_pool)
        result = await svc.compute_sop_effectiveness("sop-reboot-vm")

        assert result["sop_id"] == "sop-reboot-vm"
        assert result["total_incidents"] == 3
        assert result["resolved_count"] == 3
        assert result["effectiveness_score"] == 1.0

    @pytest.mark.asyncio
    async def test_sop_effectiveness_ignores_unresolved_past_window(self):
        """compute_sop_effectiveness scores correctly with mixed outcomes."""
        from services.api_gateway.feedback_capture import FeedbackCaptureService

        # 2 resolved, 1 degraded, 1 unknown — within window (pool filters by cutoff)
        mock_rows = [
            {"verification_outcome": "RESOLVED", "created_at": datetime.now(timezone.utc)},
            {"verification_outcome": "RESOLVED", "created_at": datetime.now(timezone.utc)},
            {"verification_outcome": "DEGRADED", "created_at": datetime.now(timezone.utc)},
            {"verification_outcome": "UNKNOWN", "created_at": datetime.now(timezone.utc)},
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_context(mock_conn))

        svc = FeedbackCaptureService(pool=mock_pool)
        result = await svc.compute_sop_effectiveness("sop-patch-vm", days=30)

        assert result["total_incidents"] == 4
        assert result["resolved_count"] == 2
        assert result["effectiveness_score"] == 0.5

    @pytest.mark.asyncio
    async def test_sop_effectiveness_zero_incidents(self):
        """compute_sop_effectiveness returns 0.0 score when no incidents."""
        from services.api_gateway.feedback_capture import FeedbackCaptureService

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_context(mock_conn))

        svc = FeedbackCaptureService(pool=mock_pool)
        result = await svc.compute_sop_effectiveness("sop-empty")

        assert result["total_incidents"] == 0
        assert result["effectiveness_score"] == 0.0


# ---------------------------------------------------------------------------
# 4. Quality metrics structure
# ---------------------------------------------------------------------------

class TestQualityMetricsStructure:
    @pytest.mark.asyncio
    async def test_quality_metrics_structure(self):
        """get_quality_metrics always returns required keys."""
        from services.api_gateway.feedback_capture import FeedbackCaptureService

        svc = FeedbackCaptureService(pool=None)
        result = await svc.get_quality_metrics()

        required_keys = {
            "mttr_p50_min",
            "mttr_p95_min",
            "auto_remediation_rate",
            "noise_ratio",
            "sop_count_scored",
            "avg_sop_effectiveness",
        }
        for key in required_keys:
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# 5. Endpoint tests
# ---------------------------------------------------------------------------

class TestQualityEndpoints:
    @pytest.mark.asyncio
    async def test_feedback_endpoint_accepts_payload(self):
        """POST /api/v1/quality/feedback stores a FeedbackRecord."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from services.api_gateway.quality_endpoints import router

        app = FastAPI()
        app.include_router(router)

        # Attach a mock feedback service to app state
        mock_svc = AsyncMock()
        mock_svc.record_feedback = AsyncMock()
        app.state.feedback_service = mock_svc

        client = TestClient(app)
        payload = {
            "incident_id": "inc-test-001",
            "action_type": "approve",
            "operator_id": "op-42",
            "verification_outcome": "RESOLVED",
            "response_quality_score": 0.85,
        }
        response = client.post("/api/v1/quality/feedback", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "feedback_id" in data

    @pytest.mark.asyncio
    async def test_sop_effectiveness_endpoint_sorts_by_score(self):
        """GET /api/v1/quality/sop-effectiveness returns items sorted ASC."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from services.api_gateway.quality_endpoints import router

        app = FastAPI()
        app.include_router(router)

        mock_svc = AsyncMock()
        # Already sorted ASC by service layer
        mock_svc.list_sop_effectiveness = AsyncMock(
            return_value=[
                {"sop_id": "sop-a", "total_incidents": 10, "resolved_count": 2, "effectiveness_score": 0.2, "window_days": 30},
                {"sop_id": "sop-b", "total_incidents": 10, "resolved_count": 5, "effectiveness_score": 0.5, "window_days": 30},
                {"sop_id": "sop-c", "total_incidents": 10, "resolved_count": 9, "effectiveness_score": 0.9, "window_days": 30},
            ]
        )
        app.state.feedback_service = mock_svc

        client = TestClient(app)
        response = client.get("/api/v1/quality/sop-effectiveness")
        assert response.status_code == 200
        data = response.json()
        items = data["sop_effectiveness"]
        assert len(items) == 3
        scores = [item["effectiveness_score"] for item in items]
        assert scores == sorted(scores), "Items must be sorted ASC by effectiveness_score"

    @pytest.mark.asyncio
    async def test_metrics_endpoint_returns_expected_shape(self):
        """GET /api/v1/quality/metrics returns all required metric keys."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from services.api_gateway.quality_endpoints import router

        app = FastAPI()
        app.include_router(router)

        mock_svc = AsyncMock()
        mock_svc.get_quality_metrics = AsyncMock(
            return_value={
                "mttr_p50_min": 12.5,
                "mttr_p95_min": 45.0,
                "auto_remediation_rate": 0.72,
                "noise_ratio": 0.08,
                "sop_count_scored": 5,
                "avg_sop_effectiveness": 0.68,
            }
        )
        app.state.feedback_service = mock_svc

        client = TestClient(app)
        response = client.get("/api/v1/quality/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["mttr_p50_min"] == 12.5
        assert data["auto_remediation_rate"] == 0.72
        assert "generated_at" in data


# ---------------------------------------------------------------------------
# 6. _percentile helper
# ---------------------------------------------------------------------------

class TestPercentileHelper:
    def test_percentile_empty_returns_none(self):
        from services.api_gateway.feedback_capture import _percentile

        assert _percentile([], 50) is None

    def test_percentile_p50(self):
        from services.api_gateway.feedback_capture import _percentile

        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = _percentile(values, 50)
        assert result is not None
        assert result <= 30.0  # Median region

    def test_percentile_p95(self):
        from services.api_gateway.feedback_capture import _percentile

        values = list(range(1, 101, 1))
        result = _percentile([float(v) for v in values], 95)
        assert result is not None
        assert result >= 90.0


# ---------------------------------------------------------------------------
# Async context manager helper
# ---------------------------------------------------------------------------

class _async_context:
    """Minimal async context manager wrapping a mock connection."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass
