from __future__ import annotations
"""Tests for budget_alert_service.py — Phase 96."""

import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.budget_alert_service import (
    _NAMESPACE,
    _classify_status,
    _fetch_budgets_for_subscription,
    _no_budget_record,
    get_budget_findings,
    get_budget_summary,
    persist_budget_findings,
    scan_budget_status,
)


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_status_no_budget_when_amount_zero():
    assert _classify_status(0.0, 0.0) == "no_budget"


@pytest.mark.unit
def test_status_exceeded_at_100():
    assert _classify_status(100.0, 1000.0) == "exceeded"


@pytest.mark.unit
def test_status_exceeded_above_100():
    assert _classify_status(115.0, 1000.0) == "exceeded"


@pytest.mark.unit
def test_status_warning_at_80():
    assert _classify_status(80.0, 1000.0) == "warning"


@pytest.mark.unit
def test_status_warning_upper_boundary():
    assert _classify_status(99.9, 1000.0) == "warning"


@pytest.mark.unit
def test_status_on_track_below_80():
    assert _classify_status(50.0, 1000.0) == "on_track"


@pytest.mark.unit
def test_status_on_track_at_zero():
    assert _classify_status(0.0, 1000.0) == "on_track"


# ---------------------------------------------------------------------------
# Spend percentage calculation
# ---------------------------------------------------------------------------


def _make_budget_api_response(items: list) -> Dict[str, Any]:
    return {"value": items}


def _budget_item(name: str, amount: float, current_spend: float, forecast: float = 0.0) -> Dict[str, Any]:
    return {
        "id": f"/subscriptions/sub-1/providers/Microsoft.Consumption/budgets/{name}",
        "name": name,
        "properties": {
            "amount": amount,
            "currentSpend": {"amount": current_spend, "unit": "USD"},
            "forecastSpend": {"amount": forecast, "unit": "USD"} if forecast else {},
            "timePeriod": {
                "startDate": "2026-01-01",
                "endDate": "2026-12-31",
            },
        },
    }


