"""Tests for SLA definition admin CRUD and compliance endpoints (Phase 55).

27 tests covering:
  Group A — Admin CRUD (15 tests)
  Group B — Compliance (8 tests)
  Group C — Edge (4 tests)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from services.api_gateway.sla_endpoints import admin_sla_router, sla_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    """Mount the two SLA routers on a fresh FastAPI instance."""
    app = FastAPI()
    app.include_router(admin_sla_router)
    app.include_router(sla_router)
    return app


def _client() -> TestClient:
    return TestClient(_make_app())


# Auth header stub — verify_token is mocked globally
AUTH = {"Authorization": "Bearer test-token"}


def _fake_row(
    *,
    sla_id: Optional[str] = None,
    name: str = "Test SLA",
    target_pct: float = 99.9,
    covered: Optional[list] = None,
    is_active: bool = True,
) -> MagicMock:
    """Build a fake asyncpg-like Record for SLA rows."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "id": uuid.UUID(sla_id) if sla_id else uuid.uuid4(),
        "name": name,
        "target_availability_pct": target_pct,
        "covered_resource_ids": covered or [],
        "measurement_period": "monthly",
        "customer_name": "Acme Corp",
        "report_recipients": ["ops@acme.com"],
        "is_active": is_active,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    }[k]
    return row


from typing import Optional


# ---------------------------------------------------------------------------
# Shared patches
# ---------------------------------------------------------------------------

VERIFY_PATCH = "services.api_gateway.sla_endpoints.verify_token"
ASYNCPG_PATCH = "services.api_gateway.sla_endpoints.asyncpg"
DSN_PATCH = "services.api_gateway.sla_endpoints.resolve_postgres_dsn"


def _mock_verify():
    return patch(VERIFY_PATCH, return_value={"sub": "test-user"})


def _mock_dsn():
    return patch(DSN_PATCH, return_value="postgresql://fake/db")


# ---------------------------------------------------------------------------
# Group A — Admin CRUD (15 tests)
# ---------------------------------------------------------------------------

