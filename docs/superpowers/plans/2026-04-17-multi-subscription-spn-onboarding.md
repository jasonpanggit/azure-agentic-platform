# Multi-Subscription SPN Onboarding Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow any Azure subscription (same or cross-tenant) to be onboarded via Service Principal credentials, with per-subscription credential routing throughout the entire API layer, a self-service onboarding UI, and cleanup of the obsolete tenants table.

**Architecture:** A new `CredentialStore` class manages per-subscription SPN credentials fetched from Key Vault (6h TTL in-memory cache, background eviction, MI fallback). Six new REST endpoints handle onboarding lifecycle. All 78 existing `Depends(get_credential)` usages in subscription-scoped endpoints are updated to `Depends(get_scoped_credential)`. The UI gets a redesigned `MonitoredSubscriptionsTab` replacing both `SubscriptionManagementTab` and `TenantAdminTab`.

**Tech Stack:** Python/FastAPI, `azure-keyvault-secrets>=4.8.0`, `azure-mgmt-subscription>=3.0.0`, Next.js 15/TypeScript, Tailwind CSS + shadcn/ui, Cosmos DB, PostgreSQL, asyncio

---

## Chunk 1: Phase 1 — CredentialStore + KV integration + onboard endpoints

### Task 1: Add azure-keyvault-secrets dependency

**Files:**
- Modify: `services/api-gateway/requirements.txt`

- [ ] **Step 1: Add the dependency**

Add to `requirements.txt` after existing azure packages:
```
azure-keyvault-secrets>=4.8.0
```

- [ ] **Step 2: Verify the file**

```bash
grep "azure-keyvault" services/api-gateway/requirements.txt
```
Expected: `azure-keyvault-secrets>=4.8.0`

- [ ] **Step 3: Commit**

```bash
git add services/api-gateway/requirements.txt
git commit -m "chore: add azure-keyvault-secrets dependency for SPN credential store"
```

---

### Task 2: CredentialStore — write the failing tests first

**Files:**
- Create: `services/api-gateway/tests/test_credential_store.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_credential_store.py -v 2>&1 | head -30
```
Expected: ImportError — `credential_store` module does not exist yet.

---

### Task 3: CredentialStore — implement

**Files:**
- Create: `services/api-gateway/credential_store.py`

- [ ] **Step 1: Create the module**

```python
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
        self._default_credential = DefaultAzureCredential()
        # Injected in tests; created lazily otherwise
        self._secret_client: Optional[SecretClient] = None

    def _get_secret_client(self) -> SecretClient:
        if self._secret_client is None:
            self._secret_client = SecretClient(
                vault_url=self._kv_url,
                credential=self._default_credential,
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
```

- [ ] **Step 2: Run tests — should pass now**

```bash
python -m pytest services/api-gateway/tests/test_credential_store.py -v
```
Expected: All 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add services/api-gateway/credential_store.py services/api-gateway/tests/test_credential_store.py
git commit -m "feat: add CredentialStore with KV-backed SPN credential resolution"
```

---

### Task 4: Wire CredentialStore into main.py lifespan

**Files:**
- Modify: `services/api-gateway/main.py`

- [ ] **Step 1: Read the lifespan section in main.py**

```bash
grep -n "lifespan\|app.state\|asynccontextmanager\|evict\|subscription" services/api-gateway/main.py | head -40
```

- [ ] **Step 2: Add CredentialStore imports and wire into lifespan**

In `main.py`, add to the imports section (near the existing `DefaultAzureCredential` import):
```python
from services.api_gateway.credential_store import CredentialStore
```

In the `lifespan` async context manager, after `app.state.credential = DefaultAzureCredential()`:
```python
# CredentialStore — per-subscription SPN credential routing
_kv_url = os.environ.get("KEY_VAULT_URL", "")
if _kv_url:
    app.state.credential_store = CredentialStore(kv_url=_kv_url)
    # Background eviction task — runs every 30 minutes
    async def _eviction_loop():
        while True:
            await asyncio.sleep(1800)
            await app.state.credential_store._evict_expired()
    asyncio.create_task(_eviction_loop())
    logger.info("credential_store: initialized with KV_URL=%s", _kv_url)

    # Startup warning: log any subscriptions expiring within 7 days (spec §6)
    async def _check_expiry_on_startup():
        try:
            cosmos = app.state.cosmos_client
            if cosmos is None:
                return
            db = cosmos.get_database_client("aap")
            container = db.get_container_client("subscriptions")
            subs = list(container.query_items(
                query="SELECT c.subscription_id, c.display_name, c.secret_expires_at FROM c WHERE NOT IS_DEFINED(c.deleted_at) OR c.deleted_at = null",
                enable_cross_partition_query=True,
            ))
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            for sub in subs:
                exp_str = sub.get("secret_expires_at")
                if not exp_str:
                    continue
                try:
                    exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                    days = (exp - now).days
                    if days < 7:
                        logger.warning(
                            "credential_store: SPN secret for sub=%s (%s) expires in %d days — rotate soon",
                            sub.get("subscription_id"), sub.get("display_name"), max(0, days),
                        )
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("credential_store: startup expiry check failed: %s", exc)
    asyncio.create_task(_check_expiry_on_startup())
else:
    app.state.credential_store = CredentialStore(kv_url="")
    logger.warning("credential_store: KEY_VAULT_URL not set — MI fallback only")
```

- [ ] **Step 3: Verify the server starts**

```bash
cd services/api-gateway && KEY_VAULT_URL="" python -c "from main import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add services/api-gateway/main.py
git commit -m "feat: wire CredentialStore into FastAPI lifespan with background eviction"
```

---

### Task 5: Add get_scoped_credential to dependencies.py

**Files:**
- Modify: `services/api-gateway/dependencies.py`

- [ ] **Step 1: Write the failing test**

Create or append to existing test file:
```python
# Append to services/api-gateway/tests/test_dependencies.py

@pytest.mark.asyncio
async def test_get_scoped_credential_calls_credential_store():
    """get_scoped_credential delegates to app.state.credential_store.get()."""
    from unittest.mock import AsyncMock, MagicMock
    from fastapi import Request
    from services.api_gateway.dependencies import get_scoped_credential

    mock_store = MagicMock()
    mock_store.get = AsyncMock(return_value=MagicMock())
    request = MagicMock(spec=Request)
    request.app.state.credential_store = mock_store

    cred = await get_scoped_credential(subscription_id="sub-abc", request=request)

    mock_store.get.assert_called_once_with("sub-abc")
    assert cred is mock_store.get.return_value
```

- [ ] **Step 2: Run — confirm it fails**

```bash
python -m pytest services/api-gateway/tests/test_dependencies.py::test_get_scoped_credential_calls_credential_store -v
```
Expected: ImportError or AttributeError — `get_scoped_credential` does not exist.

- [ ] **Step 3: Add the dependency to dependencies.py**

```python
# Add to services/api-gateway/dependencies.py

async def get_scoped_credential(
    subscription_id: str,
    request: Request,
) -> object:
    """Return the per-subscription credential from CredentialStore.

    FastAPI resolves subscription_id from the path parameter automatically.
    This dependency is safe to use on any endpoint with /{subscription_id}/ in its path.
    """
    store = request.app.state.credential_store
    return await store.get(subscription_id)
```

- [ ] **Step 4: Run tests — should pass**

```bash
python -m pytest services/api-gateway/tests/test_dependencies.py -v
```
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api-gateway/dependencies.py services/api-gateway/tests/test_dependencies.py
git commit -m "feat: add get_scoped_credential FastAPI dependency for per-subscription credential routing"
```

---

### Task 6: Cosmos schema migration — add SPN fields

**Files:**
- Create: `services/api-gateway/migrations/010_subscription_spn_fields.py`

- [ ] **Step 1: Write the test**

```python
# services/api-gateway/tests/test_subscription_spn_migration.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_migration_up_updates_existing_records():
    """Migration up() adds SPN fields with safe defaults to existing subscription records."""
    import importlib
    migration = importlib.import_module(
        "services.api_gateway.migrations.010_subscription_spn_fields"
    )

    mock_conn = MagicMock()
    # Test that the function runs without error (Cosmos migration is fire-and-forget)
    await migration.up(mock_conn)
    # No assert needed — just verify it doesn't throw


@pytest.mark.asyncio
async def test_migration_down_is_no_op():
    """Migration down() is a no-op (field removal is backwards-compatible)."""
    import importlib
    migration = importlib.import_module(
        "services.api_gateway.migrations.010_subscription_spn_fields"
    )
    mock_conn = MagicMock()
    await migration.down(mock_conn)
```

- [ ] **Step 2: Run — confirm fail**

```bash
python -m pytest services/api-gateway/tests/test_subscription_spn_migration.py -v 2>&1 | head -20
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create the migration**

```python
# services/api-gateway/migrations/010_subscription_spn_fields.py
from __future__ import annotations
"""Migration 010: Add SPN credential fields to Cosmos subscriptions container.

This migration is a no-op for SQL — the subscriptions container is in Cosmos DB
(schema-free). The new fields are added lazily on first write. This file serves
as a documentation anchor and adds safe defaults to any existing records that
lack the new fields when read by the application.

New fields added to subscription records:
  - credential_type: "mi" | "spn"  (default: "mi" for existing records)
  - client_id: str | None           (default: None)
  - tenant_id: str | None           (default: None)
  - kv_secret_name: str | None      (default: None)
  - permission_status: dict         (default: {})
  - last_validated_at: str | None   (default: None)
  - secret_expires_at: str | None   (default: None)
  - deleted_at: str | None          (default: None)
"""
import logging

logger = logging.getLogger(__name__)

DESCRIPTION = "Add SPN credential fields to Cosmos subscriptions container"


async def up(conn) -> None:  # noqa: ANN001
    """No SQL DDL required — Cosmos is schema-free.

    Documents the intent. The API layer applies defaults when reading
    existing records (see subscription_endpoints.py _enrich_record()).
    """
    logger.info("migration 010: SPN fields are schema-free in Cosmos — no DDL required")


async def down(conn) -> None:  # noqa: ANN001
    """No rollback required — field removal is backwards-compatible."""
    logger.info("migration 010 down: no-op")
```

- [ ] **Step 4: Run tests — should pass**

```bash
python -m pytest services/api-gateway/tests/test_subscription_spn_migration.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api-gateway/migrations/010_subscription_spn_fields.py services/api-gateway/tests/test_subscription_spn_migration.py
git commit -m "feat: add migration 010 documenting SPN credential fields on Cosmos subscriptions"
```

---

### Task 7: Onboarding endpoints — write tests first

**Files:**
- Create: `services/api-gateway/tests/test_subscription_credential_endpoints.py`

- [ ] **Step 1: Write the failing tests**

```python
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
    with patch(
        "services.api_gateway.subscription_credential_endpoints._list_subscriptions_from_cosmos",
        new=AsyncMock(return_value=[{"subscription_id": VALID_SUB_ID, "display_name": "Test"}]),
    ):
        resp = client.get("/api/v1/subscriptions/managed")
    assert resp.status_code == 200
    data = resp.json()
    assert "subscriptions" in data
    assert len(data["subscriptions"]) == 1


