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

Add a push notification backend to the API gateway so that P0/P1 incidents
(Sev0 and Sev1) trigger Web Push messages to all subscribed on-call operators.
Subscriptions are stored in Cosmos DB (`push_subscriptions` container).
VAPID signing uses `pywebpush`. Sending is fire-and-forget so it never blocks
incident ingestion.

---

## Tasks

<task id="56-1-1">
### Add pywebpush to requirements.txt

<read_first>
services/api-gateway/requirements.txt
</read_first>

<action>
Append the following line to `services/api-gateway/requirements.txt`, after the
`reportlab` entry and before the `# Test dependencies` comment:

```
# Web Push notifications — VAPID signing for PWA push (Phase 56)
pywebpush>=2.0.0
```
</action>

<acceptance_criteria>
- `requirements.txt` contains `pywebpush>=2.0.0`
- No other lines are modified
</acceptance_criteria>
</task>

<task id="56-1-2">
### Create push_notifications.py

<read_first>
services/api-gateway/approvals.py         (Cosmos access pattern + _get_container helper)
services/api-gateway/teams_notifier.py    (fire-and-forget async pattern)
services/api-gateway/dependencies.py      (get_cosmos_client signature)
services/api-gateway/models.py            (IncidentPayload — severity field uses Sev0/Sev1/Sev2/Sev3)
</read_first>

<action>
Create `services/api-gateway/push_notifications.py` with exactly the following
content.

Key design decisions:
- Cosmos container name: `push_subscriptions`
- Partition key on each document: `/subscription_endpoint_hash` (first 64 chars
  of SHA-256 hex digest of the endpoint URL, used as both `id` and partition key)
- `pywebpush` `WebPusher` class performs VAPID signing; it is synchronous, so
  each send runs in a thread pool via `asyncio.get_running_loop().run_in_executor`
- VAPID keys come from env vars: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
  `VAPID_EMAIL`
- `send_push_notifications` is the public fire-and-forget coroutine called from
  `main.py`; it catches all exceptions per-subscription so a single bad
  subscription never aborts the batch
- `router` exposes two FastAPI endpoints:
  - `POST /api/v1/notifications/subscribe` — upserts a subscription
  - `DELETE /api/v1/notifications/subscribe` — removes a subscription

