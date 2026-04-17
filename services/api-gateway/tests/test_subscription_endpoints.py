from __future__ import annotations
"""Tests for subscription management endpoints (Phase 68)."""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_cosmos_item(
    sub_id: str = "sub-001",
    name: str = "Production",
    label: Optional[str] = None,
    monitoring_enabled: bool = True,
    environment: str = "prod",
    last_synced: str = "2026-04-17T00:00:00+00:00",
) -> Dict[str, Any]:
    return {
        "id": sub_id,
        "subscription_id": sub_id,
        "name": name,
        "label": label or name,
        "monitoring_enabled": monitoring_enabled,
        "environment": environment,
        "last_synced": last_synced,
    }


@pytest.fixture()
def mock_cosmos():
    """Mock Cosmos client with a subscriptions and incidents container."""
    client = MagicMock(name="CosmosClient")
    subs_container = MagicMock(name="subscriptions_container")
    incidents_container = MagicMock(name="incidents_container")

    def _get_container(name):
        if name == "subscriptions":
            return subs_container
        return incidents_container

    db = MagicMock()
    db.get_container_client.side_effect = _get_container
    client.get_database_client.return_value = db

    # Default: empty incidents
    incidents_container.query_items.return_value = iter([0])

    return client, subs_container, incidents_container


@pytest.fixture()
def client(mock_cosmos):
    """TestClient with subscription management router mounted."""
    from services.api_gateway.subscription_endpoints import router
    from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

    cosmos_client, _, _ = mock_cosmos
    app = FastAPI()
    app.include_router(router)

    mock_credential = MagicMock(name="DefaultAzureCredential")

    app.dependency_overrides[get_credential] = lambda: mock_credential
    app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos_client

    return TestClient(app)


@pytest.fixture()
def client_no_cosmos():
    """TestClient with Cosmos unavailable (None)."""
    from services.api_gateway.subscription_endpoints import router
    from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

    app = FastAPI()
    app.include_router(router)

    mock_credential = MagicMock(name="DefaultAzureCredential")

    app.dependency_overrides[get_credential] = lambda: mock_credential
    app.dependency_overrides[get_optional_cosmos_client] = lambda: None

    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /managed — happy path
# ---------------------------------------------------------------------------

