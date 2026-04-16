---
wave: 1
depends_on: []
files_modified:
  - services/api-gateway/push_notifications.py
  - services/api-gateway/requirements.txt
  - services/api-gateway/main.py
  - services/api-gateway/tests/test_push_notifications.py
autonomous: true
---

## Goal

Implement the push notification backend that enables on-call operators to receive P0/P1 alerts on their phones. This wave creates `push_notifications.py` with a FastAPI router for subscription management and push delivery via `pywebpush`, stores subscriptions in Cosmos DB's `push_subscriptions` container (partition key `/subscription_endpoint_hash`), and wires a fire-and-forget push dispatch into the existing incident ingestion handler in `main.py`. Push is only triggered for severity values `Sev0`, `P0`, `Sev1`, and `P1`.

## Tasks

<task id="56-1-1">
### Create push_notifications.py with router and Cosmos subscription store

<read_first>
- file: services/api-gateway/approvals.py — model for Cosmos container access pattern, `_get_*_container()` helper, `Optional[CosmosClient]` dependency injection style, and fire-and-forget logging discipline
- file: services/api-gateway/requirements.txt — confirm `pywebpush` is not yet listed
- file: services/api-gateway/main.py lines 1-145 — understand existing import style, `DefaultAzureCredential`, `CosmosClient`, `BaseModel` usage
</read_first>

<action>
Create `services/api-gateway/push_notifications.py` with this exact structure:

```python
"""Push notification service — VAPID-signed Web Push for P0/P1 on-call alerts.

Stores subscriptions in Cosmos DB `push_subscriptions` container.
Sends push via pywebpush (VAPID). Fire-and-forget dispatch — never raises.

Env vars required:
  VAPID_PUBLIC_KEY  — URL-safe base64 VAPID public key
  VAPID_PRIVATE_KEY — URL-safe base64 VAPID private key
  VAPID_EMAIL       — mailto: contact (e.g. mailto:ops@example.com)
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

from azure.cosmos import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

# SDK guard — graceful degradation when pywebpush is not installed
try:
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover
    webpush = None  # type: ignore[assignment]
    WebPushException = Exception  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


# ─── Models ──────────────────────────────────────────────────────────────────


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    expiration_time: Optional[int] = None


# ─── Cosmos helpers ───────────────────────────────────────────────────────────


def _endpoint_hash(endpoint: str) -> str:
    """Return a short deterministic hash used as partition key."""
    return hashlib.sha256(endpoint.encode()).hexdigest()[:32]


def _get_subscriptions_container(
    cosmos_client: Optional[CosmosClient] = None,
) -> ContainerProxy:
    """Return the push_subscriptions Cosmos container, creating a client if needed."""
    if cosmos_client is None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            raise ValueError("COSMOS_ENDPOINT environment variable is required.")
        cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    database = cosmos_client.get_database_client(database_name)
    return database.get_container_client("push_subscriptions")


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.post("/subscribe", status_code=201)
async def subscribe(sub: PushSubscriptionRequest, request: Request) -> dict:
    """Store a browser push subscription in Cosmos DB.

    Called by the frontend after navigator.pushManager.subscribe().
    Idempotent — upserts by endpoint hash partition key.
    """
    cosmos_client = getattr(request.app.state, "cosmos_client", None)
    try:
        container = _get_subscriptions_container(cosmos_client=cosmos_client)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    ep_hash = _endpoint_hash(sub.endpoint)
    record = {
        "id": ep_hash,
        "subscription_endpoint_hash": ep_hash,
        "endpoint": sub.endpoint,
        "keys": sub.keys.model_dump(),
        "expiration_time": sub.expiration_time,
    }
    container.upsert_item(body=record)
    logger.info("push_subscription: upserted | hash=%s", ep_hash)
    return {"status": "subscribed", "hash": ep_hash}


@router.delete("/subscribe")
async def unsubscribe(sub: PushSubscriptionRequest, request: Request) -> dict:
    """Remove a push subscription from Cosmos DB.

    Called when the user revokes push permission or the subscription expires.
    Returns 200 even if subscription was not found (idempotent).
    """
    cosmos_client = getattr(request.app.state, "cosmos_client", None)
    try:
        container = _get_subscriptions_container(cosmos_client=cosmos_client)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    ep_hash = _endpoint_hash(sub.endpoint)
    try:
        container.delete_item(item=ep_hash, partition_key=ep_hash)
        logger.info("push_subscription: deleted | hash=%s", ep_hash)
    except CosmosResourceNotFoundError:
        logger.debug("push_subscription: delete no-op (not found) | hash=%s", ep_hash)
    return {"status": "unsubscribed", "hash": ep_hash}


@router.get("/vapid-public-key")
async def get_vapid_public_key() -> dict:
    """Return the VAPID public key for the frontend to use when subscribing.

    The frontend needs this to call pushManager.subscribe(applicationServerKey).
    """
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "")
    if not public_key:
        raise HTTPException(status_code=503, detail="VAPID_PUBLIC_KEY not configured")
    return {"vapidPublicKey": public_key}


# ─── Internal push dispatch ───────────────────────────────────────────────────


async def send_push_to_all(
    title: str,
    body: str,
    url: str = "/approvals",
    cosmos_client: Optional[CosmosClient] = None,
) -> int:
    """Send a push notification to all active subscriptions.

    Fire-and-forget: catches all exceptions per subscriber.
    Returns the count of successfully sent notifications.
    """
    if webpush is None:
        logger.warning("send_push_to_all: pywebpush not installed — push skipped")
        return 0

    vapid_private_key = os.environ.get("VAPID_PRIVATE_KEY", "")
    vapid_email = os.environ.get("VAPID_EMAIL", "mailto:ops@example.com")
    if not vapid_private_key:
        logger.warning("send_push_to_all: VAPID_PRIVATE_KEY not set — push skipped")
        return 0

    try:
        container = _get_subscriptions_container(cosmos_client=cosmos_client)
        items = list(
            container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True,
            )
        )
    except Exception as exc:
        logger.error("send_push_to_all: failed to read subscriptions | error=%s", exc)
        return 0

    payload_data = f'{{"title":"{title}","body":"{body}","url":"{url}"}}'
    sent = 0
    for item in items:
        ep_hash = item.get("subscription_endpoint_hash", "?")
        try:
            webpush(
                subscription_info={
                    "endpoint": item["endpoint"],
                    "keys": item["keys"],
                },
                data=payload_data,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_email},
            )
            sent += 1
            logger.debug("push_sent: hash=%s", ep_hash)
        except WebPushException as exc:
            # HTTP 410 Gone means the subscription was revoked — remove it
            if "410" in str(exc):
                logger.info("push_subscription: expired (410) | hash=%s", ep_hash)
                try:
                    container.delete_item(item=item["id"], partition_key=ep_hash)
                except Exception:
                    pass
            else:
                logger.warning("push_failed: hash=%s error=%s", ep_hash, exc)
        except Exception as exc:
            logger.warning("push_failed: hash=%s error=%s", ep_hash, exc)

    logger.info("send_push_to_all: sent=%d total=%d title=%r", sent, len(items), title)
    return sent
```
</action>

