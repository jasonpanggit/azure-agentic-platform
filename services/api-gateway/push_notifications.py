from __future__ import annotations
"""Push notification service — VAPID-signed Web Push for P0/P1 on-call alerts.

Stores subscriptions in Cosmos DB `push_subscriptions` container.
Sends push via pywebpush (VAPID). Fire-and-forget dispatch — never raises.

Env vars required:
  VAPID_PUBLIC_KEY  — URL-safe base64 VAPID public key
  VAPID_PRIVATE_KEY — URL-safe base64 VAPID private key
  VAPID_EMAIL       — mailto: contact (e.g. mailto:ops@example.com)
"""
import os

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
