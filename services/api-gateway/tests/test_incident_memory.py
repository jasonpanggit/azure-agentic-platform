from __future__ import annotations
"""Unit tests for incident_memory.py — INTEL-003 historical pattern matching.

All 12 tests use mocked embeddings and postgres; no real DB or Azure OpenAI
calls are made.  Async tests use pytest.mark.anyio (consistent with
test_runbook_search_availability.py).
"""

import datetime
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_gateway.runbook_rag import RunbookSearchUnavailableError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MEMORY_MODULE = "services.api_gateway.incident_memory"

FAKE_EMBEDDING = [0.1] * 1536


def _install_db_stubs(mock_conn: AsyncMock):
    """Install asyncpg + pgvector stubs into sys.modules.

    Pattern mirrors test_runbook_search_availability._install_runbook_db_stubs.
    """
    asyncpg_mod = types.ModuleType("asyncpg")
    asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
    sys.modules["asyncpg"] = asyncpg_mod

    pgvector_mod = types.ModuleType("pgvector")
    pgvector_asyncpg_mod = types.ModuleType("pgvector.asyncpg")
    pgvector_asyncpg_mod.register_vector = AsyncMock()
    sys.modules["pgvector"] = pgvector_mod
    sys.modules["pgvector.asyncpg"] = pgvector_asyncpg_mod

    return asyncpg_mod, pgvector_asyncpg_mod