<acceptance_criteria>
1. File exists at `services/api-gateway/push_notifications.py`.
2. `webpush = None` guard at top — file imports without `pywebpush` installed.
3. `router` is an `APIRouter` with prefix `/api/v1/notifications`.
4. `POST /api/v1/notifications/subscribe` upserts to Cosmos; returns `{"status": "subscribed", "hash": ...}`.
5. `DELETE /api/v1/notifications/subscribe` removes by endpoint hash; idempotent (no 404 on missing).
6. `GET /api/v1/notifications/vapid-public-key` returns `{"vapidPublicKey": ...}` or 503 if env var missing.
7. `send_push_to_all` returns `int` (count sent), never raises.
8. 410 responses from push service auto-delete the expired subscription from Cosmos.
9. Partition key field name is `subscription_endpoint_hash` matching the container design.
</acceptance_criteria>
</task>

<task id="56-1-2">
### Add pywebpush to requirements.txt and register router in main.py

<read_first>
- file: services/api-gateway/requirements.txt — locate correct position to add pywebpush; confirm no existing entry
- file: services/api-gateway/main.py lines 100-145 — see existing router import/include pattern (e.g. `from services.api_gateway.health import router as health_router` then `app.include_router(health_router)`)
- file: services/api-gateway/main.py lines 563-590 — see where `app.include_router(...)` calls are grouped
- file: services/api-gateway/main.py lines 730-760 — see `ingest_incident` signature and where the `return IncidentResponse(...)` is (line ~1024) to know the insert point for push fire-and-forget
</read_first>

<action>
**Step 1 — requirements.txt**: Add `pywebpush>=2.0.0` after the `fastapi>=0.115.0` line under the `# API Gateway dependencies` section:

```
pywebpush>=2.0.0
```

**Step 2 — main.py import**: Add this import alongside the other router imports (near line 103–134):

