from __future__ import annotations
"""Tests for quota_usage_service.py — Phase 95."""
import os

import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.quota_usage_service import (
    _NAMESPACE,
    _compute_severity,
    _fetch_quota_for_location,
    _get_locations,
    get_quota_findings,
    get_quota_summary,
    persist_quota_findings,
    scan_quota_usage,
)


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_severity_critical():
    assert _compute_severity(90.0) == "critical"


@pytest.mark.unit
def test_severity_critical_above():
    assert _compute_severity(100.0) == "critical"


@pytest.mark.unit
def test_severity_high():
    assert _compute_severity(75.0) == "high"


@pytest.mark.unit
def test_severity_high_upper_boundary():
    assert _compute_severity(89.9) == "high"


@pytest.mark.unit
def test_severity_medium():
    assert _compute_severity(50.0) == "medium"


@pytest.mark.unit
def test_severity_medium_upper_boundary():
    assert _compute_severity(74.9) == "medium"


@pytest.mark.unit
def test_severity_low():
    assert _compute_severity(0.0) == "low"


@pytest.mark.unit
def test_severity_low_boundary():
    assert _compute_severity(49.9) == "low"


# ---------------------------------------------------------------------------
# Utilisation percentage calculation (via _fetch_quota_for_location)
# ---------------------------------------------------------------------------


def _make_arm_response(items: list) -> Dict[str, Any]:
    return {"value": items}


