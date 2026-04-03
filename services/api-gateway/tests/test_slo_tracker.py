"""Unit tests for the SLO Tracking Service (INTEL-004).

Tests cover:
- _compute_status pure function (tests 1–5)
- create_slo DB interaction (tests 6–7)
- update_slo_metrics computation (tests 8–9)
- check_domain_burn_rate_alert behavior (tests 10–12)
- list_slos non-fatal availability (test 13)
- get_slo_health KeyError path (test 14)
"""
from __future__ import annotations

import sys
import types

import pytest
from unittest.mock import AsyncMock


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_conn():
    """Minimal asyncpg connection mock."""
    conn = AsyncMock()
    conn.close = AsyncMock()
    return conn


@pytest.fixture(autouse=True)
def patch_asyncpg(mock_conn, monkeypatch):
    """Install a minimal asyncpg stub so tests run without the real package."""
    asyncpg_mod = types.ModuleType("asyncpg")
    asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
    sys.modules["asyncpg"] = asyncpg_mod
    # Ensure postgres DSN resolves in every test
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://test-user:test-pass@db.test:5432/aap")
    yield asyncpg_mod


# ---------------------------------------------------------------------------
# Helper: build a fake asyncpg Record-like dict
# ---------------------------------------------------------------------------


def _make_slo_row(**overrides):
    """Return a dict that mimics an asyncpg Record for slo_definitions."""
    base = {
        "id": "slo-uuid-001",
        "name": "Compute API Availability",
        "domain": "compute",
        "metric": "availability",
        "target_pct": 99.9,
        "window_hours": 24,
        "current_value": None,
        "error_budget_pct": None,
        "burn_rate_1h": None,
        "burn_rate_15min": None,
        "status": "healthy",
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests 1–5: _compute_status pure function
# ---------------------------------------------------------------------------


class TestComputeStatus:
    """_compute_status is a pure function — no DB, no mocks needed."""

    def test_compute_status_healthy(self):
        """All metrics within bounds → healthy."""
        from services.api_gateway.slo_tracker import _compute_status

        result = _compute_status(
            burn_rate_1h=1.0,
            burn_rate_15min=1.0,
            error_budget_pct=50.0,
        )
        assert result == "healthy"

    def test_compute_status_burn_rate_1h_alert(self):
        """burn_rate_1h exceeds 2.0 threshold → burn_rate_alert."""
        from services.api_gateway.slo_tracker import _compute_status

        result = _compute_status(
            burn_rate_1h=2.1,
            burn_rate_15min=None,
            error_budget_pct=50.0,
        )
        assert result == "burn_rate_alert"

    def test_compute_status_burn_rate_15min_alert(self):
        """burn_rate_15min exceeds 3.0 threshold → burn_rate_alert."""
        from services.api_gateway.slo_tracker import _compute_status

        result = _compute_status(
            burn_rate_1h=None,
            burn_rate_15min=3.1,
            error_budget_pct=50.0,
        )
        assert result == "burn_rate_alert"

    def test_compute_status_budget_exhausted(self):
        """Negative error budget → budget_exhausted."""
        from services.api_gateway.slo_tracker import _compute_status

        result = _compute_status(
            burn_rate_1h=None,
            burn_rate_15min=None,
            error_budget_pct=-5.0,
        )
        assert result == "budget_exhausted"

    def test_compute_status_budget_exhausted_takes_priority(self):
        """budget_exhausted has higher priority than burn_rate_alert."""
        from services.api_gateway.slo_tracker import _compute_status

        result = _compute_status(
            burn_rate_1h=5.0,
            burn_rate_15min=5.0,
            error_budget_pct=-1.0,
        )
        assert result == "budget_exhausted"


# ---------------------------------------------------------------------------
# Tests 6–7: create_slo
# ---------------------------------------------------------------------------


class TestCreateSlo:
    """create_slo inserts a row and returns the full dict."""

    @pytest.mark.anyio
    async def test_create_slo_returns_dict_with_id(self, mock_conn):
        """create_slo returns dict containing id, name, domain, status='healthy'."""
        from services.api_gateway.slo_tracker import create_slo

        row = _make_slo_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        result = await create_slo(
            name="Compute API Availability",
            domain="compute",
            metric="availability",
            target_pct=99.9,
            window_hours=24,
        )

        assert "id" in result
        assert result["name"] == "Compute API Availability"
        assert result["domain"] == "compute"
        assert result["status"] == "healthy"

    @pytest.mark.anyio
    async def test_create_slo_executes_insert_sql(self, mock_conn):
        """create_slo calls fetchrow with SQL containing INSERT INTO slo_definitions."""
        from services.api_gateway.slo_tracker import create_slo

        row = _make_slo_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        await create_slo(
            name="Network Latency",
            domain="network",
            metric="latency_p99",
            target_pct=99.5,
            window_hours=12,
        )

        assert mock_conn.fetchrow.called
        call_args = mock_conn.fetchrow.call_args
        sql = call_args[0][0]
        assert "INSERT INTO slo_definitions" in sql


# ---------------------------------------------------------------------------
# Tests 8–9: update_slo_metrics
# ---------------------------------------------------------------------------


class TestUpdateSloMetrics:
    """update_slo_metrics computes error_budget_pct and status correctly."""

    @pytest.mark.anyio
    async def test_update_slo_metrics_computes_error_budget(self, mock_conn):
        """current_value=99.95, target_pct=99.9 → error_budget_pct ≈ 100.05."""
        from services.api_gateway.slo_tracker import update_slo_metrics

        target_row = {"target_pct": 99.9}
        updated_row = _make_slo_row(
            current_value=99.95,
            error_budget_pct=100.05,
            status="healthy",
        )
        mock_conn.fetchrow = AsyncMock(side_effect=[target_row, updated_row])

        result = await update_slo_metrics(
            slo_id="slo-uuid-001",
            current_value=99.95,
        )

        assert abs(result["error_budget_pct"] - 100.05) < 0.01

    @pytest.mark.anyio
    async def test_update_slo_metrics_sets_burn_rate_alert_status(self, mock_conn):
        """burn_rate_1h=2.5 above threshold → status 'burn_rate_alert' in returned dict."""
        from services.api_gateway.slo_tracker import update_slo_metrics

        target_row = {"target_pct": 99.9}
        updated_row = _make_slo_row(
            current_value=99.85,
            error_budget_pct=99.95,
            burn_rate_1h=2.5,
            status="burn_rate_alert",
        )
        mock_conn.fetchrow = AsyncMock(side_effect=[target_row, updated_row])

        result = await update_slo_metrics(
            slo_id="slo-uuid-001",
            current_value=99.85,
            burn_rate_1h=2.5,
        )

        assert result["status"] == "burn_rate_alert"


# ---------------------------------------------------------------------------
# Tests 10–12: check_domain_burn_rate_alert
# ---------------------------------------------------------------------------


class TestCheckDomainBurnRateAlert:
    """check_domain_burn_rate_alert always returns bool, never raises."""

    @pytest.mark.anyio
    async def test_check_domain_burn_rate_alert_returns_true(self, mock_conn):
        """count=1 in DB → check_domain_burn_rate_alert returns True."""
        from services.api_gateway.slo_tracker import check_domain_burn_rate_alert

        mock_conn.fetchrow = AsyncMock(return_value={"count": 1})

        result = await check_domain_burn_rate_alert("compute")

        assert result is True

    @pytest.mark.anyio
    async def test_check_domain_burn_rate_alert_returns_false_on_zero(self, mock_conn):
        """count=0 in DB → check_domain_burn_rate_alert returns False."""
        from services.api_gateway.slo_tracker import check_domain_burn_rate_alert

        mock_conn.fetchrow = AsyncMock(return_value={"count": 0})

        result = await check_domain_burn_rate_alert("compute")

        assert result is False

    @pytest.mark.anyio
    async def test_check_domain_burn_rate_alert_returns_false_on_db_error(
        self, monkeypatch
    ):
        """DB raises exception → check_domain_burn_rate_alert returns False (non-fatal)."""
        import asyncpg as asyncpg_stub
        from services.api_gateway.slo_tracker import check_domain_burn_rate_alert

        asyncpg_stub.connect = AsyncMock(side_effect=ConnectionError("DB down"))

        result = await check_domain_burn_rate_alert("compute")

        assert result is False


# ---------------------------------------------------------------------------
# Test 13: list_slos — non-fatal when postgres not configured
# ---------------------------------------------------------------------------


class TestListSlos:
    @pytest.mark.anyio
    async def test_list_slos_returns_empty_when_unavailable(self, monkeypatch):
        """resolve_postgres_dsn raises RunbookSearchUnavailableError → list_slos returns []."""
        from services.api_gateway.slo_tracker import list_slos
        from services.api_gateway.runbook_rag import RunbookSearchUnavailableError

        monkeypatch.delenv("POSTGRES_DSN", raising=False)
        monkeypatch.delenv("PGVECTOR_CONNECTION_STRING", raising=False)
        monkeypatch.delenv("POSTGRES_HOST", raising=False)

        result = await list_slos()

        assert result == []


# ---------------------------------------------------------------------------
# Test 14: get_slo_health — KeyError for unknown SLO id
# ---------------------------------------------------------------------------


class TestGetSloHealth:
    @pytest.mark.anyio
    async def test_get_slo_health_raises_keyerror_for_unknown_id(self, mock_conn):
        """fetchrow returns None → get_slo_health raises KeyError."""
        from services.api_gateway.slo_tracker import get_slo_health

        mock_conn.fetchrow = AsyncMock(return_value=None)

        with pytest.raises(KeyError):
            await get_slo_health("nonexistent-slo-id")
