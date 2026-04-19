"""Tests for database_health_endpoints — Phase 105."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_databases():
    return [
        {
            "resource_id": "/subscriptions/sub1/.../cosmos1",
            "name": "cosmos1",
            "db_type": "cosmos",
            "resource_group": "rg",
            "subscription_id": "sub1",
            "location": "eastus",
            "state": "Succeeded",
            "health_status": "healthy",
            "sku_name": "",
            "version": "",
            "findings": [],
            "scanned_at": "2026-04-19T00:00:00+00:00",
            "tags": {},
        },
        {
            "resource_id": "/subscriptions/sub1/.../pg1",
            "name": "pg1",
            "db_type": "postgresql",
            "resource_group": "rg",
            "subscription_id": "sub1",
            "location": "eastus",
            "state": "Ready",
            "health_status": "healthy",
            "sku_name": "Standard_D4ds_v5",
            "version": "16",
            "findings": [],
            "scanned_at": "2026-04-19T00:00:00+00:00",
            "tags": {},
        },
    ]


def test_list_database_health_returns_200(mock_databases, client: TestClient) -> None:
    with patch("services.api_gateway.database_health_endpoints.get_cached", return_value=mock_databases):
        response = client.get("/api/v1/database/health")
    assert response.status_code == 200
    data = response.json()
    assert "databases" in data
    assert data["total"] == 2


def test_list_database_health_filter_by_type(mock_databases, client: TestClient) -> None:
    with patch("services.api_gateway.database_health_endpoints.get_cached", return_value=mock_databases):
        response = client.get("/api/v1/database/health?db_type=cosmos")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["databases"][0]["db_type"] == "cosmos"


def test_database_health_summary_returns_200(mock_databases, client: TestClient) -> None:
    with patch("services.api_gateway.database_health_endpoints.get_cached", return_value=mock_databases):
        response = client.get("/api/v1/database/health/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "by_type" in data
    assert "by_status" in data
    assert data["by_type"]["cosmos"] == 1
    assert data["by_type"]["postgresql"] == 1


def test_slow_queries_returns_pg_and_sql_only(mock_databases, client: TestClient) -> None:
    with patch("services.api_gateway.database_health_endpoints.get_cached", return_value=mock_databases):
        response = client.get("/api/v1/database/slow-queries")
    assert response.status_code == 200
    data = response.json()
    # cosmos should be excluded
    assert all(s["db_type"] in ("postgresql", "sql") for s in data["servers"])


def test_throughput_returns_cosmos_and_sql_only(mock_databases, client: TestClient) -> None:
    with patch("services.api_gateway.database_health_endpoints.get_cached", return_value=mock_databases):
        response = client.get("/api/v1/database/throughput")
    assert response.status_code == 200
    data = response.json()
    # postgresql should be excluded
    assert all(r["db_type"] in ("cosmos", "sql") for r in data["resources"])


def test_no_scan_endpoint_exists(client: TestClient) -> None:
    response = client.post("/api/v1/database/scan", json={})
    assert response.status_code == 404  # route does not exist