def test_list_managed_subscriptions_happy_path(mock_cosmos, client):
    """Returns enriched subscription list from Cosmos."""
    _, subs_container, incidents_container = mock_cosmos
    subs_container.read_all_items.return_value = [
        _make_cosmos_item("sub-001", "Production"),
        _make_cosmos_item("sub-002", "Staging", environment="staging"),
    ]
    # Return 0 for all COUNT queries
    incidents_container.query_items.return_value = iter([0])

    resp = client.get("/api/v1/subscriptions/managed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["subscriptions"]) == 2
    assert data["subscriptions"][0]["id"] == "sub-001"
    assert data["subscriptions"][0]["name"] == "Production"
    assert data["subscriptions"][0]["monitoring_enabled"] is True
    assert "generated_at" in data


def test_list_managed_subscriptions_includes_incident_counts(mock_cosmos, client):
    """Incident counts are populated from Cosmos incidents container."""
    _, subs_container, incidents_container = mock_cosmos
    subs_container.read_all_items.return_value = [
        _make_cosmos_item("sub-001", "Production"),
    ]
    # open_incidents query returns 5, all others 0
    call_count = 0

    def _query_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return iter([5])  # open_incidents
        return iter([0])

    incidents_container.query_items.side_effect = _query_side_effect

    resp = client.get("/api/v1/subscriptions/managed")
    assert resp.status_code == 200
    sub = resp.json()["subscriptions"][0]
    assert sub["open_incidents"] == 5


# ---------------------------------------------------------------------------
# GET /managed — Cosmos unavailable
# ---------------------------------------------------------------------------

def test_list_managed_subscriptions_cosmos_unavailable(client_no_cosmos):
    """Returns empty list with warning when Cosmos is unavailable."""
    resp = client_no_cosmos.get("/api/v1/subscriptions/managed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["subscriptions"] == []
    assert "warning" in data


def test_list_managed_subscriptions_cosmos_read_error(mock_cosmos, client):
    """Returns empty list with warning when Cosmos read throws."""
    _, subs_container, _ = mock_cosmos
    subs_container.read_all_items.side_effect = Exception("Connection timeout")

    resp = client.get("/api/v1/subscriptions/managed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert "warning" in data


# ---------------------------------------------------------------------------
# PATCH /{subscription_id}
# ---------------------------------------------------------------------------

def test_patch_subscription_metadata(mock_cosmos, client):
    """Updates label, monitoring_enabled, and environment."""
    _, subs_container, _ = mock_cosmos
    existing = _make_cosmos_item("sub-001", "Production")
    subs_container.read_item.return_value = existing
    subs_container.upsert_item.return_value = None

    resp = client.patch(
        "/api/v1/subscriptions/sub-001",
        json={"label": "Prod-East", "monitoring_enabled": False, "environment": "prod"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["label"] == "Prod-East"
    assert data["monitoring_enabled"] is False
    assert data["environment"] == "prod"
    assert "updated_at" in data

    # Verify upsert was called
    subs_container.upsert_item.assert_called_once()


def test_patch_subscription_partial_update(mock_cosmos, client):
    """Partial patch — only updates provided fields."""
    _, subs_container, _ = mock_cosmos
    existing = _make_cosmos_item("sub-001", "Production", label="Old Label")
    subs_container.read_item.return_value = existing
    subs_container.upsert_item.return_value = None

    resp = client.patch(
        "/api/v1/subscriptions/sub-001",
        json={"label": "New Label"},
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "New Label"


def test_patch_subscription_not_found(mock_cosmos, client):
    """Returns 404 when subscription does not exist."""
    _, subs_container, _ = mock_cosmos
    subs_container.read_item.side_effect = Exception("Not found")
    subs_container.query_items.return_value = iter([])  # empty query result

    resp = client.patch(
        "/api/v1/subscriptions/sub-nonexistent",
        json={"label": "Ghost"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"].lower()


def test_patch_subscription_cosmos_unavailable(client_no_cosmos):
    """Returns 503 when Cosmos is unavailable."""
    resp = client_no_cosmos.patch(
        "/api/v1/subscriptions/sub-001",
        json={"label": "Test"},
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /sync
# ---------------------------------------------------------------------------

def test_sync_subscriptions(mock_cosmos, client):
    """Triggers full sync and returns synced count."""
    cosmos_client, _, _ = mock_cosmos

    with patch(
        "services.api_gateway.subscription_registry.SubscriptionRegistry"
    ) as MockRegistry:
        mock_registry = MagicMock()
        mock_registry.full_sync = AsyncMock()
        mock_registry.get_all.return_value = [{"id": "sub-001"}, {"id": "sub-002"}]
        MockRegistry.return_value = mock_registry

        resp = client.post("/api/v1/subscriptions/sync")

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 2
    assert "duration_ms" in data
    assert "synced_at" in data


def test_sync_subscriptions_uses_app_state_registry(mock_cosmos):
    """Uses registry from app.state if available."""
    from services.api_gateway.subscription_endpoints import router
    from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

    cosmos_client, _, _ = mock_cosmos
    app = FastAPI()
    app.include_router(router)

    mock_credential = MagicMock()
    app.dependency_overrides[get_credential] = lambda: mock_credential
    app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos_client

    # Attach mock registry to app.state
    mock_registry = MagicMock()
    mock_registry.full_sync = AsyncMock()
    mock_registry.get_all.return_value = [{"id": "sub-001"}]
    app.state.subscription_registry = mock_registry

    tc = TestClient(app)
    resp = tc.post("/api/v1/subscriptions/sync")
    assert resp.status_code == 200
    assert resp.json()["synced"] == 1
    mock_registry.full_sync.assert_called_once()


# ---------------------------------------------------------------------------
# GET /{subscription_id}/stats — happy path
# ---------------------------------------------------------------------------

def test_get_subscription_stats_happy_path(mock_cosmos, client):
    """Returns full stats for a known subscription."""
    _, subs_container, incidents_container = mock_cosmos
    subs_container.read_item.return_value = _make_cosmos_item("sub-001", "Production")

    call_idx = [0]
    return_values = [3, 10, [], 5]  # open, 24h-all, sev-group, resolved

    def _query(query="", **kwargs):
        i = call_idx[0]
        call_idx[0] += 1
        if i < len(return_values):
            val = return_values[i]
            if isinstance(val, list):
                return iter(val)
            return iter([val])
        return iter([0])

    incidents_container.query_items.side_effect = _query

    with patch(
        "services.api_gateway.subscription_endpoints._fetch_resource_counts",
        return_value={"resource_count": 450, "vm_count": 23},
    ):
        resp = client.get("/api/v1/subscriptions/sub-001/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["subscription_id"] == "sub-001"
    assert data["name"] == "Production"
    assert data["resource_count"] == 450
    assert data["vm_count"] == 23
    assert "generated_at" in data


def test_get_subscription_stats_cosmos_unavailable(client_no_cosmos):
    """Returns zeros for incident counts when Cosmos unavailable, nulls for resources."""
    with patch(
        "services.api_gateway.subscription_endpoints._fetch_resource_counts",
        return_value={"resource_count": None, "vm_count": None},
    ):
        resp = client_no_cosmos.get("/api/v1/subscriptions/sub-001/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["open_incidents"] == 0
    assert data["incident_count_24h"] == 0
    assert data["resource_count"] is None
    assert data["vm_count"] is None


# ---------------------------------------------------------------------------
# Exception resilience
# ---------------------------------------------------------------------------

def test_managed_list_handles_unexpected_exception(mock_cosmos, client):
    """Returns 500 on unexpected errors, never raises."""
    _, subs_container, _ = mock_cosmos
    subs_container.read_all_items.side_effect = RuntimeError("Unexpected boom")

    resp = client.get("/api/v1/subscriptions/managed")
    # Either 200 with warning or 500 — must not crash
    assert resp.status_code in (200, 500)
    data = resp.json()
    assert "subscriptions" in data or "error" in data


def test_stats_handles_cosmos_query_exception(mock_cosmos, client):
    """Stats endpoint returns gracefully when incident query fails."""
    _, subs_container, incidents_container = mock_cosmos
    subs_container.read_item.return_value = _make_cosmos_item("sub-001")
    incidents_container.query_items.side_effect = Exception("Query failed")

    with patch(
        "services.api_gateway.subscription_endpoints._fetch_resource_counts",
        return_value={"resource_count": None, "vm_count": None},
    ):
        resp = client.get("/api/v1/subscriptions/sub-001/stats")

    # Must not raise; returns zeros for counts
    assert resp.status_code == 200
    data = resp.json()
    assert data["open_incidents"] == 0
