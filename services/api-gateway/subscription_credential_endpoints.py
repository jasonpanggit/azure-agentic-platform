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

from services.api_gateway.audit_trail import write_audit_record
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
        record = {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        await write_audit_record(record)
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
    """Re-validate stored credentials and update permission_status in Cosmos."""
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
    try:
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
    """Rotate SPN credentials. Merges provided fields with existing KV blob."""
    cosmos_client = request.app.state.cosmos_client
    store = request.app.state.credential_store

    existing = await _get_cosmos_subscription(cosmos_client, subscription_id)
    if existing is None:
        raise HTTPException(status_code=404, detail={"error": "subscription_not_found"})

    # Fetch current KV blob to merge with
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

    # Write KV first, then invalidate cache (order is critical for race safety)
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
