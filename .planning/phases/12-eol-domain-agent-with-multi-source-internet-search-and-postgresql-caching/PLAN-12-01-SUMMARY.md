---
plan: PLAN-12-01
status: COMPLETE
commit: ced852f
date: 2026-03-31
---

# PLAN-12-01 Summary — Agent Spec + DB Migration + Shared Infrastructure

## Status: COMPLETE

All 4 tasks executed successfully. All 9 acceptance criteria pass.

---

## What Was Created

### New Files

| File | Description |
|------|-------------|
| `docs/agents/eol-agent.spec.md` | AGENT-009 compliant EOL agent spec — Persona, 9 Goals, 9 Workflow steps, Tool Permissions table (13 rows), Safety Constraints (7 constraints), 3 Example Flows |
| `services/api-gateway/migrations/004_create_eol_cache_table.sql` | Migration 004 — `eol_cache` table with 24h TTL, `UNIQUE(product, version, source)`, `idx_eol_cache_lookup` index, `raw_response JSONB`, `latest_version TEXT`, `lts BOOLEAN`, `support_end DATE` |

### Modified Files

| File | Change |
|------|--------|
| `services/api-gateway/models.py` | `IncidentPayload.domain` regex extended from `^(compute|network|storage|security|arc|sre)$` to `^(compute|network|storage|security|arc|sre|patch|eol)$` |
| `services/api-gateway/main.py` | `_run_startup_migrations()` now creates the `eol_cache` table and `idx_eol_cache_lookup` index on startup; log message updated to reference eol_cache |

---

## Acceptance Criteria Results

| Check | Result |
|-------|--------|
| `test -f docs/agents/eol-agent.spec.md` | PASS |
| `grep -q "agent: eol" docs/agents/eol-agent.spec.md` | PASS |
| `grep -q "## Persona" docs/agents/eol-agent.spec.md` | PASS |
| `grep -q "## Workflow" docs/agents/eol-agent.spec.md` | PASS |
| `test -f services/api-gateway/migrations/004_create_eol_cache_table.sql` | PASS |
| `grep -q "eol_cache" ...004_create_eol_cache_table.sql` | PASS (5 occurrences) |
| `grep -q "eol" services/api-gateway/models.py` | PASS |
| `grep -q "patch" services/api-gateway/models.py` | PASS |
| `grep -q "eol_cache" services/api-gateway/main.py` | PASS (4 occurrences) |

Additional spec checks:
- `TRIAGE-003` appears 6 times in spec (≥ 3 required) ✅
- `REMEDI-001` appears 7 times in spec (≥ 3 required) ✅
- `query_endoflife_date`, `query_ms_lifecycle`, `scan_estate_eol` all present in Tool Permissions ✅

---

## Deviations from Plan

None. All tasks executed exactly as specified in PLAN-12-01.

Notable alignment with RESEARCH.md findings:
- Migration numbered `004` (not `003`) per R-06 — 003 already taken by `gitops_cluster_config`
- `@tool` used in spec (not `@ai_function`) per Section 7 of RESEARCH.md
- `patch` added alongside `eol` to domain regex per R-01 critical finding

---

## Commit Hash

`ced852f` — `feat(phase-12): PLAN-12-01 — EOL agent spec, eol_cache migration, domain regex fix`
