# Phase 25: Institutional Memory and SLO Tracking - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning
**Mode:** Auto-generated (new service + API phase — discuss skipped)

<domain>
## Phase Boundary

Give the platform memory and SLO awareness:

1. **Institutional Memory** — Every resolved incident's summary + investigation transcript is embedded via pgvector and stored. New incidents automatically get top-3 historical pattern matches surfaced (INTEL-003: ≥33% of new incidents should match a historical pattern).

2. **SLO Tracking** — SLODefinition model, error budget computation, burn-rate alerts (>2x for 1h or >3x for 15min), SLO-aware incident auto-escalation.

**Requirements:**
- INTEL-003: Historical incident match surfaces in ≥33% of new incidents
- INTEL-004: SLO breach prediction alerts fire before threshold is crossed

**What this phase does:**
1. New PostgreSQL table `incident_memory` — stores resolved incident embeddings + summary + transcript
2. `services/api-gateway/incident_memory.py` — embed + store on incident resolution; search on new incident ingestion
3. Wire into `ingest_incident`: after Foundry thread creation, BackgroundTask to search `incident_memory` and attach `historical_matches` to incident document
4. New endpoint `POST /api/v1/incidents/{incident_id}/resolve` — triggers embedding + storage in `incident_memory`
5. `services/api-gateway/slo_tracker.py` — SLODefinition CRUD, error budget computation, burn-rate detection
6. New endpoints: `POST /api/v1/slos`, `GET /api/v1/slos`, `GET /api/v1/slos/{slo_id}/health`
7. SLO-aware escalation: if new incident's domain matches an SLO in burn-rate alert state, auto-escalate composite_severity to Sev0
8. Startup migration: `CREATE TABLE IF NOT EXISTS incident_memory (...)` follows existing runbooks migration pattern

**What this phase does NOT do:**
- Does not add a weekly Container App job (that requires a separate Container App — defer to Phase 28)
- Does not change the detection pipeline
- Does not add UI SLO health cards (Observability tab integration deferred)

</domain>

<decisions>
## Implementation Decisions

### Institutional Memory: PostgreSQL `incident_memory` table
```sql
CREATE TABLE IF NOT EXISTS incident_memory (
    id TEXT PRIMARY KEY,                  -- incident_id
    domain TEXT NOT NULL,
    severity TEXT NOT NULL,
    resource_type TEXT,
    title TEXT,
    summary TEXT,                         -- operator-provided or auto-generated
    transcript TEXT,                      -- Foundry thread conversation summary
    resolution TEXT,                      -- what fixed it
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    embedding VECTOR(1536)               -- text-embedding-3-small
);
CREATE INDEX IF NOT EXISTS incident_memory_embedding_idx
  ON incident_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
```

### Historical match search
- Query: embed `f"{incident.title} {incident.domain} {incident.resource_type}"` → cosine search on `incident_memory`
- Threshold: 0.35 (slightly higher than runbook 0.30 — incidents are more specific)
- Return top 3 matches with: incident_id, domain, severity, title, similarity, resolution_excerpt
- BackgroundTask: runs within 10 seconds of incident ingestion; stores on Cosmos incident document as `historical_matches`

### Incident resolution endpoint
`POST /api/v1/incidents/{incident_id}/resolve` body: `{ summary: str, resolution: str }`
- Reads incident from Cosmos
- Generates embedding for `f"{title} {domain} {resource_type} {summary} {resolution}"`
- Upserts to `incident_memory` table
- Updates Cosmos status to 'resolved'
- Returns `{ incident_id, memory_id, resolved_at }`

