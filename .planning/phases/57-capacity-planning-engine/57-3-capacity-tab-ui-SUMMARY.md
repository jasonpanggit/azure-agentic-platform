---
plan: 57-3-capacity-tab-ui-PLAN.md
completed: "2026-04-16"
status: complete
---

# Summary: Plan 57-3 — Capacity Tab UI

## What Was Built

### lib/capacity-types.ts
6 exported TypeScript types: `TrafficLight`, `CapacityQuotaItem`, `CapacityHeadroomResponse`, `SubnetHeadroomItem`, `IPSpaceHeadroomResponse`, `AKSNodePoolHeadroomItem`, `AKSHeadroomResponse`.

### 4 Proxy Routes
- `app/api/proxy/capacity/headroom/route.ts` → `/api/v1/capacity/headroom`
- `app/api/proxy/capacity/quotas/route.ts` → `/api/v1/capacity/quotas`
- `app/api/proxy/capacity/ip-space/route.ts` → `/api/v1/capacity/ip-space`
- `app/api/proxy/capacity/aks/route.ts` → `/api/v1/capacity/aks`

All follow proxy pattern: `runtime = 'nodejs'`, `dynamic = 'force-dynamic'`, `AbortSignal.timeout(15000)`.

### CapacityTab.tsx
- Header with title, location selector (eastus default), Refresh button
- Summary cards: Total / Critical / Warning / Healthy
- Quota Headroom table with traffic-light badges
- IP Address Space table (CIDR, total/available IPs, usage)
- AKS Node Pool table (cluster/pool/VM size, node counts)
- 90-day forecast LineChart (only when `snapshot_count >= 3`)
- All badges use `color-mix(in srgb, var(--accent-*) 15%, transparent)` — no hardcoded Tailwind colors

### DashboardPanel.tsx
- `'capacity'` added to `TabId` union
- `Gauge` icon added from lucide-react
- Capacity tab in "Monitoring & cost" group after sla
- CapacityTab imported and rendered

## Verification
- TypeScript: 0 new errors
- 4 proxy routes created with correct pattern
- Semantic CSS tokens used throughout (no hardcoded colors)
