# Plan 05-03: Runbook RAG System — Summary

**Status:** COMPLETE
**Completed:** 2026-03-27
**Branch:** phase-5-wave-0-test-infrastructure

---

## What Was Built

Implements TRIAGE-005: Runbook RAG (Retrieval-Augmented Generation) system using PostgreSQL pgvector + Azure OpenAI embeddings + agent integration.

---

## Deliverables

### 1. Database Migration (`services/api-gateway/migrations/001_create_runbooks_table.sql`)
- `runbooks` table with `vector(1536)` embedding column (D-16)
- HNSW index for cosine similarity search (`m=16, ef_construction=64`)
- Domain filter index for filtered vector search
- Domain constraint: `compute | network | storage | security | arc | sre`
- `gen_random_uuid()` primary key, `TIMESTAMPTZ` created/updated timestamps

### 2. Seed Script (`services/api-gateway/migrations/002_seed_runbooks.py`)
- 60 synthetic runbooks — exactly 10 per domain (compute, network, storage, security, arc, sre)
- Azure OpenAI `text-embedding-3-small` embeddings via `AzureOpenAI` client
- `uuid5` deterministic IDs for idempotent re-runs (`ON CONFLICT DO NOTHING`)
- Configurable via `EMBEDDING_DEPLOYMENT_NAME`, `POSTGRES_*`, `AZURE_OPENAI_*` env vars

### 3. Runbook RAG Module (`services/api-gateway/runbook_rag.py`)
- `generate_query_embedding(query)` — async, calls Azure OpenAI embeddings API
- `search_runbooks(embedding, domain, limit)` — async pgvector cosine similarity query
- `SIMILARITY_THRESHOLD = 0.75` (configurable via `RUNBOOK_SIMILARITY_THRESHOLD` env var)
- Domain-filtered and unfiltered query paths
- `_build_dsn()` fallback DSN construction from env vars
- `MAX_EXCERPT_LENGTH = 300` chars for content excerpt

### 4. API Endpoint (`services/api-gateway/main.py` + `models.py`)
- `RunbookResult` Pydantic model: `id, title, domain, version, similarity, content_excerpt`
- `GET /api/v1/runbooks/search` — query params: `query` (required), `domain` (optional), `limit` (default 3)
- Entra ID Bearer token auth required (same pattern as `/api/v1/incidents`)
- Returns `list[RunbookResult]`

### 5. Agent Tool (`agents/shared/runbook_tool.py`)
- `retrieve_runbooks(query, domain, limit)` — async HTTP call to api-gateway with 5s timeout
- Non-blocking: returns `[]` on any exception with WARNING log
- `format_runbook_citations(runbooks)` — formats results as `"Referenced runbooks: Title (v1.0), ..."`
- `API_GATEWAY_URL` configurable via env var (default `http://localhost:8000`)

### 6. Agent Spec Updates (all 6 domain agents)
Added to each spec's **Workflow** section (after hypothesis formulation, before remediation proposal):

```markdown
### Retrieve Relevant Runbooks (TRIAGE-005)
- Call `retrieve_runbooks(query=<diagnosis_hypothesis>, domain=<agent_domain>, limit=3)`
- Filter results with similarity >= 0.75
- Cite the top-3 runbooks (title + version) in the triage response
- Use runbook content to inform the remediation proposal
- If runbook service is unavailable, proceed without citation (non-blocking)
```

Added `retrieve_runbooks` to each agent's Tool Permissions explicit allowlist.

---

## Verification Results

| Check | Result |
|---|---|
| `vector(1536)` in migration | ✅ line 14 |
| `USING hnsw` in migration | ✅ line 21 |
| 60 runbooks in seed script | ✅ 60 (10 per domain) |
| `SIMILARITY_THRESHOLD = float(..., "0.75")` | ✅ line 14 |
| `/api/v1/runbooks/search` in main.py | ✅ lines 5, 136 |
| `retrieve_runbooks` in runbook_tool.py | ✅ |
| `format_runbook_citations` in runbook_tool.py | ✅ |
| All 6 specs contain `retrieve_runbooks` | ✅ (2 occurrences each: workflow + allowlist) |
| All 6 specs contain `TRIAGE-005` | ✅ (1 occurrence each) |

---

## Commits

1. `64d29ef` — `feat: add runbooks table SQL migration with pgvector HNSW index`
2. `fb2f39e` — `feat: add runbook seed script with 60 synthetic runbooks and Azure OpenAI embeddings`
3. `ac1cfec` — `feat: add runbook RAG retrieval endpoint GET /api/v1/runbooks/search`
4. `b9dc750` — `feat: add runbook_tool.py with retrieve_runbooks and format_runbook_citations`
5. `444b46c` — `feat: update all 6 domain agent specs with runbook retrieval step (TRIAGE-005)`

---

## Design Decisions

| Decision | Rationale |
|---|---|
| HNSW over IVFFlat index | Better recall for production; IVFFlat requires tuning `nlist` at insert time |
| `SIMILARITY_THRESHOLD = 0.75` | Prevents low-relevance runbooks from polluting triage responses |
| Non-blocking `retrieve_runbooks` | Runbook service outage must never block agent triage flow |
| `uuid5` deterministic IDs | Enables idempotent seed re-runs without duplicates |
| `content_excerpt` (300 chars) | Avoids returning full runbook content in search results; agents fetch full content if needed |
| Arc agent scoped to Phase 3+ | Arc Agent is a stub in Phase 2; runbook step added to Phase 3+ workflow section only |

---

## Dependencies Satisfied

- Depends on: **05-00** (test infrastructure scaffolded — pytest fixtures include pgvector embeddings)
- Independent of: 05-01 (triage engine), 05-02 (remediation), 05-04 through 05-06

## Next Plans

- **05-01**: Triage Engine (orchestrator + domain agent triage workflow)
- **05-02**: Remediation (approval workflow + Cosmos DB)
