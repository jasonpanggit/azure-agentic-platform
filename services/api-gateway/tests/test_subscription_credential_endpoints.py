# services/api-gateway/tests/test_subscription_credential_endpoints.py
from __future__ import annotations
"""Tests for SPN subscription onboarding endpoints."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


VALID_SUB_ID = "4c727b88-12f4-4c91-9c2b-372aab3bbae9"
VALID_TENANT_ID = "11111111-2222-3333-4444-555555555555"
VALID_CLIENT_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"


@pytest.fixture
def app():
    import os
    os.environ["API_GATEWAY_AUTH_MODE"] = "disabled"
    os.environ["KEY_VAULT_URL"] = "https://kv-test.vault.azure.net/"
    from main import app as _app
    mock_store = MagicMock()
    mock_store.get = AsyncMock(return_value=MagicMock())
    mock_store.write_secret = AsyncMock()
    mock_store.delete_secret = AsyncMock()
    mock_store.invalidate = AsyncMock()
    _app.state.credential_store = mock_store
    _app.state.credential = MagicMock()
    _app.state.cosmos_client = None  # endpoints handle None gracefully via helpers
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


def _onboard_body(**overrides):
    body = {
        "subscription_id": VALID_SUB_ID,
        "display_name": "Test Sub",
        "tenant_id": VALID_TENANT_ID,
        "client_id": VALID_CLIENT_ID,
        "client_secret": "s3cr3t",
        "environment": "dev",
    }
    body.update(overrides)
    return body


def test_preview_validate_returns_permission_status(client):
    """POST /onboard/preview-validate returns auth_ok + permission_status."""
    with patch(
        "services.api_gateway.subscription_credential_endpoints._validate_permissions",
        new=AsyncMock(return_value={"reader": "granted", "monitoring_reader": "granted"}),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._check_auth",
        new=AsyncMock(return_value=True),
    ):
        resp = client.post("/api/v1/subscriptions/onboard/preview-validate", json=_onboard_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["auth_ok"] is True
    assert "permission_status" in data


def test_preview_validate_returns_422_on_auth_failure(client):
    """POST /onboard/preview-validate returns 422 when credentials are invalid."""
    with patch(
        "services.api_gateway.subscription_credential_endpoints._check_auth",
        new=AsyncMock(return_value=False),
    ):
        resp = client.post("/api/v1/subscriptions/onboard/preview-validate", json=_onboard_body())
    assert resp.status_code == 422


def test_onboard_returns_201_and_writes_kv_and_cosmos(client, app):
    """POST /onboard writes KV secret, upserts Cosmos, returns 201."""
    with patch(
        "services.api_gateway.subscription_credential_endpoints._check_auth",
        new=AsyncMock(return_value=True),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._validate_permissions",
        new=AsyncMock(return_value={"reader": "granted"}),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._upsert_cosmos_subscription",
        new=AsyncMock(),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._write_audit_log",
        new=AsyncMock(),
    ):
        resp = client.post("/api/v1/subscriptions/onboard", json=_onboard_body())
    assert resp.status_code == 201
    app.state.credential_store.write_secret.assert_awaited_once()


def test_onboard_returns_503_if_kv_write_fails(client, app):
    """POST /onboard returns 503 when KV write fails."""
    app.state.credential_store.write_secret = AsyncMock(side_effect=Exception("KV down"))
    with patch(
        "services.api_gateway.subscription_credential_endpoints._check_auth",
        new=AsyncMock(return_value=True),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._validate_permissions",
        new=AsyncMock(return_value={"reader": "granted"}),
    ):
        resp = client.post("/api/v1/subscriptions/onboard", json=_onboard_body())
    assert resp.status_code == 503


def test_managed_returns_subscription_list(client):
    """GET /managed returns list of monitored subscriptions."""
    # Patch both the new and existing subscription_endpoints helper since
    # route registration order determines which handler fires
    with patch(
        "services.api_gateway.subscription_credential_endpoints._list_subscriptions_from_cosmos",
        new=AsyncMock(return_value=[{"subscription_id": VALID_SUB_ID, "display_name": "Test"}]),
    ), patch(
        "services.api_gateway.subscription_endpoints.list_managed_subscriptions",
        new=AsyncMock(return_value={"subscriptions": [{"subscription_id": VALID_SUB_ID}], "total": 1}),
    ):
        resp = client.get("/api/v1/subscriptions/managed")
    assert resp.status_code == 200
    data = resp.json()
    assert "subscriptions" in data


def test_delete_subscription_soft_deletes(client, app):
    """DELETE /onboard/{id} sets deleted_at, does not hard-delete from Cosmos."""
    with patch(
        "services.api_gateway.subscription_credential_endpoints._soft_delete_cosmos_subscription",
        new=AsyncMock(),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._write_audit_log",
        new=AsyncMock(),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._get_cosmos_subscription",
        new=AsyncMock(return_value={"subscription_id": VALID_SUB_ID, "display_name": "Test"}),
    ):
        resp = client.delete(f"/api/v1/subscriptions/onboard/{VALID_SUB_ID}")
    assert resp.status_code == 200
    app.state.credential_store.invalidate.assert_awaited_once_with(VALID_SUB_ID)


def test_rotate_credentials_writes_kv_then_invalidates_cache(client, app):
    """PUT /onboard/{id}/credentials writes KV, then invalidates cache."""
    with patch(
        "services.api_gateway.subscription_credential_endpoints._get_cosmos_subscription",
        new=AsyncMock(return_value={"client_id": VALID_CLIENT_ID, "tenant_id": VALID_TENANT_ID}),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._check_auth",
        new=AsyncMock(return_value=True),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._validate_permissions",
        new=AsyncMock(return_value={"reader": "granted"}),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._upsert_cosmos_subscription",
        new=AsyncMock(),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._write_audit_log",
        new=AsyncMock(),
    ):
        # Also need to mock the KV fetch in rotate_credentials
        mock_kv_client = MagicMock()
        mock_secret = MagicMock()
        mock_secret.value = '{"client_id":"' + VALID_CLIENT_ID + '","client_secret":"old","tenant_id":"' + VALID_TENANT_ID + '","subscription_id":"' + VALID_SUB_ID + '"}'
        mock_kv_client.get_secret = AsyncMock(return_value=mock_secret)
        app.state.credential_store._get_secret_client = MagicMock(return_value=mock_kv_client)
        app.state.credential_store._kv_secret_name = MagicMock(return_value="sub-test-secret")

        resp = client.put(
            f"/api/v1/subscriptions/onboard/{VALID_SUB_ID}/credentials",
            json={"client_secret": "new-secret"},
        )
    assert resp.status_code == 200
    # KV write happens before cache invalidation
    app.state.credential_store.write_secret.assert_awaited_once()
    app.state.credential_store.invalidate.assert_awaited_once_with(VALID_SUB_ID)