```python
"""Push notification backend for on-call operator PWA (Phase 56).

Stores Web Push subscriptions in Cosmos DB ``push_subscriptions`` container
and sends VAPID-signed push messages to all subscribers when a P0/P1 incident
(Sev0 or Sev1) is ingested.

Environment variables required:
    VAPID_PUBLIC_KEY   — URL-safe base64-encoded uncompressed EC public key
    VAPID_PRIVATE_KEY  — URL-safe base64-encoded EC private key
    VAPID_EMAIL        — mailto: claim for VAPID JWT (e.g. mailto:ops@example.com)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Any, Optional

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.api_gateway.dependencies import get_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notifications"])

# ---------------------------------------------------------------------------
# Severity levels that trigger push notifications
# ---------------------------------------------------------------------------
PUSH_SEVERITY_LEVELS: frozenset[str] = frozenset({"Sev0", "Sev1"})

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class PushSubscriptionKeys(BaseModel):
    """Web Push subscription key material from the browser PushSubscription.toJSON()."""

    p256dh: str = Field(..., description="P-256 DH public key (base64url)")
    auth: str = Field(..., description="Auth secret (base64url)")


class PushSubscriptionRequest(BaseModel):
    """Body for POST /api/v1/notifications/subscribe."""

    endpoint: str = Field(..., description="Push service endpoint URL", min_length=10)
    keys: PushSubscriptionKeys
    operator_id: Optional[str] = Field(
        default=None,
        description="Optional operator identifier (email / UPN) for audit.",
    )


class PushSubscriptionDeleteRequest(BaseModel):
    """Body for DELETE /api/v1/notifications/subscribe."""

    endpoint: str = Field(..., description="Push service endpoint URL to remove")


# ---------------------------------------------------------------------------
# Cosmos helper
# ---------------------------------------------------------------------------


def _endpoint_hash(endpoint: str) -> str:
    """Return the first 64 hex characters of the SHA-256 hash of the endpoint URL.

    Used as both document ``id`` and partition key so each subscription maps
    1-to-1 to a Cosmos item.
    """
    return hashlib.sha256(endpoint.encode()).hexdigest()[:64]


def _get_subscriptions_container(cosmos_client: Optional[CosmosClient] = None):
    """Return the Cosmos DB ``push_subscriptions`` container proxy.

    Creates an ad-hoc client when the singleton is not available (tests /
    cold-start edge cases).
    """
    if cosmos_client is None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            raise ValueError("COSMOS_ENDPOINT environment variable is required.")
        from azure.identity import DefaultAzureCredential

        cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    db = cosmos_client.get_database_client(database_name)
    return db.get_container_client("push_subscriptions")


# ---------------------------------------------------------------------------
# VAPID / pywebpush helpers
# ---------------------------------------------------------------------------


def _get_vapid_config() -> dict[str, str]:
    """Read VAPID environment variables and return a config dict.

    Raises ``RuntimeError`` when any required variable is absent so callers
    can degrade gracefully without crashing the gateway.
    """
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "")
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "")
    email = os.environ.get("VAPID_EMAIL", "")
    if not public_key or not private_key or not email:
        raise RuntimeError(
            "VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, and VAPID_EMAIL must all be set."
        )
    return {"public_key": public_key, "private_key": private_key, "email": email}


def _send_one_push_sync(
    subscription_info: dict[str, Any],
    payload_json: str,
    vapid: dict[str, str],
) -> None:
    """Send a single Web Push message synchronously (runs in thread pool).

    Uses ``pywebpush.WebPusher`` directly so we control every step:
    1. Build the encrypted request via ``WebPusher(subscription_info).send()``.
    2. Sign the request with VAPID using ``vapid_claims`` and ``vapid_private_key``.

    ``pywebpush>=2.0.0`` API:
        from pywebpush import WebPusher
        WebPusher(subscription_info).send(
            data=payload_bytes,
            headers={},
            vapid_private_key=private_key,
            vapid_claims={"sub": email},
        )
    The method returns a ``requests.Response``; we log non-2xx but do not raise.
    """
    try:
        from pywebpush import WebPusher  # type: ignore[import]

        payload_bytes = payload_json.encode("utf-8")
        response = WebPusher(subscription_info).send(
            data=payload_bytes,
            headers={"Content-Type": "application/json"},
            vapid_private_key=vapid["private_key"],
            vapid_claims={"sub": vapid["email"]},
        )
        if response is not None and response.status_code >= 400:
            logger.warning(
                "push: non-2xx response | endpoint_hash=%.16s status=%s",
                _endpoint_hash(subscription_info.get("endpoint", "")),
                response.status_code,
            )
        else:
            logger.debug(
                "push: sent | endpoint_hash=%.16s",
                _endpoint_hash(subscription_info.get("endpoint", "")),
            )
    except Exception as exc:  # noqa: BLE001
        # Never raise — a broken subscription must not crash the batch.
        logger.error(
            "push: send failed | endpoint_hash=%.16s error=%s",
            _endpoint_hash(subscription_info.get("endpoint", "")),
            exc,
        )


# ---------------------------------------------------------------------------
# Public API — called from main.py
# ---------------------------------------------------------------------------


async def send_push_notifications(
    incident_id: str,
    severity: str,
    title: str,
    domain: str,
    cosmos_client: Optional[CosmosClient] = None,
) -> None:
    """Send Web Push to all subscribers for a P0/P1 incident (fire-and-forget).

    Only sends when ``severity`` is in ``PUSH_SEVERITY_LEVELS`` (Sev0, Sev1).
    Reads all subscriptions from Cosmos and fans out in the thread pool.
    Catches every per-subscription exception individually so one bad sub
    does not abort the rest.

    This coroutine should be called as a BackgroundTask from
    ``POST /api/v1/incidents`` — never awaited inline.
    """
    if severity not in PUSH_SEVERITY_LEVELS:
        logger.debug("push: skipping non-critical severity | severity=%s", severity)
        return

    try:
        vapid = _get_vapid_config()
    except RuntimeError as exc:
        logger.warning("push: VAPID not configured, skipping | reason=%s", exc)
        return

    try:
        container = _get_subscriptions_container(cosmos_client)
        items = list(
            container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("push: failed to read subscriptions | error=%s", exc)
        return

    if not items:
        logger.debug("push: no subscriptions registered, nothing to send")
        return

    payload_json = json.dumps(
        {
            "incident_id": incident_id,
            "severity": severity,
            "title": title,
            "domain": domain,
            "url": "/approvals",
        }
    )

    loop = asyncio.get_running_loop()
    tasks = []
    for item in items:
        subscription_info = {
            "endpoint": item.get("endpoint", ""),
            "keys": item.get("keys", {}),
        }
        task = loop.run_in_executor(
            None,
            _send_one_push_sync,
            subscription_info,
            payload_json,
            vapid,
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    sent = sum(1 for r in results if not isinstance(r, Exception))
    logger.info(
        "push: batch complete | incident_id=%s severity=%s sent=%d/%d",
        incident_id,
        severity,
        sent,
        len(items),
    )


# ---------------------------------------------------------------------------
# FastAPI route handlers
# ---------------------------------------------------------------------------


@router.post("/api/v1/notifications/subscribe", status_code=201)
async def subscribe(
    body: PushSubscriptionRequest,
    request: Request,
    cosmos: Optional[CosmosClient] = Depends(get_cosmos_client),
) -> dict[str, str]:
    """Store a Web Push subscription in Cosmos DB.

    Idempotent — upserts by ``subscription_endpoint_hash`` so re-subscribing
    (e.g., after a service worker update) simply refreshes the keys.
    """
    endpoint_hash = _endpoint_hash(body.endpoint)
    doc: dict[str, Any] = {
        "id": endpoint_hash,
        "subscription_endpoint_hash": endpoint_hash,
        "endpoint": body.endpoint,
        "keys": {
            "p256dh": body.keys.p256dh,
            "auth": body.keys.auth,
        },
        "operator_id": body.operator_id,
    }
    try:
        container = _get_subscriptions_container(cosmos)
        container.upsert_item(body=doc)
        logger.info("push: subscription upserted | hash=%.16s", endpoint_hash)
        return {"status": "subscribed", "id": endpoint_hash}
    except Exception as exc:
        logger.error("push: subscription store failed | error=%s", exc)
        raise HTTPException(status_code=500, detail="Failed to store subscription") from exc


@router.delete("/api/v1/notifications/subscribe", status_code=200)
async def unsubscribe(
    body: PushSubscriptionDeleteRequest,
    cosmos: Optional[CosmosClient] = Depends(get_cosmos_client),
) -> dict[str, str]:
    """Remove a Web Push subscription from Cosmos DB."""
    endpoint_hash = _endpoint_hash(body.endpoint)
    try:
        container = _get_subscriptions_container(cosmos)
        container.delete_item(item=endpoint_hash, partition_key=endpoint_hash)
        logger.info("push: subscription removed | hash=%.16s", endpoint_hash)
        return {"status": "unsubscribed"}
    except CosmosResourceNotFoundError:
        # Idempotent — already removed is not an error.
        return {"status": "not_found"}
    except Exception as exc:
        logger.error("push: subscription delete failed | error=%s", exc)
        raise HTTPException(status_code=500, detail="Failed to remove subscription") from exc
```
</action>

