from __future__ import annotations
"""Tenant admin endpoints — CRUD for multi-tenant management.

Registers under /api/v1/admin/tenants.
These endpoints are excluded from TenantScopeMiddleware (admin/* skip list).
"""

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services.api_gateway.tenant_manager import Tenant, TenantManager

router = APIRouter(prefix="/api/v1/admin/tenants", tags=["tenant-admin"])
logger = logging.getLogger(__name__)


def _get_tenant_manager(request: Request) -> Optional[TenantManager]:
    """Resolve TenantManager from app.state (set in main.py lifespan)."""
    return getattr(request.app.state, "tenant_manager", None)


@router.get("", summary="List all tenants")
async def list_tenants(request: Request) -> Any:
    """Return all configured tenants.

    Returns empty list when PostgreSQL is not configured.
    """
    import time as _time
    start_time = _time.monotonic()
    try:
        mgr = _get_tenant_manager(request)
        if mgr is None:
            return {"tenants": [], "note": "TenantManager not configured"}

        tenants = await mgr.list_tenants()
        duration_ms = round((_time.monotonic() - start_time) * 1000, 1)
        logger.info("tenant_admin: list_tenants | count=%d duration_ms=%s", len(tenants), duration_ms)
        return {"tenants": [t.model_dump() for t in tenants], "total": len(tenants)}
    except Exception as exc:
        logger.warning("tenant_admin: list_tenants error | error=%s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("", summary="Create a new tenant", status_code=201)
async def create_tenant(payload: Tenant, request: Request) -> Any:
    """Create a new tenant record in PostgreSQL."""
    import time as _time
    start_time = _time.monotonic()
    try:
        mgr = _get_tenant_manager(request)
        if mgr is None:
            raise HTTPException(status_code=503, detail="TenantManager not configured")

        created = await mgr.create_tenant(payload)
        duration_ms = round((_time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "tenant_admin: create_tenant | tenant_id=%s name=%s duration_ms=%s",
            created.tenant_id, created.name, duration_ms,
        )
        return created.model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("tenant_admin: create_tenant error | error=%s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/{tenant_id}", summary="Get a tenant by ID")
async def get_tenant(tenant_id: str, request: Request) -> Any:
    """Return a single tenant by tenant_id UUID."""
    import time as _time
    start_time = _time.monotonic()
    try:
        mgr = _get_tenant_manager(request)
        if mgr is None:
            raise HTTPException(status_code=503, detail="TenantManager not configured")

        tenant = await mgr.get_tenant_by_id(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

        duration_ms = round((_time.monotonic() - start_time) * 1000, 1)
        logger.info("tenant_admin: get_tenant | tenant_id=%s duration_ms=%s", tenant_id, duration_ms)
        return tenant.model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("tenant_admin: get_tenant error | tenant_id=%s error=%s", tenant_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


class _SubscriptionUpdatePayload:
    pass


from pydantic import BaseModel


class SubscriptionListPayload(BaseModel):
    subscriptions: list[str]


@router.put("/{tenant_id}/subscriptions", summary="Update tenant subscription list")
async def update_tenant_subscriptions(
    tenant_id: str,
    payload: SubscriptionListPayload,
    request: Request,
) -> Any:
    """Replace the subscription list for a tenant."""
    import time as _time
    start_time = _time.monotonic()
    try:
        mgr = _get_tenant_manager(request)
        if mgr is None:
            raise HTTPException(status_code=503, detail="TenantManager not configured")

        updated = await mgr.update_subscriptions(tenant_id, payload.subscriptions)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

        duration_ms = round((_time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "tenant_admin: update_subscriptions | tenant_id=%s subs=%d duration_ms=%s",
            tenant_id, len(payload.subscriptions), duration_ms,
        )
        return updated.model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "tenant_admin: update_subscriptions error | tenant_id=%s error=%s", tenant_id, exc
        )
        return JSONResponse({"error": str(exc)}, status_code=500)
