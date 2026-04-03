# Plan 25-1: Incident Memory Service

**Phase:** 25 — Institutional Memory and SLO Tracking
**Wave:** 1 (independent — no dependencies on 25-2)
**Requirement:** INTEL-003 (≥33% of new incidents surface a historical pattern match)
**Autonomous:** true

---

## Goal

Create `services/api-gateway/incident_memory.py` — a self-contained module that embeds resolved incidents into pgvector and searches historical patterns for new incidents. Also add the `HistoricalMatch` Pydantic model and two new optional fields to `IncidentSummary` in `models.py`.

No wiring into `ingest_incident` or the resolve endpoint yet — that is Wave 2 (25-3).

---

## Files Changed

| File | Action |
|------|--------|
| `services/api-gateway/models.py` | Add `HistoricalMatch`, extend `IncidentSummary` |
| `services/api-gateway/incident_memory.py` | Create new module |
| `services/api-gateway/tests/test_incident_memory.py` | Create unit tests |

---

## Step 1 — Add `HistoricalMatch` model to `models.py`

Append after `ChangeCorrelation` (before `IncidentSummary`):

```python
class HistoricalMatch(BaseModel):
    """A single historical incident match from pgvector cosine similarity (INTEL-003)."""

    incident_id: str = Field(..., description="ID of the matching historical incident")
    domain: str = Field(..., description="Domain of the historical incident")
    severity: str = Field(..., description="Severity of the historical incident")
    title: Optional[str] = Field(default=None, description="Title of the historical incident")
    similarity: float = Field(..., description="Cosine similarity score (0.0–1.0)")
    resolution_excerpt: Optional[str] = Field(
        default=None, description="First 300 chars of the resolution that fixed it"
    )
    resolved_at: str = Field(..., description="ISO 8601 timestamp when the incident was resolved")
```

Extend `IncidentSummary` with two new optional fields (append after `parent_incident_id`):

```python
    historical_matches: Optional[list[HistoricalMatch]] = Field(
        default=None,
        description=(
            "Top-3 historical incidents with similar pattern. "
            "Populated within 10s of ingestion by BackgroundTask (INTEL-003)."
        ),
    )
    slo_escalated: Optional[bool] = Field(
        default=None,
        description="True when severity was escalated to Sev0 due to domain SLO burn-rate alert.",
    )
```

**Important:** Both fields are `Optional` with `default=None` — fully backward compatible; existing callers and the list endpoint are unaffected.

---

## Step 2 — Create `services/api-gateway/incident_memory.py`

### Module structure

```
incident_memory.py
├── Constants / config
├── IncidentMemoryUnavailableError
├── store_incident_memory(incident_id, domain, severity, resource_type, title, summary, resolution)
├── search_incident_memory(title, domain, resource_type, limit=3) -> list[dict]
└── (private) _is_memory_data_plane_error(exc)
```

### Constants

```python
MEMORY_SIMILARITY_THRESHOLD = float(os.environ.get("MEMORY_SIMILARITY_THRESHOLD", "0.35"))
MAX_RESOLUTION_EXCERPT_LENGTH = 300
```

### `IncidentMemoryUnavailableError`

Mirror `RunbookSearchUnavailableError` from `runbook_rag.py` — raised when postgres is missing or unreachable. Non-fatal callers must catch this and log a warning, never propagate to the HTTP layer.

### `store_incident_memory` signature

```python
async def store_incident_memory(
    incident_id: str,
    domain: str,
    severity: str,
    resource_type: Optional[str],
    title: Optional[str],
    summary: Optional[str],
    resolution: Optional[str],
) -> str:
    """Embed and upsert a resolved incident into the incident_memory table.

    Embedding text: f"{title} {domain} {resource_type} {summary} {resolution}"
    Uses generate_query_embedding imported from runbook_rag (reuse, no duplication).

    Returns:
        incident_id (the PRIMARY KEY / memory_id)

    Raises:
        IncidentMemoryUnavailableError: if postgres is unreachable.
    """
```

Key implementation details:
- Import `generate_query_embedding` and `resolve_postgres_dsn` from `services.api_gateway.runbook_rag` — do NOT re-implement embedding logic
- Build embed text: `f"{title or ''} {domain} {resource_type or ''} {summary or ''} {resolution or ''}".strip()`
- Upsert SQL uses `INSERT INTO incident_memory (...) VALUES (...) ON CONFLICT (id) DO UPDATE SET ...`
- `resolved_at` defaults to `NOW()` inside the SQL; no Python timestamp needed
- Register pgvector with `register_vector(conn)` before any vector operation (same as `runbook_rag.py`)
- `asyncpg` and `pgvector.asyncpg` are lazy imports inside the function body (same pattern as `search_runbooks`)
- Connection opened per-call and closed in `finally` block — no connection pool for now

### `search_incident_memory` signature

```python
async def search_incident_memory(
    title: Optional[str],
    domain: Optional[str],
    resource_type: Optional[str],
    limit: int = 3,
) -> list[dict]:
    """Search for historical incidents similar to the new incident.

    Query text: f"{title} {domain} {resource_type}"
    Similarity threshold: MEMORY_SIMILARITY_THRESHOLD (default 0.35)

    Returns:
        List of dicts with keys: incident_id, domain, severity, title,
        similarity, resolution_excerpt, resolved_at

    Returns [] when postgres is not configured (non-fatal — logs warning).
    Returns [] when the incident_memory table is empty.
    """
```

