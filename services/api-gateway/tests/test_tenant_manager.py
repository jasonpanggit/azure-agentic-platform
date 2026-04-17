from __future__ import annotations
"""Tests for TenantManager and tenant middleware/endpoints (Phase 64)."""
import os

import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_gateway.tenant_manager import Tenant, TenantManager, _CacheEntry


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_tenant(**kwargs) -> Tenant:
    defaults = dict(
        name="platform-team",
        subscriptions=["sub-aaa", "sub-bbb"],
        sla_definitions=[{"name": "99.9% uptime"}],
        compliance_frameworks=["SOC2", "ISO27001"],
        operator_group_id="group-abc-123",
    )
    defaults.update(kwargs)
    return Tenant(**defaults)


def _asyncpg_row(tenant: Tenant) -> dict:
    """Simulate an asyncpg Record as a dict."""
    from datetime import datetime
    return {
        "tenant_id": tenant.tenant_id,
        "name": tenant.name,
        "subscriptions": tenant.subscriptions,
        "sla_definitions": tenant.sla_definitions,
        "compliance_frameworks": tenant.compliance_frameworks,
        "operator_group_id": tenant.operator_group_id,
        "created_at": datetime.fromisoformat(tenant.created_at),
    }


# ---------------------------------------------------------------------------
# test_create_tenant_stores_to_db
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_tenant_stores_to_db():
    """create_tenant should insert a row and return the created Tenant."""
    tenant = _make_tenant(name="engineering")
    row = _asyncpg_row(tenant)

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row)
    mock_conn.close = AsyncMock()

    with patch("services.api_gateway.tenant_manager.asyncpg") as mock_asyncpg:
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        mgr = TenantManager(postgres_dsn="postgresql://test/db")
        result = await mgr.create_tenant(tenant)

    assert result.name == "engineering"
    assert result.operator_group_id == tenant.operator_group_id
    mock_conn.fetchrow.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_get_tenant_for_operator_returns_correct_tenant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tenant_for_operator_returns_correct_tenant():
    """get_tenant_for_operator should resolve tenant by operator_group_id."""
    tenant = _make_tenant(name="ops-team", operator_group_id="group-ops-999")
    row = _asyncpg_row(tenant)

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row)
    mock_conn.close = AsyncMock()

    with patch("services.api_gateway.tenant_manager.asyncpg") as mock_asyncpg:
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        mgr = TenantManager(postgres_dsn="postgresql://test/db")
        result = await mgr.get_tenant_for_operator("group-ops-999")

    assert result is not None
    assert result.name == "ops-team"
    assert result.operator_group_id == "group-ops-999"


# ---------------------------------------------------------------------------
# test_tenant_isolation_different_subscriptions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tenant_isolation_different_subscriptions():
    """Two tenants should have completely separate subscription lists."""
    tenant_a = _make_tenant(name="team-a", subscriptions=["sub-001", "sub-002"], operator_group_id="grp-a")
    tenant_b = _make_tenant(name="team-b", subscriptions=["sub-999"], operator_group_id="grp-b")

    row_a = _asyncpg_row(tenant_a)
    row_b = _asyncpg_row(tenant_b)

    call_count = 0

    async def fake_fetchrow(query, operator_id):
        nonlocal call_count
        call_count += 1
        if operator_id == "grp-a":
            return row_a
        if operator_id == "grp-b":
            return row_b
        return None

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(side_effect=fake_fetchrow)
    mock_conn.close = AsyncMock()

    with patch("services.api_gateway.tenant_manager.asyncpg") as mock_asyncpg:
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        mgr = TenantManager(postgres_dsn="postgresql://test/db")
        result_a = await mgr.get_tenant_for_operator("grp-a")
        result_b = await mgr.get_tenant_for_operator("grp-b")

    assert result_a is not None
    assert result_b is not None
    # Subscriptions are isolated
    assert set(result_a.subscriptions) & set(result_b.subscriptions) == set()
    assert "sub-001" in result_a.subscriptions
    assert "sub-999" in result_b.subscriptions


# ---------------------------------------------------------------------------
# test_get_tenant_for_operator_caches_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tenant_for_operator_caches_result():
    """Second call with same operator_id should use cache, not hit DB."""
    tenant = _make_tenant(operator_group_id="grp-cached")
    row = _asyncpg_row(tenant)

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row)
    mock_conn.close = AsyncMock()

    with patch("services.api_gateway.tenant_manager.asyncpg") as mock_asyncpg:
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        mgr = TenantManager(postgres_dsn="postgresql://test/db")
        await mgr.get_tenant_for_operator("grp-cached")
        await mgr.get_tenant_for_operator("grp-cached")

    # DB should only be called once (second call uses cache)
    assert mock_conn.fetchrow.await_count == 1