<acceptance_criteria>
- File is created at `services/api-gateway/push_notifications.py`
- `router` is a FastAPI `APIRouter` instance
- `send_push_notifications` is an `async def` coroutine
- `_send_one_push_sync` imports and calls `pywebpush.WebPusher`
- Module-level import of `pywebpush` is inside the function (try-block) so the
  module loads even if pywebpush is not yet installed in the test environment
- `_endpoint_hash` uses `hashlib.sha256`
- No secrets are hardcoded; all VAPID config comes from `os.environ`
</acceptance_criteria>
</task>

<task id="56-1-3">
### Wire push_notifications router and fire-and-forget into main.py

<read_first>
services/api-gateway/main.py    (full file — imports section ~L1-145, lifespan ~L315-420,
                                  incident ingestion handler ~L730-1030)
</read_first>

<action>
Make three targeted edits to `services/api-gateway/main.py`:

**Edit 1 — Add import** (after the existing `from services.api_gateway.war_room import ...` block,
around line 144):

```python
from services.api_gateway.push_notifications import (
    router as push_notifications_router,
    send_push_notifications,
)
```

**Edit 2 — Register router** (in the `app = FastAPI(...)` setup block, where all
other routers are included with `app.include_router(...)` — find the last
`app.include_router` call and add after it):