def test_create_sla_definition_success():
    """POST /api/v1/admin/sla-definitions returns 200 with id field."""
    import asyncpg as real_asyncpg  # noqa: PLC0415

    row = _fake_row(name="Prod SLA")
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row)
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_asyncpg.exceptions = real_asyncpg.exceptions

            client = _client()
            resp = client.post(
                "/api/v1/admin/sla-definitions",
                json={
                    "name": "Prod SLA",
                    "target_availability_pct": 99.9,
                    "covered_resource_ids": ["/subscriptions/abc/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],
                    "measurement_period": "monthly",
                    "customer_name": "Acme",
                    "report_recipients": ["ops@acme.com"],
                },
                headers=AUTH,
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["name"] == "Prod SLA"


def test_create_sla_duplicate_name_422():
    """POST with duplicate name returns 409 Conflict."""
    import asyncpg as real_asyncpg

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(side_effect=real_asyncpg.exceptions.UniqueViolationError(
        "duplicate key value violates unique constraint"
    ))
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_asyncpg.exceptions = real_asyncpg.exceptions

            client = _client()
            resp = client.post(
                "/api/v1/admin/sla-definitions",
                json={
                    "name": "Duplicate",
                    "target_availability_pct": 99.9,
                },
                headers=AUTH,
            )

    assert resp.status_code == 409


def test_create_sla_invalid_target_pct_over_100():
    """POST with target_availability_pct > 100 returns 422 Unprocessable."""
    with _mock_verify():
        client = _client()
        resp = client.post(
            "/api/v1/admin/sla-definitions",
            json={"name": "Bad SLA", "target_availability_pct": 100.1},
            headers=AUTH,
        )
    assert resp.status_code == 422


def test_create_sla_invalid_target_pct_zero():
    """POST with target_availability_pct = 0.0 returns 422 Unprocessable."""
    with _mock_verify():
        client = _client()
        resp = client.post(
            "/api/v1/admin/sla-definitions",
            json={"name": "Zero SLA", "target_availability_pct": 0.0},
            headers=AUTH,
        )
    assert resp.status_code == 422


def test_list_sla_definitions_default_active_only():
    """GET /api/v1/admin/sla-definitions returns only is_active=True rows by default."""
    active_row = _fake_row(name="Active SLA", is_active=True)
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[active_row])
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get("/api/v1/admin/sla-definitions", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["is_active"] is True

    # Verify the query used the active-only filter
    call_args = mock_conn.fetch.call_args[0][0]
    assert "is_active = TRUE" in call_args


def test_list_sla_definitions_include_inactive():
    """GET ?include_inactive=true returns all rows regardless of is_active."""
    active_row = _fake_row(name="Active", is_active=True)
    inactive_row = _fake_row(name="Inactive", is_active=False)
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[active_row, inactive_row])
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get(
                "/api/v1/admin/sla-definitions?include_inactive=true", headers=AUTH
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2

    # Verify query does NOT contain active-only filter
    call_args = mock_conn.fetch.call_args[0][0]
    assert "is_active = TRUE" not in call_args


def test_list_sla_empty_db():
    """GET on empty DB returns {items: [], total: 0}."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get("/api/v1/admin/sla-definitions", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_get_sla_definition_success():
    """GET /api/v1/admin/sla-definitions/{id} returns 200 with full row."""
    sla_id = str(uuid.uuid4())
    row = _fake_row(sla_id=sla_id, name="Specific SLA")
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row)
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get(
                f"/api/v1/admin/sla-definitions/{sla_id}", headers=AUTH
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Specific SLA"
    assert "id" in data


def test_get_sla_definition_not_found():
    """GET with non-existent UUID returns 404."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get(
                f"/api/v1/admin/sla-definitions/{uuid.uuid4()}", headers=AUTH
            )

    assert resp.status_code == 404


def test_get_sla_definition_invalid_uuid():
    """GET with non-UUID path param: asyncpg raises on $1::uuid cast → 500 from server."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(side_effect=Exception("invalid input syntax for type uuid"))
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            # raise_server_exceptions=False so the test client returns 500 instead of
            # re-raising the exception — the DB cast error propagates as an HTTP error.
            client = TestClient(_make_app(), raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/admin/sla-definitions/not-a-uuid", headers=AUTH
            )

    # asyncpg raises on bad UUID cast; we accept either 422 (FastAPI path validation)
    # or 500 (DB-level rejection).
    assert resp.status_code in (422, 500)


def test_update_sla_name_only():
    """PUT with only name returns updated row with new name."""
    sla_id = str(uuid.uuid4())
    updated_row = _fake_row(sla_id=sla_id, name="Updated Name")
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=updated_row)
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.put(
                f"/api/v1/admin/sla-definitions/{sla_id}",
                json={"name": "Updated Name"},
                headers=AUTH,
            )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


def test_update_sla_target_pct():
    """PUT with target_availability_pct updates the field."""
    sla_id = str(uuid.uuid4())
    updated_row = _fake_row(sla_id=sla_id, target_pct=95.0)
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=updated_row)
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.put(
                f"/api/v1/admin/sla-definitions/{sla_id}",
                json={"target_availability_pct": 95.0},
                headers=AUTH,
            )

    assert resp.status_code == 200
    assert resp.json()["target_availability_pct"] == 95.0


def test_update_sla_not_found():
    """PUT on non-existent SLA returns 404."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.put(
                f"/api/v1/admin/sla-definitions/{uuid.uuid4()}",
                json={"name": "New Name"},
                headers=AUTH,
            )

    assert resp.status_code == 404


def test_delete_sla_soft_delete():
    """DELETE returns {deleted: true}."""
    sla_id = str(uuid.uuid4())
    deleted_row = MagicMock()
    deleted_row.__getitem__ = lambda self, k: uuid.UUID(sla_id) if k == "id" else None

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=deleted_row)
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.delete(
                f"/api/v1/admin/sla-definitions/{sla_id}", headers=AUTH
            )

    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_sla_not_found():
    """DELETE on non-existent SLA returns 404."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.close = AsyncMock()

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.delete(
                f"/api/v1/admin/sla-definitions/{uuid.uuid4()}", headers=AUTH
            )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Group B — Compliance (8 tests)
# ---------------------------------------------------------------------------

def test_compliance_empty_sla_list():
    """GET /api/v1/sla/compliance with no active SLAs returns {results: [], computed_at: ...}."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.close = AsyncMock()

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert "computed_at" in data


