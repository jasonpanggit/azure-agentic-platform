"""Tests for the runbook RAG search (REMEDI-008, TRIAGE-005).

Async tests in this module use `pytest.mark.anyio` so focused local runs work
with the AnyIO plugin available in the workspace runner.
"""
import sys
import time
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def _set_test_runbook_dsn(monkeypatch: pytest.MonkeyPatch):
    """Provide an explicit DSN for runbook RAG tests.

    The production code now requires a configured DSN instead of silently
    falling back to localhost.
    """
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://test-user:test-pass@db.test:5432/aap")


def _make_row(id_val, title, domain, version, content, similarity):
    """Build a dict-like asyncpg Record mock."""
    return {
        "id": id_val,
        "title": title,
        "domain": domain,
        "version": version,
        "content": content,
        "similarity": similarity,
    }


def _install_asyncpg_stub(mock_conn):
    """Install a minimal asyncpg stub into sys.modules so imports succeed."""
    asyncpg_mod = types.ModuleType("asyncpg")
    asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
    sys.modules["asyncpg"] = asyncpg_mod

    pgvector_mod = types.ModuleType("pgvector")
    pgvector_asyncpg_mod = types.ModuleType("pgvector.asyncpg")
    pgvector_asyncpg_mod.register_vector = AsyncMock()
    sys.modules["pgvector"] = pgvector_mod
    sys.modules["pgvector.asyncpg"] = pgvector_asyncpg_mod

    return asyncpg_mod, pgvector_asyncpg_mod


class TestRunbookRAG:
    """Tests for the runbook RAG search (TRIAGE-005, REMEDI-008)."""

    @pytest.mark.anyio
    async def test_search_returns_top_3_results(self, pre_seeded_embeddings):
        """search_runbooks returns at most 3 results when 3 rows returned."""
        rows = [
            _make_row("1", "VM CPU Runbook", "compute", "v1.2", "CPU content", 0.92),
            _make_row("2", "NSG Fix Runbook", "network", "v2.0", "NSG content", 0.85),
            _make_row("3", "Storage Runbook", "storage", "v1.0", "Storage content", 0.78),
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_conn.close = AsyncMock()

        asyncpg_mod, pgvector_mod = _install_asyncpg_stub(mock_conn)
        asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
        pgvector_mod.register_vector = AsyncMock()

        # Force reimport to pick up stubs
        if "services.api_gateway.runbook_rag" in sys.modules:
            del sys.modules["services.api_gateway.runbook_rag"]

        from services.api_gateway.runbook_rag import search_runbooks
        results = await search_runbooks(pre_seeded_embeddings[0], limit=3)

        assert len(results) == 3

    @pytest.mark.anyio
    async def test_similarity_above_075_threshold(self, pre_seeded_embeddings):
        """Only results with similarity >= 0.75 are returned."""
        rows = [
            _make_row("1", "High Match", "compute", "v1.0", "content1", 0.92),
            _make_row("2", "Good Match", "compute", "v1.0", "content2", 0.85),
            _make_row("3", "Border Match", "compute", "v1.0", "content3", 0.78),
            _make_row("4", "Below Threshold", "compute", "v1.0", "content4", 0.60),
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_conn.close = AsyncMock()

        asyncpg_mod, pgvector_mod = _install_asyncpg_stub(mock_conn)
        asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
        pgvector_mod.register_vector = AsyncMock()

        if "services.api_gateway.runbook_rag" in sys.modules:
            del sys.modules["services.api_gateway.runbook_rag"]

        from services.api_gateway.runbook_rag import search_runbooks
        results = await search_runbooks(pre_seeded_embeddings[0], limit=4)

        assert len(results) == 3, (
            f"Expected 3 results above 0.75, got {len(results)}: "
            f"{[r['similarity'] for r in results]}"
        )
        assert all(r["similarity"] >= 0.75 for r in results)

    @pytest.mark.anyio
    async def test_search_latency_under_500ms(self, pre_seeded_embeddings):
        """End-to-end runbook search completes in under 500ms with mocks."""
        rows = [
            _make_row("1", "Fast Runbook", "compute", "v1.0", "content", 0.88),
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_conn.close = AsyncMock()

        asyncpg_mod, pgvector_mod = _install_asyncpg_stub(mock_conn)
        asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
        pgvector_mod.register_vector = AsyncMock()

        if "services.api_gateway.runbook_rag" in sys.modules:
            del sys.modules["services.api_gateway.runbook_rag"]

        from services.api_gateway.runbook_rag import search_runbooks
        start = time.monotonic()
        await search_runbooks(pre_seeded_embeddings[0])
        elapsed = time.monotonic() - start

        assert elapsed < 0.5, f"Search took {elapsed:.3f}s — expected < 0.5s"

    @pytest.mark.anyio
    async def test_domain_filter_applied(self, pre_seeded_embeddings):
        """When domain param provided, SQL contains WHERE domain = $2."""
        captured_sql: list = []

        async def mock_fetch(sql, *args):
            captured_sql.append(sql)
            return []

        mock_conn = AsyncMock()
        mock_conn.fetch = mock_fetch
        mock_conn.close = AsyncMock()

        asyncpg_mod, pgvector_mod = _install_asyncpg_stub(mock_conn)
        asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
        pgvector_mod.register_vector = AsyncMock()

        if "services.api_gateway.runbook_rag" in sys.modules:
            del sys.modules["services.api_gateway.runbook_rag"]

        from services.api_gateway.runbook_rag import search_runbooks
        await search_runbooks(pre_seeded_embeddings[0], domain="compute")

        assert len(captured_sql) == 1, "Expected exactly one SQL call"
        assert "WHERE domain = $2" in captured_sql[0], (
            f"Expected 'WHERE domain = $2' in SQL, got:\n{captured_sql[0]}"
        )

    @pytest.mark.anyio
    async def test_citation_includes_title_and_version(self, pre_seeded_embeddings):
        """Each result includes non-empty title and version fields."""
        rows = [
            _make_row("1", "VM High CPU Runbook", "compute", "v2.1", "CPU steps", 0.91),
            _make_row("2", "Memory Leak Runbook", "compute", "v1.5", "Memory steps", 0.82),
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_conn.close = AsyncMock()

        asyncpg_mod, pgvector_mod = _install_asyncpg_stub(mock_conn)
        asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
        pgvector_mod.register_vector = AsyncMock()

        if "services.api_gateway.runbook_rag" in sys.modules:
            del sys.modules["services.api_gateway.runbook_rag"]

        from services.api_gateway.runbook_rag import search_runbooks
        results = await search_runbooks(pre_seeded_embeddings[0])

        assert len(results) > 0, "Expected at least one result"
        for r in results:
            assert "title" in r, "Each result must have a 'title' key"
            assert "version" in r, "Each result must have a 'version' key"
            assert r["title"], "title must be non-empty"
            assert r["version"], "version must be non-empty"
