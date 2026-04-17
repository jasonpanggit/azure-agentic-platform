from __future__ import annotations
"""Runbook search availability and connection contract tests.

Async tests in this module use `pytest.mark.anyio` so focused local runs work
with the AnyIO plugin available in the workspace runner.
"""

import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


RUNBOOK_MODULE_NAME = "services.api_gateway.runbook_rag"


def _reload_runbook_module(monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop(RUNBOOK_MODULE_NAME, None)
    module = importlib.import_module(RUNBOOK_MODULE_NAME)
    return importlib.reload(module)


def _install_runbook_db_stubs(mock_conn: AsyncMock):
    asyncpg_mod = types.ModuleType("asyncpg")
    asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
    sys.modules["asyncpg"] = asyncpg_mod

    pgvector_mod = types.ModuleType("pgvector")
    pgvector_asyncpg_mod = types.ModuleType("pgvector.asyncpg")
    pgvector_asyncpg_mod.register_vector = AsyncMock()
    sys.modules["pgvector"] = pgvector_mod
    sys.modules["pgvector.asyncpg"] = pgvector_asyncpg_mod

    return asyncpg_mod, pgvector_asyncpg_mod


@pytest.mark.anyio
async def test_search_runbooks_uses_pgvector_connection_string(monkeypatch):
    monkeypatch.setenv(
        "PGVECTOR_CONNECTION_STRING",
        "postgresql://pgvector-user:secret@db.internal:5432/aap",
    )
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.close = AsyncMock()

    asyncpg_mod, _ = _install_runbook_db_stubs(mock_conn)
    runbook_rag = _reload_runbook_module(monkeypatch)

    await runbook_rag.search_runbooks([0.1, 0.2, 0.3], limit=3)

    asyncpg_mod.connect.assert_awaited_once_with(
        "postgresql://pgvector-user:secret@db.internal:5432/aap"
    )


@pytest.mark.anyio
async def test_search_runbooks_raises_when_database_not_configured(monkeypatch):
    monkeypatch.delenv("PGVECTOR_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    runbook_rag = _reload_runbook_module(monkeypatch)

    with pytest.raises(runbook_rag.RunbookSearchUnavailableError, match="not configured"):
        await runbook_rag.search_runbooks([0.1, 0.2, 0.3], limit=3)


def test_runbook_search_endpoint_returns_503_when_database_unavailable(client):
    from services.api_gateway.runbook_rag import RunbookSearchUnavailableError

    with patch(
        "services.api_gateway.main.generate_query_embedding",
        new=AsyncMock(return_value=[0.1, 0.2, 0.3]),
    ), patch(
        "services.api_gateway.main.search_runbooks",
        new=AsyncMock(
            side_effect=RunbookSearchUnavailableError(
                "Runbook search database is not configured."
            )
        ),
    ):
        response = client.get(
            "/api/v1/runbooks/search",
            params={"query": "high cpu"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Runbook search database is not configured."