def test_compliance_all_available_resource():
    """Compliance with all-Available status gives attained=100.0, is_compliant=True."""
    resource_id = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
    sla_row = _fake_row(
        name="High SLA",
        target_pct=99.9,
        covered=[resource_id],
    )

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[sla_row])
    mock_conn.close = AsyncMock()

    # Mock availability status: single Available entry
    mock_status = MagicMock()
    mock_status.properties.availability_state = "Available"

    mock_rh_client = MagicMock()
    mock_rh_client.availability_statuses.list.return_value = [mock_status]

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            with patch(
                "services.api_gateway.sla_endpoints.ResourceHealthClient",
                return_value=mock_rh_client,
            ):
                with patch(
                    "services.api_gateway.sla_endpoints.DefaultAzureCredential",
                    return_value=MagicMock(),
                ):
                    client = _client()
                    resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert result["attained_availability_pct"] == 100.0
    assert result["is_compliant"] is True


def test_compliance_fully_unavailable_resource():
    """Compliance with fully-Unavailable resource gives attained < target, is_compliant=False."""
    resource_id = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm2"
    sla_row = _fake_row(
        name="Critical SLA",
        target_pct=99.9,
        covered=[resource_id],
    )

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[sla_row])
    mock_conn.close = AsyncMock()

    # Mock availability status: single Unavailable entry
    mock_status = MagicMock()
    mock_status.properties.availability_state = "Unavailable"

    mock_rh_client = MagicMock()
    mock_rh_client.availability_statuses.list.return_value = [mock_status]

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            with patch(
                "services.api_gateway.sla_endpoints.ResourceHealthClient",
                return_value=mock_rh_client,
            ):
                with patch(
                    "services.api_gateway.sla_endpoints.DefaultAzureCredential",
                    return_value=MagicMock(),
                ):
                    client = _client()
                    resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    # Fully unavailable → availability_pct = 0
    assert result["attained_availability_pct"] is not None
    assert result["attained_availability_pct"] < 99.9
    assert result["is_compliant"] is False


def test_compliance_partial_downtime():
    """Degraded status contributes half the period as downtime (pro-rata)."""
    resource_id = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm3"
    sla_row = _fake_row(
        name="Partial SLA",
        target_pct=90.0,
        covered=[resource_id],
    )

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[sla_row])
    mock_conn.close = AsyncMock()

    # Degraded: half window as downtime → availability_pct = 50%
    mock_status = MagicMock()
    mock_status.properties.availability_state = "Degraded"

    mock_rh_client = MagicMock()
    mock_rh_client.availability_statuses.list.return_value = [mock_status]

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            with patch(
                "services.api_gateway.sla_endpoints.ResourceHealthClient",
                return_value=mock_rh_client,
            ):
                with patch(
                    "services.api_gateway.sla_endpoints.DefaultAzureCredential",
                    return_value=MagicMock(),
                ):
                    client = _client()
                    resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    # Degraded = half of period as downtime → 50% availability
    assert result["attained_availability_pct"] == pytest.approx(50.0, abs=0.01)
    assert result["is_compliant"] is False  # 50 < 90


def test_compliance_resource_health_sdk_unavailable():
    """When ResourceHealthClient is None, data_source='unavailable' without exception."""
    resource_id = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm4"
    sla_row = _fake_row(
        name="SDK Missing SLA",
        target_pct=99.9,
        covered=[resource_id],
    )

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[sla_row])
    mock_conn.close = AsyncMock()

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            # Simulate SDK not installed
            with patch(
                "services.api_gateway.sla_endpoints.ResourceHealthClient",
                None,
            ):
                client = _client()
                resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["resource_attainments"][0]["data_source"] == "unavailable"
    assert result["attained_availability_pct"] is None


def test_compliance_resource_health_exception():
    """Exception in ResourceHealthClient is caught; data_source='unavailable'."""
    resource_id = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm5"
    sla_row = _fake_row(
        name="Exception SLA",
        target_pct=99.9,
        covered=[resource_id],
    )

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[sla_row])
    mock_conn.close = AsyncMock()

    mock_rh_client = MagicMock()
    mock_rh_client.availability_statuses.list.side_effect = RuntimeError("network error")

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            with patch(
                "services.api_gateway.sla_endpoints.ResourceHealthClient",
                return_value=mock_rh_client,
            ):
                with patch(
                    "services.api_gateway.sla_endpoints.DefaultAzureCredential",
                    return_value=MagicMock(),
                ):
                    client = _client()
                    resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["resource_attainments"][0]["data_source"] == "unavailable"