```python
from services.api_gateway.push_notifications import router as push_router
from services.api_gateway.push_notifications import send_push_to_all
```

**Step 3 — main.py router registration**: Add this line in the `app.include_router(...)` block (after `app.include_router(compliance_router)`):

```python
app.include_router(push_router)
```

**Step 4 — main.py fire-and-forget**: In `ingest_incident`, immediately before the `return IncidentResponse(...)` statement (around line 1024), insert the following block. The existing `return` statement must remain intact after this block:

```python
    # Phase 56: Fire-and-forget push notification for P0/P1 incidents
    if payload.severity in ("Sev0", "P0", "Sev1", "P1"):
        _push_body = (
            payload.description[:100]
            if getattr(payload, "description", None)
            else "New incident requires attention"
        )
        asyncio.ensure_future(
            send_push_to_all(
                title=f"{payload.severity} Incident: {payload.title}",
                body=_push_body,
                url="/approvals",
                cosmos_client=cosmos,
            )
        )
        logger.info(
            "push: fire-and-forget dispatched | incident=%s severity=%s",
            payload.incident_id,
            payload.severity,
        )
```

Note: `payload.title` is already on `IncidentPayload` (confirmed from existing log message on line 749–753). The `cosmos` parameter is the `Depends(get_optional_cosmos_client)` arg already in scope.
</action>

<acceptance_criteria>
1. `pywebpush>=2.0.0` appears in `requirements.txt`.
2. `push_router` is imported from `services.api_gateway.push_notifications` in `main.py`.
3. `app.include_router(push_router)` is present in the router registration block.
4. `send_push_to_all` is imported in `main.py`.
5. The fire-and-forget block is inside `ingest_incident` and only fires for severities in `("Sev0", "P0", "Sev1", "P1")`.
6. `asyncio.ensure_future(send_push_to_all(...))` is used — not `await` (must not block the response).
7. The existing `return IncidentResponse(...)` is unchanged and still present.
8. `GET /api/v1/notifications/vapid-public-key` is reachable at runtime (router registered).
</acceptance_criteria>
</task>

<task id="56-1-3">
### Write tests for push_notifications.py

<read_first>
- file: services/api-gateway/push_notifications.py — the file just created; test every route and `send_push_to_all`
- file: services/api-gateway/approvals.py lines 1-30 — confirm import style used in test files for Cosmos mocking patterns
</read_first>

<action>
Create `services/api-gateway/tests/test_push_notifications.py`:

```python
"""Tests for push_notifications.py — routes and send_push_to_all logic."""
from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

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
```
</action>

<acceptance_criteria>
1. File exists at `services/api-gateway/tests/test_push_notifications.py`.
2. At least 15 test functions are defined.
3. Tests cover: VAPID key endpoint (key present + missing), subscribe (success + Cosmos 503), unsubscribe (success + 410 idempotent), `send_push_to_all` (no webpush, no VAPID key, sends to N subscriptions, 410 cleanup, per-subscriber error isolation, Cosmos read failure), and `_endpoint_hash` (deterministic + distinct).
4. All mocking uses `unittest.mock.patch` or `monkeypatch` — no real Cosmos or network calls.
5. `pytest.mark.asyncio` used for all `async` test functions.
</acceptance_criteria>
</task>

## Verification

```bash
# Confirm pywebpush added to requirements
grep "pywebpush" services/api-gateway/requirements.txt

# Confirm router import added to main.py
grep "push_router\|push_notifications" services/api-gateway/main.py

# Confirm fire-and-forget block present
grep "send_push_to_all\|ensure_future" services/api-gateway/main.py

# Run push notification tests (from repo root)
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_push_notifications.py -v

# Confirm module imports cleanly without pywebpush installed (SDK guard)
python -c "from services.api_gateway.push_notifications import router, send_push_to_all; print('import ok')"
```

## must_haves
- [ ] `pywebpush>=2.0.0` in `requirements.txt`
- [ ] SDK guard: `webpush = None` when `ImportError` — module loads without pywebpush
- [ ] Cosmos partition key field is `subscription_endpoint_hash`
- [ ] `send_push_to_all` never raises — all subscriber errors caught individually
- [ ] 410 HTTP response from push service auto-removes the stale subscription from Cosmos
- [ ] Fire-and-forget uses `asyncio.ensure_future(...)` — not `await` — does not block incident ingestion response
- [ ] Only `Sev0`, `P0`, `Sev1`, `P1` trigger push in `ingest_incident`
- [ ] 15+ tests all passing
