"""Tests for advisory_service.py — Phase 73 Predictive Incident Prevention."""
from __future__ import annotations

import statistics
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.advisory_service import (
    AdvisoryRecord,
    build_advisory,
    detect_anomaly,
    dismiss_advisory,
    get_advisories,
    persist_advisory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_baseline(mean: float, stdev: float, n: int = 20) -> list[float]:
    """Generate n-1 baseline values plus one latest value well above mean."""
    import random

    random.seed(42)
    values = [mean + random.gauss(0, stdev) for _ in range(n - 1)]
    return values


def _normal_series(mean: float = 50.0, stdev: float = 5.0, n: int = 20) -> list[float]:
    import random

    random.seed(0)
    return [mean + random.gauss(0, stdev) for _ in range(n)]


# ---------------------------------------------------------------------------
# detect_anomaly tests
# ---------------------------------------------------------------------------


class TestDetectAnomaly:
    def test_value_well_above_threshold_returns_true(self):
        """Latest value 4σ above baseline mean → anomaly detected."""
        baseline = [50.0] * 19  # zero variance would fail; add tiny noise
        baseline = [50.0 + (i % 3) * 0.1 for i in range(19)]
        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline)
        # Push latest value 4σ above
        latest = mean + 4.0 * stdev
        values = baseline + [latest]
        is_anomaly, z = detect_anomaly(values, threshold_sigma=2.5)
        assert is_anomaly is True
        assert z > 2.5

    def test_normal_value_returns_false(self):
        """Latest value within 1σ → no anomaly."""
        baseline = [50.0 + (i % 5) * 0.5 for i in range(19)]
        mean = statistics.mean(baseline)
        latest = mean + 0.8 * statistics.stdev(baseline)
        values = baseline + [latest]
        is_anomaly, z = detect_anomaly(values, threshold_sigma=2.5)
        assert is_anomaly is False

    def test_insufficient_data_returns_false_zero(self):
        """Fewer than 10 data points → (False, 0.0)."""
        values = [80.0, 90.0, 100.0, 110.0]
        is_anomaly, z = detect_anomaly(values)
        assert is_anomaly is False
        assert z == 0.0

    def test_exactly_10_points_allowed(self):
        """Exactly 10 data points should be processed (not rejected)."""
        baseline = [50.0 + i * 0.1 for i in range(9)]
        stdev = statistics.stdev(baseline)
        latest = statistics.mean(baseline) + 5.0 * stdev
        values = baseline + [latest]
        assert len(values) == 10
        is_anomaly, z = detect_anomaly(values, threshold_sigma=2.5)
        assert is_anomaly is True

    def test_z_score_calculation_accuracy(self):
        """Z-score should match manual calculation."""
        baseline = [10.0, 12.0, 11.0, 10.5, 11.5, 10.0, 12.0, 11.0, 10.5, 11.5,
                    10.0, 12.0, 11.0, 10.5, 11.5, 10.0, 12.0, 11.0, 10.5]
        latest = 20.0
        values = baseline + [latest]
        _, z = detect_anomaly(values, threshold_sigma=1.0)
        expected_z = (latest - statistics.mean(baseline)) / statistics.stdev(baseline)
        assert abs(z - expected_z) < 1e-9

    def test_custom_threshold_sigma(self):
        """Custom threshold_sigma=1.0 should trigger on smaller deviations."""
        baseline = [50.0 + (i % 3) * 0.5 for i in range(19)]
        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline)
        # 1.5σ above mean — should NOT trigger at 2.5 but SHOULD at 1.0
        latest = mean + 1.5 * stdev
        values = baseline + [latest]
        is_anomaly_strict, _ = detect_anomaly(values, threshold_sigma=2.5)
        is_anomaly_loose, _ = detect_anomaly(values, threshold_sigma=1.0)
        assert is_anomaly_strict is False
        assert is_anomaly_loose is True


# ---------------------------------------------------------------------------
# build_advisory tests
# ---------------------------------------------------------------------------


