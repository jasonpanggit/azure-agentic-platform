---
plan_id: "42-1"
phase: 42
wave: 1
title: "Runbooks Tab — PostgreSQL-backed runbook library with semantic search and domain filters"
goal: "Add a Runbooks tab to the dashboard that lets operators browse, search (semantic + keyword), and filter the runbook library stored in PostgreSQL + pgvector, with domain/severity/tag facets and a detail drawer."
---

# Plan 42-1: Runbooks Tab

## Context

Phase 42 surfaces the existing runbook library (PostgreSQL + pgvector, seeded in Phase 30) in the web UI. Operators need to find relevant runbooks during an incident without leaving the dashboard.

**Current DashboardPanel state:** 11 tabs — `ops | alerts | audit | topology | resources | vms | vmss | aks | cost | observability | patch`.

**Target after this plan:** 12 tabs — `runbooks` appended as last tab:
`ops | alerts | audit | topology | resources | vms | vmss | aks | cost | observability | patch | runbooks`

**Key files to read before tasks:**
- `services/web-ui/components/PatchTab.tsx` — list tab pattern
- `services/web-ui/app/api/proxy/vms/route.ts` — proxy route pattern
- `services/api-gateway/main.py` — router include pattern

---

## Tasks

### Task 1 — API Gateway: runbook search endpoint
- `GET /api/v1/runbooks` — query params: `q` (text), `domain`, `severity`, `tag`, `limit`
- Hybrid search: pgvector cosine similarity + keyword fallback
- Returns: `[{ id, title, domain, severity, tags, summary, steps_preview }]`
- Graceful degradation: returns empty list if PostgreSQL unavailable

### Task 2 — Proxy route
- `services/web-ui/app/api/proxy/runbooks/route.ts`
- Forwards `GET` with query params to API gateway `/api/v1/runbooks`
- Standard `getApiGatewayUrl()` + `buildUpstreamHeaders()` + 15s timeout

### Task 3 — RunbookTab component
- `services/web-ui/components/RunbookTab.tsx`
- Search bar (text input, 300ms debounce)
- Domain filter chips (All, Compute, Network, Storage, Security, Arc, SRE, Patch, EOL)
- Severity filter (All, P1, P2, P3)
- Runbook cards: title, domain badge, severity badge, summary excerpt
- Click-to-expand detail drawer with full steps
- Skeleton loading state, empty state

### Task 4 — DashboardPanel wiring
- Import `RunbookTab`
- Add `BookOpen` icon from lucide-react
- Add `'runbooks'` to `TabId` union
- Add tab entry and tab panel

### Task 5 — Tests
- Unit tests for the API gateway runbook endpoint
- Mock PostgreSQL client
