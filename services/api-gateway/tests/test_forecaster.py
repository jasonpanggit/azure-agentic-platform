from __future__ import annotations
"""Unit tests for the Forecaster Service (INTEL-005).

Tests cover:
- _holt_smooth math (tests 1–5)
- _compute_mape (tests 6–8)
- _compute_time_to_breach (tests 9–12)
- ForecasterClient.update_baseline (tests 13–15)
- ForecasterClient.get_forecasts (test 16)
- _emit_forecast_alert structure (test 17)
"""

from unittest.mock import MagicMock, patch

import pytest

# Import under test (no Azure packages needed for unit tests)
from services.api_gateway.forecaster import (
    ForecasterClient,
    _compute_mape,
    _compute_time_to_breach,
    _emit_forecast_alert,
    _holt_smooth,
)


# ---------------------------------------------------------------------------
# Tests 1–5: _holt_smooth pure function
# ---------------------------------------------------------------------------


class TestHoltSmooth:
    """_holt_smooth is deterministic pure math — no mocks needed."""

    def test_holt_smooth_empty_list(self):
        """Empty list returns (0.0, 0.0)."""
        level, trend = _holt_smooth([])
        assert level == 0.0
        assert trend == 0.0

    def test_holt_smooth_single_value(self):
        """Single element returns (value, 0.0)."""
        level, trend = _holt_smooth([42.0])
        assert level == 42.0
        assert trend == 0.0

    def test_holt_smooth_flat_series(self):
        """Constant series has near-zero trend (smoothing dampens to ~0)."""
        values = [50.0] * 20
        level, trend = _holt_smooth(values)
        # Level should stay near 50
        assert abs(level - 50.0) < 1.0
        # Trend should be essentially zero for a flat series
        assert abs(trend) < 0.01

    def test_holt_smooth_rising_series(self):
        """Rising series: level near last value, trend > 0."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        level, trend = _holt_smooth(values)
        # Level should be close to the most recent value (smoothed)
        assert level > 30.0
        # Trend must be positive
        assert trend > 0.0

    def test_holt_smooth_falling_series(self):
        """Falling series: trend is negative."""
        values = [50.0, 40.0, 30.0, 20.0, 10.0]
        level, trend = _holt_smooth(values)
        # Trend must be negative
        assert trend < 0.0

    def test_holt_smooth_deterministic(self):
        """Same inputs always produce same outputs (no randomness)."""
        values = [10.0, 15.0, 25.0, 40.0, 60.0, 85.0]
        result1 = _holt_smooth(values)
        result2 = _holt_smooth(values)
        assert result1 == result2

    def test_holt_smooth_two_values(self):
        """Two values: first iteration is handled without IndexError."""
        level, trend = _holt_smooth([10.0, 20.0])
        # Trend initialized as values[1] - values[0] = 10, then one smoothing step
        assert isinstance(level, float)
        assert isinstance(trend, float)


# ---------------------------------------------------------------------------
# Tests 6–8: _compute_mape pure function
# ---------------------------------------------------------------------------


class TestComputeMape:
    """_compute_mape is a pure function — no mocks needed."""

    def test_compute_mape_perfect(self):
        """actual == predicted → MAPE = 0.0."""
        actual = [10.0, 20.0, 30.0]
        predicted = [10.0, 20.0, 30.0]
        assert _compute_mape(actual, predicted) == 0.0

    def test_compute_mape_known_error(self):
        """Predicted 10% above actual → MAPE ≈ 10.0."""
        actual = [100.0, 200.0, 300.0]
        predicted = [110.0, 220.0, 330.0]
        mape = _compute_mape(actual, predicted)
        assert abs(mape - 10.0) < 0.001

    def test_compute_mape_skips_zero_actuals(self):
        """Zeros in actual are skipped gracefully (no division by zero)."""
        actual = [0.0, 100.0, 0.0, 200.0]
        predicted = [50.0, 120.0, 10.0, 220.0]
        # Only indices 1 and 3 are valid (non-zero actuals)
        # Index 1: |100-120|/100 * 100 = 20%
        # Index 3: |200-220|/200 * 100 = 10%
        # MAPE = (20 + 10) / 2 = 15%
        mape = _compute_mape(actual, predicted)
        assert abs(mape - 15.0) < 0.001

    def test_compute_mape_mismatched_lengths_returns_zero(self):
        """Length mismatch → returns 0.0."""
        assert _compute_mape([1.0, 2.0], [1.0]) == 0.0

    def test_compute_mape_empty_returns_zero(self):
        """Empty lists → returns 0.0."""
        assert _compute_mape([], []) == 0.0

    def test_compute_mape_all_zero_actuals(self):
        """All-zero actuals → returns 0.0 (no valid pairs)."""
        assert _compute_mape([0.0, 0.0], [1.0, 2.0]) == 0.0


# ---------------------------------------------------------------------------
# Tests 9–12: _compute_time_to_breach pure function
# ---------------------------------------------------------------------------


class TestComputeTimeToBreach:
    """_compute_time_to_breach is a pure function — no mocks needed."""

    def test_ttb_rising_normal(self):
        """Rising trend + headroom → positive minutes returned."""
        # level=50, trend=2 per interval (10% per 5min), threshold=90
        # intervals = (90-50)/2 = 20, minutes = 20*5 = 100
        ttb = _compute_time_to_breach(level=50.0, trend=2.0, threshold=90.0)
        assert ttb is not None
        assert ttb > 0.0
        assert abs(ttb - 100.0) < 0.1

    def test_ttb_flat_trend_returns_none(self):
        """Trend = 0 → None (no breach projected)."""
        ttb = _compute_time_to_breach(level=50.0, trend=0.0, threshold=90.0)
        assert ttb is None

    def test_ttb_declining_normal_returns_none(self):
        """Falling trend + normal (non-inverted) metric → None."""
        ttb = _compute_time_to_breach(level=50.0, trend=-1.0, threshold=90.0)
        assert ttb is None

    def test_ttb_invert_metric_falling(self):
        """Falling trend + invert=True → positive minutes (memory draining)."""
        # level=10.0 GB, trend=-0.5 per interval, threshold=0.1 GB (invert)
        # intervals = (10.0 - 0.1) / 0.5 = 19.8, minutes = 99.0
        ttb = _compute_time_to_breach(
            level=10.0, trend=-0.5, threshold=0.1, invert=True
        )
        assert ttb is not None
        assert ttb > 0.0
        assert abs(ttb - 99.0) < 0.1

    def test_ttb_already_breached_returns_none(self):
        """Level already >= threshold → None (already breached)."""
        ttb = _compute_time_to_breach(level=95.0, trend=1.0, threshold=90.0)
        assert ttb is None

    def test_ttb_invert_already_breached_returns_none(self):
        """Inverted: level already <= threshold → None."""
        ttb = _compute_time_to_breach(
            level=0.05, trend=-0.1, threshold=0.1, invert=True
        )
        assert ttb is None

    def test_ttb_beyond_24h_returns_none(self):
        """More than 1440 minutes (24h) ahead → None (too low confidence)."""
        # trend=0.001, threshold=90, level=1 → intervals=89000, minutes=445000 >> 1440
        ttb = _compute_time_to_breach(level=1.0, trend=0.001, threshold=90.0)
        assert ttb is None

    def test_ttb_rising_invert_returns_none(self):
        """Rising trend + invert=True (memory increasing) → None."""
        ttb = _compute_time_to_breach(
            level=5.0, trend=0.5, threshold=0.1, invert=True
        )
        assert ttb is None


# ---------------------------------------------------------------------------
# Tests 13–15: ForecasterClient.update_baseline
# ---------------------------------------------------------------------------


def _make_data_points(n: int, start: float = 10.0, step: float = 1.0):
    """Helper: generate n data points with linear values."""
    return [
        {"timestamp": f"2026-04-01T00:{i:02d}:00Z", "value": start + i * step}
        for i in range(n)
    ]


class TestForecasterClientUpdateBaseline:
    """update_baseline computes Holt smoothing and upserts to Cosmos."""

    def test_update_baseline_insufficient_data(self):
        """Fewer than 2 data points → returns None, no Cosmos write."""
        mock_cosmos = MagicMock()
        client = ForecasterClient(mock_cosmos, None)

        result = client.update_baseline(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_type="microsoft.compute/virtualmachines",
            metric_name="Percentage CPU",
            data_points=[{"timestamp": "2026-04-01T00:00:00Z", "value": 50.0}],
            threshold=90.0,
        )

        assert result is None
        mock_cosmos.get_database_client.assert_not_called()

    def test_update_baseline_upserts_to_cosmos(self):
        """24 data points → Cosmos upsert_item called once with correct doc structure."""
        mock_container = MagicMock()
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        client = ForecasterClient(mock_cosmos, None)
        data_points = _make_data_points(24, start=50.0, step=1.0)

        result = client.update_baseline(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_type="microsoft.compute/virtualmachines",
            metric_name="Percentage CPU",
            data_points=data_points,
            threshold=90.0,
        )

        assert result is not None
        mock_container.upsert_item.assert_called_once()

        # Verify doc structure
        call_args = mock_container.upsert_item.call_args[0][0]
        assert "id" in call_args
        assert call_args["metric_name"] == "Percentage CPU"
        assert call_args["resource_type"] == "microsoft.compute/virtualmachines"
        assert "level" in call_args
        assert "trend" in call_args
        assert "threshold" in call_args
        assert "confidence" in call_args
        assert "mape" in call_args
        assert "last_updated" in call_args
        assert call_args["threshold"] == 90.0

    def test_update_baseline_cosmos_error_non_fatal(self):
        """Cosmos raises → returns baseline (not None), logs warning."""
        mock_container = MagicMock()
        mock_container.upsert_item.side_effect = RuntimeError("Cosmos unavailable")
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        client = ForecasterClient(mock_cosmos, None)
        data_points = _make_data_points(5, start=60.0, step=2.0)

        # Should NOT raise — must return the baseline despite Cosmos failure
        result = client.update_baseline(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_type="microsoft.compute/virtualmachines",
            metric_name="Percentage CPU",
            data_points=data_points,
            threshold=90.0,
        )

        assert result is not None
        assert result.metric_name == "Percentage CPU"

    def test_update_baseline_no_cosmos_still_returns_baseline(self):
        """cosmos_client=None → Cosmos write skipped, but baseline still returned."""
        client = ForecasterClient(None, None)
        data_points = _make_data_points(5, start=20.0, step=3.0)

        result = client.update_baseline(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_type="microsoft.compute/virtualmachines",
            metric_name="Percentage CPU",
            data_points=data_points,
            threshold=90.0,
        )

        assert result is not None
        assert result.level > 0.0


# ---------------------------------------------------------------------------
# Test 16: ForecasterClient.get_forecasts
# ---------------------------------------------------------------------------


class TestForecasterClientGetForecasts:
    """get_forecasts queries Cosmos or returns empty list gracefully."""

    def test_get_forecasts_returns_empty_when_cosmos_none(self):
        """ForecasterClient(None, None).get_forecasts(...) → []."""
        client = ForecasterClient(None, None)
        result = client.get_forecasts("/subscriptions/sub-1/resourceGroups/rg/providers/vm1")
        assert result == []

    def test_get_forecasts_returns_items_from_cosmos(self):
        """get_forecasts returns filtered Cosmos items without _ keys."""
        fake_item = {
            "id": "rid:metric",
            "resource_id": "/subscriptions/sub-1/vm1",
            "metric_name": "Percentage CPU",
            "level": 75.0,
            "_rid": "internal",
            "_ts": 12345,
        }
        mock_container = MagicMock()
        mock_container.query_items.return_value = iter([fake_item])
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        client = ForecasterClient(mock_cosmos, None)
        result = client.get_forecasts("/subscriptions/sub-1/vm1")

        assert len(result) == 1
        assert "_rid" not in result[0]
        assert "_ts" not in result[0]
        assert result[0]["metric_name"] == "Percentage CPU"

    def test_get_forecasts_returns_empty_on_cosmos_error(self):
        """Cosmos raises → returns [] (non-fatal)."""
        mock_db = MagicMock()
        mock_db.get_container_client.side_effect = RuntimeError("DB error")
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        client = ForecasterClient(mock_cosmos, None)
        result = client.get_forecasts("/subscriptions/sub-1/vm1")

        assert result == []


# ---------------------------------------------------------------------------
# Test 17: _emit_forecast_alert structure
# ---------------------------------------------------------------------------


class TestEmitForecastAlert:
    """_emit_forecast_alert constructs a correct IncidentPayload-compatible dict."""

    def test_emit_forecast_alert_structure(self):
        """Verify all required fields are present in the returned dict."""
        resource_id = "/subscriptions/sub-abc123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
        payload = _emit_forecast_alert(
            incident_id="forecast-test-001",
            resource_id=resource_id,
            resource_type="microsoft.compute/virtualmachines",
            metric_name="Percentage CPU",
            threshold=90.0,
            ttb=45.0,
            confidence="high",
        )

        # Required top-level fields
        assert payload["incident_id"] == "forecast-test-001"
        assert payload["severity"] == "Sev2"
        assert payload["domain"] == "compute"
        assert payload["detection_rule"] == "forecast_capacity_exhaustion"
        assert "title" in payload
        assert "description" in payload
        assert "affected_resources" in payload
        assert len(payload["affected_resources"]) == 1

        # Affected resource fields
        ar = payload["affected_resources"][0]
        assert ar["resource_id"] == resource_id
        assert ar["resource_type"] == "microsoft.compute/virtualmachines"
        assert ar["subscription_id"] == "sub-abc123"

        # Title/description content
        assert "45" in payload["title"]
        assert "Percentage CPU" in payload["description"]
        assert "high" in payload["description"]

    def test_emit_forecast_alert_storage_domain(self):
        """SQL resource type → domain='storage'."""
        payload = _emit_forecast_alert(
            incident_id="forecast-sql-001",
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Sql/servers/srv/databases/db",
            resource_type="microsoft.sql/servers/databases",
            metric_name="dtu_consumption_percent",
            threshold=90.0,
            ttb=30.0,
            confidence="medium",
        )
        assert payload["domain"] == "storage"

    def test_emit_forecast_alert_missing_subscription_uses_unknown(self):
        """Malformed resource_id without subscriptions → subscription_id='unknown'."""
        payload = _emit_forecast_alert(
            incident_id="forecast-bad-001",
            resource_id="/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_type="microsoft.compute/virtualmachines",
            metric_name="Percentage CPU",
            threshold=90.0,
            ttb=30.0,
            confidence="low",
        )
        assert payload["affected_resources"][0]["subscription_id"] == "unknown"