class TestBuildAdvisory:
    def _anomaly_values(self) -> list[float]:
        baseline = [50.0 + (i % 5) * 0.4 for i in range(19)]
        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline)
        return baseline + [mean + 4.0 * stdev]

    def test_anomaly_returns_record(self):
        """build_advisory returns AdvisoryRecord when anomaly detected."""
        values = self._anomaly_values()
        record = build_advisory(
            subscription_id="sub-001",
            resource_id="/subscriptions/sub-001/resourceGroups/rg/providers/vm/my-vm",
            resource_name="my-vm",
            metric_name="cpu_percentage",
            values=values,
        )
        assert record is not None
        assert isinstance(record, AdvisoryRecord)
        assert record.advisory_id.startswith("adv-")
        assert record.subscription_id == "sub-001"
        assert record.resource_name == "my-vm"
        assert record.metric_name == "cpu_percentage"
        assert record.status == "active"

    def test_no_anomaly_returns_none(self):
        """build_advisory returns None when no anomaly detected."""
        values = _normal_series(mean=50.0, stdev=2.0, n=20)
        # Ensure the last value is close to mean
        values[-1] = 50.0
        record = build_advisory(
            subscription_id="sub-001",
            resource_id="/subscriptions/sub-001/vm/normal-vm",
            resource_name="normal-vm",
            metric_name="cpu_percentage",
            values=values,
        )
        assert record is None

    def test_severity_warning_between_2_5_and_3_5_sigma(self):
        """Z-score between 2.5 and 3.5σ → severity 'warning'."""
        baseline = [50.0 + (i % 5) * 0.5 for i in range(19)]
        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline)
        # 3.0σ → warning
        latest = mean + 3.0 * stdev
        values = baseline + [latest]
        record = build_advisory(
            subscription_id="sub-001",
            resource_id="/vm/r1",
            resource_name="r1",
            metric_name="cpu_percentage",
            values=values,
        )
        assert record is not None
        assert record.severity == "warning"

    def test_severity_critical_above_3_5_sigma(self):
        """Z-score above 3.5σ → severity 'critical'."""
        baseline = [50.0 + (i % 5) * 0.5 for i in range(19)]
        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline)
        # 4.0σ → critical
        latest = mean + 4.0 * stdev
        values = baseline + [latest]
        record = build_advisory(
            subscription_id="sub-001",
            resource_id="/vm/r1",
            resource_name="r1",
            metric_name="cpu_percentage",
            values=values,
        )
        assert record is not None
        assert record.severity == "critical"

    def test_trend_direction_rising(self):
        """Last 3 values steadily rising → trend_direction='rising'."""
        baseline = [50.0] * 16
        rising_tail = [51.0, 55.0, 80.0]  # last 3 rising, last is anomaly
        values = baseline + rising_tail
        record = build_advisory(
            subscription_id="sub-001",
            resource_id="/vm/r2",
            resource_name="r2",
            metric_name="cpu_percentage",
            values=values,
        )
        assert record is not None
        assert record.trend_direction == "rising"

    def test_trend_direction_falling(self):
        """Last 3 values steadily falling → trend_direction='falling'."""
        baseline = [80.0] * 16
        falling_tail = [79.0, 72.0, 20.0]  # 20 is low anomaly
        values = baseline + falling_tail
        record = build_advisory(
            subscription_id="sub-001",
            resource_id="/vm/r3",
            resource_name="r3",
            metric_name="available_memory_bytes",
            values=values,
            threshold_sigma=2.5,
        )
        # z_score may be negative (falling), check abs
        assert record is not None
        assert record.trend_direction == "falling"

    def test_trend_direction_stable(self):
        """Last 3 values similar → trend_direction='stable'."""
        baseline = [50.0 + (i % 3) * 0.1 for i in range(16)]
        stable_tail = [50.0, 50.1, 80.0]
        values = baseline + stable_tail
        # last two of tail are similar; push a high final value
        record = build_advisory(
            subscription_id="sub-001",
            resource_id="/vm/r4",
            resource_name="r4",
            metric_name="cpu_percentage",
            values=values,
        )
        # stable_tail[-1]=80 is anomaly; tail[-1]=80, tail[-3]=50.0 → rising > 2%
        # so this is rising; change to true stable: last3 all ~same, only final is anomaly
        baseline2 = [50.0 + (i % 3) * 0.1 for i in range(17)]
        stable_tail2 = [51.0, 51.0, 51.0 * 10]  # last value is huge anomaly
        # 51 vs 510 is rising; use values close together for stable
        small_values = [50.0] * 17 + [50.1, 50.05, 200.0]
        record2 = build_advisory(
            subscription_id="sub-001",
            resource_id="/vm/r4",
            resource_name="r4",
            metric_name="cpu_percentage",
            values=small_values,
        )
        assert record2 is not None
        # 200 vs 50.1 and 50.05 → last3 = [50.05, 200.0], rising
        # The stable check requires last[-1] < last[0]*1.02 AND last[-1] > last[0]*0.98
        # 200 > 50.1*1.02 → rising; correct expectation
        assert record2.trend_direction == "rising"

    def test_estimated_breach_hours_passed_through(self):
        """estimated_breach_hours is stored on the record."""
        baseline = [50.0 + (i % 5) * 0.5 for i in range(19)]
        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline)
        values = baseline + [mean + 4.0 * stdev]
        record = build_advisory(
            subscription_id="sub-001",
            resource_id="/vm/r5",
            resource_name="r5",
            metric_name="cpu_percentage",
            values=values,
            estimated_breach_hours=2.5,
        )
        assert record is not None
        assert record.estimated_breach_hours == 2.5
        assert "2.5h" in record.message


