"""Tests for admin_endpoints.py — CRUD for remediation policies (Phase 51)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_DSN = "postgresql://test:test@localhost/test"


def _make_policy_row(
    *,
    name: str = "restart-dev-vms",
    action_class: str = "restart_vm",
    policy_id: str | None = None,
    enabled: bool = True,
    resource_tag_filter: str = "{}",
) -> dict[str, Any]:
    """Build a dict mimicking an asyncpg Record for remediation_policies."""
    pid = policy_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    return {
        "id": uuid.UUID(pid) if len(pid) == 36 else pid,
        "name": name,
        "description": "Test policy",
        "action_class": action_class,
        "resource_tag_filter": resource_tag_filter,
        "max_blast_radius": 10,
        "max_daily_executions": 20,
        "require_slo_healthy": True,
        "maintenance_window_exempt": False,
        "enabled": enabled,
        "created_at": now,
        "updated_at": now,
    }


class _FakeRecord(dict):
    """Dict subclass that supports attribute-style AND bracket access like asyncpg.Record."""

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


def _row(data: dict[str, Any]) -> _FakeRecord:
    return _FakeRecord(data)


# ---------------------------------------------------------------------------
# Fixture: FastAPI TestClient with mocked auth + postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """TestClient with admin_endpoints mounted + verify_token bypassed."""
    from services.api_gateway.admin_endpoints import router

    app = FastAPI()
    app.include_router(router)

    # Provide cosmos_client on app.state (set to None — no Cosmos)
    app.state.cosmos_client = None

    with patch(
        "services.api_gateway.admin_endpoints.verify_token",
        return_value={"sub": "test-user"},
    ):
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

POLICY_ID = str(uuid.uuid4())


class TestListPolicies:
    """GET /api/v1/admin/remediation-policies."""

    def test_list_policies_empty(self, client: TestClient):
        """Returns empty list when no policies exist."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.get("/api/v1/admin/remediation-policies")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_policies_returns_rows(self, client: TestClient):
        """Returns policies from PostgreSQL."""
        rows = [_row(_make_policy_row(name="policy-1")), _row(_make_policy_row(name="policy-2"))]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.get("/api/v1/admin/remediation-policies")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "policy-1"


class TestCreatePolicy:
    """POST /api/v1/admin/remediation-policies."""

    def test_create_policy_success(self, client: TestClient):
        """Creates a policy and returns 201."""
        created_row = _row(_make_policy_row(name="new-policy", policy_id=POLICY_ID))
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=created_row)
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.post(
                "/api/v1/admin/remediation-policies",
                json={
                    "name": "new-policy",
                    "action_class": "restart_vm",
                    "max_blast_radius": 5,
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "new-policy"
        assert body["action_class"] == "restart_vm"
        assert body["max_blast_radius"] == 10  # from row defaults

    def test_create_policy_invalid_action_class(self, client: TestClient):
        """Returns 400 for unknown action_class."""
        resp = client.post(
            "/api/v1/admin/remediation-policies",
            json={
                "name": "bad-policy",
                "action_class": "nonexistent",
            },
        )
        assert resp.status_code == 400
        assert "nonexistent" in resp.json()["detail"]

    def test_create_policy_duplicate_name(self, client: TestClient):
        """Returns 409 for duplicate policy name."""
        import asyncpg

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(
            side_effect=asyncpg.UniqueViolationError("")
        )
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.post(
                "/api/v1/admin/remediation-policies",
                json={
                    "name": "duplicate-name",
                    "action_class": "restart_vm",
                },
            )

        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]


class TestGetPolicy:
    """GET /api/v1/admin/remediation-policies/{policy_id}."""

    def test_get_policy_success(self, client: TestClient):
        """Returns the policy by UUID."""
        row = _row(_make_policy_row(policy_id=POLICY_ID))
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.get(f"/api/v1/admin/remediation-policies/{POLICY_ID}")

        assert resp.status_code == 200
        assert resp.json()["name"] == "restart-dev-vms"

    def test_get_policy_not_found(self, client: TestClient):
        """Returns 404 for nonexistent UUID."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.get(f"/api/v1/admin/remediation-policies/{POLICY_ID}")

        assert resp.status_code == 404


class TestUpdatePolicy:
    """PUT /api/v1/admin/remediation-policies/{policy_id}."""

    def test_update_policy_success(self, client: TestClient):
        """Updates specified fields and returns 200."""
        updated_row = _row(_make_policy_row(
            policy_id=POLICY_ID,
            name="updated-name",
        ))
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=updated_row)
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.put(
                f"/api/v1/admin/remediation-policies/{POLICY_ID}",
                json={"name": "updated-name"},
            )

        assert resp.status_code == 200
        assert resp.json()["name"] == "updated-name"

    def test_update_policy_not_found(self, client: TestClient):
        """Returns 404 for nonexistent UUID."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.put(
                f"/api/v1/admin/remediation-policies/{POLICY_ID}",
                json={"name": "nope"},
            )

        assert resp.status_code == 404

    def test_update_policy_invalid_action_class(self, client: TestClient):
        """Returns 400 when updating to an invalid action_class."""
        resp = client.put(
            f"/api/v1/admin/remediation-policies/{POLICY_ID}",
            json={"action_class": "bad_action"},
        )
        assert resp.status_code == 400


class TestDeletePolicy:
    """DELETE /api/v1/admin/remediation-policies/{policy_id}."""

    def test_delete_policy_success(self, client: TestClient):
        """Returns 204 on successful deletion."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.delete(f"/api/v1/admin/remediation-policies/{POLICY_ID}")

        assert resp.status_code == 204

    def test_delete_policy_not_found(self, client: TestClient):
        """Returns 404 when policy doesn't exist."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")
        mock_conn.close = AsyncMock()

        with patch(
            "services.api_gateway.admin_endpoints._get_pg_connection",
            return_value=mock_conn,
        ):
            resp = client.delete(f"/api/v1/admin/remediation-policies/{POLICY_ID}")

        assert resp.status_code == 404


class TestGetPolicyExecutions:
    """GET /api/v1/admin/remediation-policies/{policy_id}/executions."""

    def test_get_policy_executions_empty(self, client: TestClient):
        """Returns empty list when cosmos_client is None."""
        resp = client.get(f"/api/v1/admin/remediation-policies/{POLICY_ID}/executions")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_policy_executions_with_data(self, client: TestClient):
        """Returns executions from Cosmos when available."""
        from services.api_gateway.admin_endpoints import router

        # Create a fresh app with mock cosmos
        app = FastAPI()
        app.include_router(router)

        mock_container = MagicMock()
        mock_container.query_items.return_value = [
            {
                "id": "exec-1",
                "resource_id": "/subscriptions/sub-1/rg/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
                "proposed_action": "restart_vm",
                "status": "complete",
                "verification_result": "RESOLVED",
                "executed_at": "2026-04-14T10:00:00Z",
                "duration_ms": 1200.5,
            },
        ]

        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container
        app.state.cosmos_client = mock_cosmos

        with patch(
            "services.api_gateway.admin_endpoints.verify_token",
            return_value={"sub": "test-user"},
        ):
            test_client = TestClient(app)
            resp = test_client.get(
                f"/api/v1/admin/remediation-policies/{POLICY_ID}/executions"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["execution_id"] == "exec-1"
        assert data[0]["status"] == "complete"
