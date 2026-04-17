# services/api-gateway/tests/test_credential_store.py
from __future__ import annotations
"""Tests for CredentialStore — SPN credential resolution with KV + cache."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError, ServiceRequestError
from azure.identity import ClientSecretCredential, DefaultAzureCredential


@pytest.fixture
def kv_secret_json():
    return (
        '{"client_id":"cli-123","client_secret":"sec-abc",'
        '"tenant_id":"ten-456","subscription_id":"sub-789"}'
    )


@pytest.fixture
def mock_secret(kv_secret_json):
    s = MagicMock()
    s.value = kv_secret_json
    return s


@pytest.fixture
def mock_secret_client(mock_secret):
    client = MagicMock()
    client.get_secret = AsyncMock(return_value=mock_secret)
    client.set_secret = AsyncMock(return_value=mock_secret)
    client.delete_secret = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_get_returns_client_secret_credential_on_kv_hit(mock_secret_client):
    """CredentialStore.get() returns ClientSecretCredential when KV has the secret."""
    from services.api_gateway.credential_store import CredentialStore

    store = CredentialStore(kv_url="https://kv-test.vault.azure.net/")
    store._secret_client = mock_secret_client

    cred = await store.get("4c727b88-12f4-4c91-9c2b-372aab3bbae9")

    assert isinstance(cred, ClientSecretCredential)
    mock_secret_client.get_secret.assert_called_once_with(
        "sub-4c727b8812f44c919c2b372aab3bbae9-secret"
    )


@pytest.mark.asyncio
async def test_get_caches_credential_on_second_call(mock_secret_client):
    """Second call for same sub_id hits cache, not KV."""
    from services.api_gateway.credential_store import CredentialStore

    store = CredentialStore(kv_url="https://kv-test.vault.azure.net/")
    store._secret_client = mock_secret_client

    await store.get("sub-aaa")
    await store.get("sub-aaa")

    # KV called only once despite two get() calls
    assert mock_secret_client.get_secret.call_count == 1


@pytest.mark.asyncio
async def test_get_falls_back_to_default_credential_on_kv_404(mock_secret_client):
    """Returns DefaultAzureCredential when KV 404s (no secret for this sub)."""
    from services.api_gateway.credential_store import CredentialStore

    err = ResourceNotFoundError("not found")
    mock_secret_client.get_secret = AsyncMock(side_effect=err)

    store = CredentialStore(kv_url="https://kv-test.vault.azure.net/")
    store._secret_client = mock_secret_client

    cred = await store.get("sub-unknown")
    assert isinstance(cred, DefaultAzureCredential)


@pytest.mark.asyncio
async def test_get_falls_back_to_default_credential_on_kv_unavailable(mock_secret_client):
    """Returns DefaultAzureCredential when KV is unreachable (network error)."""
    from services.api_gateway.credential_store import CredentialStore

    mock_secret_client.get_secret = AsyncMock(
        side_effect=ServiceRequestError("connection refused")
    )
    store = CredentialStore(kv_url="https://kv-test.vault.azure.net/")
    store._secret_client = mock_secret_client

    cred = await store.get("sub-offline")
    assert isinstance(cred, DefaultAzureCredential)


@pytest.mark.asyncio
async def test_invalidate_removes_cache_entry(mock_secret_client):
    """invalidate() causes next get() to re-fetch from KV."""
    from services.api_gateway.credential_store import CredentialStore

    store = CredentialStore(kv_url="https://kv-test.vault.azure.net/")
    store._secret_client = mock_secret_client

    await store.get("sub-rotate")
    await store.invalidate("sub-rotate")
    await store.get("sub-rotate")

    assert mock_secret_client.get_secret.call_count == 2


@pytest.mark.asyncio
async def test_evict_expired_removes_stale_entries():
    """_evict_expired() removes entries past their TTL."""
    from services.api_gateway.credential_store import CredentialStore

    store = CredentialStore(kv_url="https://kv-test.vault.azure.net/")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    store._cache["sub-stale"] = (MagicMock(), past)
    store._cache["sub-fresh"] = (MagicMock(), datetime.now(timezone.utc) + timedelta(hours=5))

    await store._evict_expired()

    assert "sub-stale" not in store._cache
    assert "sub-fresh" in store._cache


@pytest.mark.asyncio
async def test_kv_secret_name_strips_dashes():
    """KV secret name strips dashes from subscription ID."""
    from services.api_gateway.credential_store import CredentialStore

    store = CredentialStore(kv_url="https://kv-test.vault.azure.net/")
    name = store._kv_secret_name("4c727b88-12f4-4c91-9c2b-372aab3bbae9")
    assert name == "sub-4c727b8812f44c919c2b372aab3bbae9-secret"


@pytest.mark.asyncio
async def test_scoped_credential_used_for_subscription_endpoints():
    """Verify that subscription-scoped endpoints call credential_store.get() not app.state.credential."""
    # This test verifies the pattern is correct by checking subscription_endpoints uses get_scoped_credential
    # for per-subscription routes (/{subscription_id}/stats)
    import ast
    import pathlib

    p = pathlib.Path("services/api-gateway/subscription_endpoints.py")
    src = p.read_text()
    assert "get_scoped_credential" in src, (
        "subscription_endpoints.py must use get_scoped_credential for per-subscription routes"
    )