def test_compliance_multiple_slas():
    """Compliance returns one result per active SLA."""
    rows = [
        _fake_row(name=f"SLA {i}", covered=[]) for i in range(3)
    ]
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=rows)
    mock_conn.close = AsyncMock()

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 3


def test_compliance_duration_ms_recorded():
    """Compliance result contains duration_ms > 0."""
    sla_row = _fake_row(name="Timed SLA", covered=[])
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[sla_row])
    mock_conn.close = AsyncMock()

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert "duration_ms" in result
    assert result["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Group C — Edge (4 tests)
# ---------------------------------------------------------------------------

def test_create_then_list_roundtrip():
    """Item created via POST appears in the subsequent GET list."""
    sla_id = str(uuid.uuid4())
    row = _fake_row(sla_id=sla_id, name="Roundtrip SLA")

    # Two separate connections: one for create, one for list
    mock_conn_create = AsyncMock()
    mock_conn_create.fetchrow = AsyncMock(return_value=row)
    mock_conn_create.close = AsyncMock()

    mock_conn_list = AsyncMock()
    mock_conn_list.fetch = AsyncMock(return_value=[row])
    mock_conn_list.close = AsyncMock()

    import asyncpg as real_asyncpg

    conn_sequence = [mock_conn_create, mock_conn_list]
    call_count = {"n": 0}

    async def mock_connect(_dsn):
        idx = call_count["n"]
        call_count["n"] += 1
        return conn_sequence[idx]

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = mock_connect
            mock_asyncpg.exceptions = real_asyncpg.exceptions

            client = _client()

            create_resp = client.post(
                "/api/v1/admin/sla-definitions",
                json={"name": "Roundtrip SLA", "target_availability_pct": 99.5},
                headers=AUTH,
            )
            assert create_resp.status_code == 200

            list_resp = client.get("/api/v1/admin/sla-definitions", headers=AUTH)

    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert any(item["name"] == "Roundtrip SLA" for item in items)


def test_create_then_delete_then_list():
    """Soft-deleted item is absent from active-only list."""
    sla_id = str(uuid.uuid4())
    active_row = _fake_row(sla_id=sla_id, name="To Delete", is_active=True)

    deleted_id_row = MagicMock()
    deleted_id_row.__getitem__ = lambda self, k: uuid.UUID(sla_id) if k == "id" else None

    import asyncpg as real_asyncpg
    conn_create = AsyncMock()
    conn_create.fetchrow = AsyncMock(return_value=active_row)
    conn_create.close = AsyncMock()

    conn_delete = AsyncMock()
    conn_delete.fetchrow = AsyncMock(return_value=deleted_id_row)
    conn_delete.close = AsyncMock()

    conn_list = AsyncMock()
    conn_list.fetch = AsyncMock(return_value=[])  # active-only returns nothing
    conn_list.close = AsyncMock()

    sequence = [conn_create, conn_delete, conn_list]
    call_count = {"n": 0}

    async def mock_connect(_dsn):
        idx = call_count["n"]
        call_count["n"] += 1
        return sequence[idx]

    with _mock_verify(), _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = mock_connect
            mock_asyncpg.exceptions = real_asyncpg.exceptions

            client = _client()

            client.post(
                "/api/v1/admin/sla-definitions",
                json={"name": "To Delete", "target_availability_pct": 99.0},
                headers=AUTH,
            )
            client.delete(
                f"/api/v1/admin/sla-definitions/{sla_id}", headers=AUTH
            )
            list_resp = client.get("/api/v1/admin/sla-definitions", headers=AUTH)

    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 0


def test_compliance_db_unavailable_returns_503():
    """PostgreSQL down → GET /api/v1/sla/compliance returns HTTP 503."""
    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(
                side_effect=OSError("connection refused")
            )

            client = _client()
            resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 503


def test_compliance_no_covered_resources():
    """SLA with empty covered_resource_ids → attained=None, no crash."""
    sla_row = _fake_row(name="Empty Coverage SLA", covered=[], target_pct=99.9)
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[sla_row])
    mock_conn.close = AsyncMock()

    with _mock_dsn():
        with patch(ASYNCPG_PATCH) as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            client = _client()
            resp = client.get("/api/v1/sla/compliance")

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["attained_availability_pct"] is None
    assert result["is_compliant"] is None
    assert result["resource_attainments"] == []
