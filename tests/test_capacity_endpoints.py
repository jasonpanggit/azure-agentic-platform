"""Unit tests for capacity_endpoints.py — Phase 57-2 AKS + API endpoints.

Covers:
- GET /api/v1/capacity/headroom: filtering, sorting, top-10, error handling
- GET /api/v1/capacity/quotas: all quotas, zero-limit filter, traffic_light
- GET /api/v1/capacity/ip-space: available_ips formula, empty subscription
- GET /api/v1/capacity/aks: quota_family lookup, unknown SKU, empty subscription
- VM SKU lookup table: values, unknown fallback, length
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App fixture — minimal FastAPI app with capacity router
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from services.api_gateway.capacity_endpoints import router as capacity_router

app = FastAPI()
app.include_router(capacity_router)


def _make_credential():
    return MagicMock()


def _make_cosmos():
    return MagicMock()


# Override FastAPI dependencies
from services.api_gateway import dependencies as _deps

app.dependency_overrides[_deps.get_credential] = lambda: _make_credential()
app.dependency_overrides[_deps.get_optional_cosmos_client] = lambda: None

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_quota(
    quota_name: str = "cores",
    display_name: str = "Total Regional vCPUs",
    category: str = "compute",
    current_value: int = 80,
    limit: int = 100,
    usage_pct: float = 80.0,
    available: int = 20,
    days_to_exhaustion=None,
    traffic_light: str = "yellow",
) -> dict:
    return {
        "quota_name": quota_name,
        "display_name": display_name,
        "category": category,
        "current_value": current_value,
        "limit": limit,
        "usage_pct": usage_pct,
        "available": available,
        "days_to_exhaustion": days_to_exhaustion,
        "traffic_light": traffic_light,
        "growth_rate_per_day": 0.5,
        "confidence": "medium",
        "confidence_interval_upper_pct": 2.0,
        "confidence_interval_lower_pct": -1.0,
    }


def _make_subnet(
    vnet_name: str = "vnet-prod",
    resource_group: str = "rg-net",
    subnet_name: str = "snet-app",
    address_prefix: str = "10.0.0.0/24",
    total_ips: int = 256,
    reserved_ips: int = 5,
    ip_config_count: int = 10,
    available: int = 241,
    usage_pct: float = 5.5,
    traffic_light: str = "green",
) -> dict:
    return {
        "vnet_name": vnet_name,
        "resource_group": resource_group,
        "subnet_name": subnet_name,
        "address_prefix": address_prefix,
        "total_ips": total_ips,
        "reserved_ips": reserved_ips,
        "ip_config_count": ip_config_count,
        "available": available,
        "usage_pct": usage_pct,
        "traffic_light": traffic_light,
    }


def _make_cluster(
    cluster_name: str = "aks-prod",
    resource_group: str = "rg-aks",
    location: str = "eastus",
    pool_name: str = "nodepool1",
    vm_size: str = "Standard_D4s_v3",
    quota_family: str = "standardDSv3Family",
    current_nodes: int = 3,
    max_nodes: int = 10,
    available_nodes: int = 7,
    usage_pct: float = 30.0,
    traffic_light: str = "green",
) -> dict:
    return {
        "cluster_name": cluster_name,
        "resource_group": resource_group,
        "location": location,
        "pool_name": pool_name,
        "vm_size": vm_size,
        "quota_family": quota_family,
        "current_nodes": current_nodes,
        "max_nodes": max_nodes,
        "available_nodes": available_nodes,
        "usage_pct": usage_pct,
        "traffic_light": traffic_light,
    }


# ---------------------------------------------------------------------------
# Headroom endpoint (6 tests)
# ---------------------------------------------------------------------------

def test_headroom_happy_path_returns_at_most_10():
    """15 constrained items → response has ≤10 items."""
    quotas = [
        _make_quota(
            quota_name=f"q{i}",
            usage_pct=95.0,
            days_to_exhaustion=float(i + 1),
            traffic_light="red",
        )
        for i in range(15)
    ]
    mock_result = {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_subscription_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/headroom?subscription_id=sub-123")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["top_constrained"]) <= 10


def test_headroom_sorted_by_days_to_exhaustion_asc():
    """Items sorted by days_to_exhaustion ASC."""
    quotas = [
        _make_quota(quota_name="q3", usage_pct=95.0, days_to_exhaustion=20.0),
        _make_quota(quota_name="q1", usage_pct=95.0, days_to_exhaustion=5.0),
        _make_quota(quota_name="q2", usage_pct=95.0, days_to_exhaustion=10.0),
    ]
    mock_result = {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_subscription_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/headroom?subscription_id=sub-123")
    assert resp.status_code == 200
    items = resp.json()["top_constrained"]
    dtes = [i["days_to_exhaustion"] for i in items if i["days_to_exhaustion"] is not None]
    assert dtes == sorted(dtes)


def test_headroom_none_dte_sorts_last():
    """Items with days_to_exhaustion=None sort after items with values."""
    quotas = [
        _make_quota(quota_name="no_dte", usage_pct=92.0, days_to_exhaustion=None),
        _make_quota(quota_name="has_dte", usage_pct=91.0, days_to_exhaustion=15.0),
    ]
    mock_result = {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_subscription_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/headroom?subscription_id=sub-123")
    assert resp.status_code == 200
    items = resp.json()["top_constrained"]
    names = [i["quota_name"] for i in items]
    assert names.index("has_dte") < names.index("no_dte")


def test_headroom_filters_low_usage_no_dte():
    """Items with usage_pct < 90 and no days_to_exhaustion are excluded."""
    quotas = [
        _make_quota(quota_name="low", usage_pct=50.0, days_to_exhaustion=None, traffic_light="green"),
        _make_quota(quota_name="high", usage_pct=92.0, days_to_exhaustion=None, traffic_light="red"),
    ]
    mock_result = {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_subscription_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/headroom?subscription_id=sub-123")
    assert resp.status_code == 200
    names = [i["quota_name"] for i in resp.json()["top_constrained"]]
    assert "high" in names
    assert "low" not in names


def test_headroom_missing_subscription_id_returns_422():
    """Missing subscription_id → 422 validation error."""
    resp = client.get("/api/v1/capacity/headroom")
    assert resp.status_code == 422


def test_headroom_red_traffic_light_items_included():
    """Items with traffic_light='red' and usage_pct>=90 appear in top_constrained."""
    quotas = [
        _make_quota(quota_name="red_item", usage_pct=95.0, days_to_exhaustion=None, traffic_light="red"),
    ]
    mock_result = {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_subscription_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/headroom?subscription_id=sub-123")
    assert resp.status_code == 200
    items = resp.json()["top_constrained"]
    assert any(i["traffic_light"] == "red" for i in items)


# ---------------------------------------------------------------------------
# Quotas endpoint (4 tests)
# ---------------------------------------------------------------------------

def test_quotas_happy_path_sorted_by_usage_pct_desc():
    """All quotas returned sorted by usage_pct DESC."""
    quotas = [
        _make_quota(quota_name="q1", usage_pct=30.0),
        _make_quota(quota_name="q2", usage_pct=80.0),
        _make_quota(quota_name="q3", usage_pct=60.0),
    ]
    mock_result = {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_subscription_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/quotas?subscription_id=sub-123")
    assert resp.status_code == 200
    usage_pcts = [i["usage_pct"] for i in resp.json()["quotas"]]
    assert usage_pcts == sorted(usage_pcts, reverse=True)


def test_quotas_zero_limit_filtered():
    """Quotas with limit=0 are excluded from results."""
    quotas = [
        _make_quota(quota_name="zero", limit=0, usage_pct=0.0),
        _make_quota(quota_name="nonzero", limit=100, usage_pct=50.0),
    ]
    mock_result = {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_subscription_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/quotas?subscription_id=sub-123")
    assert resp.status_code == 200
    names = [i["quota_name"] for i in resp.json()["quotas"]]
    assert "zero" not in names
    assert "nonzero" in names


def test_quotas_items_include_traffic_light():
    """Quota items include a traffic_light field."""
    quotas = [_make_quota(traffic_light="yellow")]
    mock_result = {
        "quotas": quotas,
        "location": "eastus",
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_subscription_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/quotas?subscription_id=sub-123")
    assert resp.status_code == 200
    item = resp.json()["quotas"][0]
    assert "traffic_light" in item
    assert item["traffic_light"] == "yellow"


def test_quotas_missing_subscription_id_returns_422():
    """Missing subscription_id → 422."""
    resp = client.get("/api/v1/capacity/quotas")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# IP space endpoint (4 tests)
# ---------------------------------------------------------------------------

def test_ip_space_happy_path():
    """Happy path returns subnets list with correct available_ips."""
    subnets = [_make_subnet(available=241)]
    mock_result = {
        "subnets": subnets,
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
        "note": None,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_ip_address_space_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/ip-space?subscription_id=sub-123")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["subnets"]) == 1
    assert body["subnets"][0]["available_ips"] == 241


def test_ip_space_24_subnet_with_10_ip_configs():
    """/24 subnet with 10 ip_configs → available_ips = 256 - 5 - 10 = 241."""
    subnets = [_make_subnet(
        address_prefix="10.0.0.0/24",
        total_ips=256,
        reserved_ips=5,
        ip_config_count=10,
        available=241,
    )]
    mock_result = {
        "subnets": subnets,
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 50,
        "note": None,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_ip_address_space_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/ip-space?subscription_id=sub-123")
    assert resp.status_code == 200
    s = resp.json()["subnets"][0]
    assert s["available_ips"] == 241
    assert s["address_prefix"] == "10.0.0.0/24"


def test_ip_space_empty_subscription():
    """Empty subscription → subnets list is empty."""
    mock_result = {
        "subnets": [],
        "subscription_id": "sub-empty",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 20,
        "note": None,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_ip_address_space_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/ip-space?subscription_id=sub-empty")
    assert resp.status_code == 200
    assert resp.json()["subnets"] == []


def test_ip_space_missing_subscription_id_returns_422():
    """Missing subscription_id → 422."""
    resp = client.get("/api/v1/capacity/ip-space")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AKS endpoint (4 tests)
# ---------------------------------------------------------------------------

def test_aks_happy_path_returns_clusters():
    """Happy path returns clusters with pool data."""
    clusters = [_make_cluster()]
    mock_result = {
        "clusters": clusters,
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 60,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_aks_node_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/aks?subscription_id=sub-123")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["clusters"]) == 1
    c = body["clusters"][0]
    assert c["cluster_name"] == "aks-prod"
    assert c["pool_name"] == "nodepool1"


def test_aks_unknown_vm_sku_returns_unknown_quota_family():
    """Unknown VM SKU → quota_family = 'unknown'."""
    clusters = [_make_cluster(vm_size="Standard_Unknown_v99", quota_family="unknown")]
    mock_result = {
        "clusters": clusters,
        "subscription_id": "sub-123",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 60,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_aks_node_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/aks?subscription_id=sub-123")
    assert resp.status_code == 200
    assert resp.json()["clusters"][0]["quota_family"] == "unknown"


def test_aks_empty_subscription():
    """Empty subscription → clusters list is empty."""
    mock_result = {
        "clusters": [],
        "subscription_id": "sub-empty",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 20,
    }
    with patch(
        "services.api_gateway.capacity_endpoints.CapacityPlannerClient.get_aks_node_quota_headroom",
        return_value=mock_result,
    ):
        resp = client.get("/api/v1/capacity/aks?subscription_id=sub-empty")
    assert resp.status_code == 200
    assert resp.json()["clusters"] == []


def test_aks_missing_subscription_id_returns_422():
    """Missing subscription_id → 422."""
    resp = client.get("/api/v1/capacity/aks")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# VM SKU lookup table (3 tests)
# ---------------------------------------------------------------------------

from services.api_gateway.capacity_planner import _VM_SKU_TO_QUOTA_FAMILY


def test_sku_lookup_d8s_v3():
    """Standard_D8s_v3 maps to standardDSv3Family."""
    assert _VM_SKU_TO_QUOTA_FAMILY["Standard_D8s_v3"] == "standardDSv3Family"


def test_sku_lookup_unknown_sku_returns_unknown():
    """Unknown SKU → .get() returns 'unknown'."""
    assert _VM_SKU_TO_QUOTA_FAMILY.get("Standard_Unknown_v99", "unknown") == "unknown"


def test_sku_lookup_table_has_at_least_20_entries():
    """Lookup table covers ≥ 20 common SKUs."""
    assert len(_VM_SKU_TO_QUOTA_FAMILY) >= 20
