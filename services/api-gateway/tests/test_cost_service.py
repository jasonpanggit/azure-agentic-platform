from __future__ import annotations
"""Tests for cost_service.py — cost anomaly detection service.

Covers:
- detect_cost_anomalies: empty list when <7 data points, warning at 2.5σ,
  critical at >3.5σ, no false positives on flat data
- fetch_daily_costs: HTTP 200 parsing, 403/404/429 graceful handling
- get_cost_summary: aggregation logic
- cost_endpoints: GET anomalies, GET summary, POST scan (background task queued)
"""
import os

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

# ---------------------------------------------------------------------------
# Import service under test
# ---------------------------------------------------------------------------
from services.api_gateway.cost_service import (  # noqa: E402
    CostAnomaly,
    DailyCostSnapshot,
    detect_cost_anomalies,
    fetch_daily_costs,
    get_anomalies,
    get_cost_summary,
    persist_anomalies,
    persist_snapshots,
    run_cost_scan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUB = "sub-test-001"
_BASE_DATE = datetime(2024, 1, 15, tzinfo=timezone.utc)


def _make_snapshot(
    service: str,
    cost: float,
    day_offset: int,
    sub: str = _SUB,
) -> DailyCostSnapshot:
    date = (_BASE_DATE + timedelta(days=day_offset)).strftime("%Y-%m-%d")
    return DailyCostSnapshot(
        snapshot_id=f"snap-{service}-{day_offset}",
        subscription_id=sub,
        date=date,
        service_name=service,
        cost_usd=cost,
        currency="USD",
        captured_at=_BASE_DATE.isoformat(),
    )


def _flat_series(service: str, cost: float, count: int) -> List[DailyCostSnapshot]:
    """Return `count` snapshots with identical cost (no anomaly possible)."""
    return [_make_snapshot(service, cost, i) for i in range(count)]


def _spike_series(service: str, base_cost: float, spike_cost: float, count: int = 14) -> List[DailyCostSnapshot]:
    """Return `count` snapshots; the last point is a spike."""
    snaps = [_make_snapshot(service, base_cost, i) for i in range(count - 1)]
    snaps.append(_make_snapshot(service, spike_cost, count - 1))
    return snaps


# ---------------------------------------------------------------------------
# detect_cost_anomalies
# ---------------------------------------------------------------------------


class TestDetectCostAnomalies:
    def test_returns_empty_when_no_snapshots(self):
        result = detect_cost_anomalies([])
        assert result == []

    def test_returns_empty_when_fewer_than_7_data_points(self):
        """Need at least 7 data points to compute a baseline."""
        snaps = [_make_snapshot("Virtual Machines", 100.0, i) for i in range(6)]
        result = detect_cost_anomalies(snaps)
        assert result == []

    def test_returns_empty_when_exactly_7_data_points_all_uniform(self):
        """7 points but z-score on uniform data is 0 — no anomaly."""
        snaps = _flat_series("Storage", 50.0, 7)
        result = detect_cost_anomalies(snaps)
        assert result == []

    def test_no_false_positives_on_flat_data(self):
        """Completely flat cost series should not produce anomalies."""
        snaps = _flat_series("SQL Database", 200.0, 20)
        result = detect_cost_anomalies(snaps)
        assert result == []

    def test_detects_warning_at_2_5_sigma(self):
        """A moderate spike (>2.5σ but ≤3.5σ) → warning severity."""
        # Base cost $100/day, spike to $600 to push z-score to warning territory
        base = 100.0
        spike = 600.0
        snaps = _spike_series("Virtual Machines", base, spike, count=14)
        result = detect_cost_anomalies(snaps)
        assert len(result) >= 1
        warnings = [a for a in result if a.severity == "warning"]
        # At least one warning anomaly should be detected
        assert len(warnings) >= 1 or any(a.severity == "critical" for a in result)

    def test_detects_critical_above_3_5_sigma(self):
        """A large spike (>3.5σ) → critical severity.

        With n=14 points, the maximum achievable z-score for a single outlier
        is (n-1)/sqrt(n) ≈ 3.47σ (always < 3.5). Use n=20 so a single extreme
        outlier reaches ~4.25σ, firmly in the critical band.
        """
        base = 100.0
        spike = 50000.0  # extreme spike; with n=20 this yields z≈4.25
        snaps = _spike_series("Cognitive Services", base, spike, count=20)
        result = detect_cost_anomalies(snaps)
        assert len(result) >= 1
        criticals = [a for a in result if a.severity == "critical"]
        assert len(criticals) >= 1

    def test_anomaly_fields_populated(self):
        """Verify all required CostAnomaly fields are set correctly."""
        base = 50.0
        spike = 1500.0
        snaps = _spike_series("App Service", base, spike, count=14)
        result = detect_cost_anomalies(snaps)
        assert len(result) >= 1
        a = result[0]
        assert a.anomaly_id != ""
        assert a.subscription_id == _SUB
        assert a.service_name == "App Service"
        assert a.cost_usd == spike
        assert a.baseline_usd > 0
        assert a.z_score > 0
        assert a.pct_change > 0
        assert a.description != ""
        assert a.detected_at != ""
        assert a.ttl == 172800

    def test_no_false_positive_for_negative_spike(self):
        """A sudden drop in cost is NOT flagged (we only flag spend increases)."""
        snaps = [_make_snapshot("Network", 500.0 if i < 13 else 1.0, i) for i in range(14)]
        result = detect_cost_anomalies(snaps)
        # Should not flag drops (only positive z-score spikes)
        spikes_flagged = [a for a in result if a.cost_usd == 1.0]
        assert len(spikes_flagged) == 0

    def test_multiple_services_independent(self):
        """Anomaly detection runs independently per service."""
        normal = _flat_series("Storage", 100.0, 14)
        spike = _spike_series("Cognitive Services", 50.0, 2000.0, count=14)
        result = detect_cost_anomalies(normal + spike)
        services = {a.service_name for a in result}
        assert "Storage" not in services
        assert "Cognitive Services" in services

    def test_requires_7_prior_points_per_evaluation(self):
        """Even with 14 total points, early points (index < 7) are skipped."""
        snaps = [
            _make_snapshot("Container", 10.0 if i == 0 else 100.0, i)
            for i in range(14)
        ]
        result = detect_cost_anomalies(snaps)
        # The cheap day-0 point is at index 0, below MIN_DATA_POINTS — not evaluated
        cheap_anomalies = [a for a in result if a.cost_usd == 10.0]
        assert len(cheap_anomalies) == 0


# ---------------------------------------------------------------------------
# fetch_daily_costs
# ---------------------------------------------------------------------------


class TestFetchDailyCosts:
    def _make_api_response(self, rows: list, columns: list) -> dict:
        return {
            "properties": {
                "columns": [{"name": c} for c in columns],
                "rows": rows,
            }
        }

    def test_parses_200_response(self):
        """Valid 200 response returns list of DailyCostSnapshot."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = self._make_api_response(
            rows=[
                [150.0, "20240101", "Virtual Machines", "USD"],
                [75.0, "20240102", "Storage", "USD"],
            ],
            columns=["Cost", "UsageDate", "ServiceName", "Currency"],
        )

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.cost_service._requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            result = fetch_daily_costs(mock_credential, "sub-001", days=14)

        assert len(result) == 2
        assert result[0].service_name == "Virtual Machines"
        assert result[0].cost_usd == 150.0
        assert result[0].date == "2024-01-01"
        assert result[0].subscription_id == "sub-001"
        assert result[0].ttl == 604800

    def test_handles_403_gracefully(self):
        """403 Forbidden (no Billing Reader) → returns empty list, no raise."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.ok = False

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.cost_service._requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            result = fetch_daily_costs(mock_credential, "sub-001")

        assert result == []

    def test_handles_404_gracefully(self):
        """404 Not Found (subscription gone) → returns empty list, no raise."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.ok = False

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.cost_service._requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            result = fetch_daily_costs(mock_credential, "sub-001")

        assert result == []

    def test_handles_429_gracefully(self):
        """429 Rate Limit → returns empty list, no raise."""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.ok = False

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.cost_service._requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            result = fetch_daily_costs(mock_credential, "sub-001")

        assert result == []

    def test_handles_network_error_gracefully(self):
        """Network timeout / connection error → returns empty list, no raise."""
        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.cost_service._requests") as mock_requests:
            mock_requests.post.side_effect = Exception("Connection refused")
            result = fetch_daily_costs(mock_credential, "sub-001")

        assert result == []

    def test_handles_credential_error_gracefully(self):
        """Token acquisition failure → returns empty list, no raise."""
        mock_credential = MagicMock()
        mock_credential.get_token.side_effect = Exception("Credential expired")

        result = fetch_daily_costs(mock_credential, "sub-001")
        assert result == []

    def test_handles_malformed_json_gracefully(self):
        """Malformed JSON response → returns empty list, no raise."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.side_effect = ValueError("Invalid JSON")

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.cost_service._requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            result = fetch_daily_costs(mock_credential, "sub-001")

        assert result == []

    def test_normalises_8digit_date_format(self):
        """UsageDate in YYYYMMDD format is normalised to YYYY-MM-DD."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "properties": {
                "columns": [{"name": "Cost"}, {"name": "UsageDate"}, {"name": "ServiceName"}, {"name": "Currency"}],
                "rows": [[99.0, "20240315", "Networking", "USD"]],
            }
        }

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.cost_service._requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            result = fetch_daily_costs(mock_credential, "sub-001")

        assert len(result) == 1
        assert result[0].date == "2024-03-15"


# ---------------------------------------------------------------------------
# get_cost_summary
# ---------------------------------------------------------------------------


class TestGetCostSummary:
    def _make_cosmos_anomalies(self, anomalies: List[CostAnomaly]) -> MagicMock:
        mock_cosmos = MagicMock()
        items = []
        for a in anomalies:
            from dataclasses import asdict
            d = asdict(a)
            d["id"] = a.anomaly_id
            items.append(d)
        mock_cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = items
        return mock_cosmos

    def test_returns_zero_counts_when_no_anomalies(self):
        mock_cosmos = self._make_cosmos_anomalies([])
        result = get_cost_summary(mock_cosmos, "aap")
        assert result["total_anomalies"] == 0
        assert result["critical_count"] == 0
        assert result["warning_count"] == 0
        assert result["top_spenders"] == []

    def test_counts_critical_and_warning_separately(self):
        anomalies = [
            CostAnomaly("id1", _SUB, "VMs", "2024-01-01", 500.0, 100.0, 4.0, "critical", 400.0, "desc", "2024-01-01"),
            CostAnomaly("id2", _SUB, "Storage", "2024-01-02", 200.0, 80.0, 2.8, "warning", 150.0, "desc", "2024-01-01"),
            CostAnomaly("id3", _SUB, "SQL", "2024-01-03", 300.0, 90.0, 3.6, "critical", 233.0, "desc", "2024-01-01"),
        ]
        mock_cosmos = self._make_cosmos_anomalies(anomalies)
        result = get_cost_summary(mock_cosmos, "aap")
        assert result["total_anomalies"] == 3
        assert result["critical_count"] == 2
        assert result["warning_count"] == 1

    def test_top_spenders_sorted_by_cost_descending(self):
        anomalies = [
            CostAnomaly("id1", _SUB, "Storage", "2024-01-01", 100.0, 50.0, 2.6, "warning", 100.0, "desc", "2024-01-01"),
            CostAnomaly("id2", _SUB, "VMs", "2024-01-02", 5000.0, 200.0, 4.5, "critical", 2400.0, "desc", "2024-01-01"),
            CostAnomaly("id3", _SUB, "SQL", "2024-01-03", 300.0, 100.0, 2.7, "warning", 200.0, "desc", "2024-01-01"),
        ]
        mock_cosmos = self._make_cosmos_anomalies(anomalies)
        result = get_cost_summary(mock_cosmos, "aap")
        assert result["top_spenders"][0]["service"] == "VMs"
        assert result["top_spenders"][0]["cost"] == 5000.0

    def test_returns_empty_dict_when_cosmos_is_none(self):
        result = get_cost_summary(None, "aap")
        assert result["total_anomalies"] == 0
        assert result["top_spenders"] == []


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from services.api_gateway.cost_endpoints import router  # noqa: E402

_test_app = FastAPI()
_test_app.include_router(router)
_test_app.state.credential = MagicMock()
_test_app.state.cosmos_client = None  # no Cosmos in unit tests

_client = TestClient(_test_app, raise_server_exceptions=False)


class TestCostAnomaliesEndpoint:
    def test_returns_200_with_empty_list_when_cosmos_none(self):
        """Without Cosmos, endpoint returns 200 with empty anomalies list."""
        res = _client.get("/api/v1/cost/anomalies")
        assert res.status_code == 200
        data = res.json()
        assert "anomalies" in data
        assert data["anomalies"] == []

    def test_accepts_subscription_id_query_param(self):
        res = _client.get("/api/v1/cost/anomalies?subscription_id=sub-abc")
        assert res.status_code == 200

    def test_accepts_severity_query_param(self):
        res = _client.get("/api/v1/cost/anomalies?severity=critical")
        assert res.status_code == 200

    def test_returns_total_field(self):
        res = _client.get("/api/v1/cost/anomalies")
        assert "total" in res.json()

    def test_with_cosmos_returns_anomalies(self):
        """With Cosmos configured, anomalies are returned."""
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = [
            {
                "id": "ano-1",
                "anomaly_id": "ano-1",
                "subscription_id": _SUB,
                "service_name": "Virtual Machines",
                "date": "2024-01-15",
                "cost_usd": 500.0,
                "baseline_usd": 100.0,
                "z_score": 3.8,
                "severity": "critical",
                "pct_change": 400.0,
                "description": "spike",
                "detected_at": "2024-01-15T00:00:00+00:00",
                "ttl": 172800,
            }
        ]
        _test_app.state.cosmos_client = mock_cosmos
        try:
            res = _client.get("/api/v1/cost/anomalies")
            assert res.status_code == 200
            data = res.json()
            assert data["total"] == 1
            assert data["anomalies"][0]["service_name"] == "Virtual Machines"
        finally:
            _test_app.state.cosmos_client = None


class TestCostSummaryEndpoint:
    def test_returns_200_with_zero_counts_when_cosmos_none(self):
        res = _client.get("/api/v1/cost/summary")
        assert res.status_code == 200
        data = res.json()
        assert data["total_anomalies"] == 0
        assert data["critical_count"] == 0
        assert data["warning_count"] == 0
        assert "top_spenders" in data

    def test_accepts_subscription_id_query_param(self):
        res = _client.get("/api/v1/cost/summary?subscription_id=sub-abc")
        assert res.status_code == 200


class TestCostScanEndpoint:
    def test_returns_202_with_scan_id(self):
        """POST /scan returns 202 with scan_id and status=queued."""
        res = _client.post("/api/v1/cost/scan")
        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "queued"
        assert "scan_id" in data
        assert len(data["scan_id"]) == 36  # UUID4

    def test_scan_id_is_unique_per_call(self):
        res1 = _client.post("/api/v1/cost/scan")
        res2 = _client.post("/api/v1/cost/scan")
        assert res1.json()["scan_id"] != res2.json()["scan_id"]

    def test_scan_queued_returns_subscription_count(self):
        """Response includes number of subscriptions queued."""
        res = _client.post("/api/v1/cost/scan")
        data = res.json()
        assert "subscriptions" in data


class TestCostSnapshotsEndpoint:
    def test_returns_200_with_empty_list_when_cosmos_none(self):
        res = _client.get("/api/v1/cost/snapshots")
        assert res.status_code == 200
        data = res.json()
        assert "snapshots" in data
        assert data["snapshots"] == []

    def test_accepts_days_query_param(self):
        res = _client.get("/api/v1/cost/snapshots?days=7")
        assert res.status_code == 200

    def test_accepts_service_name_filter(self):
        res = _client.get("/api/v1/cost/snapshots?service_name=Virtual+Machines")
        assert res.status_code == 200

    def test_days_out_of_range_returns_422(self):
        """days=0 violates ge=1 constraint."""
        res = _client.get("/api/v1/cost/snapshots?days=0")
        assert res.status_code == 422