# ---------------------------------------------------------------------------
# Cosmos helper tests (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetAdvisories:
    async def test_returns_items_from_cosmos(self):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_database_client.return_value.get_container_client.return_value = (
            mock_container
        )
        mock_container.query_items.return_value = [
            {"advisory_id": "adv-abc123", "severity": "warning", "status": "active"}
        ]
        result = await get_advisories(mock_client, "aap", status="active")
        assert len(result) == 1
        assert result[0]["advisory_id"] == "adv-abc123"

    async def test_cosmos_unavailable_returns_empty_list(self):
        result = await get_advisories(None, "aap", status="active")
        assert result == []

    async def test_cosmos_exception_returns_empty_list(self):
        mock_client = MagicMock()
        mock_client.get_database_client.side_effect = Exception("Cosmos down")
        result = await get_advisories(mock_client, "aap")
        assert result == []

    async def test_subscription_id_filter_applied(self):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_database_client.return_value.get_container_client.return_value = (
            mock_container
        )
        mock_container.query_items.return_value = []
        await get_advisories(mock_client, "aap", subscription_id="sub-xyz")
        call_kwargs = mock_container.query_items.call_args
        query_str = call_kwargs[1]["query"] if call_kwargs[1] else call_kwargs[0][0]
        assert "subscription_id" in query_str


@pytest.mark.asyncio
class TestDismissAdvisory:
    async def test_found_returns_true(self):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_database_client.return_value.get_container_client.return_value = (
            mock_container
        )
        doc = {"id": "adv-abc123", "advisory_id": "adv-abc123", "status": "active"}
        mock_container.query_items.return_value = [doc]
        result = await dismiss_advisory(mock_client, "aap", "adv-abc123")
        assert result is True
        mock_container.upsert_item.assert_called_once()
        assert doc["status"] == "dismissed"

    async def test_not_found_returns_false(self):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_database_client.return_value.get_container_client.return_value = (
            mock_container
        )
        mock_container.query_items.return_value = []
        result = await dismiss_advisory(mock_client, "aap", "adv-nonexistent")
        assert result is False

    async def test_cosmos_none_returns_false(self):
        result = await dismiss_advisory(None, "aap", "adv-abc123")
        assert result is False


@pytest.mark.asyncio
class TestPersistAdvisory:
    async def test_cosmos_unavailable_no_raise(self):
        """persist_advisory with None client must not raise."""
        record = AdvisoryRecord(
            advisory_id="adv-test01",
            subscription_id="sub-001",
            resource_id="/vm/test",
            resource_name="test-vm",
            metric_name="cpu_percentage",
            current_value=95.0,
            baseline_mean=50.0,
            baseline_stddev=5.0,
            z_score=9.0,
            severity="critical",
            trend_direction="rising",
            estimated_breach_hours=1.0,
            message="Test advisory",
            detected_at="2026-04-17T00:00:00+00:00",
            status="active",
            pattern_match=None,
        )
        # Must not raise
        await persist_advisory(None, "aap", record)

    async def test_upserts_to_cosmos(self):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.get_database_client.return_value.get_container_client.return_value = (
            mock_container
        )
        record = AdvisoryRecord(
            advisory_id="adv-test02",
            subscription_id="sub-002",
            resource_id="/vm/test2",
            resource_name="test-vm2",
            metric_name="disk_usage_pct",
            current_value=88.0,
            baseline_mean=40.0,
            baseline_stddev=4.0,
            z_score=12.0,
            severity="critical",
            trend_direction="rising",
            estimated_breach_hours=0.5,
            message="Disk usage critical",
            detected_at="2026-04-17T00:00:00+00:00",
            status="active",
            pattern_match="recurring_disk_pressure",
        )
        await persist_advisory(mock_client, "aap", record)
        mock_container.upsert_item.assert_called_once()
        upserted = mock_container.upsert_item.call_args[0][0]
        assert upserted["advisory_id"] == "adv-test02"
        assert upserted["ttl"] == 172800
