---
phase: 52-finops-intelligence-agent
plan: 3
subsystem: frontend
tags: [finops, next-js, recharts, hitl, cost-tab, proxy-routes, css-tokens]

# Dependency graph
requires:
  - phase: 52-1 (agents/finops/ Python backend with 6 @ai_function tools)
  - phase: 52-2 (API gateway /api/v1/finops/* endpoints)

provides:
  - 6 Next.js proxy routes under app/api/proxy/finops/
  - Extended CostTab.tsx with FinOps KPIs, cost breakdown chart, idle resource waste list, RI utilisation card
  - DashboardPanel.tsx tab renamed from "Cost" to "FinOps" with DollarSign icon

affects:
  - services/web-ui/components/CostTab.tsx
  - services/web-ui/components/DashboardPanel.tsx
  - services/web-ui/app/api/proxy/finops/ (new directory, 6 route files)

# Tech tracking
tech-stack:
  used:
    - recharts ^3.8.1 (BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer — already in package.json)
    - shadcn/ui Table (TableHeader, TableBody, TableRow, TableHead, TableCell)
    - lucide-react DollarSign (added to DashboardPanel import)
  patterns:
    - Promise.allSettled for parallel FinOps endpoint fetches (independent error states)
    - CSS semantic token system (var(--accent-*), var(--text-*), color-mix(...)) — no hardcoded colors
    - HITL approve/reject via existing /api/proxy/approvals/{id}/approve|reject endpoints
    - Budget burn rate gauge: simple CSS horizontal progress bar, color thresholds at 90%/110%
    - Recharts layout="vertical" bar chart for resource group names (long labels)

key-files:
  created:
    - services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts
    - services/web-ui/app/api/proxy/finops/resource-cost/route.ts
    - services/web-ui/app/api/proxy/finops/idle-resources/route.ts
    - services/web-ui/app/api/proxy/finops/ri-utilization/route.ts
    - services/web-ui/app/api/proxy/finops/cost-forecast/route.ts
    - services/web-ui/app/api/proxy/finops/top-cost-drivers/route.ts
  modified:
    - services/web-ui/components/CostTab.tsx (extended, existing content preserved)
    - services/web-ui/components/DashboardPanel.tsx (DollarSign import + tab label/icon)

key-decisions:
  - "Existing CostTab.tsx EXTENDED (not replaced) — all Advisor recommendations card grid, impactBadgeStyle, formatCurrency, cleanServiceType helpers preserved unchanged"
  - "Empty state guard updated: only shows 'no recommendations' when ALL data sources (recommendations + FinOps endpoints) return empty"
  - "Refresh button now calls both fetchCostData() and fetchFinopsData() in parallel"
  - "finopsLoading guard added around all FinOps JSX sections to prevent layout shift during load"
  - "TopCostDriversResponse type defined but not fetched in fetchFinopsData (top-cost-drivers proxy route exists; UI can wire it in a future enhancement)"

# Metrics
duration: 25min
completed: 2026-04-14
---

# Phase 52-3: Frontend FinOps Tab Summary

**6 Next.js proxy routes + extended CostTab with FinOps KPIs, vertical bar chart, idle resource waste table with HITL buttons, and RI utilisation card — 0 TypeScript errors**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-14
- **Completed:** 2026-04-14
- **Tasks:** 3
- **Files created:** 6 proxy routes
- **Files modified:** 2 (CostTab.tsx, DashboardPanel.tsx)

## Accomplishments

### Task 1: 6 Proxy Routes
Created all 6 Next.js API proxy routes under `services/web-ui/app/api/proxy/finops/`:
- `cost-breakdown/route.ts` → `GET /api/v1/finops/cost-breakdown`
- `resource-cost/route.ts` → `GET /api/v1/finops/resource-cost`
- `idle-resources/route.ts` → `GET /api/v1/finops/idle-resources`
- `ri-utilization/route.ts` → `GET /api/v1/finops/ri-utilization`
- `cost-forecast/route.ts` → `GET /api/v1/finops/cost-forecast`
- `top-cost-drivers/route.ts` → `GET /api/v1/finops/top-cost-drivers`

All routes follow the exact `vms/cost-summary/route.ts` pattern: `getApiGatewayUrl()`, `buildUpstreamHeaders()`, `AbortSignal.timeout(15000)`, graceful error fallbacks, `logger.child({ route })`, `export const runtime = 'nodejs'`, `export const dynamic = 'force-dynamic'`.

### Task 2: DashboardPanel Tab Rename
- Added `DollarSign` to lucide-react import
- Changed `{ id: 'cost', label: 'Cost', Icon: TrendingDown }` → `{ id: 'cost', label: 'FinOps', Icon: DollarSign }`
- `TabId` type unchanged — no downstream breakage

### Task 3: CostTab.tsx Extended
Added above the existing Advisor card grid:

**7 new TypeScript interfaces:** `CostBreakdownItem`, `CostBreakdownResponse`, `CostForecastResponse`, `IdleResource`, `IdleResourcesResponse`, `RiUtilisationResponse`, `TopCostDriver`/`TopCostDriversResponse`

**New state:** `breakdown`, `forecast`, `idleResources`, `riUtilisation`, `finopsLoading`, `finopsError`, `approvingId`

**`fetchFinopsData`:** `Promise.allSettled` parallel fetch of 4 FinOps endpoints (independent failure — one endpoint failing doesn't block others)

**New UI sections:**
1. **FinOps KPIs row** — Month-to-Date Spend card, Forecast Month-End card, Budget burn rate gauge (CSS horizontal bar, green/orange/red at 90%/110% thresholds)
2. **Cost Breakdown Chart** — Recharts `layout="vertical"` BarChart, top-10 resource groups by 30d spend, `var(--accent-blue)` bars
3. **Idle Resources table** — shadcn/ui Table, avg CPU (orange), monthly cost (green), HITL Approve/Reject buttons calling `/api/proxy/approvals/{id}/approve|reject`
4. **RI Utilisation card** — RI benefit consumed (amortized-delta), utilisation note
5. **Section divider** — "Azure Advisor Cost Recommendations" heading before existing card grid

**Preserved unchanged:** `impactBadgeStyle()`, `formatCurrency()`, `cleanServiceType()`, `extractTitle()`, Advisor card grid, all existing state variables and `fetchCostData` callback

## Task Commits

1. **Task 1: 6 proxy routes** — `0399332` (feat: add 6 Next.js proxy routes under app/api/proxy/finops/)
2. **Task 2: DashboardPanel tab rename** — `91982a6` (feat: rename Cost tab to FinOps with DollarSign icon)
3. **Task 3: CostTab extension** — `77718d1` (feat: extend CostTab with FinOps KPIs, cost breakdown chart, idle resources, and RI utilisation)

## Verification Results

```
TypeScript: 0 errors (tsc --noEmit)
All 6 proxy routes: ✓
DashboardPanel label 'FinOps': ✓
DashboardPanel id 'cost' unchanged: ✓
CostTab FinOps markers: 18 (≥4 required)
No hardcoded Tailwind color classes: 0
No hardcoded hex colors: 0
```

## Deviations from Plan

### Auto-fixed: Empty state guard updated
- **Issue:** Original plan's empty-state check `recommendations.length === 0` would show "No recommendations" immediately before FinOps data loads (since `fetchFinopsData` runs async).
- **Fix:** Updated guard to `recommendations.length === 0 && !finopsLoading && !forecast && breakdown.length === 0 && idleResources.length === 0` — only shows empty state when ALL data sources are empty.
- **Impact:** Better UX; no scope change.

### Auto-fixed: Refresh button wires both fetch callbacks
- **Plan:** Button only called `fetchCostData`.
- **Fix:** `onClick={() => { fetchCostData(); fetchFinopsData(); }}` and `disabled={loading || finopsLoading}`.
- **Impact:** Refresh now refreshes all FinOps data, not just Advisor recommendations.

### TopCostDrivers not wired to fetchFinopsData
- **Reason:** The plan's `fetchFinopsData` fetched 4 endpoints (breakdown, forecast, idle, ri). `top-cost-drivers` proxy route was created but not wired into the UI fetch (no corresponding UI section in the plan JSX). The type `TopCostDriversResponse` is defined for future use.
- **Impact:** Zero — proxy route exists and is ready; wiring to a UI section is a future enhancement if needed.

## Issues Encountered

None — 0 TypeScript errors on first compile pass.

## User Setup Required

None — proxy routes are passive (no backend changes needed until Plan 52-2 API gateway endpoints are deployed). The FinOps sections will show loading state and then remain empty until the gateway routes exist.

## Next Phase Readiness

- Frontend FinOps tab is complete and type-safe
- Requires Plan 52-2 API gateway endpoints to be deployed for live data
- Terraform (Plan 52-4) needed to provision `ca-finops-prod` Container App

---
*Phase: 52-finops-intelligence-agent*
*Plan: 52-3 (Frontend FinOps Tab)*
*Completed: 2026-04-14*