def test_delete_subscription_soft_deletes(client, app):
    """DELETE /onboard/{id} sets deleted_at, does not hard-delete from Cosmos."""
    with patch(
        "services.api_gateway.subscription_credential_endpoints._soft_delete_cosmos_subscription",
        new=AsyncMock(),
    ), patch(
        "services.api_gateway.subscription_credential_endpoints._write_audit_log",
        new=AsyncMock(),
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
        resp = client.put(
            f"/api/v1/subscriptions/onboard/{VALID_SUB_ID}/credentials",
            json={"client_secret": "new-secret"},
        )
    assert resp.status_code == 200
    # KV write happens before cache invalidation
    app.state.credential_store.write_secret.assert_awaited_once()
    app.state.credential_store.invalidate.assert_awaited_once_with(VALID_SUB_ID)
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
python -m pytest services/api-gateway/tests/test_subscription_credential_endpoints.py -v 2>&1 | head -30
```
Expected: ImportError — `subscription_credential_endpoints` module does not exist.

---

### Task 8: Implement onboarding endpoints

**Files:**
- Create: `services/api-gateway/subscription_credential_endpoints.py`

- [ ] **Step 1: Create the endpoints module**

```python
# services/api-gateway/subscription_credential_endpoints.py
from __future__ import annotations
"""SPN subscription onboarding endpoints — Phase: Multi-Subscription.

Endpoints:
  POST   /api/v1/subscriptions/onboard/preview-validate  — validate creds without saving
  POST   /api/v1/subscriptions/onboard                   — onboard a new subscription
  GET    /api/v1/subscriptions/managed                   — list all monitored subscriptions
  POST   /api/v1/subscriptions/onboard/{id}/validate     — re-validate stored credentials
  PUT    /api/v1/subscriptions/onboard/{id}/credentials  — rotate credentials
  DELETE /api/v1/subscriptions/onboard/{id}              — remove subscription (soft-delete)

All endpoints require verify_token (Entra ID Bearer token).
client_secret is NEVER logged, returned, or stored anywhere except Key Vault.
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import ClientSecretCredential
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from services.api_gateway.audit_trail import write_audit_entry
from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_optional_cosmos_client

router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscription-onboarding"])
logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
COSMOS_DATABASE = "aap"
SUBSCRIPTIONS_CONTAINER = "subscriptions"


# ─── Pydantic models ─────────────────────────────────────────────────────────

class OnboardRequest(BaseModel):
    subscription_id: str
    display_name: str = ""
    tenant_id: str
    client_id: str
    client_secret: str
    secret_expires_at: Optional[str] = None
    environment: str = "prod"

    @field_validator("subscription_id", "tenant_id", "client_id")
    @classmethod
    def must_be_uuid(cls, v: str) -> str:
        if not _UUID_RE.match(v):
            raise ValueError(f"'{v}' is not a valid UUID")
        return v


class RotateCredentialsRequest(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    secret_expires_at: Optional[str] = None


# ─── Internal helpers ─────────────────────────────────────────────────────────

async def _check_auth(tenant_id: str, client_id: str, client_secret: str, subscription_id: str) -> bool:
    """Verify SPN credentials can authenticate and read the target subscription."""
    try:
        from azure.mgmt.subscription import SubscriptionClient
        cred = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        loop = asyncio.get_event_loop()
        sub_client = SubscriptionClient(cred)
        await loop.run_in_executor(None, sub_client.subscriptions.get, subscription_id)
        return True
    except Exception as exc:
        logger.debug("_check_auth failed: %s", exc)
        return False


async def _validate_permissions(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    subscription_id: str,
) -> dict[str, str]:
    """Run all 7 permission checks concurrently. Returns permission_status dict."""
    cred = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    scope = f"/subscriptions/{subscription_id}"
    results: dict[str, str] = {}

    async def check_reader() -> None:
        try:
            from azure.mgmt.subscription import SubscriptionClient
            loop = asyncio.get_event_loop()
            client = SubscriptionClient(cred)
            await loop.run_in_executor(None, client.subscriptions.get, subscription_id)
            results["reader"] = "granted"
        except Exception:
            results["reader"] = "missing"

    async def check_role(key: str, checker_fn) -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, checker_fn)
            results[key] = "granted"
        except Exception:
            results[key] = "missing"

    async def check_monitoring_reader() -> None:
        try:
            from azure.mgmt.monitor import MonitorManagementClient
            client = MonitorManagementClient(cred, subscription_id)
            loop = asyncio.get_event_loop()
            gen = client.metric_definitions.list(f"{scope}/providers/Microsoft.Compute/virtualMachines/dummy")
            await loop.run_in_executor(None, lambda: next(iter(gen), None))
            results["monitoring_reader"] = "granted"
        except Exception:
            results["monitoring_reader"] = "missing"

    async def check_security_reader() -> None:
        try:
            from azure.mgmt.security import SecurityCenter
            client = SecurityCenter(cred, subscription_id)
            loop = asyncio.get_event_loop()
            gen = client.secure_scores.list()
            await loop.run_in_executor(None, lambda: next(iter(gen), None))
            results["security_reader"] = "granted"
        except Exception:
            results["security_reader"] = "missing"

    async def check_cost_reader() -> None:
        try:
            from azure.mgmt.costmanagement import CostManagementClient
            client = CostManagementClient(cred)
            # Attempt to list resource groups (cost management reader allows this)
            from azure.mgmt.resource import ResourceManagementClient
            rm_client = ResourceManagementClient(cred, subscription_id)
            loop = asyncio.get_event_loop()
            gen = rm_client.resource_groups.list()
            await loop.run_in_executor(None, lambda: next(iter(gen), None))
            results["cost_management_reader"] = "granted"
        except Exception:
            results["cost_management_reader"] = "missing"

    async def _check_action_permissions(key: str, required_action: str) -> None:
        try:
            from azure.mgmt.authorization import AuthorizationManagementClient
            client = AuthorizationManagementClient(cred, subscription_id)
            loop = asyncio.get_event_loop()
            # List permissions at subscription scope
            perms = await loop.run_in_executor(
                None,
                lambda: list(client.permissions.list_for_resource_group(
                    resource_group_name="dummy-rg-permission-check"
                )),
            )
            granted = any(
                required_action in (p.actions or []) or "*" in (p.actions or [])
                for p in perms
            )
            results[key] = "granted" if granted else "missing"
        except Exception:
            results[key] = "missing"

    await asyncio.gather(
        check_reader(),
        check_monitoring_reader(),
        check_security_reader(),
        check_cost_reader(),
        _check_action_permissions("vm_contributor", "Microsoft.Compute/virtualMachines/restart/action"),
        _check_action_permissions("aks_contributor", "Microsoft.ContainerService/managedClusters/write"),
        _check_action_permissions("container_apps_contributor", "Microsoft.App/containerApps/restart/action"),
    )
    return results


async def _upsert_cosmos_subscription(
    cosmos_client,
    sub_id: str,
    record: dict,
) -> None:
    """Upsert the subscription record in Cosmos DB."""
    if cosmos_client is None:
        logger.warning("_upsert_cosmos_subscription: no Cosmos client — skipping persistence")
        return
    db = cosmos_client.get_database_client(COSMOS_DATABASE)
    container = db.get_container_client(SUBSCRIPTIONS_CONTAINER)
    container.upsert_item(record)


async def _get_cosmos_subscription(cosmos_client, sub_id: str) -> Optional[dict]:
    """Fetch a subscription record from Cosmos. Returns None if not found."""
    if cosmos_client is None:
        return None
    try:
        db = cosmos_client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(SUBSCRIPTIONS_CONTAINER)
        return container.read_item(item=sub_id, partition_key=sub_id)
    except Exception:
        return None


async def _soft_delete_cosmos_subscription(cosmos_client, sub_id: str) -> None:
    """Mark subscription as deleted (soft-delete for audit trail)."""
    existing = await _get_cosmos_subscription(cosmos_client, sub_id)
    if existing is None:
        return
    existing["deleted_at"] = datetime.now(timezone.utc).isoformat()
    existing["monitoring_enabled"] = False
    await _upsert_cosmos_subscription(cosmos_client, sub_id, existing)


async def _list_subscriptions_from_cosmos(cosmos_client) -> list[dict]:
    """Fetch all non-deleted subscriptions."""
    if cosmos_client is None:
        return []
    try:
        db = cosmos_client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(SUBSCRIPTIONS_CONTAINER)
        query = "SELECT * FROM c WHERE NOT IS_DEFINED(c.deleted_at) OR c.deleted_at = null"
        return list(container.query_items(query=query, enable_cross_partition_query=True))
    except Exception as exc:
        logger.error("_list_subscriptions_from_cosmos: %s", exc)
        return []


async def _write_audit_log(request: Request, event_type: str, fields: dict) -> None:
    """Write an audit log entry. Fire-and-forget — never raises."""
    try:
        await write_audit_entry(
            request=request,
            event_type=event_type,
            resource_type="subscription",
            **fields,
        )
    except Exception as exc:
        logger.warning("_write_audit_log: failed to write audit log: %s", exc)


def _compute_days_until_expiry(expires_at: Optional[str]) -> Optional[int]:
    if not expires_at:
        return None
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        delta = exp - datetime.now(timezone.utc)
        return max(0, delta.days)
    except Exception:
        return None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/onboard/preview-validate", dependencies=[Depends(verify_token)])
async def preview_validate(body: OnboardRequest, request: Request):
    """Validate SPN credentials without saving anything."""
    auth_ok = await _check_auth(body.tenant_id, body.client_id, body.client_secret, body.subscription_id)
    if not auth_ok:
        raise HTTPException(status_code=422, detail={"error": "credential_auth_failed"})

    permission_status = await _validate_permissions(
        body.tenant_id, body.client_id, body.client_secret, body.subscription_id
    )

    # Write audit log (spec §13: subscription_preview_validated)
    await _write_audit_log(request, "subscription_preview_validated", {
        "subscription_id": body.subscription_id,
        "auth_ok": True,
        "permission_status": permission_status,
    })

    return {"auth_ok": True, "permission_status": permission_status}


@router.post("/onboard", status_code=201, dependencies=[Depends(verify_token)])
async def onboard_subscription(body: OnboardRequest, request: Request):
    """Onboard a new subscription with SPN credentials."""
    cosmos_client = request.app.state.cosmos_client
    store = request.app.state.credential_store

    # 1. Validate secret_expires_at is in the future if provided
    if body.secret_expires_at:
        exp = datetime.fromisoformat(body.secret_expires_at.replace("Z", "+00:00"))
        if exp <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail={"error": "secret_expires_at must be in the future"})

    # 2. Authenticate
    auth_ok = await _check_auth(body.tenant_id, body.client_id, body.client_secret, body.subscription_id)
    if not auth_ok:
        raise HTTPException(status_code=422, detail={"error": "credential_auth_failed"})

    # 3. Validate permissions (non-blocking — soft roles can be missing)
    permission_status = await _validate_permissions(
        body.tenant_id, body.client_id, body.client_secret, body.subscription_id
    )

    # 4. Write secret to KV
    kv_secret_name = store._kv_secret_name(body.subscription_id)
    kv_blob = {
        "client_id": body.client_id,
        "client_secret": body.client_secret,
        "tenant_id": body.tenant_id,
        "subscription_id": body.subscription_id,
    }
    try:
        await store.write_secret(body.subscription_id, kv_blob)
    except Exception as exc:
        logger.error("onboard: KV write failed for sub=%s: %s", body.subscription_id, exc)
        raise HTTPException(status_code=503, detail={"error": "kv_write_failed"})

    # 5. Upsert Cosmos record
    now = datetime.now(timezone.utc).isoformat()
    cosmos_record = {
        "id": body.subscription_id,
        "subscription_id": body.subscription_id,
        "display_name": body.display_name or body.subscription_id,
        "credential_type": "spn",
        "client_id": body.client_id,
        "tenant_id": body.tenant_id,
        "kv_secret_name": kv_secret_name,
        "secret_expires_at": body.secret_expires_at,
        "permission_status": permission_status,
        "last_validated_at": now,
        "monitoring_enabled": True,
        "environment": body.environment,
        "onboarded_at": now,
        "deleted_at": None,
    }
    try:
        await _upsert_cosmos_subscription(cosmos_client, body.subscription_id, cosmos_record)
    except Exception as exc:
        logger.error("onboard: Cosmos upsert failed for sub=%s: %s", body.subscription_id, exc)
        # Compensating transaction: attempt to delete KV secret
        try:
            await store.delete_secret(body.subscription_id)
        except Exception as kv_exc:
            logger.error(
                "onboard: compensating KV delete also failed for sub=%s secret=%s: %s",
                body.subscription_id, kv_secret_name, kv_exc,
            )
        raise HTTPException(status_code=503, detail={"error": "cosmos_write_failed"})

    # 6. Invalidate cache, write audit log
    await store.invalidate(body.subscription_id)
    await _write_audit_log(request, "subscription_onboarded", {
        "subscription_id": body.subscription_id,
        "display_name": body.display_name,
        "credential_type": "spn",
        "permission_status": permission_status,
    })

    return {
        "subscription_id": body.subscription_id,
        "display_name": body.display_name,
        "credential_type": "spn",
        "permission_status": permission_status,
        "message": "Subscription onboarded. Some permissions may take 2-5 minutes to propagate — re-validate if any show missing.",
    }


@router.get("/managed", dependencies=[Depends(verify_token)])
async def list_managed_subscriptions(request: Request):
    """List all monitored subscriptions (no secrets returned)."""
    cosmos_client = request.app.state.cosmos_client
    subs = await _list_subscriptions_from_cosmos(cosmos_client)

    enriched = []
    for sub in subs:
        enriched.append({
            "subscription_id": sub.get("subscription_id"),
            "display_name": sub.get("display_name", sub.get("subscription_id", "")),
            "credential_type": sub.get("credential_type", "mi"),
            "client_id": sub.get("client_id"),
            "permission_status": sub.get("permission_status", {}),
            "secret_expires_at": sub.get("secret_expires_at"),
            "days_until_expiry": _compute_days_until_expiry(sub.get("secret_expires_at")),
            "last_validated_at": sub.get("last_validated_at"),
            "monitoring_enabled": sub.get("monitoring_enabled", True),
            "environment": sub.get("environment", "prod"),
            "last_synced": sub.get("last_synced"),
        })

    return {"subscriptions": enriched, "total": len(enriched)}


@router.post("/onboard/{subscription_id}/validate", dependencies=[Depends(verify_token)])
async def revalidate_subscription(subscription_id: str, request: Request):
    """Re-validate stored credentials and update permission_status in Cosmos.

    Reads client_id + tenant_id from Cosmos (never from KV — client_secret is never
    returned), then re-fetches the full KV blob via CredentialStore to get the secret.
    This avoids accessing private attributes on ClientSecretCredential.
    """
    cosmos_client = request.app.state.cosmos_client
    store = request.app.state.credential_store

    existing = await _get_cosmos_subscription(cosmos_client, subscription_id)
    if existing is None:
        raise HTTPException(status_code=404, detail={"error": "subscription_not_found"})

    if existing.get("credential_type") != "spn":
        raise HTTPException(
            status_code=422,
            detail={"error": "subscription uses MI credentials — re-onboard with SPN first"},
        )

    # Re-fetch KV blob directly to get client_secret for validation
    # (CredentialStore.write_secret stores the full blob; we read it back)
    try:
        from azure.keyvault.secrets.aio import SecretClient as _KVClient
        import json as _json
        kv_client = store._get_secret_client()
        secret = await kv_client.get_secret(store._kv_secret_name(subscription_id))
        blob = _json.loads(secret.value)
    except Exception as exc:
        logger.warning("revalidate: KV fetch failed for sub=%s: %s", subscription_id, exc)
        raise HTTPException(status_code=424, detail={"error": "subscription_credentials_invalid"})

    permission_status = await _validate_permissions(
        blob["tenant_id"], blob["client_id"], blob["client_secret"],
        subscription_id,
    )

    now = datetime.now(timezone.utc).isoformat()
    previous_status = existing.get("permission_status", {})
    existing["permission_status"] = permission_status
    existing["last_validated_at"] = now
    await _upsert_cosmos_subscription(cosmos_client, subscription_id, existing)

    await _write_audit_log(request, "subscription_validated", {
        "subscription_id": subscription_id,
        "permission_status": permission_status,
        "changed_from": previous_status,
    })

    return {"subscription_id": subscription_id, "permission_status": permission_status}


@router.put("/onboard/{subscription_id}/credentials", dependencies=[Depends(verify_token)])
async def rotate_credentials(
    subscription_id: str,
    body: RotateCredentialsRequest,
    request: Request,
):
    """Rotate SPN credentials. Merges provided fields with existing KV blob.

    All four body fields are optional — only provided fields are updated.
    Sending only {"client_secret": "new-secret"} keeps existing client_id/tenant_id.
    At least client_secret must be supplied for re-authentication to work.
    """
    cosmos_client = request.app.state.cosmos_client
    store = request.app.state.credential_store

    existing = await _get_cosmos_subscription(cosmos_client, subscription_id)
    if existing is None:
        raise HTTPException(status_code=404, detail={"error": "subscription_not_found"})

    # Fetch current KV blob to merge with — avoids re-requiring client_secret if not rotating it
    try:
        import json as _json
        kv_client = store._get_secret_client()
        secret = await kv_client.get_secret(store._kv_secret_name(subscription_id))
        current_blob = _json.loads(secret.value)
    except Exception as exc:
        logger.warning("rotate_credentials: KV fetch failed for sub=%s: %s", subscription_id, exc)
        current_blob = {}

    # Merge — body fields override current blob; fall back to current values
    new_client_id = body.client_id or current_blob.get("client_id") or existing.get("client_id")
    new_tenant_id = body.tenant_id or current_blob.get("tenant_id") or existing.get("tenant_id")
    new_client_secret = body.client_secret or current_blob.get("client_secret")

    if not new_client_secret:
        raise HTTPException(status_code=422, detail={"error": "client_secret required — no existing secret found in KV"})

    # Validate merged credentials
    auth_ok = await _check_auth(new_tenant_id, new_client_id, new_client_secret, subscription_id)
    if not auth_ok:
        raise HTTPException(status_code=422, detail={"error": "credential_auth_failed"})

    # Write KV first, then invalidate cache (order is critical for race safety — spec §5.5)
    kv_blob = {
        "client_id": new_client_id,
        "client_secret": new_client_secret,
        "tenant_id": new_tenant_id,
        "subscription_id": subscription_id,
    }
    await store.write_secret(subscription_id, kv_blob)
    await store.invalidate(subscription_id)

    # Re-validate permissions with new creds
    permission_status = await _validate_permissions(
        new_tenant_id, new_client_id, new_client_secret, subscription_id
    )

    # Update Cosmos
    now = datetime.now(timezone.utc).isoformat()
    existing["client_id"] = new_client_id
    existing["tenant_id"] = new_tenant_id
    existing["permission_status"] = permission_status
    existing["last_validated_at"] = now
    if body.secret_expires_at:
        existing["secret_expires_at"] = body.secret_expires_at
    await _upsert_cosmos_subscription(cosmos_client, subscription_id, existing)

    await _write_audit_log(request, "subscription_credentials_rotated", {
        "subscription_id": subscription_id,
        "new_expires_at": body.secret_expires_at,
    })

    return {"subscription_id": subscription_id, "permission_status": permission_status}


@router.delete("/onboard/{subscription_id}", dependencies=[Depends(verify_token)])
async def remove_subscription(subscription_id: str, request: Request):
    """Soft-delete a subscription (preserves audit trail)."""
    cosmos_client = request.app.state.cosmos_client
    store = request.app.state.credential_store

    existing = await _get_cosmos_subscription(cosmos_client, subscription_id)
    if existing is None:
        raise HTTPException(status_code=404, detail={"error": "subscription_not_found"})

    display_name = existing.get("display_name", subscription_id)

    # Delete KV secret
    await store.delete_secret(subscription_id)

    # Soft-delete in Cosmos
    await _soft_delete_cosmos_subscription(cosmos_client, subscription_id)

    # Invalidate cache
    await store.invalidate(subscription_id)

    await _write_audit_log(request, "subscription_removed", {
        "subscription_id": subscription_id,
        "display_name": display_name,
    })

    return {"subscription_id": subscription_id, "status": "removed"}
```

- [ ] **Step 2: Register the router in main.py**

In `main.py`, add the import near other router imports:
```python
from services.api_gateway.subscription_credential_endpoints import router as subscription_credential_router
```

And register it (after existing subscription router):
```python
app.include_router(subscription_credential_router)
```

- [ ] **Step 3: Run tests — should pass**

```bash
python -m pytest services/api-gateway/tests/test_subscription_credential_endpoints.py -v
```
Expected: All tests PASS (or most pass — auth-check and permission tests will use mocks).

- [ ] **Step 4: Commit**

```bash
git add services/api-gateway/subscription_credential_endpoints.py services/api-gateway/tests/test_subscription_credential_endpoints.py services/api-gateway/main.py
git commit -m "feat: add SPN subscription onboarding endpoints (onboard, managed, validate, rotate, remove)"
```

---

## Chunk 2: Phase 2 — Credential routing across all endpoint files

### Task 9: Update all 78 get_credential usages to get_scoped_credential

**Files (affected — 78 usages across ~22 files):**

Key files to update (full list from grep output):
- `compliance_endpoints.py` (2 usages)
- `simulation_endpoints.py` (4 usages)
- `vm_detail.py` (4 usages)
- `alert_rule_audit_endpoints.py` (1 usage)
- `vnet_peering_endpoints.py` (2 usages)
- `budget_alert_endpoints.py` (1 usage)
- `vm_cost.py` (1 usage)
- `queue_depth_endpoints.py` (1 usage)
- `cve_endpoints.py` (2 usages)
- `identity_risk_endpoints.py` (1 usage)
- `patch_endpoints.py` (4 usages)
- `change_intelligence_endpoints.py` (1 usage)
- `app_service_endpoints.py` (1 usage)
- `topology_tree.py` (1 usage)
- `defender_endpoints.py` (1 usage)
- `aks_health_endpoints.py` (1 usage)
- `aks_endpoints.py` (1 usage)
- `lock_audit_endpoints.py` (1 usage)
- `backup_compliance_endpoints.py` (2 usages)
- `vm_chat.py` (1 usage)
- `quota_usage_endpoints.py` (1 usage)
- `security_posture_endpoints.py` (2 usages)
- `quota_endpoints.py` (4 usages)
- `vmss_endpoints.py` (1 usage)
- `private_endpoint_endpoints.py` (2 usages)
- `drift_endpoints.py` (3 usages)
- `vm_inventory.py` (1 usage)
- `vm_extension_endpoints.py` (1 usage)
- `subscription_endpoints.py` (2 usages)

- [ ] **Step 1: Write a test verifying the credential routing**

```python
# Append to services/api-gateway/tests/test_credential_store.py

@pytest.mark.asyncio
async def test_scoped_credential_used_for_subscription_endpoints():
    """Verify that subscription-scoped endpoints call credential_store.get() not app.state.credential."""
    # This test verifies the pattern is correct by checking vm_inventory uses get_scoped_credential
    import ast
    import pathlib

    p = pathlib.Path("services/api-gateway/vm_inventory.py")
    src = p.read_text()
    assert "get_scoped_credential" in src, (
        "vm_inventory.py must use get_scoped_credential, not get_credential"
    )
```

- [ ] **Step 2: Run — confirm fail**

```bash
python -m pytest services/api-gateway/tests/test_credential_store.py::test_scoped_credential_used_for_subscription_endpoints -v
```
Expected: FAIL — `get_scoped_credential` not yet in vm_inventory.py.

- [ ] **Step 3: Run the automated sed replacement across all 40 files**

The complete list of files to update (confirmed via grep — all contain both `Depends(get_credential)` and subscription-scoped routes):

```bash
FILES=(
  "services/api-gateway/aks_endpoints.py"
  "services/api-gateway/aks_health_endpoints.py"
  "services/api-gateway/alert_rule_audit_endpoints.py"
  "services/api-gateway/app_service_endpoints.py"
  "services/api-gateway/backup_compliance_endpoints.py"
  "services/api-gateway/budget_alert_endpoints.py"
  "services/api-gateway/capacity_endpoints.py"
  "services/api-gateway/cert_expiry_endpoints.py"
  "services/api-gateway/change_intelligence_endpoints.py"
  "services/api-gateway/compliance_endpoints.py"
  "services/api-gateway/cost_endpoints.py"
  "services/api-gateway/cve_endpoints.py"
  "services/api-gateway/defender_endpoints.py"
  "services/api-gateway/disk_audit_endpoints.py"
  "services/api-gateway/drift_endpoints.py"
  "services/api-gateway/finops_endpoints.py"
  "services/api-gateway/identity_risk_endpoints.py"
  "services/api-gateway/lock_audit_endpoints.py"
  "services/api-gateway/maintenance_endpoints.py"
  "services/api-gateway/nsg_audit_endpoints.py"
  "services/api-gateway/patch_endpoints.py"
  "services/api-gateway/policy_compliance_endpoints.py"
  "services/api-gateway/private_endpoint_endpoints.py"
  "services/api-gateway/queue_depth_endpoints.py"
  "services/api-gateway/quota_endpoints.py"
  "services/api-gateway/quota_usage_endpoints.py"
  "services/api-gateway/resources_inventory.py"
  "services/api-gateway/security_posture_endpoints.py"
  "services/api-gateway/simulation_endpoints.py"
  "services/api-gateway/storage_security_endpoints.py"
  "services/api-gateway/subscription_endpoints.py"
  "services/api-gateway/tagging_endpoints.py"
  "services/api-gateway/topology_tree.py"
  "services/api-gateway/vm_chat.py"
  "services/api-gateway/vm_cost.py"
  "services/api-gateway/vm_detail.py"
  "services/api-gateway/vm_extension_endpoints.py"
  "services/api-gateway/vm_inventory.py"
  "services/api-gateway/vmss_endpoints.py"
  "services/api-gateway/vnet_peering_endpoints.py"
)

# Run replacements for each file
for f in "${FILES[@]}"; do
  # Replace import — handles: "import get_credential", "import get_credential," and "import get_credential, X"
  sed -i '' 's/\bget_credential\b/get_scoped_credential/g' "$f"
  echo "Updated: $f"
done
```

> **DO NOT** change `dependencies.py` (the definition file — already done in Task 5), `main.py`, or any `test_*.py` file.
> **DO NOT** change files that lack `/{subscription_id}/` in their route paths (audit, auth, admin — these don't appear in the list above).

Verify: the `get_credential` function definition in `dependencies.py` still exists (we only renamed usages, not the definition):

```bash
grep "def get_credential" services/api-gateway/dependencies.py
```
Expected: `def get_credential(request: Request) -> DefaultAzureCredential:`

- [ ] **Step 4: Run the full test suite to catch regressions**

```bash
python -m pytest services/api-gateway/tests/ -v -x --timeout=60 2>&1 | tail -30
```
Expected: All existing tests PASS. New routing test PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api-gateway/*.py
git commit -m "feat: route all subscription-scoped endpoints through CredentialStore.get_scoped_credential"
```

---

## Chunk 3: Phase 3 — setup_spn.sh + Onboarding UI

### Task 10: Create setup_spn.sh script

**Files:**
- Create: `scripts/setup_spn.sh`

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# setup_spn.sh — Grant required Azure RBAC roles to a Service Principal
# and optionally onboard it to the AAP monitoring platform.
#
# Usage:
#   ./setup_spn.sh --subscription-id <uuid> --client-id <uuid> --tenant-id <uuid> [options]
#
# Options:
#   --subscription-id   Required. Azure subscription GUID
#   --client-id         Required. App Registration (SPN) client ID
#   --tenant-id         Required. Entra tenant ID
#   --sp-name           Optional. Label (default: aap-monitor-<sub-short>)
#   --onboard           Flag. Call platform onboard API after role assignments
#   --api-url           Required if --onboard. API gateway base URL
#   --skip-reader       Flag. Skip Reader assignment (already granted)
#   --dry-run           Flag. Print commands without executing
#   --help              Show this message

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
SUBSCRIPTION_ID=""
CLIENT_ID=""
TENANT_ID=""
SP_NAME=""
ONBOARD=false
API_URL=""
SKIP_READER=false
DRY_RUN=false

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription-id) SUBSCRIPTION_ID="$2"; shift 2 ;;
    --client-id)       CLIENT_ID="$2"; shift 2 ;;
    --tenant-id)       TENANT_ID="$2"; shift 2 ;;
    --sp-name)         SP_NAME="$2"; shift 2 ;;
    --onboard)         ONBOARD=true; shift ;;
    --api-url)         API_URL="$2"; shift 2 ;;
    --skip-reader)     SKIP_READER=true; shift ;;
    --dry-run)         DRY_RUN=true; shift ;;
    --help|-h)
      sed -n '/^# Usage/,/^$/p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Validate required args ────────────────────────────────────────────────────
if [[ -z "$SUBSCRIPTION_ID" || -z "$CLIENT_ID" || -z "$TENANT_ID" ]]; then
  echo "ERROR: --subscription-id, --client-id, and --tenant-id are required." >&2
  echo "Run with --help for usage." >&2
  exit 1
fi

if [[ "$ONBOARD" == true && -z "$API_URL" ]]; then
  echo "ERROR: --api-url is required when --onboard is set." >&2
  exit 1
fi

SP_NAME="${SP_NAME:-aap-monitor-${SUBSCRIPTION_ID:0:8}}"

# ── Helper ────────────────────────────────────────────────────────────────────
run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY-RUN] $*"
  else
    "$@"
  fi
}

check_mark() { echo "✅ $1"; }
warn_mark()  { echo "⚠️  $1"; }
fail_mark()  { echo "❌ $1"; }

# ── Verify subscription access ────────────────────────────────────────────────
echo ""
echo "Verifying subscription access..."
if ! az account show --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  echo "ERROR: Cannot access subscription $SUBSCRIPTION_ID. Run 'az login' first." >&2
  exit 1
fi
check_mark "Subscription $SUBSCRIPTION_ID accessible"

# ── Role assignments ──────────────────────────────────────────────────────────
echo ""
echo "Assigning required roles to SPN $CLIENT_ID on subscription $SUBSCRIPTION_ID..."
echo ""

SCOPE="/subscriptions/$SUBSCRIPTION_ID"

declare -a ROLES=(
  "Monitoring Reader"
  "Security Reader"
  "Cost Management Reader"
  "Virtual Machine Contributor"
  "Azure Kubernetes Service Contributor Role"
  "Container Apps Contributor"
)

if [[ "$SKIP_READER" == false ]]; then
  ROLES=("Reader" "${ROLES[@]}")
fi

for ROLE in "${ROLES[@]}"; do
  if run az role assignment create \
      --assignee "$CLIENT_ID" \
      --role "$ROLE" \
      --scope "$SCOPE" \
      --output none 2>/dev/null; then
    check_mark "$(printf '%-42s' "$ROLE") assigned"
  else
    warn_mark "$(printf '%-42s' "$ROLE") already assigned or assignment failed — check manually"
  fi
done

# ── Onboard to platform ───────────────────────────────────────────────────────
if [[ "$ONBOARD" == true ]]; then
  echo ""
  echo "Onboarding subscription to AAP..."
  echo ""

  # Secure secret input — never on command line, never in history
  echo -n "Enter client secret (input hidden): "
  read -rs CLIENT_SECRET
  echo ""

  # Optional: display name and expiry
  echo -n "Display name for this subscription (press Enter to skip): "
  read DISPLAY_NAME
  echo -n "Secret expiry date ISO-8601 e.g. 2027-01-01T00:00:00Z (press Enter to skip): "
  read SECRET_EXPIRES_AT

  # Build JSON body (secret passed via stdin heredoc — never in process args)
  BODY=$(cat <<EOF
{
  "subscription_id": "$SUBSCRIPTION_ID",
  "display_name": "$DISPLAY_NAME",
  "tenant_id": "$TENANT_ID",
  "client_id": "$CLIENT_ID",
  "client_secret": "$CLIENT_SECRET",
  "secret_expires_at": "$SECRET_EXPIRES_AT",
  "environment": "prod"
}
EOF
)

  echo "Calling $API_URL/api/v1/subscriptions/onboard ..."

  # Validate AAP_TOKEN is set before calling auth-gated API
  if [[ -z "${AAP_TOKEN:-}" ]]; then
    echo "WARNING: AAP_TOKEN environment variable is not set."
    echo "The onboard endpoint requires an Entra ID Bearer token."
    echo "Set it with: export AAP_TOKEN=\$(az account get-access-token --query accessToken -o tsv)"
    echo ""
    echo "Skipping API onboard call — run manually with:"
    echo "  curl -X POST $API_URL/api/v1/subscriptions/onboard -H 'Authorization: Bearer <token>' -d '<body>'"
    exit 1
  fi

  RESPONSE=$(echo "$BODY" | curl -s -X POST \
    "$API_URL/api/v1/subscriptions/onboard" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${AAP_TOKEN}" \
    -d @- 2>&1) || true

  echo ""
  echo "Platform response:"
  echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

  # Parse and display permission_status
  if echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); [print('  ✅' if v=='granted' else '  ⚠️ ', k, '-', v) for k,v in d.get('permission_status',{}).items()]" 2>/dev/null; then
    echo ""
    echo "Note: permissions showing 'missing' may still be propagating (2-5 min). Re-validate in the UI."
  fi
fi

echo ""
echo "Done. If any roles show warnings, verify in Azure Portal > Subscriptions > Access control (IAM)."
```

```bash
chmod +x scripts/setup_spn.sh
```

- [ ] **Step 2: Smoke test the help output**

```bash
bash scripts/setup_spn.sh --help
```
Expected: Usage instructions printed.

- [ ] **Step 3: Commit**

```bash
git add scripts/setup_spn.sh
git commit -m "feat: add setup_spn.sh for automated SPN role assignment and subscription onboarding"
```

---

### Task 11: MonitoredSubscriptionsTab — write failing component test

**Files:**
- Create: `services/web-ui/components/__tests__/MonitoredSubscriptionsTab.test.tsx`
- Create: `services/web-ui/components/MonitoredSubscriptionsTab.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// services/web-ui/components/__tests__/MonitoredSubscriptionsTab.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MonitoredSubscriptionsTab } from '../MonitoredSubscriptionsTab'

// Mock fetch
beforeEach(() => {
  global.fetch = jest.fn()
})

const mockSubscriptions = [
  {
    subscription_id: '4c727b88-12f4-4c91-9c2b-372aab3bbae9',
    display_name: 'Production',
    credential_type: 'mi',
    client_id: null,
    permission_status: { reader: 'granted', monitoring_reader: 'granted' },
    secret_expires_at: null,
    days_until_expiry: null,
    last_validated_at: '2026-04-17T00:00:00Z',
    monitoring_enabled: true,
    environment: 'prod',
  },
]

test('renders subscription list from API', async () => {
  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ subscriptions: mockSubscriptions, total: 1 }),
  })

  render(<MonitoredSubscriptionsTab />)

  await waitFor(() => expect(screen.getByText('Production')).toBeInTheDocument())
  expect(screen.getByText('1')).toBeInTheDocument() // total badge
})

test('shows info banner collapsed by default', async () => {
  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ subscriptions: [], total: 0 }),
  })

  render(<MonitoredSubscriptionsTab />)

  expect(screen.getByText(/How to onboard/i)).toBeInTheDocument()
  // Banner content should be hidden initially
  expect(screen.queryByText(/Step 1: Create an App Registration/i)).not.toBeInTheDocument()
})

test('shows Add Subscription button', async () => {
  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ subscriptions: [], total: 0 }),
  })

  render(<MonitoredSubscriptionsTab />)

  await waitFor(() => expect(screen.getByRole('button', { name: /Add/i })).toBeInTheDocument())
})

test('shows MI badge for platform-managed subscriptions', async () => {
  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ subscriptions: mockSubscriptions, total: 1 }),
  })

  render(<MonitoredSubscriptionsTab />)

  await waitFor(() =>
    expect(screen.getByText(/Platform MI/i)).toBeInTheDocument()
  )
})
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd services/web-ui && npx jest MonitoredSubscriptionsTab --passWithNoTests 2>&1 | tail -20
```
Expected: FAIL — component does not exist.

---

### Task 12: Implement MonitoredSubscriptionsTab

**Files:**
- Create: `services/web-ui/components/MonitoredSubscriptionsTab.tsx`

- [ ] **Step 1: Create the component**

```tsx
// services/web-ui/components/MonitoredSubscriptionsTab.tsx
'use client'

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  ChevronDown,
  ChevronRight,
  Plus,
  RefreshCw,
  MoreHorizontal,
} from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ManagedSubscription {
  subscription_id: string
  display_name: string
  credential_type: 'spn' | 'mi'
  client_id: string | null
  permission_status: Record<string, string>
  secret_expires_at: string | null
  days_until_expiry: number | null
  last_validated_at: string | null
  monitoring_enabled: boolean
  environment: string
}

// ─── Permission icons ─────────────────────────────────────────────────────────

function PermIcon({ status }: { status: string }) {
  if (status === 'granted') return <span title="Granted">✅</span>
  if (status === 'missing') return <span title="Missing">⚠️</span>
  return <span title="Unknown">❓</span>
}

// ─── Expiry badge ─────────────────────────────────────────────────────────────

function ExpiryBadge({ daysUntilExpiry, secretExpiresAt }: {
  daysUntilExpiry: number | null
  secretExpiresAt: string | null
}) {
  if (!secretExpiresAt) {
    return (
      <Badge
        style={{ background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)' }}
        className="text-xs"
        title="No expiry date tracked"
      >
        ⚠️ No expiry
      </Badge>
    )
  }
  if (daysUntilExpiry !== null && daysUntilExpiry <= 0) {
    return (
      <Badge
        style={{ background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)' }}
        className="text-xs text-[var(--accent-red)]"
      >
        🔴 Expired
      </Badge>
    )
  }
  if (daysUntilExpiry !== null && daysUntilExpiry <= 30) {
    return (
      <Badge
        style={{ background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)' }}
        className="text-xs"
      >
        🟡 {daysUntilExpiry}d
      </Badge>
    )
  }
  return (
    <Badge
      style={{ background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)' }}
      className="text-xs text-[var(--accent-green)]"
    >
      🟢 {daysUntilExpiry}d
    </Badge>
  )
}

// ─── Info Banner ─────────────────────────────────────────────────────────────

function InfoBanner() {
  const [expanded, setExpanded] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('aap.spnBannerExpanded') === 'true'
    }
    return false
  })

  const toggle = () => {
    const next = !expanded
    setExpanded(next)
    if (typeof window !== 'undefined') {
      localStorage.setItem('aap.spnBannerExpanded', String(next))
    }
  }

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-canvas)] p-4 mb-4">
      <button
        onClick={toggle}
        className="flex w-full items-center justify-between text-sm font-medium text-[var(--text-primary)]"
      >
        <span>ℹ️ How to onboard a subscription</span>
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      {expanded && (
        <div className="mt-4 space-y-4 text-sm text-[var(--text-secondary)]">
          <div>
            <p className="font-semibold text-[var(--text-primary)] mb-1">
              Step 1: Create an App Registration (requires Entra ID access)
            </p>
            <ul className="ml-4 space-y-1 list-disc">
              <li>Azure Portal → Entra ID → App Registrations → New Registration</li>
              <li>Name: e.g. <code>aap-monitor-&lt;subscription-name&gt;</code></li>
              <li>Note the <strong>Application (client) ID</strong> and <strong>Directory (tenant) ID</strong></li>
              <li>Go to Certificates &amp; Secrets → New client secret</li>
              <li>⚠️ Copy the secret value immediately — it is shown once only</li>
            </ul>
          </div>

          <div>
            <p className="font-semibold text-[var(--text-primary)] mb-1">
              Step 2: Grant required roles on the target subscription
            </p>
            <p className="mb-2">
              Prerequisite: Owner or User Access Administrator on the target subscription.
            </p>
            <div className="bg-[var(--bg-surface)] rounded p-3 font-mono text-xs mb-2">
              {`./setup_spn.sh \\
  --subscription-id <id> \\
  --client-id <client-id> \\
  --tenant-id <tenant-id> \\
  --onboard \\
  --api-url https://your-api-gateway-url`}
            </div>
            <p className="text-xs">
              Required roles: Reader · Monitoring Reader · Security Reader ·
              Cost Management Reader · Virtual Machine Contributor ·
              Azure Kubernetes Service Contributor · Container Apps Contributor
            </p>
            <a
              href="/scripts/setup_spn.sh"
              download
              className="inline-flex items-center gap-1 text-[var(--accent-blue)] text-xs mt-1 hover:underline"
            >
              ⬇ Download setup_spn.sh
            </a>
          </div>

          <div>
            <p className="font-semibold text-[var(--text-primary)] mb-1">
              Step 3: Click &quot;+ Add&quot; above and enter your credentials
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export function MonitoredSubscriptionsTab() {
  const [subscriptions, setSubscriptions] = useState<ManagedSubscription[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAddDrawer, setShowAddDrawer] = useState(false)

  const fetchSubscriptions = async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/proxy/subscriptions/managed')
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setSubscriptions(data.subscriptions ?? [])
    } catch (e) {
      setError('Failed to load subscriptions')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchSubscriptions() }, [])

  return (
    <div className="space-y-4">
      <InfoBanner />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-[var(--text-primary)]">
            Monitored Subscriptions
          </h3>
          {!loading && (
            <Badge variant="secondary" className="text-xs">
              {subscriptions.length}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchSubscriptions}
            disabled={loading}
            title="Refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button
            size="sm"
            onClick={() => setShowAddDrawer(true)}
            className="bg-[var(--accent-blue)] text-white hover:opacity-90"
          >
            <Plus className="h-4 w-4 mr-1" />
            Add
          </Button>
        </div>
      </div>

      {error && (
        <p className="text-sm text-[var(--accent-red)]">{error}</p>
      )}

      {loading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 rounded bg-[var(--bg-surface)] animate-pulse" />
          ))}
        </div>
      ) : subscriptions.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--text-secondary)]">
          No subscriptions onboarded yet. Click &quot;+ Add&quot; to get started.
        </div>
      ) : (
        <div className="rounded-lg border border-[var(--border)] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--bg-surface)]">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Name</th>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Subscription ID</th>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Credential</th>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Permissions</th>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Secret Expiry</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {subscriptions.map((sub) => (
                <tr key={sub.subscription_id} className="hover:bg-[var(--bg-surface)] transition-colors">
                  <td className="px-3 py-2 font-medium text-[var(--text-primary)]">
                    {sub.display_name || sub.subscription_id}
                    {sub.environment && (
                      <span className="ml-1 text-xs text-[var(--text-secondary)]">
                        ({sub.environment})
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-[var(--text-secondary)]">
                    {sub.subscription_id}
                  </td>
                  <td className="px-3 py-2">
                    {sub.credential_type === 'spn' ? (
                      <Badge
                        style={{ background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)' }}
                        className="text-xs"
                      >
                        🔑 SPN
                      </Badge>
                    ) : (
                      <Badge
                        style={{ background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)' }}
                        className="text-xs"
                        title="Platform Managed Identity — re-onboard required"
                      >
                        🔵 Platform MI
                      </Badge>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-0.5">
                      {['reader', 'monitoring_reader', 'security_reader', 'cost_management_reader'].map((k) => (
                        <PermIcon key={k} status={sub.permission_status?.[k] ?? 'unknown'} />
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <ExpiryBadge
                      daysUntilExpiry={sub.days_until_expiry}
                      secretExpiresAt={sub.secret_expires_at}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => {}}>
                          Re-validate permissions
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => {}}>
                          Update credentials
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-[var(--accent-red)]"
                          onClick={() => {}}
                        >
                          Remove subscription
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Run component tests**

```bash
cd services/web-ui && npx jest MonitoredSubscriptionsTab 2>&1 | tail -20
```
Expected: All 4 tests PASS.

- [ ] **Step 3: Add proxy route for managed subscriptions endpoint**

Check if proxy route exists:
```bash
ls services/web-ui/app/api/proxy/subscriptions/ 2>/dev/null || echo "missing"
```

If missing, create `services/web-ui/app/api/proxy/subscriptions/managed/route.ts`:
```typescript
// services/web-ui/app/api/proxy/subscriptions/managed/route.ts
import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function GET(request: NextRequest) {
  const upstream = `${getApiGatewayUrl()}/api/v1/subscriptions/managed`
  const resp = await fetch(upstream, {
    headers: buildUpstreamHeaders(request),
    signal: AbortSignal.timeout(15000),
  })
  const data = await resp.json()
  return Response.json(data, { status: resp.status })
}
```

- [ ] **Step 4: Wire MonitoredSubscriptionsTab into AdminHubTab**

Read `services/web-ui/components/AdminHubTab.tsx` and update the sub-tabs:

Replace the `"Subscriptions"` tab reference with `"Monitored Subscriptions"` and render `<MonitoredSubscriptionsTab />`. Hide the `"Tenant & Admin"` tab (conditionally render `null` or remove from tabs array).

```tsx
// In AdminHubTab.tsx — update tabs array:
// BEFORE:
// { value: "subscriptions", label: "Subscriptions", component: <SubscriptionManagementTab /> }
// { value: "tenant", label: "Tenant & Admin", component: <TenantAdminTab /> }
//
// AFTER:
// { value: "monitored-subscriptions", label: "Monitored Subscriptions", component: <MonitoredSubscriptionsTab /> }
// (remove Tenant & Admin tab — hidden starting Phase 3)
```

- [ ] **Step 5: Commit**

```bash
git add services/web-ui/components/MonitoredSubscriptionsTab.tsx \
        services/web-ui/components/__tests__/MonitoredSubscriptionsTab.test.tsx \
        services/web-ui/app/api/proxy/subscriptions/ \
        services/web-ui/components/AdminHubTab.tsx
git commit -m "feat: add MonitoredSubscriptionsTab replacing SubscriptionManagementTab + TenantAdminTab"
```

---

### Task 12b: Add/Update Credential drawers + remaining proxy routes

**Files:**
- Modify: `services/web-ui/components/MonitoredSubscriptionsTab.tsx`
- Create: `services/web-ui/app/api/proxy/subscriptions/onboard/route.ts`
- Create: `services/web-ui/app/api/proxy/subscriptions/onboard/preview-validate/route.ts`
- Create: `services/web-ui/app/api/proxy/subscriptions/onboard/[id]/validate/route.ts`
- Create: `services/web-ui/app/api/proxy/subscriptions/onboard/[id]/credentials/route.ts`
- Create: `services/web-ui/app/api/proxy/subscriptions/onboard/[id]/route.ts`
- Create: `services/web-ui/components/__tests__/AddSubscriptionDrawer.test.tsx`
- Create: `services/web-ui/components/AddSubscriptionDrawer.tsx`

- [ ] **Step 1: Write failing tests for AddSubscriptionDrawer**

```tsx
// services/web-ui/components/__tests__/AddSubscriptionDrawer.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AddSubscriptionDrawer } from '../AddSubscriptionDrawer'

beforeEach(() => {
  global.fetch = jest.fn()
})

test('Validate button calls preview-validate endpoint', async () => {
  const user = userEvent.setup()
  const onSuccess = jest.fn()

  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      auth_ok: true,
      permission_status: { reader: 'granted', monitoring_reader: 'granted' },
    }),
  })

  render(<AddSubscriptionDrawer open={true} onClose={() => {}} onSuccess={onSuccess} />)

  await user.type(screen.getByLabelText(/Subscription ID/i), '4c727b88-12f4-4c91-9c2b-372aab3bbae9')
  await user.type(screen.getByLabelText(/Tenant ID/i), '11111111-2222-3333-4444-555555555555')
  await user.type(screen.getByLabelText(/Client ID/i), 'aaaabbbb-cccc-dddd-eeee-ffffffffffff')
  await user.type(screen.getByLabelText(/Client Secret/i), 's3cr3t')

  await user.click(screen.getByRole('button', { name: /Validate/i }))

  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/proxy/subscriptions/onboard/preview-validate',
      expect.objectContaining({ method: 'POST' }),
    )
  )
  expect(screen.getByText(/reader/i)).toBeInTheDocument()
})

test('Save button is disabled until Reader permission is confirmed', async () => {
  render(<AddSubscriptionDrawer open={true} onClose={() => {}} onSuccess={jest.fn()} />)
  expect(screen.getByRole('button', { name: /Save/i })).toBeDisabled()
})

test('Save button calls onboard endpoint on click', async () => {
  const user = userEvent.setup()
  const onSuccess = jest.fn()

  // First call: preview-validate
  ;(global.fetch as jest.Mock)
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        auth_ok: true,
        permission_status: { reader: 'granted' },
      }),
    })
    // Second call: onboard
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ subscription_id: '4c727b88-12f4-4c91-9c2b-372aab3bbae9' }),
    })

  render(<AddSubscriptionDrawer open={true} onClose={() => {}} onSuccess={onSuccess} />)

  await user.type(screen.getByLabelText(/Subscription ID/i), '4c727b88-12f4-4c91-9c2b-372aab3bbae9')
  await user.type(screen.getByLabelText(/Tenant ID/i), '11111111-2222-3333-4444-555555555555')
  await user.type(screen.getByLabelText(/Client ID/i), 'aaaabbbb-cccc-dddd-eeee-ffffffffffff')
  await user.type(screen.getByLabelText(/Client Secret/i), 's3cr3t')
  await user.click(screen.getByRole('button', { name: /Validate/i }))

  await waitFor(() => screen.getByRole('button', { name: /Save/i }))
  const saveBtn = screen.getByRole('button', { name: /Save/i })
  expect(saveBtn).not.toBeDisabled()
  await user.click(saveBtn)

  await waitFor(() => expect(onSuccess).toHaveBeenCalled())
})
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd services/web-ui && npx jest AddSubscriptionDrawer --passWithNoTests 2>&1 | tail -10
```
Expected: FAIL — component does not exist.

- [ ] **Step 3: Create AddSubscriptionDrawer component**

```tsx
// services/web-ui/components/AddSubscriptionDrawer.tsx
'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Loader2 } from 'lucide-react'

interface AddSubscriptionDrawerProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}

interface PermissionStatus {
  reader?: string
  monitoring_reader?: string
  security_reader?: string
  cost_management_reader?: string
  vm_contributor?: string
  aks_contributor?: string
  container_apps_contributor?: string
}

const PERM_LABELS: Record<string, string> = {
  reader: 'Reader',
  monitoring_reader: 'Monitoring Reader',
  security_reader: 'Security Reader',
  cost_management_reader: 'Cost Management Reader',
  vm_contributor: 'VM Contributor',
  aks_contributor: 'AKS Contributor',
  container_apps_contributor: 'Container Apps Contributor',
}

export function AddSubscriptionDrawer({ open, onClose, onSuccess }: AddSubscriptionDrawerProps) {
  const [form, setForm] = useState({
    subscription_id: '',
    display_name: '',
    tenant_id: '',
    client_id: '',
    client_secret: '',
    secret_expires_at: '',
    environment: 'prod',
  })
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [permStatus, setPermStatus] = useState<PermissionStatus | null>(null)
  const [validateError, setValidateError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [readerGranted, setReaderGranted] = useState(false)

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const handleValidate = async () => {
    setValidating(true)
    setValidateError(null)
    setPermStatus(null)
    setReaderGranted(false)
    try {
      const resp = await fetch('/api/proxy/subscriptions/onboard/preview-validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const data = await resp.json()
      if (!resp.ok) {
        setValidateError(data?.detail?.error ?? 'Validation failed')
        return
      }
      setPermStatus(data.permission_status)
      setReaderGranted(data.permission_status?.reader === 'granted')
    } catch {
      setValidateError('Network error — check API connectivity')
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const resp = await fetch('/api/proxy/subscriptions/onboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const data = await resp.json()
      if (!resp.ok) {
        setSaveError(data?.detail?.error ?? 'Onboard failed')
        return
      }
      onSuccess()
      onClose()
      setForm({ subscription_id: '', display_name: '', tenant_id: '', client_id: '', client_secret: '', secret_expires_at: '', environment: 'prod' })
      setPermStatus(null)
    } catch {
      setSaveError('Network error — check API connectivity')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={v => !v && onClose()}>
      <SheetContent className="w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Add Subscription</SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-4">
          <div>
            <label htmlFor="sub-id" className="block text-sm font-medium mb-1">Subscription ID *</label>
            <Input id="sub-id" aria-label="Subscription ID" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={form.subscription_id} onChange={set('subscription_id')} />
          </div>
          <div>
            <label htmlFor="display-name" className="block text-sm font-medium mb-1">Display Name</label>
            <Input id="display-name" aria-label="Display Name" placeholder="e.g. Production - APAC" value={form.display_name} onChange={set('display_name')} />
          </div>
          <div>
            <label htmlFor="tenant-id" className="block text-sm font-medium mb-1">Tenant ID *</label>
            <Input id="tenant-id" aria-label="Tenant ID" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={form.tenant_id} onChange={set('tenant_id')} />
          </div>
          <div>
            <label htmlFor="client-id" className="block text-sm font-medium mb-1">Client ID *</label>
            <Input id="client-id" aria-label="Client ID" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={form.client_id} onChange={set('client_id')} />
          </div>
          <div>
            <label htmlFor="client-secret" className="block text-sm font-medium mb-1">Client Secret *</label>
            <Input id="client-secret" aria-label="Client Secret" type="password" placeholder="App Registration client secret" value={form.client_secret} onChange={set('client_secret')} />
          </div>
          <div>
            <label htmlFor="secret-expiry" className="block text-sm font-medium mb-1">Secret Expiry Date</label>
            <Input id="secret-expiry" aria-label="Secret Expiry Date" type="date" value={form.secret_expires_at} onChange={set('secret_expires_at')} />
            {!form.secret_expires_at && (
              <p className="text-xs text-yellow-600 mt-1">⚠️ No expiry set — add one to enable expiry alerts</p>
            )}
          </div>
          <div>
            <label htmlFor="environment" className="block text-sm font-medium mb-1">Environment</label>
            <select id="environment" aria-label="Environment" className="w-full rounded border border-[var(--border)] p-2 text-sm bg-[var(--bg-canvas)]" value={form.environment} onChange={set('environment')}>
              <option value="prod">Production</option>
              <option value="staging">Staging</option>
              <option value="dev">Development</option>
            </select>
          </div>

          {validateError && (
            <p className="text-sm text-[var(--accent-red)] rounded border border-[var(--accent-red)] p-2">{validateError}</p>
          )}

          {permStatus && (
            <div className="rounded border border-[var(--border)] p-3 space-y-1">
              <p className="text-xs font-medium text-[var(--text-secondary)] mb-2">Permission Check Results</p>
              {Object.entries(PERM_LABELS).map(([key, label]) => {
                const status = permStatus[key as keyof PermissionStatus] ?? 'unknown'
                return (
                  <div key={key} className="flex items-center justify-between text-sm">
                    <span>{label}</span>
                    <Badge style={{ background: status === 'granted' ? 'color-mix(in srgb, var(--accent-green) 15%, transparent)' : 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)' }} className="text-xs">
                      {status === 'granted' ? '✅ Granted' : `⚠️ ${status}`}
                    </Badge>
                  </div>
                )
              })}
              {!readerGranted && (
                <p className="text-xs text-[var(--accent-red)] mt-2">⛔ Reader permission is required — cannot save until granted.</p>
              )}
              {readerGranted && (
                <p className="text-xs text-[var(--accent-green)] mt-2">Some permissions may still be propagating (2-5 min) — re-validate after saving if needed.</p>
              )}
            </div>
          )}

          {saveError && (
            <p className="text-sm text-[var(--accent-red)] rounded border border-[var(--accent-red)] p-2">{saveError}</p>
          )}

          <div className="flex gap-2 pt-2">
            <Button variant="outline" className="flex-1" onClick={handleValidate} disabled={validating}>
              {validating ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Validate
            </Button>
            <Button
              className="flex-1 bg-[var(--accent-blue)] text-white hover:opacity-90"
              onClick={handleSave}
              disabled={!readerGranted || saving}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Save
            </Button>
          </div>
          <Button variant="ghost" className="w-full" onClick={onClose}>Cancel</Button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 4: Create all remaining proxy routes**

```typescript
// services/web-ui/app/api/proxy/subscriptions/onboard/route.ts
import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function POST(request: NextRequest) {
  const body = await request.text()
  const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard`, {
    method: 'POST',
    headers: { ...buildUpstreamHeaders(request), 'Content-Type': 'application/json' },
    body,
    signal: AbortSignal.timeout(30000),
  })
  return Response.json(await resp.json(), { status: resp.status })
}
```

```typescript
// services/web-ui/app/api/proxy/subscriptions/onboard/preview-validate/route.ts
import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function POST(request: NextRequest) {
  const body = await request.text()
  const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard/preview-validate`, {
    method: 'POST',
    headers: { ...buildUpstreamHeaders(request), 'Content-Type': 'application/json' },
    body,
    signal: AbortSignal.timeout(30000),
  })
  return Response.json(await resp.json(), { status: resp.status })
}
```

```typescript
// services/web-ui/app/api/proxy/subscriptions/onboard/[id]/validate/route.ts
import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard/${params.id}/validate`, {
    method: 'POST',
    headers: buildUpstreamHeaders(request),
    signal: AbortSignal.timeout(30000),
  })
  return Response.json(await resp.json(), { status: resp.status })
}
```

```typescript
// services/web-ui/app/api/proxy/subscriptions/onboard/[id]/credentials/route.ts
import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function PUT(request: NextRequest, { params }: { params: { id: string } }) {
  const body = await request.text()
  const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard/${params.id}/credentials`, {
    method: 'PUT',
    headers: { ...buildUpstreamHeaders(request), 'Content-Type': 'application/json' },
    body,
    signal: AbortSignal.timeout(30000),
  })
  return Response.json(await resp.json(), { status: resp.status })
}
```

```typescript
// services/web-ui/app/api/proxy/subscriptions/onboard/[id]/route.ts
import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function DELETE(request: NextRequest, { params }: { params: { id: string } }) {
  const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard/${params.id}`, {
    method: 'DELETE',
    headers: buildUpstreamHeaders(request),
    signal: AbortSignal.timeout(15000),
  })
  return Response.json(await resp.json(), { status: resp.status })
}
```

- [ ] **Step 5: Wire AddSubscriptionDrawer into MonitoredSubscriptionsTab**

In `MonitoredSubscriptionsTab.tsx`, replace `{showAddDrawer && null}` (the stub) with:

```tsx
// Add import at top of MonitoredSubscriptionsTab.tsx:
import { AddSubscriptionDrawer } from './AddSubscriptionDrawer'

// Replace end of return JSX — add drawer after closing </div>:
<AddSubscriptionDrawer
  open={showAddDrawer}
  onClose={() => setShowAddDrawer(false)}
  onSuccess={fetchSubscriptions}
/>
```

Also wire up the DropdownMenu action items in the subscription rows:

```tsx
// Replace onClick={() => {}} stubs with real handlers:
// 1. Re-validate:
onClick={async () => {
  await fetch(`/api/proxy/subscriptions/onboard/${sub.subscription_id}/validate`, { method: 'POST' })
  fetchSubscriptions()
}}

// 2. Update credentials — open update drawer (add useState for updateTarget):
onClick={() => setUpdateTarget(sub.subscription_id)}

// 3. Remove subscription:
onClick={async () => {
  if (!confirm(`Remove monitoring for ${sub.display_name}? This cannot be undone.`)) return
  await fetch(`/api/proxy/subscriptions/onboard/${sub.subscription_id}`, { method: 'DELETE' })
  fetchSubscriptions()
}}
```

Add `updateTarget` state and an `UpdateCredentialsDrawer` (same as `AddSubscriptionDrawer` but with read-only `subscription_id`, calls `PUT /credentials`, and pre-fills `client_id`):

```tsx
const [updateTarget, setUpdateTarget] = useState<string | null>(null)

// Add after AddSubscriptionDrawer in JSX:
{updateTarget && (
  <UpdateCredentialsDrawer
    open={!!updateTarget}
    subscriptionId={updateTarget}
    onClose={() => setUpdateTarget(null)}
    onSuccess={fetchSubscriptions}
  />
)}
```

Create `services/web-ui/components/UpdateCredentialsDrawer.tsx` — same structure as `AddSubscriptionDrawer` but:
- `subscription_id` field is read-only (display only, not editable)
- `client_secret` placeholder: `"••••••••• — enter new secret to rotate"`
- On Save calls `PUT /api/proxy/subscriptions/onboard/{id}/credentials`
- All four body fields optional (per spec §5.5)

- [ ] **Step 6: Run tests**

```bash
cd services/web-ui && npx jest AddSubscriptionDrawer 2>&1 | tail -10
```
Expected: All 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add services/web-ui/components/AddSubscriptionDrawer.tsx \
        services/web-ui/components/UpdateCredentialsDrawer.tsx \
        services/web-ui/components/MonitoredSubscriptionsTab.tsx \
        services/web-ui/components/__tests__/AddSubscriptionDrawer.test.tsx \
        services/web-ui/app/api/proxy/subscriptions/
git commit -m "feat: add AddSubscriptionDrawer, UpdateCredentialsDrawer and all subscription proxy routes"
```

---

### Task 13: Populate SubscriptionContext from onboarded subscriptions

**Files:**
- Modify: `services/web-ui/lib/app-state-context.tsx` (or create `SubscriptionContext.tsx` if separate)

> The `selectedSubscriptions` state already exists in `app-state-context.tsx` and `NavSubscriptionPill.tsx` already exists. This task wires them to the real data.

- [ ] **Step 1: Read app-state-context.tsx to understand current shape**

```bash
head -60 services/web-ui/lib/app-state-context.tsx
```

- [ ] **Step 2: Add subscriptions data fetch to context provider**

In `app-state-context.tsx`, add a `managedSubscriptions` state that fetches from `/api/proxy/subscriptions/managed` on mount. Expose `managedSubscriptions` from the context. `NavSubscriptionPill` can then populate its dropdown from this data.

```typescript
// Add to AppState interface:
managedSubscriptions: ManagedSubscription[]

// Add to provider:
const [managedSubscriptions, setManagedSubscriptions] = useState<ManagedSubscription[]>([])

useEffect(() => {
  fetch('/api/proxy/subscriptions/managed')
    .then(r => r.json())
    .then(d => setManagedSubscriptions(d.subscriptions ?? []))
    .catch(() => {}) // silent fail — non-critical
}, [])
```

- [ ] **Step 3: Update NavSubscriptionPill to show real subscription names**

`NavSubscriptionPill.tsx` already exists. Read it to understand current rendering, then ensure it renders subscription display_name from `managedSubscriptions` context, grouped by environment.

- [ ] **Step 4: Add Subscription column to resource tables**

For each major resource table that shows multi-subscription data, add a Subscription column. Start with the most-used tab: `VMInventoryTab` / `ResourcesTab`.

Pattern to follow (find the relevant table file):
```bash
grep -rn "subscription_id" services/web-ui/components/ --include="*.tsx" | grep "column\|th\|header" | head -10
```

Add column definition pattern:
```tsx
// In table column definitions, add:
{
  header: 'Subscription',
  cell: ({ row }) => {
    const subId = row.original.subscription_id
    const sub = managedSubscriptions.find(s => s.subscription_id === subId)
    return (
      <span title={subId} className="text-xs text-[var(--text-secondary)]">
        {sub?.display_name ?? subId?.slice(0, 8) ?? '—'}
      </span>
    )
  }
}
```

- [ ] **Step 5: Commit**

```bash
git add services/web-ui/lib/app-state-context.tsx services/web-ui/components/NavSubscriptionPill.tsx services/web-ui/components/
git commit -m "feat: populate SubscriptionContext from API and add Subscription column to resource tables"
```

---

## Chunk 5: Phase 5 — Data migration + cleanup

### Task 14: Migrate tenants → platform_settings and drop tenants table

**Files:**
- Create: `services/api-gateway/migrations/011_migrate_tenants_to_settings.py`

- [ ] **Step 1: Write the test**

```python
# services/api-gateway/tests/test_tenant_migration.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_migration_up_copies_tenant_data():
    """Migration copies compliance_frameworks and operator_group_id to platform_settings."""
    import importlib
    migration = importlib.import_module(
        "services.api_gateway.migrations.011_migrate_tenants_to_settings"
    )

    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {"compliance_frameworks": '["ISO27001"]', "operator_group_id": "grp-abc"}
    ])
    mock_conn.execute = AsyncMock()

    await migration.up(mock_conn)

    # Should have called SELECT on tenants and INSERT/UPSERT to platform_settings
    mock_conn.fetch.assert_called_once()
    assert mock_conn.execute.call_count >= 1  # At minimum: upsert + drop


@pytest.mark.asyncio
async def test_migration_down_is_no_op():
    """down() is a no-op — DROP TABLE is irreversible; down documents this."""
    import importlib
    migration = importlib.import_module(
        "services.api_gateway.migrations.011_migrate_tenants_to_settings"
    )
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    await migration.down(mock_conn)
    # down is intentionally a no-op
```

- [ ] **Step 2: Run — confirm fail**

```bash
python -m pytest services/api-gateway/tests/test_tenant_migration.py -v 2>&1 | head -20
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create the migration**

```python
# services/api-gateway/migrations/011_migrate_tenants_to_settings.py
from __future__ import annotations
"""Migration 011: Move tenant data to platform_settings, then drop tenants table.

This migration:
1. Creates platform_settings table if it doesn't exist
2. Copies compliance_frameworks + operator_group_id from tenants → platform_settings
3. DROPs the tenants table

Run UP_SQL first in a transaction. Verify with down() (which is a no-op because
DROP TABLE is irreversible — re-create tenants from a backup if rollback needed).

Idempotent: safe to re-run if interrupted before DROP TABLE.
"""
import logging

logger = logging.getLogger(__name__)

UP_SQL = """
-- Step 1: Create platform_settings if not exists
CREATE TABLE IF NOT EXISTS platform_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Step 2: Copy compliance_frameworks from first (and typically only) tenant record
INSERT INTO platform_settings (key, value, updated_at)
SELECT 'compliance_frameworks', compliance_frameworks, NOW()
FROM tenants
WHERE compliance_frameworks IS NOT NULL
ORDER BY created_at ASC
LIMIT 1
ON CONFLICT (key) DO UPDATE
  SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;

-- Step 3: Copy operator_group_id from first tenant record
INSERT INTO platform_settings (key, value, updated_at)
SELECT 'operator_group_id', operator_group_id, NOW()
FROM tenants
WHERE operator_group_id IS NOT NULL
ORDER BY created_at ASC
LIMIT 1
ON CONFLICT (key) DO UPDATE
  SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;

-- Step 4: Drop tenants table (data is now in platform_settings)
DROP TABLE IF EXISTS tenants;
"""

DOWN_SQL = """
-- down() intentionally empty — DROP TABLE is irreversible.
-- If rollback is needed, restore the tenants table from a database backup.
SELECT 'migration 011 down: no-op - restore tenants from backup if required';
"""

DESCRIPTION = "Migrate tenant data to platform_settings and drop tenants table"


async def up(conn) -> None:  # noqa: ANN001
    """Run the migration. Idempotent."""
    logger.info("migration 011: reading tenants table...")
    rows = await conn.fetch("SELECT compliance_frameworks, operator_group_id FROM tenants LIMIT 1")
    if rows:
        row = rows[0]
        logger.info(
            "migration 011: found tenant data — compliance_frameworks=%s operator_group_id=%s",
            row.get("compliance_frameworks"),
            row.get("operator_group_id"),
        )
    await conn.execute(UP_SQL)
    logger.info("migration 011: tenants → platform_settings migration complete, tenants table dropped")


async def down(conn) -> None:  # noqa: ANN001
    """No-op — DROP TABLE is irreversible."""
    logger.warning(
        "migration 011 down: DROP TABLE is irreversible. "
        "Restore tenants table from a database backup if rollback is needed."
    )
    await conn.execute(DOWN_SQL)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest services/api-gateway/tests/test_tenant_migration.py -v
```
Expected: PASS.

- [ ] **Step 5: Verify no remaining code references the tenants table**

```bash
grep -rn "tenants" services/api-gateway/ --include="*.py" | grep -v test | grep -v __pycache__ | grep -v "migration" | grep -E "FROM tenants|INTO tenants|tenants WHERE|tenant_endpoints" | head -20
```
Expected: No results (or only migration files).

- [ ] **Step 6: Hide TenantAdminTab in AdminHubTab (if not already done in Phase 3)**

In `AdminHubTab.tsx`, verify the TenantAdminTab is no longer rendered.

- [ ] **Step 7: Remove TenantAdminTab.tsx**

Only do this after confirming no imports reference it:
```bash
grep -rn "TenantAdminTab" services/web-ui/ --include="*.tsx" --include="*.ts"
```
If only found in `TenantAdminTab.tsx` itself:
```bash
rm services/web-ui/components/TenantAdminTab.tsx
```

- [ ] **Step 8: Commit**

```bash
git add services/api-gateway/migrations/011_migrate_tenants_to_settings.py \
        services/api-gateway/tests/test_tenant_migration.py \
        services/web-ui/components/AdminHubTab.tsx
git commit -m "feat: migrate tenants table to platform_settings, remove TenantAdminTab"
```

---

## Chunk 6: Final integration + deployment wiring

### Task 15: Add KEY_VAULT_URL env var documentation and verify full test suite

**Files:**
- Modify: `services/api-gateway/.env.example` (if it exists, else README)

- [ ] **Step 1: Check for .env.example**

```bash
ls services/api-gateway/.env* 2>/dev/null || ls services/api-gateway/README* 2>/dev/null | head -5
```

- [ ] **Step 2: Add KEY_VAULT_URL to env example**

Add to the env example file:
```
# Key Vault URL for per-subscription SPN credential storage
KEY_VAULT_URL=https://kv-aap-prod.vault.azure.net/
```

- [ ] **Step 3: Run the full backend test suite**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/ -v --timeout=60 -x 2>&1 | tail -40
```
Expected: All existing tests + new tests PASS. Zero failures.

- [ ] **Step 4: Run frontend tests**

```bash
cd services/web-ui && npx jest --passWithNoTests 2>&1 | tail -20
```
Expected: All tests PASS.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: add KEY_VAULT_URL env documentation for SPN credential store"
```

---

### Task 16: ACR build and smoke test

- [ ] **Step 1: Build and push the API gateway image**

```bash
az acr build \
  --registry aapcrprodjgmjti \
  --image api-gateway:spn-onboarding \
  --agent-pool aap-builder-prod \
  --file services/api-gateway/Dockerfile \
  . 2>&1 | tail -20
```
Expected: `Run ID: ... was successful`

- [ ] **Step 2: Smoke test new endpoints against prod**

```bash
# List managed subscriptions (should return 200)
curl -s https://ca-api-gateway-prod.{your-domain}/api/v1/subscriptions/managed \
  -H "Authorization: Bearer $AAP_TOKEN" | python3 -m json.tool

# Preview validate (should return 422 — no real credentials)
curl -s -X POST https://ca-api-gateway-prod.{your-domain}/api/v1/subscriptions/onboard/preview-validate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AAP_TOKEN" \
  -d '{"subscription_id":"00000000-0000-0000-0000-000000000000","tenant_id":"00000000-0000-0000-0000-000000000001","client_id":"00000000-0000-0000-0000-000000000002","client_secret":"fake"}' | python3 -m json.tool
```

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: post-deploy smoke test fixes for SPN onboarding endpoints"
```

---

## Appendix: Files Created / Modified

| File | Action | Phase |
|------|--------|-------|
| `services/api-gateway/requirements.txt` | Modify — add azure-keyvault-secrets | 1 |
| `services/api-gateway/credential_store.py` | **Create** | 1 |
| `services/api-gateway/subscription_credential_endpoints.py` | **Create** | 1 |
| `services/api-gateway/migrations/010_subscription_spn_fields.py` | **Create** | 1 |
| `services/api-gateway/main.py` | Modify — wire CredentialStore + register router | 1 |
| `services/api-gateway/dependencies.py` | Modify — add get_scoped_credential | 1 |
| `services/api-gateway/tests/test_credential_store.py` | **Create** | 1 |
| `services/api-gateway/tests/test_subscription_credential_endpoints.py` | **Create** | 1 |
| `services/api-gateway/tests/test_subscription_spn_migration.py` | **Create** | 1 |
| `services/api-gateway/tests/test_dependencies.py` | Modify — append test | 1 |
| All 22+ subscription-scoped endpoint files | Modify — get_credential → get_scoped_credential | 2 |
| `scripts/setup_spn.sh` | **Create** | 3 |
| `services/web-ui/components/MonitoredSubscriptionsTab.tsx` | **Create** | 3 |
| `services/web-ui/components/__tests__/MonitoredSubscriptionsTab.test.tsx` | **Create** | 3 |
| `services/web-ui/app/api/proxy/subscriptions/managed/route.ts` | **Create** | 3 |
| `services/web-ui/components/AdminHubTab.tsx` | Modify — swap tabs | 3 |
| `services/web-ui/lib/app-state-context.tsx` | Modify — add managedSubscriptions | 4 |
| `services/web-ui/components/NavSubscriptionPill.tsx` | Modify — wire to real data | 4 |
| Resource table components (VMs, AKS, etc.) | Modify — add Subscription column | 4 |
| `services/api-gateway/migrations/011_migrate_tenants_to_settings.py` | **Create** | 5 |
| `services/api-gateway/tests/test_tenant_migration.py` | **Create** | 5 |
| `services/web-ui/components/TenantAdminTab.tsx` | **Delete** | 5 |
