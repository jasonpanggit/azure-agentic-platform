# services/api-gateway/credential_store.py
from __future__ import annotations
"""Per-subscription SPN credential store with Key Vault backend.

Resolution order for CredentialStore.get(subscription_id):
1. In-memory cache (6h TTL, lazy expiry check on hit)
2. Key Vault secret fetch → build ClientSecretCredential → cache
3. DefaultAzureCredential fallback (KV 404 or KV unavailable)

Thread-safe via asyncio.Lock. Never raises — always returns a usable credential.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError, ServiceRequestError
from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient

logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 6
_KV_SECRET_PREFIX = "sub-"
_KV_SECRET_SUFFIX = "-secret"


class CredentialStore:
    """Resolves the correct Azure credential for a given subscription ID.

    Instantiate once at startup; attach to app.state.credential_store.
    Lazy — no KV calls until first get().
    """

    def __init__(self, kv_url: str) -> None:
        self._kv_url = kv_url
        self._cache: dict[str, tuple[object, datetime]] = {}
        self._lock = asyncio.Lock()
        # Sync credential returned to callers (e.g. Azure SDK clients outside KV)
        self._default_credential = DefaultAzureCredential()
        # Async credential used exclusively for the async KV SecretClient
        self._async_kv_credential = AsyncDefaultAzureCredential()
        # Injected in tests; created lazily otherwise
        self._secret_client: Optional[SecretClient] = None

    def _get_secret_client(self) -> SecretClient:
        if self._secret_client is None:
            self._secret_client = SecretClient(
                vault_url=self._kv_url,
                credential=self._async_kv_credential,
            )
        return self._secret_client

    def _kv_secret_name(self, subscription_id: str) -> str:
        """Derive KV secret name: sub-{id_no_dashes}-secret."""
        return f"{_KV_SECRET_PREFIX}{subscription_id.replace('-', '')}{_KV_SECRET_SUFFIX}"

    async def get(self, subscription_id: str) -> object:
        """Return the credential for subscription_id. Never raises."""
        async with self._lock:
            entry = self._cache.get(subscription_id)
            if entry is not None:
                cred, expires_at = entry
                if datetime.now(timezone.utc) < expires_at:
                    return cred
                # Expired — fall through to re-fetch

        # Outside lock for KV network call
        try:
            client = self._get_secret_client()
            secret_name = self._kv_secret_name(subscription_id)
            secret = await client.get_secret(secret_name)
            blob = json.loads(secret.value)
            cred = ClientSecretCredential(
                tenant_id=blob["tenant_id"],
                client_id=blob["client_id"],
                client_secret=blob["client_secret"],
            )
            expires_at = datetime.now(timezone.utc) + timedelta(hours=_CACHE_TTL_HOURS)
            async with self._lock:
                self._cache[subscription_id] = (cred, expires_at)
            return cred
        except ResourceNotFoundError:
            logger.debug(
                "credential_store: no KV secret for sub=%s, using MI fallback",
                subscription_id,
            )
            return self._default_credential
        except (HttpResponseError, ServiceRequestError, Exception) as exc:
            logger.warning(
                "credential_store: KV unavailable for sub=%s (%s), using MI fallback",
                subscription_id,
                exc,
            )
            return self._default_credential

    async def invalidate(self, subscription_id: str) -> None:
        """Remove subscription_id from cache. Call AFTER writing new secret to KV."""
        async with self._lock:
            self._cache.pop(subscription_id, None)

    async def _evict_expired(self) -> None:
        """Remove all cache entries whose TTL has elapsed."""
        now = datetime.now(timezone.utc)
        async with self._lock:
            expired = [sid for sid, (_, exp) in self._cache.items() if now >= exp]
            for sid in expired:
                del self._cache[sid]
        if expired:
            logger.debug("credential_store: evicted %d expired entries", len(expired))

    async def write_secret(self, subscription_id: str, blob: dict) -> None:
        """Write a credential blob to KV. Caller must call invalidate() after."""
        client = self._get_secret_client()
        secret_name = self._kv_secret_name(subscription_id)
        await client.set_secret(secret_name, json.dumps(blob))

    async def delete_secret(self, subscription_id: str) -> None:
        """Delete the KV secret for subscription_id (used on subscription removal)."""
        client = self._get_secret_client()
        secret_name = self._kv_secret_name(subscription_id)
        try:
            await client.delete_secret(secret_name)
        except ResourceNotFoundError:
            pass  # Already gone — idempotent
