from __future__ import annotations
"""Tests for quota endpoints (Phase 67)."""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal FastAPI app fixture that includes only the quota router
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """TestClient with quota router mounted and dependencies overridden."""
    from fastapi import FastAPI
    from services.api_gateway.quota_endpoints import router
    from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

    app = FastAPI()
    app.include_router(router)

    mock_credential = MagicMock(name="DefaultAzureCredential")
    mock_cosmos = None

    app.dependency_overrides[get_credential] = lambda: mock_credential
    app.dependency_overrides[get_optional_cosmos_client] = lambda: mock_cosmos

    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers — build mock CapacityPlannerClient responses
# ---------------------------------------------------------------------------

def _make_quota(
    name: str = "cores",
    display_name: str = "Total Regional vCPUs",
    category: str = "compute",
    current_value: int = 80,
    limit: int = 100,
) -> Dict[str, Any]:
    usage_pct = round(current_value / limit * 100, 2)
    available = limit - current_value
    if usage_pct >= 90:
        traffic_light = "red"
    elif usage_pct >= 75:
        traffic_light = "yellow"
    else:
        traffic_light = "green"
    return {
        "quota_name": name,
        "display_name": display_name,
        "category": category,
        "current_value": current_value,
        "limit": limit,
        "usage_pct": usage_pct,
        "available": available,
        "traffic_light": traffic_light,
        "days_to_exhaustion": None,
        "growth_rate_per_day": 0.0,
        "confidence": "low",
        "confidence_interval_upper_pct": 0.0,
        "confidence_interval_lower_pct": 0.0,
    }


def _mock_planner_result(quotas: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-test",
        "generated_at": "2026-04-16T00:00:00+00:00",
        "duration_ms": 42.0,
    }


# ---------------------------------------------------------------------------
# 1. test_quota_list_returns_all_quotas
# ---------------------------------------------------------------------------

def test_quota_list_returns_all_quotas(client: TestClient):
    """GET /api/v1/quotas returns all quotas sorted by usage_pct DESC."""
    quotas = [
        _make_quota("cores", current_value=80, limit=100),       # 80% — yellow
        _make_quota("standardDSv3Family", current_value=10, limit=200),  # 5% — green
        _make_quota("publicIPAddresses", category="network", current_value=95, limit=100),  # 95% — red
    ]

    with patch(
        "services.api_gateway.quota_endpoints.CapacityPlannerClient"
    ) as MockPlanner:
        MockPlanner.return_value.get_subscription_quota_headroom.return_value = (
            _mock_planner_result(quotas)
        )
        response = client.get("/api/v1/quotas?subscription_id=sub-test&location=eastus")

    assert response.status_code == 200
    data = response.json()
    assert "quotas" in data
    assert len(data["quotas"]) == 3
    # Should be sorted by usage_pct DESC
    pcts = [q["usage_pct"] for q in data["quotas"]]
    assert pcts == sorted(pcts, reverse=True)
    assert "pagination" in data
    assert data["pagination"]["total"] == 3


# ---------------------------------------------------------------------------
# 2. test_quota_summary_structure
# ---------------------------------------------------------------------------

def test_quota_summary_structure(client: TestClient):
    """GET /api/v1/quotas/summary returns correct counts and top_constrained."""
    quotas = [
        _make_quota("q1", current_value=95, limit=100),   # red
        _make_quota("q2", current_value=80, limit=100),   # yellow
        _make_quota("q3", current_value=80, limit=100),   # yellow
        _make_quota("q4", current_value=10, limit=100),   # green
    ]

    with patch(
        "services.api_gateway.quota_endpoints.CapacityPlannerClient"
    ) as MockPlanner:
        MockPlanner.return_value.get_subscription_quota_headroom.return_value = (
            _mock_planner_result(quotas)
        )
        response = client.get("/api/v1/quotas/summary?subscription_id=sub-test&location=eastus")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4
    assert data["critical"] == 1
    assert data["warning"] == 2
    assert data["healthy"] == 1
    assert "top_constrained" in data
    assert len(data["top_constrained"]) <= 10
    assert "categories" in data
    assert "compute" in data["categories"]


# ---------------------------------------------------------------------------
# 3. test_quota_filter_by_resource_type
# ---------------------------------------------------------------------------