@pytest.mark.unit
@patch("services.api_gateway.budget_alert_service.requests")
def test_spend_pct_calculated_correctly(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_budget_api_response([
        _budget_item("MonthlyBudget", 1000.0, 800.0, 900.0),
    ])
    mock_requests.get.return_value = mock_resp

    results = _fetch_budgets_for_subscription("sub-1", "fake-token")
    assert len(results) == 1
    assert results[0]["spend_pct"] == 80.0
    assert results[0]["status"] == "warning"
    assert results[0]["budget_amount"] == 1000.0
    assert results[0]["current_spend"] == 800.0
    assert results[0]["forecast_spend"] == 900.0


@pytest.mark.unit
@patch("services.api_gateway.budget_alert_service.requests")
def test_exceeded_status_when_over_budget(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_budget_api_response([
        _budget_item("MonthlyBudget", 1000.0, 1050.0),
    ])
    mock_requests.get.return_value = mock_resp

    results = _fetch_budgets_for_subscription("sub-1", "fake-token")
    assert results[0]["status"] == "exceeded"
    assert results[0]["spend_pct"] == 105.0


@pytest.mark.unit
@patch("services.api_gateway.budget_alert_service.requests")
def test_on_track_status(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_budget_api_response([
        _budget_item("MonthlyBudget", 1000.0, 300.0),
    ])
    mock_requests.get.return_value = mock_resp

    results = _fetch_budgets_for_subscription("sub-1", "fake-token")
    assert results[0]["status"] == "on_track"
    assert results[0]["spend_pct"] == 30.0


# ---------------------------------------------------------------------------
# No-budget case
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("services.api_gateway.budget_alert_service.requests")
def test_empty_budgets_returns_no_budget_record(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"value": []}
    mock_requests.get.return_value = mock_resp

    results = _fetch_budgets_for_subscription("sub-1", "fake-token")
    assert len(results) == 1
    assert results[0]["status"] == "no_budget"
    assert results[0]["budget_name"] == "NO_BUDGET"


@pytest.mark.unit
@patch("services.api_gateway.budget_alert_service.requests")
def test_404_returns_no_budget_record(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    mock_requests.get.return_value = mock_resp

    results = _fetch_budgets_for_subscription("sub-1", "fake-token")
    assert len(results) == 1
    assert results[0]["status"] == "no_budget"


@pytest.mark.unit
def test_no_budget_record_stable_id():
    r1 = _no_budget_record("sub-1", "2026-04-17T00:00:00")
    r2 = _no_budget_record("sub-1", "2026-04-17T00:00:00")
    assert r1["id"] == r2["id"]
    expected_id = str(uuid.uuid5(_NAMESPACE, "sub-1:no-budget"))
    assert r1["id"] == expected_id


# ---------------------------------------------------------------------------
# API failure handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("services.api_gateway.budget_alert_service.requests")
def test_arm_api_5xx_returns_empty(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 500
    mock_resp.text = "Server Error"
    mock_requests.get.return_value = mock_resp

    results = _fetch_budgets_for_subscription("sub-1", "fake-token")
    assert results == []


@pytest.mark.unit
@patch("services.api_gateway.budget_alert_service.requests")
def test_request_exception_returns_empty(mock_requests):
    mock_requests.get.side_effect = ConnectionError("timeout")
    results = _fetch_budgets_for_subscription("sub-1", "fake-token")
    assert results == []


# ---------------------------------------------------------------------------
# Token failure
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("services.api_gateway.budget_alert_service._get_bearer_token", return_value=None)
def test_scan_without_token_returns_empty(mock_token):
    results = scan_budget_status(["sub-1"])
    assert results == []


@pytest.mark.unit
def test_scan_with_empty_subscription_list():
    results = scan_budget_status([])
    assert results == []


# ---------------------------------------------------------------------------
# Cosmos operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_persist_budget_findings_upserts_all():
    mock_cosmos = MagicMock()
    mock_container = MagicMock()
    mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

    findings = [
        {"id": "a", "subscription_id": "sub-1", "status": "warning"},
        {"id": "b", "subscription_id": "sub-2", "status": "no_budget"},
    ]
    persist_budget_findings(findings, cosmos_client=mock_cosmos)
    assert mock_container.upsert_item.call_count == 2


@pytest.mark.unit
def test_persist_budget_findings_no_cosmos_no_raise():
    persist_budget_findings([{"id": "a"}], cosmos_client=None)


@pytest.mark.unit
def test_persist_budget_findings_empty_list():
    mock_cosmos = MagicMock()
    persist_budget_findings([], cosmos_client=mock_cosmos)
    mock_cosmos.get_database_client.assert_not_called()


@pytest.mark.unit
def test_persist_budget_findings_cosmos_error():
    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.side_effect = RuntimeError("cosmos down")
    persist_budget_findings([{"id": "a"}], cosmos_client=mock_cosmos)


# ---------------------------------------------------------------------------
# Filters in get_budget_findings
# ---------------------------------------------------------------------------


def _make_mock_cosmos_with_items(items: list) -> MagicMock:
    mock_cosmos = MagicMock()
    mock_container = MagicMock()
    mock_container.query_items.return_value = items
    mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container
    return mock_cosmos


@pytest.mark.unit
def test_get_budget_findings_no_cosmos():
    assert get_budget_findings(cosmos_client=None) == []


@pytest.mark.unit
def test_get_budget_findings_returns_items():
    items = [{"id": "a", "status": "warning", "budget_name": "Dev"}]
    mock_cosmos = _make_mock_cosmos_with_items(items)
    result = get_budget_findings(cosmos_client=mock_cosmos)
    assert len(result) == 1


@pytest.mark.unit
def test_get_budget_findings_strips_cosmos_internals():
    items = [{"id": "a", "_rid": "xxx", "_ts": 123, "status": "on_track"}]
    mock_cosmos = _make_mock_cosmos_with_items(items)
    result = get_budget_findings(cosmos_client=mock_cosmos)
    assert "_rid" not in result[0]


@pytest.mark.unit
def test_get_budget_findings_cosmos_error_returns_empty():
    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.side_effect = RuntimeError("error")
    result = get_budget_findings(cosmos_client=mock_cosmos)
    assert result == []


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_budget_summary_empty():
    mock_cosmos = _make_mock_cosmos_with_items([])
    summary = get_budget_summary(cosmos_client=mock_cosmos)
    assert summary["total_budgets"] == 0
    assert summary["exceeded_count"] == 0
    assert summary["no_budget_count"] == 0


@pytest.mark.unit
def test_get_budget_summary_counts_correctly():
    items = [
        {"id": "a", "status": "exceeded", "spend_pct": 105.0},
        {"id": "b", "status": "warning", "spend_pct": 85.0},
        {"id": "c", "status": "on_track", "spend_pct": 40.0},
        {"id": "d", "status": "no_budget", "spend_pct": 0.0},
        {"id": "e", "status": "no_budget", "spend_pct": 0.0},
    ]
    mock_cosmos = _make_mock_cosmos_with_items(items)
    summary = get_budget_summary(cosmos_client=mock_cosmos)
    assert summary["total_budgets"] == 5
    assert summary["exceeded_count"] == 1
    assert summary["warning_count"] == 1
    assert summary["on_track_count"] == 1
    assert summary["no_budget_count"] == 2


@pytest.mark.unit
def test_get_budget_summary_no_cosmos():
    summary = get_budget_summary(cosmos_client=None)
    assert summary["total_budgets"] == 0
