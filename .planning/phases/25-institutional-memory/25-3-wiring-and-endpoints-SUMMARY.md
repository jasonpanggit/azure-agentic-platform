# Phase 25 Summary — Institutional Memory and SLO Tracking

**Phase:** 25
**Branch:** `gsd/phase-25-institutional-memory`
**Completed:** 2026-04-04
**Requirements:** INTEL-003 (historical incident memory) + INTEL-004 (SLO tracking)

---

## What Was Built

### Wave 1: New Services (25-1, 25-2)

| File | Description |
|------|-------------|
| `services/api-gateway/incident_memory.py` | pgvector-backed historical incident matching. `store_incident_memory` embeds + upserts resolved incidents; `search_incident_memory` does cosine similarity search with 0.35 threshold. Non-fatal when postgres unavailable. |
| `services/api-gateway/slo_tracker.py` | SLO CRUD + burn-rate alerting. `create_slo`, `list_slos`, `get_slo_health`, `update_slo_metrics`, `check_domain_burn_rate_alert`. Google SRE Book thresholds: 1h>2.0, 15min>3.0. Always returns bool (non-fatal). |

### Wave 2: Wiring and Endpoints (25-3)

| File | Changes |
|------|---------|
| `services/api-gateway/main.py` | +imports, +migrations, +SLO escalation, +_attach_historical_matches BackgroundTask, +resolve endpoint, +SLO routes |
| `services/api-gateway/incidents_list.py` | SELECT projection includes `historical_matches`, `slo_escalated` |
| `services/api-gateway/models.py` | Added `HistoricalMatch`, `SLODefinition`, `SLOHealth`, `SLOCreateRequest`; added `historical_matches` + `slo_escalated` to `IncidentSummary` |

---

## New API Endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/api/v1/incidents/{id}/resolve` | 200 | Resolve incident, store embedding in incident_memory |
| `POST` | `/api/v1/slos` | 201 | Create SLO definition |
| `GET` | `/api/v1/slos` | 200 | List SLOs (optional `?domain=` filter) |
| `GET` | `/api/v1/slos/{slo_id}/health` | 200 | SLO health snapshot |

---

## Startup Migrations Added

Both use `CREATE TABLE IF NOT EXISTS` (idempotent):
- `incident_memory` table with `VECTOR(1536)` embedding column
- `incident_memory_embedding_idx` — ivfflat index (lists=50)
- `slo_definitions` table with burn-rate metric columns
- `slo_definitions_domain_status_idx` — composite (domain, status) index

---

## Incident Pipeline Integration

### SLO Escalation (INTEL-004)
After `compute_composite_severity` runs, if `_composite_severity != "Sev0"`:
- Calls `check_domain_burn_rate_alert(payload.domain)`
- If True: escalates to Sev0, sets `_slo_escalated = True`
- Non-fatal: exceptions logged as WARNING, incident proceeds
- `slo_escalated` patched onto Cosmos incident doc alongside `composite_severity`

### Historical Memory BackgroundTask (INTEL-003)
After change correlator is queued:
- `_attach_historical_matches` queued as BackgroundTask
- Searches `incident_memory` for top-3 similar past incidents
- Patches `historical_matches` onto Cosmos incident doc
- Non-fatal: exceptions logged as WARNING, never blocks 202 response
- Must complete within 10s (INTEL-003 requirement)

### Incident Status Lifecycle (updated)
```
new → evidence_ready → investigating → resolved  (operator via POST .../resolve)
                                     → closed    (system-triggered)
                   → suppressed_cascade          (noise reducer)
                   → correlated                  (noise reducer)
```

`resolved` = operator confirmed root cause; embedding stored in `incident_memory`
`closed` = system-triggered (e.g. Azure Monitor auto-resolved)

---

## Test Results

| Category | Count |
|----------|-------|
| New tests (Phase 25) | 15 |
| Previous tests (pre-Phase 25) | 440 |
| Skipped (pre-existing) | 2 |
| **Total passing** | **455** |
| Failed | 0 |

### New test file: `test_institutional_memory_wiring.py`

- `TestHistoricalMemoryWiring` (2 tests) — BackgroundTask queuing verification
- `TestSLOEscalation` (4 tests) — escalation, no-escalation, no-double-escalation, failure non-fatal
- `TestResolveEndpoint` (4 tests) — 200 success, 404 not found, 503 no cosmos, 503 memory unavailable
- `TestSLORoutes` (5 tests) — create 201, list 200, domain filter, health 200, health 404

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| `incident_memory` migration idempotent | ✅ |
| `slo_definitions` migration idempotent | ✅ |
| Both indexes created | ✅ |
| Startup log updated | ✅ |
| `search_incident_memory`, `store_incident_memory` imported | ✅ |
| `check_domain_burn_rate_alert`, `create_slo`, `list_slos`, `get_slo_health` imported | ✅ |
| New models imported | ✅ |
| SLO escalation non-fatal | ✅ |
| `slo_escalated` on Cosmos doc | ✅ |
| `_attach_historical_matches` BackgroundTask | ✅ |
| BackgroundTask non-fatal | ✅ |
| Resolve endpoint 200/404/503 | ✅ |
| SLO routes 201/200/404 | ✅ |
| 15 tests, all passing | ✅ |
| Full regression clean | ✅ |