# ---------------------------------------------------------------------------
# test_get_tenant_for_operator_returns_none_for_unknown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tenant_for_operator_returns_none_for_unknown():
    """Operator not in any tenant → returns None."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.close = AsyncMock()

    with patch("services.api_gateway.tenant_manager.asyncpg") as mock_asyncpg:
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        mgr = TenantManager(postgres_dsn="postgresql://test/db")
        result = await mgr.get_tenant_for_operator("unknown-operator")

    assert result is None


# ---------------------------------------------------------------------------
# test_middleware_returns_403_for_unknown_operator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_middleware_returns_403_for_unknown_operator():
    """Middleware should return 403 when operator is not in any tenant."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.api_gateway.tenant_middleware import TenantScopeMiddleware

    app = FastAPI()

    @app.get("/api/v1/test")
    async def test_endpoint():
        return {"ok": True}

    mock_mgr = AsyncMock()
    mock_mgr.get_tenant_for_operator = AsyncMock(return_value=None)

    app.add_middleware(TenantScopeMiddleware, tenant_manager=mock_mgr)

    import os
    with patch.dict(os.environ, {"TENANT_SCOPE_ENABLED": "true"}):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/test", headers={"X-Operator-Id": "unknown-op"})

    assert response.status_code == 403
    assert "not assigned to any tenant" in response.json()["error"]


# ---------------------------------------------------------------------------
# test_middleware_skips_health_and_admin_routes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_middleware_skips_health_and_admin_routes():
    """Middleware should pass through /health and /api/v1/admin/* without tenant check."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.api_gateway.tenant_middleware import TenantScopeMiddleware

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/admin/tenants")
    async def admin_tenants():
        return {"tenants": []}

    mock_mgr = AsyncMock()
    mock_mgr.get_tenant_for_operator = AsyncMock(return_value=None)

    app.add_middleware(TenantScopeMiddleware, tenant_manager=mock_mgr)

    import os
    with patch.dict(os.environ, {"TENANT_SCOPE_ENABLED": "true"}):
        client = TestClient(app, raise_server_exceptions=False)
        r1 = client.get("/health")
        r2 = client.get("/api/v1/admin/tenants")

    assert r1.status_code == 200
    assert r2.status_code == 200
    # Manager should NOT have been called for either
    mock_mgr.get_tenant_for_operator.assert_not_called()


# ---------------------------------------------------------------------------
# test_admin_list_tenants_endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_list_tenants_endpoint():
    """GET /api/v1/admin/tenants should return list of tenants."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.api_gateway.tenant_endpoints import router

    app = FastAPI()
    app.include_router(router)

    tenant_a = _make_tenant(name="alpha", operator_group_id="grp-alpha")
    tenant_b = _make_tenant(name="beta", operator_group_id="grp-beta")

    mock_mgr = AsyncMock()
    mock_mgr.list_tenants = AsyncMock(return_value=[tenant_a, tenant_b])
    app.state.tenant_manager = mock_mgr

    client = TestClient(app)
    response = client.get("/api/v1/admin/tenants")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    names = [t["name"] for t in data["tenants"]]
    assert "alpha" in names
    assert "beta" in names


# ---------------------------------------------------------------------------
# test_create_tenant_endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_tenant_endpoint():
    """POST /api/v1/admin/tenants should create and return a new tenant."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.api_gateway.tenant_endpoints import router

    app = FastAPI()
    app.include_router(router)

    new_tenant = _make_tenant(name="new-team", operator_group_id="grp-new")

    mock_mgr = AsyncMock()
    mock_mgr.create_tenant = AsyncMock(return_value=new_tenant)
    app.state.tenant_manager = mock_mgr

    client = TestClient(app)
    response = client.post(
        "/api/v1/admin/tenants",
        json={
            "name": "new-team",
            "operator_group_id": "grp-new",
            "subscriptions": ["sub-x"],
            "compliance_frameworks": ["SOC2"],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "new-team"
    mock_mgr.create_tenant.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_tenant_subscription_filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tenant_subscription_filter():
    """update_subscriptions should update and return the modified tenant."""
    tenant = _make_tenant(name="infra", subscriptions=["sub-old"], operator_group_id="grp-infra")
    updated = _make_tenant(name="infra", subscriptions=["sub-new-1", "sub-new-2"], operator_group_id="grp-infra")
    updated_row = _asyncpg_row(updated)

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=updated_row)
    mock_conn.close = AsyncMock()

    with patch("services.api_gateway.tenant_manager.asyncpg") as mock_asyncpg:
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        mgr = TenantManager(postgres_dsn="postgresql://test/db")
        result = await mgr.update_subscriptions(tenant.tenant_id, ["sub-new-1", "sub-new-2"])

    assert result is not None
    assert "sub-new-1" in result.subscriptions
    assert "sub-new-2" in result.subscriptions
    assert "sub-old" not in result.subscriptions