```python
app.include_router(push_notifications_router)
```

**Edit 3 — Fire-and-forget push in incident ingestion** (in the
`async def ingest_incident(...)` handler, immediately after the
`background_tasks.add_task(correlate_incident_changes, ...)` call block,
before the `blast_radius_summary` computation):

```python
    # Phase 56: Fire-and-forget Web Push to on-call operators for P0/P1
    background_tasks.add_task(
        send_push_notifications,
        incident_id=payload.incident_id,
        severity=payload.severity,
        title=payload.title,
        domain=payload.domain,
        cosmos_client=cosmos,
    )
    logger.info(
        "push: queued | incident_id=%s severity=%s",
        payload.incident_id,
        payload.severity,
    )
```

Verify that `payload.title` exists in `IncidentPayload` by checking `models.py`
before inserting — if the field name is different, use the correct name.
</action>

<acceptance_criteria>
- `push_notifications_router` is imported and registered with `app.include_router`
- `send_push_notifications` background task is queued inside the incident
  ingestion handler
- The push task is added AFTER the change-correlator task (maintaining existing
  ordering of background tasks)
- No existing code is removed or reordered — only additions
- `main.py` is still syntactically valid Python (no import errors)
</acceptance_criteria>
</task>

<task id="56-1-4">
### Write test_push_notifications.py (15+ tests)

<read_first>
services/api-gateway/tests/conftest.py             (fixture patterns — client, mock_cosmos_*)
services/api-gateway/tests/test_teams_notifier.py  (async mock pattern with patch)
services/api-gateway/push_notifications.py         (just created)
</read_first>

<action>
Create `services/api-gateway/tests/test_push_notifications.py` with the
following content. All tests use `pytest.mark.asyncio` for async coroutines and
`unittest.mock` for external dependencies.