Key implementation details:
- Build query text: `f"{title or ''} {domain or ''} {resource_type or ''}".strip()`
- If query text is empty string: return `[]` immediately (nothing to embed)
- SQL: cosine distance operator `<=>`, `ORDER BY embedding <=> $1 LIMIT $2`
- No domain filter — historical matches should cross domains (e.g. a network issue that preceded a compute incident)
- Filter by `sim >= MEMORY_SIMILARITY_THRESHOLD` after fetch (same pattern as `search_runbooks`)
- `resolved_at` returned as `.isoformat()` from the asyncpg `datetime` value
- `resolution_excerpt` = `resolution[:MAX_RESOLUTION_EXCERPT_LENGTH]` if resolution is not None
- Catch `IncidentMemoryUnavailableError` internally → log warning → return `[]`
- Re-raise unexpected exceptions (programming errors, not data plane issues)

### SQL for search

```sql
SELECT id, domain, severity, title, resolution, resolved_at,
       1 - (embedding <=> $1) AS similarity
FROM incident_memory
ORDER BY embedding <=> $1
LIMIT $2
```

---

## Step 3 — Unit Tests: `services/api-gateway/tests/test_incident_memory.py`

**Minimum:** 10 tests. Target: 12.

### Test setup helpers

```python
def _install_db_stubs(mock_conn):
    """Install asyncpg + pgvector stubs into sys.modules."""
    # Pattern from test_runbook_search_availability.py
    asyncpg_mod = types.ModuleType("asyncpg")
    asyncpg_mod.connect = AsyncMock(return_value=mock_conn)
    sys.modules["asyncpg"] = asyncpg_mod

    pgvector_mod = types.ModuleType("pgvector")
    pgvector_asyncpg_mod = types.ModuleType("pgvector.asyncpg")
    pgvector_asyncpg_mod.register_vector = AsyncMock()
    sys.modules["pgvector"] = pgvector_mod
    sys.modules["pgvector.asyncpg"] = pgvector_asyncpg_mod
```

### Test list

| # | Test name | What it verifies |
|---|-----------|-----------------|
| 1 | `test_store_incident_memory_calls_generate_embedding` | `generate_query_embedding` called with `f"{title} {domain} {resource_type} {summary} {resolution}"` |
| 2 | `test_store_incident_memory_executes_upsert_sql` | `conn.execute` called with SQL containing `INSERT INTO incident_memory` |
| 3 | `test_store_incident_memory_returns_incident_id` | Return value equals the incident_id passed in |
| 4 | `test_store_incident_memory_handles_none_fields` | When title/summary/resolution are None, embed text is built without crashing |
| 5 | `test_search_incident_memory_returns_matches_above_threshold` | When `similarity >= 0.35`, result is included in return list |
| 6 | `test_search_incident_memory_filters_below_threshold` | When `similarity < 0.35`, result is excluded |
| 7 | `test_search_incident_memory_returns_empty_list_when_no_rows` | Empty `rows` from `conn.fetch` → returns `[]` |
| 8 | `test_search_incident_memory_returns_empty_on_missing_postgres` | When `resolve_postgres_dsn` raises `RunbookSearchUnavailableError`, returns `[]` (non-fatal) |
| 9 | `test_search_incident_memory_returns_empty_on_empty_query` | When title/domain/resource_type all None → returns `[]` without calling DB |
| 10 | `test_search_incident_memory_resolution_excerpt_truncated` | `resolution_excerpt` is at most 300 chars even if resolution is 1000 chars |
| 11 | `test_search_incident_memory_resolved_at_is_string` | `resolved_at` field is a string (ISO 8601), not a datetime object |
| 12 | `test_historical_match_model_fields` | `HistoricalMatch` Pydantic model validates correctly; `slo_escalated` on `IncidentSummary` defaults to None |

### Mock pattern for embedding

```python
@patch(
    "services.api_gateway.incident_memory.generate_query_embedding",
    new_callable=AsyncMock,
    return_value=[0.1] * 1536,
)
```

### Mock pattern for `resolve_postgres_dsn` not configured

```python
@patch(
    "services.api_gateway.incident_memory.resolve_postgres_dsn",
    side_effect=RunbookSearchUnavailableError("not configured"),
)
```

---

## Acceptance Criteria

- [ ] `HistoricalMatch` model in `models.py` with all 7 fields
- [ ] `IncidentSummary.historical_matches` and `IncidentSummary.slo_escalated` added (both `Optional`, both default `None`)
- [ ] `incident_memory.py` exports `store_incident_memory` and `search_incident_memory`
- [ ] `generate_query_embedding` and `resolve_postgres_dsn` imported from `runbook_rag` — not reimplemented
- [ ] `search_incident_memory` returns `[]` (non-fatal) when postgres is unavailable
- [ ] `store_incident_memory` raises `IncidentMemoryUnavailableError` on DB failure
- [ ] 12 unit tests, all passing
- [ ] No new environment variables required beyond `MEMORY_SIMILARITY_THRESHOLD` (optional, default 0.35)
- [ ] File is < 200 lines (focused, high cohesion)

---

## Migration SQL (reference for 25-3)

The startup migration for the `incident_memory` table will be added in Plan 25-3 alongside the `slo_definitions` table. This plan does NOT modify `main.py`.

```sql
CREATE TABLE IF NOT EXISTS incident_memory (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    severity TEXT NOT NULL,
    resource_type TEXT,
    title TEXT,
    summary TEXT,
    transcript TEXT,
    resolution TEXT,
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    embedding VECTOR(1536)
);
CREATE INDEX IF NOT EXISTS incident_memory_embedding_idx
  ON incident_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
```

---

## Reminders

- Import `from __future__ import annotations` at top of new file
- All function signatures include type annotations (PEP 8 / Python rules)
- Use `logging.getLogger(__name__)` — no `print()` statements
- `asyncpg` and `pgvector.asyncpg` are lazy imports inside function bodies (same pattern as `runbook_rag.py`) so the module can be imported in test environments without those packages installed
- Immutability: build new dicts for results; never mutate `row` objects from asyncpg
