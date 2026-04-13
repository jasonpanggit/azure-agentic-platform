---
plan_id: "44-1"
phase: 44
wave: 1
title: "Operations Dashboard — real-time AIOps command centre tab (OpsTab)"
goal: "Give shift operators a real-time situational awareness tab — the first tab they open to understand the entire fleet at a glance before diving into any specific incident."
---

# Plan 44-1: Operations Dashboard

## Context

Phase 44 adds the Ops tab as the default first tab in the dashboard. Operators currently have no single-pane view of platform health; they must manually open multiple tabs to assess the fleet. This closes that gap.

**Note:** This phase was originally scoped under the placeholder directory `42-ai-ops-dashboard-tab-with-operational-dashboards`. It was executed as Phase 44 per the ROADMAP.

**Current DashboardPanel state (before):** 11 tabs, `alerts` as default.

**Target after this plan:** 12 tabs, `ops` as the first and default tab:
`ops | alerts | audit | topology | resources | vms | vmss | aks | cost | observability | patch | runbooks`

**Pattern source files:**
- `services/web-ui/components/ResourcesTab.tsx` — data-fetching + skeleton pattern
- `services/web-ui/app/api/proxy/vms/route.ts` — proxy route pattern
- `services/api-gateway/main.py` — router include pattern

---

## Tasks

### Task 1 — API Gateway: 3 ops endpoints
- `GET /api/v1/ops/platform-health` — 6 KPIs: MTTR P50/P95, noise reduction %, SLO compliance %, auto-remediation rate %, pipeline lag ms, savings 30d $
- `GET /api/v1/ops/patterns` — top recurring incident patterns with frequency and domain
- `GET /api/v1/ops/imminent-breaches` — SLO breach progress bars (% consumed of error budget)

### Task 2 — 3 proxy routes
- `services/web-ui/app/api/proxy/ops/platform-health/route.ts`
- `services/web-ui/app/api/proxy/ops/patterns/route.ts`
- `services/web-ui/app/api/proxy/ops/imminent-breaches/route.ts`

### Task 3 — OpsTab component
- `services/web-ui/components/OpsTab.tsx`
- 6-KPI header row with color-coded thresholds (green/amber/red)
- Active P1/P2 incident table sorted by severity then age
- Imminent breach progress bars
- Top recurring pattern cards
- Error budget portfolio stacked bars
- 30s auto-refresh via parallel `Promise.allSettled()`
- Per-section error isolation (one section failure doesn't block others)

### Task 4 — DashboardPanel wiring
- Import `OpsTab`, `LayoutDashboard` icon
- Add `'ops'` to `TabId` union as first entry
- Set `useState<TabId>('ops')` as default active tab
- Add tab entry (first) and tab panel