```python
"""Tests for push_notifications.py (Phase 56)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_cosmos_push():
    """Mocked Cosmos DB push_subscriptions container."""
    container = MagicMock()
    container.upsert_item.return_value = {"id": "abc123"}
    container.delete_item.return_value = None
    container.query_items.return_value = []
    return container


@pytest.fixture()
def sample_subscription():
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/fake-token",
        "keys": {
            "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlTiMxp2KQVh5OqxW8Skfv2E6OvzD6tX6q2tFq8",
            "auth": "tBHItJI5svbpez7KI4CCXg",
        },
    }


@pytest.fixture()
def sample_subscription_doc(sample_subscription):
    return {
        "id": "abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
        "subscription_endpoint_hash": "abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
        "endpoint": sample_subscription["endpoint"],
        "keys": sample_subscription["keys"],
        "operator_id": "ops@example.com",
    }


# ---------------------------------------------------------------------------
# Unit tests — _endpoint_hash
# ---------------------------------------------------------------------------


class TestEndpointHash:
    def test_returns_64_char_hex_string(self):
        from services.api_gateway.push_notifications import _endpoint_hash

        result = _endpoint_hash("https://example.com/push/token")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_is_deterministic(self):
        from services.api_gateway.push_notifications import _endpoint_hash

        url = "https://fcm.googleapis.com/fcm/send/abc"
        assert _endpoint_hash(url) == _endpoint_hash(url)

    def test_different_urls_produce_different_hashes(self):
        from services.api_gateway.push_notifications import _endpoint_hash

        assert _endpoint_hash("https://a.com") != _endpoint_hash("https://b.com")


# ---------------------------------------------------------------------------
# Unit tests — _get_vapid_config
# ---------------------------------------------------------------------------


class TestGetVapidConfig:
    def test_returns_dict_when_all_vars_set(self):
        from services.api_gateway.push_notifications import _get_vapid_config

        with patch.dict(
            "os.environ",
            {
                "VAPID_PUBLIC_KEY": "pubkey",
                "VAPID_PRIVATE_KEY": "privkey",
                "VAPID_EMAIL": "mailto:ops@example.com",
            },
        ):
            config = _get_vapid_config()
        assert config["public_key"] == "pubkey"
        assert config["private_key"] == "privkey"
        assert config["email"] == "mailto:ops@example.com"

    def test_raises_runtime_error_when_vars_missing(self):
        from services.api_gateway.push_notifications import _get_vapid_config

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="VAPID"):
                _get_vapid_config()


# ---------------------------------------------------------------------------
# Unit tests — send_push_notifications
# ---------------------------------------------------------------------------


class TestSendPushNotifications:
    @pytest.mark.asyncio
    async def test_skips_low_severity(self):
        """Sev2 and Sev3 do not trigger push."""
        from services.api_gateway.push_notifications import send_push_notifications

        with patch("services.api_gateway.push_notifications._get_subscriptions_container") as mock_cont:
            await send_push_notifications(
                incident_id="inc-001",
                severity="Sev2",
                title="Disk full",
                domain="storage",
            )
            mock_cont.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_vapid_not_configured(self):
        """send_push_notifications returns early without crashing when VAPID is missing."""
        from services.api_gateway.push_notifications import send_push_notifications

        with patch.dict("os.environ", {}, clear=True), \
             patch("services.api_gateway.push_notifications._get_subscriptions_container") as mock_cont:
            # Should not raise
            await send_push_notifications(
                incident_id="inc-001",
                severity="Sev0",
                title="CPU critical",
                domain="compute",
            )
            mock_cont.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_to_all_subscribers_sev0(self, sample_subscription_doc):
        """Sev0 incident sends push to every subscription in Cosmos."""
        from services.api_gateway.push_notifications import send_push_notifications

        mock_container = MagicMock()
        mock_container.query_items.return_value = [sample_subscription_doc, sample_subscription_doc]

        mock_webpusher_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_webpusher_instance.send.return_value = mock_response

        with patch.dict(
            "os.environ",
            {"VAPID_PUBLIC_KEY": "pub", "VAPID_PRIVATE_KEY": "priv", "VAPID_EMAIL": "mailto:a@b.com"},
        ), \
        patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container), \
        patch("services.api_gateway.push_notifications.WebPusher", return_value=mock_webpusher_instance, create=True):
            await send_push_notifications(
                incident_id="inc-sev0",
                severity="Sev0",
                title="Host unreachable",
                domain="compute",
            )

        assert mock_container.query_items.called
        assert mock_webpusher_instance.send.call_count == 2

    @pytest.mark.asyncio
    async def test_sends_for_sev1(self, sample_subscription_doc):
        """Sev1 is also in PUSH_SEVERITY_LEVELS."""
        from services.api_gateway.push_notifications import send_push_notifications

        mock_container = MagicMock()
        mock_container.query_items.return_value = [sample_subscription_doc]

        mock_webpusher_instance = MagicMock()
        mock_webpusher_instance.send.return_value = MagicMock(status_code=201)

        with patch.dict(
            "os.environ",
            {"VAPID_PUBLIC_KEY": "pub", "VAPID_PRIVATE_KEY": "priv", "VAPID_EMAIL": "mailto:a@b.com"},
        ), \
        patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container), \
        patch("services.api_gateway.push_notifications.WebPusher", return_value=mock_webpusher_instance, create=True):
            await send_push_notifications(
                incident_id="inc-sev1",
                severity="Sev1",
                title="Memory pressure",
                domain="compute",
            )

        mock_webpusher_instance.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_op_when_no_subscriptions(self):
        """send_push_notifications completes without error when subscriber list is empty."""
        from services.api_gateway.push_notifications import send_push_notifications

        mock_container = MagicMock()
        mock_container.query_items.return_value = []

        with patch.dict(
            "os.environ",
            {"VAPID_PUBLIC_KEY": "pub", "VAPID_PRIVATE_KEY": "priv", "VAPID_EMAIL": "mailto:a@b.com"},
        ), \
        patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container):
            await send_push_notifications(
                incident_id="inc-001",
                severity="Sev0",
                title="Test",
                domain="compute",
            )
        # No exception raised; query_items was called once
        mock_container.query_items.assert_called_once()

    @pytest.mark.asyncio
    async def test_one_failing_push_does_not_abort_batch(self, sample_subscription_doc):
        """A RuntimeError from one WebPusher.send call must not abort the remaining sends."""
        from services.api_gateway.push_notifications import send_push_notifications

        mock_container = MagicMock()
        mock_container.query_items.return_value = [sample_subscription_doc, sample_subscription_doc]

        call_count = {"n": 0}

        def mock_send(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Push service unreachable")
            return MagicMock(status_code=201)

        mock_webpusher_instance = MagicMock()
        mock_webpusher_instance.send.side_effect = mock_send

        with patch.dict(
            "os.environ",
            {"VAPID_PUBLIC_KEY": "pub", "VAPID_PRIVATE_KEY": "priv", "VAPID_EMAIL": "mailto:a@b.com"},
        ), \
        patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container), \
        patch("services.api_gateway.push_notifications.WebPusher", return_value=mock_webpusher_instance, create=True):
            # Must not raise
            await send_push_notifications(
                incident_id="inc-001",
                severity="Sev0",
                title="Test",
                domain="compute",
            )

    @pytest.mark.asyncio
    async def test_payload_json_contains_approvals_url(self, sample_subscription_doc):
        """Push payload includes url=/approvals so the notification deep-links."""
        from services.api_gateway.push_notifications import send_push_notifications

        sent_payloads = []

        mock_container = MagicMock()
        mock_container.query_items.return_value = [sample_subscription_doc]

        def capture_send(data, **kwargs):
            sent_payloads.append(json.loads(data.decode("utf-8")))
            return MagicMock(status_code=201)

        mock_webpusher_instance = MagicMock()
        mock_webpusher_instance.send.side_effect = capture_send

        with patch.dict(
            "os.environ",
            {"VAPID_PUBLIC_KEY": "pub", "VAPID_PRIVATE_KEY": "priv", "VAPID_EMAIL": "mailto:a@b.com"},
        ), \
        patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container), \
        patch("services.api_gateway.push_notifications.WebPusher", return_value=mock_webpusher_instance, create=True):
            await send_push_notifications(
                incident_id="inc-789",
                severity="Sev0",
                title="Disk failure",
                domain="storage",
            )

        assert len(sent_payloads) == 1
        assert sent_payloads[0]["url"] == "/approvals"
        assert sent_payloads[0]["incident_id"] == "inc-789"
        assert sent_payloads[0]["severity"] == "Sev0"


# ---------------------------------------------------------------------------
# Integration tests — REST endpoints via TestClient
# ---------------------------------------------------------------------------


class TestSubscribeEndpoint:
    def test_subscribe_returns_201(self, sample_subscription):
        import os
        os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
        from services.api_gateway.main import app

        app.state.credential = MagicMock()
        app.state.cosmos_client = MagicMock()

        mock_container = MagicMock()
        mock_container.upsert_item.return_value = {"id": "hash"}

        with patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/notifications/subscribe",
                    json={
                        "endpoint": sample_subscription["endpoint"],
                        "keys": sample_subscription["keys"],
                        "operator_id": "ops@example.com",
                    },
                )
        assert resp.status_code == 201
        assert resp.json()["status"] == "subscribed"

    def test_subscribe_upserts_with_endpoint_hash_as_id(self, sample_subscription):
        import os
        os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
        from services.api_gateway.main import app
        from services.api_gateway.push_notifications import _endpoint_hash

        app.state.credential = MagicMock()
        app.state.cosmos_client = MagicMock()

        upserted_docs = []
        mock_container = MagicMock()
        mock_container.upsert_item.side_effect = lambda body: upserted_docs.append(body) or body

        with patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container):
            with TestClient(app) as client:
                client.post(
                    "/api/v1/notifications/subscribe",
                    json={
                        "endpoint": sample_subscription["endpoint"],
                        "keys": sample_subscription["keys"],
                    },
                )

        assert len(upserted_docs) == 1
        expected_hash = _endpoint_hash(sample_subscription["endpoint"])
        assert upserted_docs[0]["id"] == expected_hash
        assert upserted_docs[0]["subscription_endpoint_hash"] == expected_hash

    def test_subscribe_requires_endpoint_field(self):
        import os
        os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
        from services.api_gateway.main import app

        app.state.credential = MagicMock()
        app.state.cosmos_client = MagicMock()

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/notifications/subscribe",
                json={"keys": {"p256dh": "x", "auth": "y"}},
            )
        assert resp.status_code == 422

    def test_unsubscribe_returns_200(self, sample_subscription):
        import os
        os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
        from services.api_gateway.main import app

        app.state.credential = MagicMock()
        app.state.cosmos_client = MagicMock()

        mock_container = MagicMock()
        mock_container.delete_item.return_value = None

        with patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container):
            with TestClient(app) as client:
                resp = client.request(
                    method="DELETE",
                    url="/api/v1/notifications/subscribe",
                    json={"endpoint": sample_subscription["endpoint"]},
                )
        assert resp.status_code == 200
        assert resp.json()["status"] == "unsubscribed"

    def test_unsubscribe_not_found_is_200(self, sample_subscription):
        """Deleting a non-existent subscription returns 200 (idempotent)."""
        import os
        os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
        from services.api_gateway.main import app
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        app.state.credential = MagicMock()
        app.state.cosmos_client = MagicMock()

        mock_container = MagicMock()
        mock_container.delete_item.side_effect = CosmosResourceNotFoundError(
            message="Not found", response=MagicMock(status_code=404)
        )

        with patch("services.api_gateway.push_notifications._get_subscriptions_container", return_value=mock_container):
            with TestClient(app) as client:
                resp = client.request(
                    method="DELETE",
                    url="/api/v1/notifications/subscribe",
                    json={"endpoint": sample_subscription["endpoint"]},
                )
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"
```
</action>

