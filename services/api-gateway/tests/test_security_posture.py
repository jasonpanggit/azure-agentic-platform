"""Tests for SecurityPostureClient and security posture endpoints (Phase 59)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.security_posture import (
    SecurityPostureClient,
    _clamp,
    _compute_composite,
    _score_color,
    WEIGHT_SECURE_SCORE,
    WEIGHT_POLICY_COMPLIANCE,
    WEIGHT_CUSTOM_CONTROLS,
)


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------

class TestClamp:
    def test_clamp_within_range(self):
        assert _clamp(50.0) == 50.0

    def test_clamp_below_min(self):
        assert _clamp(-10.0) == 0.0

    def test_clamp_above_max(self):
        assert _clamp(110.0) == 100.0

    def test_clamp_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(100.0) == 100.0


class TestScoreColor:
    def test_green_above_75(self):
        assert _score_color(80.0) == "green"
        assert _score_color(75.1) == "green"

    def test_yellow_between_50_and_75(self):
        assert _score_color(50.0) == "yellow"
        assert _score_color(74.9) == "yellow"

    def test_red_below_50(self):
        assert _score_color(49.9) == "red"
        assert _score_color(0.0) == "red"


class TestComputeComposite:
    def test_composite_score_calculation(self):
        """Composite = 50%*80 + 30%*60 + 20%*70 = 40+18+14 = 72."""
        result = _compute_composite(80.0, 60.0, 70.0)
        expected = round(
            WEIGHT_SECURE_SCORE * 80.0
            + WEIGHT_POLICY_COMPLIANCE * 60.0
            + WEIGHT_CUSTOM_CONTROLS * 70.0,
            1,
        )
        assert result["composite_score"] == expected

    def test_score_bounded_0_100_high_inputs(self):
        """All 100 → composite 100."""
        result = _compute_composite(100.0, 100.0, 100.0)
        assert 0.0 <= result["composite_score"] <= 100.0
        assert result["composite_score"] == 100.0

    def test_score_bounded_0_100_zero_inputs(self):
        """All 0 → composite 0."""
        result = _compute_composite(0.0, 0.0, 0.0)
        assert result["composite_score"] == 0.0

    def test_score_bounded_0_100_none_inputs(self):
        """None inputs treated as 0 — composite still in [0,100]."""
        result = _compute_composite(None, None, None)
        assert 0.0 <= result["composite_score"] <= 100.0

    def test_none_secure_score_adds_warning(self):
        result = _compute_composite(None, 80.0, 70.0)
        assert any("Defender" in w for w in result["warnings"])

    def test_none_policy_compliance_adds_warning(self):
        result = _compute_composite(80.0, None, 70.0)
        assert any("Policy" in w for w in result["warnings"])

    def test_sub_scores_present_in_result(self):
        result = _compute_composite(75.0, 60.0, 50.0)
        assert "sub_scores" in result
        assert result["sub_scores"]["defender_secure_score"] == 75.0
        assert result["sub_scores"]["policy_compliance"] == 60.0
        assert result["sub_scores"]["custom_controls"] == 50.0

    def test_color_field_in_result(self):
        green = _compute_composite(90.0, 90.0, 90.0)
        assert green["color"] == "green"
        red = _compute_composite(10.0, 10.0, 10.0)
        assert red["color"] == "red"


# ---------------------------------------------------------------------------
# SecurityPostureClient tests (mocked Azure SDKs)
# ---------------------------------------------------------------------------

def _make_client(cosmos=None):
    return SecurityPostureClient(
        cosmos_client=cosmos,
        credential=MagicMock(),
        subscription_id="sub-test-1234",
    )


class TestGetCompositeScore:
    def test_posture_endpoint_returns_score(self):
        """get_composite_score returns dict with composite_score field."""
        client = _make_client()
        # Mock internal methods to avoid real Azure calls
        client._get_defender_secure_score = MagicMock(return_value=80.0)
        client._get_policy_compliance_pct = MagicMock(return_value=70.0)
        client._get_custom_controls_score = MagicMock(return_value=None)
        client._upsert_posture = MagicMock()

        result = client.get_composite_score()

        assert "composite_score" in result
        assert isinstance(result["composite_score"], float)
        assert 0.0 <= result["composite_score"] <= 100.0
        assert result["subscription_id"] == "sub-test-1234"

    def test_get_composite_score_no_cosmos(self):
        """get_composite_score works without Cosmos (upsert is no-op)."""
        client = _make_client(cosmos=None)
        client._get_defender_secure_score = MagicMock(return_value=65.0)
        client._get_policy_compliance_pct = MagicMock(return_value=55.0)
        client._get_custom_controls_score = MagicMock(return_value=None)

        result = client.get_composite_score()
        assert "composite_score" in result
        assert result["composite_score"] >= 0.0

    def test_get_composite_score_sdk_exception_does_not_raise(self):
        """If internal method raises, get_composite_score returns error dict."""
        client = _make_client()
        client._get_defender_secure_score = MagicMock(side_effect=RuntimeError("boom"))
        client._get_policy_compliance_pct = MagicMock(return_value=50.0)
        client._get_custom_controls_score = MagicMock(return_value=None)
        client._upsert_posture = MagicMock()

        result = client.get_composite_score()
        # Should return error dict, not raise
        assert "error" in result or "composite_score" in result


class TestGetTopFindings:
    def test_findings_endpoint_returns_list(self):
        """get_top_findings returns dict with findings list."""
        client = _make_client()
        client._get_top_findings_raw = MagicMock(return_value=[
            {
                "finding": "Enable MFA",
                "severity": "High",
                "resource_id": "/subscriptions/sub-test-1234/resourceGroups/rg1",
                "resource_name": "rg1",
                "recommendation": "Enable MFA for all users",
                "control": "Identity",
            }
        ])

        result = client.get_top_findings(limit=25)

        assert "findings" in result
        assert isinstance(result["findings"], list)
        assert result["total"] == 1
        assert result["findings"][0]["severity"] == "High"

    def test_findings_empty_when_sdk_unavailable(self):
        """get_top_findings returns empty list when SDK call returns empty."""
        client = _make_client()
        client._get_top_findings_raw = MagicMock(return_value=[])

        result = client.get_top_findings()
        assert result["findings"] == []
        assert result["total"] == 0


class TestGetPostureTrend:
    def test_trend_empty_without_cosmos(self):
        """get_posture_trend returns empty trend when Cosmos is None."""
        client = _make_client(cosmos=None)
        result = client.get_posture_trend(days=30)
        assert "trend" in result
        assert result["trend"] == []

    def test_trend_returns_list_with_cosmos(self):
        """get_posture_trend queries Cosmos and returns trend points."""
        mock_cosmos = MagicMock()
        mock_container = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container
        mock_container.query_items.return_value = [
            {"generated_at": "2026-04-01T10:00:00+00:00", "composite_score": 72.5},
            {"generated_at": "2026-04-02T10:00:00+00:00", "composite_score": 74.0},
        ]

        client = _make_client(cosmos=mock_cosmos)
        result = client.get_posture_trend(days=30)

        assert "trend" in result
        assert len(result["trend"]) == 2
        assert result["trend"][0]["score"] == 72.5
        assert result["trend"][0]["date"] == "2026-04-01"
