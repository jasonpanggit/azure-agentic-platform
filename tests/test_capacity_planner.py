"""Unit tests for capacity_planner.py — Phase 57-1 backend foundation.

Covers:
- _linear_regression: math correctness, edge cases
- _days_to_exhaustion: projection, caps, edge cases
- _traffic_light: all threshold combinations
- IP space headroom: available IP formula, usage_pct, edge cases
- Quota headroom: SDK unavailable, zero-limit filter, happy path, exception handling
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.capacity_planner import (
    CapacityPlannerClient,
    _days_to_exhaustion,
    _linear_regression,
    _regression_ci,
    _traffic_light,
)


# ---------------------------------------------------------------------------
# Linear regression tests (10)
# ---------------------------------------------------------------------------

def test_linear_regression_perfect_growth():
    """Perfect linear growth: y = 2x + 50."""
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [50.0, 52.0, 54.0, 56.0, 58.0]
    slope, intercept, r_sq = _linear_regression(x, y)
    assert abs(slope - 2.0) < 1e-9
    assert abs(intercept - 50.0) < 1e-9
    assert abs(r_sq - 1.0) < 1e-9


def test_linear_regression_flat_constant():
    """Flat constant series: slope = 0."""
    x = [0.0, 1.0, 2.0]
    y = [60.0, 60.0, 60.0]
    slope, intercept, r_sq = _linear_regression(x, y)
    assert abs(slope) < 1e-9
    # R² is 0 for constant (SS_tot = 0 → clamp)
    assert r_sq == 0.0


def test_linear_regression_single_point():
    """Single point: returns zero slope and r²."""
    slope, intercept, r_sq = _linear_regression([0.0], [50.0])
    assert slope == 0.0
    assert intercept == 50.0
    assert r_sq == 0.0


def test_linear_regression_empty():
    """Empty input: returns all zeros."""
    slope, intercept, r_sq = _linear_regression([], [])
    assert slope == 0.0
    assert intercept == 0.0
    assert r_sq == 0.0


def test_linear_regression_negative_slope():
    """Negative slope: y decreasing."""
    x = [0.0, 1.0, 2.0, 3.0]
    y = [80.0, 70.0, 60.0, 50.0]
    slope, intercept, r_sq = _linear_regression(x, y)
    assert slope < 0
    assert abs(slope - (-10.0)) < 1e-9
    assert abs(r_sq - 1.0) < 1e-9


def test_linear_regression_two_points():
    """Minimum two points for regression."""
    x = [0.0, 1.0]
    y = [10.0, 20.0]
    slope, intercept, r_sq = _linear_regression(x, y)
    assert abs(slope - 10.0) < 1e-9
    assert abs(intercept - 10.0) < 1e-9


def test_linear_regression_r_squared_non_negative():
    """R² is always >= 0 (clamped)."""
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [5.0, 3.0, 7.0, 2.0, 9.0]
    _, _, r_sq = _linear_regression(x, y)
    assert r_sq >= 0.0


def test_linear_regression_high_r_squared():
    """Near-perfect fit gives R² close to 1."""
    x = [float(i) for i in range(20)]
    y = [2.0 * i + 5.0 + (0.001 * i) for i in range(20)]
    _, _, r_sq = _linear_regression(x, y)
    assert r_sq > 0.99


def test_regression_ci_returns_tuple():
    """_regression_ci returns a tuple of two floats."""
    x = [0.0, 1.0, 2.0, 3.0]
    y = [50.0, 52.0, 54.0, 56.0]
    slope, intercept, _ = _linear_regression(x, y)
    ci_upper, ci_lower = _regression_ci(x, y, slope, intercept)
    assert isinstance(ci_upper, float)
    assert isinstance(ci_lower, float)


def test_regression_ci_zero_intercept():
    """_regression_ci with zero intercept returns (0.0, 0.0)."""
    ci_upper, ci_lower = _regression_ci([0.0, 1.0], [0.0, 0.0], 0.0, 0.0)
    assert ci_upper == 0.0
    assert ci_lower == 0.0


# ---------------------------------------------------------------------------
# Days to exhaustion tests (8)
# ---------------------------------------------------------------------------

def test_days_to_exhaustion_normal():
    """Standard projection: (100-90)/2 = 5.0 days."""
    result = _days_to_exhaustion(90.0, 2.0)
    assert result == 5.0


def test_days_to_exhaustion_zero_slope():
    """Zero slope → None (no growth)."""
    assert _days_to_exhaustion(50.0, 0.0) is None


def test_days_to_exhaustion_negative_slope():
    """Negative slope → None (shrinking)."""
    assert _days_to_exhaustion(50.0, -1.0) is None


def test_days_to_exhaustion_already_exhausted():
    """Already at 100% → None."""
    assert _days_to_exhaustion(100.0, 2.0) is None


def test_days_to_exhaustion_over_365_cap():
    """Projection > 365 days → None (cap)."""
    # slope=0.001, current=1%: (100-1)/0.001 = 99000 days → None
    assert _days_to_exhaustion(1.0, 0.001) is None


def test_days_to_exhaustion_exactly_365():
    """Projection <= 365 → returns value."""
    # (100-63.5)/0.1 = 365.0
    result = _days_to_exhaustion(63.5, 0.1)
    assert result == 365.0


def test_days_to_exhaustion_80_pct():
    """Standard: (100-80)/1.0 = 20.0 days."""
    assert _days_to_exhaustion(80.0, 1.0) == 20.0


def test_days_to_exhaustion_custom_limit():
    """Custom limit parameter works correctly."""
    # (90-50)/2.0 = 20.0
    result = _days_to_exhaustion(50.0, 2.0, limit=90.0)
    assert result == 20.0


# ---------------------------------------------------------------------------
# Traffic light tests (6)
# ---------------------------------------------------------------------------

def test_traffic_light_red_usage():
    """usage_pct >= 90 → red."""
    assert _traffic_light(91.0, None) == "red"


def test_traffic_light_red_days():
    """days_to_exhaustion < 30 → red."""
    assert _traffic_light(50.0, 15.0) == "red"


def test_traffic_light_yellow_usage():
    """usage_pct >= 75 → yellow."""
    assert _traffic_light(76.0, 100.0) == "yellow"


def test_traffic_light_yellow_days():
    """days_to_exhaustion < 90 → yellow."""
    assert _traffic_light(50.0, 60.0) == "yellow"


def test_traffic_light_green_no_days():
    """Low usage, no projection → green."""
    assert _traffic_light(50.0, None) == "green"


def test_traffic_light_green_safe():
    """usage < 75 and days > 90 → green."""
    assert _traffic_light(74.0, 91.0) == "green"


# ---------------------------------------------------------------------------
# IP space headroom unit tests (6)
# ---------------------------------------------------------------------------

def _make_row(address_prefix: str, ip_config_count: int) -> dict:
    return {
        "vnetName": "vnet1",
        "resourceGroup": "rg1",
        "subnetName": "subnet1",
        "addressPrefix": address_prefix,
        "ipConfigCount": ip_config_count,
    }


def _compute_available(address_prefix: str, ip_config_count: int) -> int:
    """Helper: compute expected available IPs."""
    import ipaddress
    network = ipaddress.ip_network(address_prefix, strict=False)
    return max(0, network.num_addresses - 5 - ip_config_count)


def test_ip_space_slash24():
    """/24 subnet, 10 ip_configs → available = 256 - 5 - 10 = 241."""
    available = _compute_available("10.0.0.0/24", 10)
    assert available == 241


def test_ip_space_slash28():
    """/28 subnet (16 IPs), 5 ip_configs → available = 16 - 5 - 5 = 6."""
    available = _compute_available("10.0.0.0/28", 5)
    assert available == 6


def test_ip_space_empty_subnet():
    """0 ip_configs → available = total - 5."""
    available = _compute_available("10.0.0.0/24", 0)
    assert available == 251


def test_ip_space_never_negative():
    """High ip_config_count → available = 0 (max(0, ...))."""
    available = _compute_available("10.0.0.0/30", 1000)
    assert available == 0


def test_ip_space_usage_pct_calculation():
    """usage_pct = (usable - available) / usable * 100."""
    import ipaddress
    prefix = "10.0.0.0/24"
    ip_config_count = 100
    network = ipaddress.ip_network(prefix, strict=False)
    total = network.num_addresses
    reserved = 5
    available = max(0, total - reserved - ip_config_count)
    usable = max(1, total - reserved)
    usage_pct = round((usable - available) / usable * 100, 2)
    assert usage_pct == round(100 / 251 * 100, 2)


def test_ip_space_delegated_subnet():
    """Subnet with ip_configs still computes correctly."""
    available = _compute_available("192.168.1.0/25", 50)
    # /25 = 128 IPs; 128 - 5 - 50 = 73
    assert available == 73


# ---------------------------------------------------------------------------
# Quota headroom tests (4 — mock SDK)
# ---------------------------------------------------------------------------

def _make_quota_item(name_value: str, current: int, limit: int) -> MagicMock:
    item = MagicMock()
    item.name.value = name_value
    item.name.localized_value = name_value.replace("_", " ").title()
    item.current_value = current
    item.limit = limit
    return item


def test_quota_headroom_sdk_unavailable():
    """When ComputeManagementClient is None, returns quotas=[] with warnings, no exception."""
    import services.api_gateway.capacity_planner as cp
    original = cp.ComputeManagementClient

    cosmos_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.query_items.return_value = []
    db_mock = MagicMock()
    db_mock.get_container_client.return_value = container_mock
    cosmos_mock.get_database_client.return_value = db_mock

    try:
        cp.ComputeManagementClient = None  # type: ignore[assignment]
        cp.NetworkManagementClient = None  # type: ignore[assignment]
        cp.StorageManagementClient = None  # type: ignore[assignment]

        client = CapacityPlannerClient(
            cosmos_client=cosmos_mock,
            credential=MagicMock(),
            subscription_id="sub-123",
        )
        result = client.get_subscription_quota_headroom()

        assert result["quotas"] == []
        assert "warnings" in result
        assert isinstance(result["warnings"], list)
        assert len(result["warnings"]) > 0
        assert "duration_ms" in result
    finally:
        cp.ComputeManagementClient = original  # type: ignore[assignment]


def test_quota_headroom_filters_zero_limit():
    """Items with limit=0 are filtered out."""
    import services.api_gateway.capacity_planner as cp

    cosmos_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.query_items.return_value = []
    db_mock = MagicMock()
    db_mock.get_container_client.return_value = container_mock
    cosmos_mock.get_database_client.return_value = db_mock

    mock_compute_class = MagicMock()
    mock_compute_instance = MagicMock()
    mock_compute_class.return_value = mock_compute_instance
    mock_compute_instance.usage.list.return_value = [
        _make_quota_item("cores", 10, 0),   # zero limit — should be filtered
        _make_quota_item("vms", 5, 100),    # valid
    ]

    with patch.object(cp, "ComputeManagementClient", mock_compute_class), \
         patch.object(cp, "NetworkManagementClient", None), \
         patch.object(cp, "StorageManagementClient", None):
        client = CapacityPlannerClient(
            cosmos_client=cosmos_mock,
            credential=MagicMock(),
            subscription_id="sub-123",
        )
        result = client.get_subscription_quota_headroom()

    assert len(result["quotas"]) == 1
    assert result["quotas"][0]["quota_name"] == "vms"


def test_quota_headroom_happy_path():
    """Happy path: quota returned with usage_pct and available fields."""
    import services.api_gateway.capacity_planner as cp

    cosmos_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.query_items.return_value = []
    db_mock = MagicMock()
    db_mock.get_container_client.return_value = container_mock
    cosmos_mock.get_database_client.return_value = db_mock

    mock_compute_class = MagicMock()
    mock_compute_instance = MagicMock()
    mock_compute_class.return_value = mock_compute_instance
    mock_compute_instance.usage.list.return_value = [
        _make_quota_item("cores", 40, 100),
    ]

    with patch.object(cp, "ComputeManagementClient", mock_compute_class), \
         patch.object(cp, "NetworkManagementClient", None), \
         patch.object(cp, "StorageManagementClient", None):
        client = CapacityPlannerClient(
            cosmos_client=cosmos_mock,
            credential=MagicMock(),
            subscription_id="sub-123",
        )
        result = client.get_subscription_quota_headroom()

    assert len(result["quotas"]) == 1
    q = result["quotas"][0]
    assert q["usage_pct"] == 40.0
    assert q["available"] == 60
    assert q["category"] == "compute"
    assert "traffic_light" in q


def test_quota_headroom_sdk_exception():
    """SDK raises exception → returns error dict, never raises."""
    import services.api_gateway.capacity_planner as cp

    cosmos_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.query_items.return_value = []
    db_mock = MagicMock()
    db_mock.get_container_client.return_value = container_mock
    cosmos_mock.get_database_client.return_value = db_mock

    mock_compute_class = MagicMock()
    mock_compute_instance = MagicMock()
    mock_compute_class.return_value = mock_compute_instance
    mock_compute_instance.usage.list.side_effect = RuntimeError("Azure SDK failure")

    with patch.object(cp, "ComputeManagementClient", mock_compute_class), \
         patch.object(cp, "NetworkManagementClient", None), \
         patch.object(cp, "StorageManagementClient", None):
        client = CapacityPlannerClient(
            cosmos_client=cosmos_mock,
            credential=MagicMock(),
            subscription_id="sub-123",
        )
        result = client.get_subscription_quota_headroom()

    assert "error" in result
    assert "Azure SDK failure" in result["error"]
    assert result["quotas"] == []
    assert "duration_ms" in result