def _arm_item(name: str, current: int, limit: int) -> Dict[str, Any]:
    return {
        "name": {"value": name, "localizedValue": name},
        "currentValue": current,
        "limit": limit,
    }


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service.requests")
def test_utilisation_calculated_correctly(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_arm_response([
        _arm_item("cores", 80, 100),  # 80% → high
    ])
    mock_requests.get.return_value = mock_resp

    results = _fetch_quota_for_location("sub-1", "eastus", "fake-token")
    assert len(results) == 1
    assert results[0]["utilisation_pct"] == 80.0
    assert results[0]["severity"] == "high"
    assert results[0]["current_value"] == 80
    assert results[0]["limit"] == 100


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service.requests")
def test_zero_limit_does_not_divide(mock_requests):
    """Items with limit=0 should produce utilisation_pct=0 without ZeroDivisionError."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_arm_response([
        _arm_item("cores", 0, 0),
    ])
    mock_requests.get.return_value = mock_resp

    # utilisation = 0, filtered out (< 25%)
    results = _fetch_quota_for_location("sub-1", "eastus", "fake-token")
    assert results == []


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service.requests")
def test_below_25pct_filtered_out(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_arm_response([
        _arm_item("cores", 10, 100),  # 10% → filtered
    ])
    mock_requests.get.return_value = mock_resp

    results = _fetch_quota_for_location("sub-1", "eastus", "fake-token")
    assert results == []


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service.requests")
def test_exactly_25pct_included(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_arm_response([
        _arm_item("cores", 25, 100),  # exactly 25%
    ])
    mock_requests.get.return_value = mock_resp

    results = _fetch_quota_for_location("sub-1", "eastus", "fake-token")
    assert len(results) == 1
    assert results[0]["utilisation_pct"] == 25.0


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service.requests")
def test_stable_uuid_generation(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_arm_response([
        _arm_item("standardDSv3Family", 50, 100),
    ])
    mock_requests.get.return_value = mock_resp

    r1 = _fetch_quota_for_location("sub-1", "eastus", "fake-token")
    mock_requests.get.return_value = mock_resp
    r2 = _fetch_quota_for_location("sub-1", "eastus", "fake-token")

    assert r1[0]["id"] == r2[0]["id"]
    expected_id = str(uuid.uuid5(_NAMESPACE, "sub-1:eastus:standardDSv3Family"))
    assert r1[0]["id"] == expected_id


# ---------------------------------------------------------------------------
# API failure handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service.requests")
def test_arm_api_4xx_returns_empty(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"
    mock_requests.get.return_value = mock_resp

    results = _fetch_quota_for_location("sub-1", "eastus", "fake-token")
    assert results == []


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service.requests")
def test_arm_api_404_returns_empty(mock_requests):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    mock_requests.get.return_value = mock_resp

    results = _fetch_quota_for_location("sub-1", "eastus", "fake-token")
    assert results == []


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service.requests")
def test_request_exception_returns_empty(mock_requests):
    mock_requests.get.side_effect = ConnectionError("timeout")
    results = _fetch_quota_for_location("sub-1", "eastus", "fake-token")
    assert results == []


# ---------------------------------------------------------------------------
# Token failure
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("services.api_gateway.quota_usage_service._get_bearer_token", return_value=None)
def test_scan_without_token_returns_empty(mock_token):
    results = scan_quota_usage(["sub-1"])
    assert results == []


@pytest.mark.unit
def test_scan_with_empty_subscription_list():
    results = scan_quota_usage([])
    assert results == []


# ---------------------------------------------------------------------------
# Cosmos operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_persist_quota_findings_upserts_all():
    mock_cosmos = MagicMock()
    mock_container = MagicMock()
    mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

    findings = [
        {"id": "a", "subscription_id": "sub-1", "quota_name": "cores", "utilisation_pct": 80.0},
        {"id": "b", "subscription_id": "sub-1", "quota_name": "vms", "utilisation_pct": 60.0},
    ]
    persist_quota_findings(findings, cosmos_client=mock_cosmos)
    assert mock_container.upsert_item.call_count == 2


@pytest.mark.unit
def test_persist_quota_findings_no_cosmos_no_raise():
    # Should not raise
    persist_quota_findings([{"id": "a"}], cosmos_client=None)


@pytest.mark.unit
def test_persist_quota_findings_empty_list():
    mock_cosmos = MagicMock()
    persist_quota_findings([], cosmos_client=mock_cosmos)
    mock_cosmos.get_database_client.assert_not_called()


@pytest.mark.unit
def test_persist_quota_findings_cosmos_error():
    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.side_effect = RuntimeError("cosmos down")
    # Should not raise
    persist_quota_findings([{"id": "a"}], cosmos_client=mock_cosmos)


# ---------------------------------------------------------------------------
# Filters in get_quota_findings
# ---------------------------------------------------------------------------


def _make_mock_cosmos_with_items(items: list) -> MagicMock:
    mock_cosmos = MagicMock()
    mock_container = MagicMock()
    mock_container.query_items.return_value = items
    mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container
    return mock_cosmos


@pytest.mark.unit
def test_get_quota_findings_no_cosmos():
    assert get_quota_findings(cosmos_client=None) == []


@pytest.mark.unit
def test_get_quota_findings_returns_items():
    items = [{"id": "a", "quota_name": "cores", "utilisation_pct": 80.0}]
    mock_cosmos = _make_mock_cosmos_with_items(items)
    result = get_quota_findings(cosmos_client=mock_cosmos)
    assert len(result) == 1
    assert result[0]["id"] == "a"


@pytest.mark.unit
def test_get_quota_findings_strips_cosmos_internals():
    items = [{"id": "a", "_rid": "xxx", "_ts": 123, "quota_name": "cores"}]
    mock_cosmos = _make_mock_cosmos_with_items(items)
    result = get_quota_findings(cosmos_client=mock_cosmos)
    assert "_rid" not in result[0]
    assert "_ts" not in result[0]


@pytest.mark.unit
def test_get_quota_findings_cosmos_error_returns_empty():
    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.side_effect = RuntimeError("error")
    result = get_quota_findings(cosmos_client=mock_cosmos)
    assert result == []


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_quota_summary_empty():
    mock_cosmos = _make_mock_cosmos_with_items([])
    summary = get_quota_summary(cosmos_client=mock_cosmos)
    assert summary["total_count"] == 0
    assert summary["most_constrained"] == []


@pytest.mark.unit
def test_get_quota_summary_counts_correctly():
    items = [
        {"id": "a", "severity": "critical", "utilisation_pct": 95.0, "quota_name": "A", "location": "eastus", "subscription_id": "sub-1", "current_value": 95, "limit": 100},
        {"id": "b", "severity": "critical", "utilisation_pct": 91.0, "quota_name": "B", "location": "eastus", "subscription_id": "sub-1", "current_value": 91, "limit": 100},
        {"id": "c", "severity": "high", "utilisation_pct": 78.0, "quota_name": "C", "location": "westus2", "subscription_id": "sub-1", "current_value": 78, "limit": 100},
        {"id": "d", "severity": "medium", "utilisation_pct": 55.0, "quota_name": "D", "location": "westus2", "subscription_id": "sub-1", "current_value": 55, "limit": 100},
    ]
    mock_cosmos = _make_mock_cosmos_with_items(items)
    summary = get_quota_summary(cosmos_client=mock_cosmos)
    assert summary["critical_count"] == 2
    assert summary["high_count"] == 1
    assert summary["medium_count"] == 1
    assert summary["total_count"] == 4
    assert len(summary["most_constrained"]) <= 5


@pytest.mark.unit
def test_get_quota_summary_no_cosmos():
    summary = get_quota_summary(cosmos_client=None)
    assert summary["total_count"] == 0


# ---------------------------------------------------------------------------
# Locations config
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_locations_defaults():
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("QUOTA_SCAN_LOCATIONS", None)
        locs = _get_locations()
        assert "eastus" in locs
        assert len(locs) == 5


@pytest.mark.unit
def test_get_locations_from_env():
    with patch.dict("os.environ", {"QUOTA_SCAN_LOCATIONS": "eastus,westus2"}):
        locs = _get_locations()
        assert locs == ["eastus", "westus2"]