def test_quota_filter_by_resource_type(client: TestClient):
    """GET /api/v1/quotas?resource_type=network returns only network quotas."""
    quotas = [
        _make_quota("cores", category="compute", current_value=50, limit=100),
        _make_quota("virtualNetworks", category="network", current_value=5, limit=50),
        _make_quota("publicIPAddresses", category="network", current_value=40, limit=50),
        _make_quota("storageAccounts", category="storage", current_value=10, limit=250),
    ]

    with patch(
        "services.api_gateway.quota_endpoints.CapacityPlannerClient"
    ) as MockPlanner:
        MockPlanner.return_value.get_subscription_quota_headroom.return_value = (
            _mock_planner_result(quotas)
        )
        response = client.get(
            "/api/v1/quotas?subscription_id=sub-test&location=eastus&resource_type=network"
        )

    assert response.status_code == 200
    data = response.json()
    assert all(q["category"] == "network" for q in data["quotas"])
    assert data["pagination"]["total"] == 2


# ---------------------------------------------------------------------------
# 4. test_quota_request_increase_endpoint
# ---------------------------------------------------------------------------

def test_quota_request_increase_endpoint(client: TestClient):
    """POST /api/v1/quotas/request-increase returns a request_id and status."""
    payload = {
        "subscription_id": "sub-test",
        "location": "eastus",
        "quota_name": "cores",
        "resource_type": "compute",
        "current_limit": 100,
        "requested_limit": 200,
        "justification": "Expanding workload capacity for new project deployment.",
    }

    # azure-mgmt-support not available in test env — simulated path
    response = client.post("/api/v1/quotas/request-increase", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "request_id" in data
    assert data["request_id"] is not None
    assert "status" in data
    assert data["quota_name"] == "cores"
    assert data["current_limit"] == 100
    assert data["requested_limit"] == 200


# ---------------------------------------------------------------------------
# 5. test_quota_pagination
# ---------------------------------------------------------------------------

def test_quota_pagination(client: TestClient):
    """GET /api/v1/quotas?page=2&page_size=2 returns correct page slice."""
    quotas = [
        _make_quota(f"quota_{i}", current_value=i * 10, limit=100)
        for i in range(1, 6)
    ]

    with patch(
        "services.api_gateway.quota_endpoints.CapacityPlannerClient"
    ) as MockPlanner:
        MockPlanner.return_value.get_subscription_quota_headroom.return_value = (
            _mock_planner_result(quotas)
        )
        response = client.get(
            "/api/v1/quotas?subscription_id=sub-test&location=eastus&page=2&page_size=2"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["page"] == 2
    assert data["pagination"]["page_size"] == 2
    assert data["pagination"]["total"] == 5
    assert data["pagination"]["total_pages"] == 3
    assert len(data["quotas"]) == 2


# ---------------------------------------------------------------------------
# 6. test_quota_request_increase_validation_error
# ---------------------------------------------------------------------------

def test_quota_request_increase_validation_error(client: TestClient):
    """POST /api/v1/quotas/request-increase returns 400 when requested_limit <= current_limit."""
    payload = {
        "subscription_id": "sub-test",
        "location": "eastus",
        "quota_name": "cores",
        "resource_type": "compute",
        "current_limit": 200,
        "requested_limit": 100,  # less than current — invalid
        "justification": "This should fail validation immediately.",
    }

    response = client.post("/api/v1/quotas/request-increase", json=payload)

    assert response.status_code == 400
    data = response.json()
    assert "error" in data


# ---------------------------------------------------------------------------
# 7. test_quota_list_name_search
# ---------------------------------------------------------------------------

def test_quota_list_name_search(client: TestClient):
    """GET /api/v1/quotas?search=cores returns only quotas matching 'cores'."""
    quotas = [
        _make_quota("cores", display_name="Total Regional vCPUs", current_value=50, limit=100),
        _make_quota("standardDSv3Family", display_name="Standard DSv3 Family vCPUs",
                    current_value=10, limit=100),
        _make_quota("publicIPAddresses", display_name="Public IP Addresses",
                    category="network", current_value=5, limit=50),
    ]

    with patch(
        "services.api_gateway.quota_endpoints.CapacityPlannerClient"
    ) as MockPlanner:
        MockPlanner.return_value.get_subscription_quota_headroom.return_value = (
            _mock_planner_result(quotas)
        )
        response = client.get(
            "/api/v1/quotas?subscription_id=sub-test&location=eastus&search=cores"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == 1
    assert "cores" in data["quotas"][0]["quota_name"].lower() or \
           "cores" in data["quotas"][0]["display_name"].lower()