### SLO Tracking: PostgreSQL `slo_definitions` table
```sql
CREATE TABLE IF NOT EXISTS slo_definitions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    metric TEXT NOT NULL,              -- e.g. "error_rate", "latency_p99", "availability"
    target_pct FLOAT NOT NULL,         -- e.g. 99.9
    window_hours INT NOT NULL,         -- rolling window
    current_value FLOAT,               -- last computed value (updated by monitor)
    error_budget_pct FLOAT,            -- (current/target)*100 remaining budget
    burn_rate_1h FLOAT,               -- consumption rate over last 1h
    burn_rate_15min FLOAT,            -- consumption rate over last 15min
    status TEXT DEFAULT 'healthy',     -- healthy | burn_rate_alert | budget_exhausted
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Burn-rate alert thresholds
- Burn-rate alert: `burn_rate_1h > 2.0` OR `burn_rate_15min > 3.0`
- These match the Google SRE book's alerting conditions (Chapter 5)
- When alert fires: set `status = 'burn_rate_alert'`

### SLO-aware escalation
In `ingest_incident` (after composite_severity computation):
- If any SLO for `payload.domain` has `status = 'burn_rate_alert'`
- AND new incident's composite_severity is not already Sev0
- → escalate to Sev0, add `slo_escalated: True` field to incident doc

### Error budget computation
`error_budget_pct = (current_value / target_pct) * 100`
- If `current_value = 99.95` and `target_pct = 99.9` → budget = 100.5% (above target, healthy)
- If `current_value = 99.5` and `target_pct = 99.9` → budget = 99.6% (below target)

</decisions>

<code_context>
## Existing Code Insights

### PostgreSQL Migration Pattern (from main.py)
```python
# Startup migration in lifespan:
dsn = resolve_postgres_dsn()
conn = await asyncpg.connect(dsn)
await register_vector(conn)
await conn.execute("CREATE TABLE IF NOT EXISTS runbooks (...)")
await conn.execute("CREATE INDEX IF NOT EXISTS ...")
await conn.close()
```

### Runbook RAG Pattern (reuse for incident_memory)
- `generate_query_embedding(text)` — uses AzureOpenAI text-embedding-3-small, already implemented in `runbook_rag.py`
- `resolve_postgres_dsn()` — reads POSTGRES_DSN or POSTGRES_HOST/PORT/DB/USER/PASSWORD
- Similarity search pattern with `asyncpg` + `pgvector.asyncpg.register_vector`
- All in `runbook_rag.py` — reuse `generate_query_embedding` and `resolve_postgres_dsn` by import

### Environment Variables Available
- `POSTGRES_DSN` or `POSTGRES_HOST/PORT/DB/USER/PASSWORD` — already used
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` / `EMBEDDING_DEPLOYMENT_NAME` — already used
- `MEMORY_SIMILARITY_THRESHOLD` (new, default: "0.35")

### Incident status flow
Current: `new` → `evidence_ready` → `investigating` → `closed`
Phase 25 adds: `investigating` → `resolved` (via POST /api/v1/incidents/{id}/resolve)
'resolved' differs from 'closed' — closed is system-triggered, resolved is operator-triggered with summary

### Existing IncidentSummary fields
All optional, backward compatible additions needed:
- `historical_matches: Optional[list[dict]] = None` — top-3 similar past incidents
- `slo_escalated: Optional[bool] = None` — True if severity was escalated due to SLO burn rate

</code_context>

<specifics>
## Specific Ideas

### HistoricalMatch model
```python
class HistoricalMatch(BaseModel):
    incident_id: str
    domain: str
    severity: str
    title: Optional[str]
    similarity: float
    resolution_excerpt: Optional[str]
    resolved_at: str
```

### SLODefinition model
```python
class SLODefinition(BaseModel):
    id: str
    name: str
    domain: str
    metric: str
    target_pct: float
    window_hours: int
    current_value: Optional[float] = None
    error_budget_pct: Optional[float] = None
    burn_rate_1h: Optional[float] = None
    burn_rate_15min: Optional[float] = None
    status: str = "healthy"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
```

### SLO health endpoint
`GET /api/v1/slos/{slo_id}/health` → `{ slo_id, status, error_budget_pct, burn_rate_1h, burn_rate_15min, alert: bool }`

</specifics>

<deferred>
## Deferred Ideas

- Weekly Container App job for systemic pattern identification (Phase 28)
- SLO health cards in Observability tab UI (deferred)
- Automatic transcript extraction from Foundry thread (complex; operator provides summary for now)
- SLO metric computation from actual Azure Monitor data (Phase 26 handles metric ingestion)

</deferred>

---

*Phase: 25-institutional-memory*
*Context gathered: 2026-04-03 via autonomous mode*
