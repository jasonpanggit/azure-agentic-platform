"""Tests for push_notifications.py — routes and send_push_to_all logic."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with the push router mounted."""
    from services.api_gateway.push_notifications import router

    app = FastAPI()
    app.include_router(router)
    app.state.cosmos_client = None
    return app


@pytest.fixture()
def client():
    return TestClient(_make_app())


@pytest.fixture()
def mock_container():
    container = MagicMock()
    container.upsert_item.return_value = {}
    container.delete_item.return_value = {}
    container.query_items.return_value = []
    return container


SUB_PAYLOAD = {
    "endpoint": "https://push.example.com/sub/abc123",
    "keys": {"p256dh": "BNaKey==", "auth": "auth=="},
}


# ─── GET /vapid-public-key ────────────────────────────────────────────────────


def test_vapid_public_key_returns_key(client, monkeypatch):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "test-vapid-key")
    res = client.get("/api/v1/notifications/vapid-public-key")
    assert res.status_code == 200
    assert res.json()["vapidPublicKey"] == "test-vapid-key"


def test_vapid_public_key_503_when_not_set(client, monkeypatch):
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    res = client.get("/api/v1/notifications/vapid-public-key")
    assert res.status_code == 503


# ─── POST /subscribe ─────────────────────────────────────────────────────────


def test_subscribe_upserts_to_cosmos(client, mock_container):
    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        return_value=mock_container,
    ):
        res = client.post("/api/v1/notifications/subscribe", json=SUB_PAYLOAD)
    assert res.status_code == 201
    assert res.json()["status"] == "subscribed"
    mock_container.upsert_item.assert_called_once()
    upserted = mock_container.upsert_item.call_args[1]["body"]
    assert upserted["endpoint"] == SUB_PAYLOAD["endpoint"]
    assert "subscription_endpoint_hash" in upserted


def test_subscribe_returns_hash(client, mock_container):
    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        return_value=mock_container,
    ):
        res = client.post("/api/v1/notifications/subscribe", json=SUB_PAYLOAD)
    assert "hash" in res.json()
    assert len(res.json()["hash"]) == 32


def test_subscribe_503_when_cosmos_not_configured(client, monkeypatch):
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        side_effect=ValueError("COSMOS_ENDPOINT environment variable is required."),
    ):
        res = client.post("/api/v1/notifications/subscribe", json=SUB_PAYLOAD)
    assert res.status_code == 503


# ─── DELETE /subscribe ────────────────────────────────────────────────────────


def test_unsubscribe_deletes_from_cosmos(client, mock_container):
    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        return_value=mock_container,
    ):
        res = client.request(
            "DELETE", "/api/v1/notifications/subscribe", json=SUB_PAYLOAD
        )
    assert res.status_code == 200
    assert res.json()["status"] == "unsubscribed"
    mock_container.delete_item.assert_called_once()


def test_unsubscribe_idempotent_when_not_found(client, mock_container):
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    mock_container.delete_item.side_effect = CosmosResourceNotFoundError(
        message="Not found", response=MagicMock(status_code=404)
    )
    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        return_value=mock_container,
    ):
        res = client.request(
            "DELETE", "/api/v1/notifications/subscribe", json=SUB_PAYLOAD
        )
    assert res.status_code == 200


# ─── send_push_to_all ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_push_skips_when_webpush_none(monkeypatch):
    import services.api_gateway.push_notifications as pn

    monkeypatch.setattr(pn, "webpush", None)
    result = await pn.send_push_to_all("title", "body")
    assert result == 0


@pytest.mark.asyncio
async def test_send_push_skips_when_no_vapid_key(monkeypatch):
    import services.api_gateway.push_notifications as pn

    monkeypatch.setattr(pn, "webpush", MagicMock())
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    result = await pn.send_push_to_all("title", "body")
    assert result == 0


@pytest.mark.asyncio
async def test_send_push_sends_to_all_subscriptions(monkeypatch):
    import services.api_gateway.push_notifications as pn

    mock_wp = MagicMock()
    monkeypatch.setattr(pn, "webpush", mock_wp)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private-key")
    monkeypatch.setenv("VAPID_EMAIL", "mailto:ops@example.com")

    mock_container = MagicMock()
    mock_container.query_items.return_value = [
        {
            "id": "hash1",
            "subscription_endpoint_hash": "hash1",
            "endpoint": "https://push.example.com/1",
            "keys": {"p256dh": "key1", "auth": "auth1"},
        },
        {
            "id": "hash2",
            "subscription_endpoint_hash": "hash2",
            "endpoint": "https://push.example.com/2",
            "keys": {"p256dh": "key2", "auth": "auth2"},
        },
    ]

    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        return_value=mock_container,
    ):
        result = await pn.send_push_to_all("P0 Alert", "Server down", url="/approvals")

    assert result == 2
    assert mock_wp.call_count == 2


@pytest.mark.asyncio
async def test_send_push_removes_expired_410_subscription(monkeypatch):
    import services.api_gateway.push_notifications as pn

    mock_wp = MagicMock(side_effect=pn.WebPushException("410 Gone"))
    monkeypatch.setattr(pn, "webpush", mock_wp)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private-key")

    mock_container = MagicMock()
    mock_container.query_items.return_value = [
        {
            "id": "hash1",
            "subscription_endpoint_hash": "hash1",
            "endpoint": "https://push.example.com/1",
            "keys": {"p256dh": "key1", "auth": "auth1"},
        }
    ]

    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        return_value=mock_container,
    ):
        result = await pn.send_push_to_all("P0 Alert", "Server down")

    assert result == 0
    mock_container.delete_item.assert_called_once()


@pytest.mark.asyncio
async def test_send_push_continues_after_per_subscriber_error(monkeypatch):
    import services.api_gateway.push_notifications as pn

    call_count = 0

    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("network error")
        # second call succeeds

    mock_wp = MagicMock(side_effect=side_effect)
    monkeypatch.setattr(pn, "webpush", mock_wp)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private-key")

    mock_container = MagicMock()
    mock_container.query_items.return_value = [
        {
            "id": "h1",
            "subscription_endpoint_hash": "h1",
            "endpoint": "https://push.example.com/1",
            "keys": {"p256dh": "k1", "auth": "a1"},
        },
        {
            "id": "h2",
            "subscription_endpoint_hash": "h2",
            "endpoint": "https://push.example.com/2",
            "keys": {"p256dh": "k2", "auth": "a2"},
        },
    ]

    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        return_value=mock_container,
    ):
        result = await pn.send_push_to_all("title", "body")

    assert result == 1  # second subscriber succeeded


@pytest.mark.asyncio
async def test_send_push_returns_zero_on_cosmos_read_failure(monkeypatch):
    import services.api_gateway.push_notifications as pn

    monkeypatch.setattr(pn, "webpush", MagicMock())
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private-key")

    with patch(
        "services.api_gateway.push_notifications._get_subscriptions_container",
        side_effect=Exception("Cosmos unavailable"),
    ):
        result = await pn.send_push_to_all("title", "body")

    assert result == 0


# ─── _endpoint_hash ───────────────────────────────────────────────────────────


def test_endpoint_hash_is_deterministic():
    from services.api_gateway.push_notifications import _endpoint_hash

    h1 = _endpoint_hash("https://push.example.com/sub/abc")
    h2 = _endpoint_hash("https://push.example.com/sub/abc")
    assert h1 == h2
    assert len(h1) == 32


def test_endpoint_hash_differs_for_different_endpoints():
    from services.api_gateway.push_notifications import _endpoint_hash

    assert _endpoint_hash("https://a.example.com") != _endpoint_hash("https://b.example.com")