def _make_mock_conn(rows=None):
    """Return a mock asyncpg connection."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows or [])
    conn.execute = AsyncMock()
    conn.close = AsyncMock()
    return conn


def _make_row(
    *,
    incident_id: str = "inc-hist-001",
    domain: str = "compute",
    severity: str = "Sev1",
    title: str | None = "High CPU on vm-prod",
    resolution: str | None = "Restarted the VM",
    resolved_at: datetime.datetime | None = None,
    similarity: float = 0.75,
) -> MagicMock:
    """Build a fake asyncpg row dict-like object."""
    if resolved_at is None:
        resolved_at = datetime.datetime(2026, 3, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": incident_id,
        "domain": domain,
        "severity": severity,
        "title": title,
        "resolution": resolution,
        "resolved_at": resolved_at,
        "similarity": similarity,
    }[key]
    return row


# ---------------------------------------------------------------------------
# store_incident_memory tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_store_incident_memory_calls_generate_embedding(
    mock_dsn, mock_embed
):
    """generate_query_embedding must be called with the full embed text."""
    mock_conn = _make_mock_conn()
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    await incident_memory.store_incident_memory(
        incident_id="inc-001",
        domain="compute",
        severity="Sev1",
        resource_type="Microsoft.Compute/virtualMachines",
        title="High CPU",
        summary="CPU above 95%",
        resolution="Restarted VM",
    )

    expected_text = "High CPU compute Microsoft.Compute/virtualMachines CPU above 95% Restarted VM"
    mock_embed.assert_awaited_once_with(expected_text)


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_store_incident_memory_executes_upsert_sql(mock_dsn, mock_embed):
    """conn.execute must be called with INSERT INTO incident_memory SQL."""
    mock_conn = _make_mock_conn()
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    await incident_memory.store_incident_memory(
        incident_id="inc-002",
        domain="network",
        severity="Sev2",
        resource_type=None,
        title=None,
        summary=None,
        resolution=None,
    )

    mock_conn.execute.assert_awaited_once()
    call_args = mock_conn.execute.call_args
    sql = call_args[0][0]
    assert "INSERT INTO incident_memory" in sql
    assert "ON CONFLICT" in sql


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_store_incident_memory_returns_incident_id(mock_dsn, mock_embed):
    """Return value must equal the incident_id passed in."""
    mock_conn = _make_mock_conn()
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    result = await incident_memory.store_incident_memory(
        incident_id="inc-abc-123",
        domain="storage",
        severity="Sev3",
        resource_type=None,
        title="Disk full",
        summary=None,
        resolution="Cleared old logs",
    )

    assert result == "inc-abc-123"


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_store_incident_memory_handles_none_fields(mock_dsn, mock_embed):
    """When title/summary/resolution are None, embed text is built without crashing."""
    mock_conn = _make_mock_conn()
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    # Should not raise even with all optional fields None
    result = await incident_memory.store_incident_memory(
        incident_id="inc-none-fields",
        domain="arc",
        severity="Sev2",
        resource_type=None,
        title=None,
        summary=None,
        resolution=None,
    )

    assert result == "inc-none-fields"
    # embed text should just be the domain with surrounding whitespace stripped
    embed_call_text = mock_embed.call_args[0][0]
    assert "arc" in embed_call_text
    assert "None" not in embed_call_text


# ---------------------------------------------------------------------------
# search_incident_memory tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_search_incident_memory_returns_matches_above_threshold(
    mock_dsn, mock_embed
):
    """Rows with similarity >= 0.35 must appear in the returned list."""
    row = _make_row(similarity=0.80)
    mock_conn = _make_mock_conn(rows=[row])
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    results = await incident_memory.search_incident_memory(
        title="High CPU",
        domain="compute",
        resource_type="Microsoft.Compute/virtualMachines",
    )

    assert len(results) == 1
    assert results[0]["incident_id"] == "inc-hist-001"
    assert results[0]["similarity"] == 0.8
    assert results[0]["domain"] == "compute"


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_search_incident_memory_filters_below_threshold(mock_dsn, mock_embed):
    """Rows with similarity < 0.35 must be excluded from results."""
    row_below = _make_row(incident_id="inc-low", similarity=0.20)
    row_above = _make_row(incident_id="inc-high", similarity=0.60)
    mock_conn = _make_mock_conn(rows=[row_below, row_above])
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    results = await incident_memory.search_incident_memory(
        title="Disk full",
        domain="storage",
        resource_type=None,
    )

    assert len(results) == 1
    assert results[0]["incident_id"] == "inc-high"


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_search_incident_memory_returns_empty_list_when_no_rows(
    mock_dsn, mock_embed
):
    """Empty rows from conn.fetch → returns []."""
    mock_conn = _make_mock_conn(rows=[])
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    results = await incident_memory.search_incident_memory(
        title="NSG rule blocked",
        domain="network",
        resource_type=None,
    )

    assert results == []


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.resolve_postgres_dsn",
    side_effect=RunbookSearchUnavailableError("not configured"),
)
async def test_search_incident_memory_returns_empty_on_missing_postgres(mock_dsn):
    """When resolve_postgres_dsn raises RunbookSearchUnavailableError, returns [] non-fatally."""
    from services.api_gateway import incident_memory

    results = await incident_memory.search_incident_memory(
        title="Pod crash loop",
        domain="arc",
        resource_type=None,
    )

    assert results == []


@pytest.mark.anyio
async def test_search_incident_memory_returns_empty_on_empty_query():
    """When title/domain/resource_type are all None, returns [] without calling DB."""
    from services.api_gateway import incident_memory

    with patch(f"{MEMORY_MODULE}.resolve_postgres_dsn") as mock_dsn:
        results = await incident_memory.search_incident_memory(
            title=None,
            domain=None,
            resource_type=None,
        )

    assert results == []
    mock_dsn.assert_not_called()


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_search_incident_memory_resolution_excerpt_truncated(
    mock_dsn, mock_embed
):
    """resolution_excerpt must be at most 300 chars even if resolution is 1000 chars."""
    long_resolution = "x" * 1000
    row = _make_row(similarity=0.70, resolution=long_resolution)
    mock_conn = _make_mock_conn(rows=[row])
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    results = await incident_memory.search_incident_memory(
        title="VM unresponsive",
        domain="compute",
        resource_type=None,
    )

    assert len(results) == 1
    assert len(results[0]["resolution_excerpt"]) == 300
    assert results[0]["resolution_excerpt"] == "x" * 300


@pytest.mark.anyio
@patch(
    f"{MEMORY_MODULE}.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=FAKE_EMBEDDING,
)
@patch(f"{MEMORY_MODULE}.resolve_postgres_dsn", return_value="postgresql://test/aap")
async def test_search_incident_memory_resolved_at_is_string(mock_dsn, mock_embed):
    """resolved_at in the result dict must be a string (ISO 8601), not a datetime."""
    dt = datetime.datetime(2026, 3, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)
    row = _make_row(similarity=0.50, resolved_at=dt)
    mock_conn = _make_mock_conn(rows=[row])
    _install_db_stubs(mock_conn)

    from services.api_gateway import incident_memory

    results = await incident_memory.search_incident_memory(
        title="Storage throttle",
        domain="storage",
        resource_type=None,
    )

    assert len(results) == 1
    resolved_at = results[0]["resolved_at"]
    assert isinstance(resolved_at, str)
    assert "2026" in resolved_at


# ---------------------------------------------------------------------------
# Model validation test
# ---------------------------------------------------------------------------


def test_historical_match_model_fields():
    """HistoricalMatch Pydantic model validates correctly.

    Also verifies that IncidentSummary.slo_escalated and
    IncidentSummary.historical_matches default to None.
    """
    from services.api_gateway.models import HistoricalMatch, IncidentSummary

    match = HistoricalMatch(
        incident_id="inc-hist-001",
        domain="compute",
        severity="Sev1",
        title="High CPU",
        similarity=0.75,
        resolution_excerpt="Restarted the VM to recover from CPU spike.",
        resolved_at="2026-03-15T10:00:00+00:00",
    )
    assert match.incident_id == "inc-hist-001"
    assert match.similarity == 0.75
    assert match.title == "High CPU"

    # Optional title defaults to None
    match_no_title = HistoricalMatch(
        incident_id="inc-hist-002",
        domain="network",
        severity="Sev2",
        similarity=0.40,
        resolved_at="2026-03-10T08:00:00+00:00",
    )
    assert match_no_title.title is None
    assert match_no_title.resolution_excerpt is None

    # IncidentSummary new fields default to None — backward compatible
    summary = IncidentSummary(
        incident_id="inc-001",
        severity="Sev1",
        domain="compute",
        status="new",
        created_at="2026-04-01T12:00:00Z",
    )
    assert summary.historical_matches is None
    assert summary.slo_escalated is None

    # IncidentSummary accepts historical_matches list
    summary_with_matches = IncidentSummary(
        incident_id="inc-002",
        severity="Sev1",
        domain="compute",
        status="investigating",
        created_at="2026-04-01T12:00:00Z",
        historical_matches=[match],
        slo_escalated=True,
    )
    assert len(summary_with_matches.historical_matches) == 1
    assert summary_with_matches.slo_escalated is True