<acceptance_criteria>
- File is created at `services/api-gateway/tests/test_push_notifications.py`
- Contains at least 15 test functions / methods
- All tests are importable without a real Cosmos DB or VAPID keys
- `pytest services/api-gateway/tests/test_push_notifications.py -v` passes (with
  pywebpush installed or mocked)
- No test modifies global `os.environ` state without restoring it (all use
  `patch.dict` context managers)
</acceptance_criteria>
</task>

---

## Verification

```bash
# 1. Confirm pywebpush appears in requirements
grep "pywebpush" services/api-gateway/requirements.txt

# 2. Syntax check new module
python -c "import ast; ast.parse(open('services/api-gateway/push_notifications.py').read()); print('syntax OK')"

# 3. Syntax check main.py still valid
python -c "import ast; ast.parse(open('services/api-gateway/main.py').read()); print('syntax OK')"

# 4. Run push notification tests (set AUTH_MODE to skip Entra)
cd /Users/jasonmba/workspace/azure-agentic-platform
API_GATEWAY_AUTH_MODE=disabled pytest services/api-gateway/tests/test_push_notifications.py -v

# 5. Check router is registered in main.py
grep "push_notifications_router" services/api-gateway/main.py

# 6. Check background task is wired
grep "send_push_notifications" services/api-gateway/main.py
```

## must_haves
- [ ] `pywebpush>=2.0.0` added to `requirements.txt`
- [ ] `push_notifications.py` created with `router`, `send_push_notifications`, `subscribe`, `unsubscribe`
- [ ] VAPID keys read exclusively from env vars — no hardcoded values
- [ ] `send_push_notifications` is fire-and-forget: never raises, per-subscription errors are caught
- [ ] Only `Sev0` and `Sev1` trigger push (Sev2/Sev3 skipped)
- [ ] `main.py` imports and registers `push_notifications_router`
- [ ] `main.py` queues `send_push_notifications` as BackgroundTask in incident ingestion
- [ ] 15+ tests in `test_push_notifications.py` all pass
- [ ] No existing tests broken (run `pytest services/api-gateway/tests/ -x -q` to confirm)
