# Design Spec: VMSS + AKS Compute Tabs

**Date:** 2026-04-11
**Status:** Approved
**Scope:** Compute Expansion — add VMSSTab and AKSTab to the web UI dashboard

---

## 1. Overview

Add two new dedicated compute resource tabs — **VMSS** and **AKS** — to the existing dashboard, following the established VMTab → VMDetailPanel pattern. No new architectural patterns are introduced; this is a pure extension of proven components.

**Goals:**
- Give operators first-class visibility into Virtual Machine Scale Sets and AKS clusters
- Consistent experience with the existing VM tab (same badge system, same detail panel structure, same AI chat pattern)
- Dedicated contextual AI chat per resource, scoped to that VMSS or cluster

**Out of scope (this phase):**
- Backend agent tools for VMSS/AKS (Phase 32 tools already exist; Phase 34 wires them)
- VMSS instance-level drill-down chat
- AKS log streaming / kubectl-style output
- Arc-connected AKS clusters (handled by Arc agent)

---

## 2. Tab Registration

**Tab order:** Alerts · Audit · Topology · Resources · VMs · **VMSS** · **AKS** · Observability · Patch

VMSS and AKS are inserted immediately after VMs, grouping all compute resource types together. This preserves existing muscle memory while making the compute group visually adjacent.

**DashboardPanel.tsx changes:**

```typescript
// Add to TABS array (after vms, before observability):
// Note: existing TABS array uses Icon (capital I) as the property name
{ id: 'vmss', label: 'VMSS', Icon: Scaling },   // lucide-react: Scaling
{ id: 'aks',  label: 'AKS',  Icon: Container },  // lucide-react: Container

// Also update the TabId union type:
type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'observability' | 'patch'

// Add to panel render section:
<div hidden={activeTab !== 'vmss'}>
  <VMSSTab subscriptions={selectedSubscriptions} onVMSSClick={handleVMSSClick} />
</div>
<div hidden={activeTab !== 'aks'}>
  <AKSTab subscriptions={selectedSubscriptions} onAKSClick={handleAKSClick} />
</div>
```

All panels stay always-mounted (using `hidden={...}`, not conditional rendering) — consistent with the existing pattern to avoid remounting/refetch on tab switch.

---

## 3. Shared Types — `types/azure-resources.ts`

Extract all inline resource type definitions into a single shared file. This is a necessary cleanup that makes all three compute tabs maintainable.

```typescript
// Extracted from VMTab.tsx (unchanged)
export interface VMRow { ... }
export interface EolEntry { ... }

// Extracted from VMDetailPanel.tsx (unchanged)
export interface VMDetail { ... }
export interface VMMetricSeries { ... }
export interface Evidence { ... }

// Extracted from VMDetailPanel.tsx (add to shared types)
export interface ActiveIncident {
  incident_id: string
  severity: string
  title?: string
  created_at: string
  status: string
  investigation_status?: string
}

// New for VMSS
export interface VMSSRow {
  id: string                    // ARM resource ID
  name: string
  resource_group: string
  subscription_id: string
  location: string
  sku: string                   // e.g. "Standard_D4s_v3"
  instance_count: number        // total instances
  healthy_instance_count: number
  os_type: string               // "Windows" | "Linux"
  os_image_version: string      // e.g. "Ubuntu 22.04"
  power_state: string           // "running" | "stopped" | "deallocated"
  health_state: string          // "available" | "degraded" | "unavailable" | "unknown"
  autoscale_enabled: boolean
  active_alert_count: number
}

export interface VMSSDetail extends VMSSRow {
  min_count: number
  max_count: number
  upgrade_policy: string        // "Automatic" | "Manual" | "Rolling"
  active_incidents: ActiveIncident[]
  health_summary: string | null
}

export interface VMSSInstance {
  instance_id: string
  name: string
  power_state: string
  health_state: string
  provisioning_state: string
}

// New for AKS
export interface AKSCluster {
  id: string                    // ARM resource ID
  name: string
  resource_group: string
  subscription_id: string
  location: string
  kubernetes_version: string    // e.g. "1.28.5"
  latest_available_version: string | null  // null if already current
  node_pool_count: number
  node_pools_ready: number      // pools where all nodes are ready
  total_nodes: number
  ready_nodes: number
  system_pod_health: 'healthy' | 'degraded' | 'unknown'
  fqdn: string | null
  network_plugin: string        // "azure" | "kubenet"
  rbac_enabled: boolean
  active_alert_count: number
}

export interface AKSNodePool {
  name: string
  vm_size: string
  node_count: number
  ready_node_count: number
  mode: 'System' | 'User'
  os_type: 'Linux' | 'Windows'
  min_count: number | null      // null if autoscaler disabled
  max_count: number | null
  provisioning_state: string
}

export interface AKSWorkloadSummary {
  running_pods: number
  crash_loop_pods: number
  pending_pods: number
  namespace_count: number
}
```

---

## 4. VMSSTab — List View

**File:** `components/VMSSTab.tsx`

**Props:** `{ subscriptions: string[], onVMSSClick?: (resourceId: string, resourceName: string) => void }`

**Columns:**

| Column | Notes |
|--------|-------|
| Name | Clickable row |
| Resource Group | |
| SKU | VM size used by instances |
| Instances | `InstanceCountBadge` — green if all healthy, yellow if degraded, red if >20% unhealthy |
| Power State | `PowerStateBadge` (reused from VMTab) |
| Health | `HealthBadge` (reused from VMTab) |
| Active Alerts | Count badge, red when >0 |

**Data fetch:** `GET /api/proxy/vmss?subscriptions=...`

**Secondary fetch (non-blocking):** EOL lookup reused — VMSS instances share an OS image, so `POST /api/proxy/vms/eol` can be called with `os_image_version` strings. Verify that the existing `/api/v1/vms/eol` endpoint accepts arbitrary OS name strings (not VM resource IDs) before relying on this; if not, a dedicated VMSS EOL call or inline display of the raw `os_image_version` string is the fallback.

**Loading state:** 5 skeleton rows (same pattern as VMTab).

**Row click:** opens `VMSSDetailPanel` as a fixed right-side overlay with backdrop.

**New badge — `InstanceCountBadge`:**
```
all healthy   → green "3/3"
some unhealthy → yellow "3/5"
>20% unhealthy → red "1/5"
```

**Styling convention:** CSS custom properties (`var(--accent-*)`) matching VMTab, not Tailwind utility classes.

---

## 5. VMSSDetailPanel — Tabbed Detail

**File:** `components/VMSSDetailPanel.tsx`

**Props:** `{ resourceId: string, resourceName: string, onClose: () => void }`

**Tabs:**

### Tab 1 — Overview
- Summary cards: Healthy instances, Unhealthy instances, Total instances, Active Alerts
- Metadata: SKU, location, autoscale min/max, OS image version, upgrade policy
- Active Incidents list (same `ActiveIncident[]` pattern as VMDetailPanel)

### Tab 2 — Instances
- Table: Instance ID, Power State, Health State, Provisioning State
- Sortable by health state (unhealthy first by default)
- Searchable by instance ID
- Data: fetched as part of `GET /api/proxy/vmss/[vmssId]`

### Tab 3 — Metrics
- Azure Monitor charts via `recharts` (same pattern as VMDetailPanel)
- Metrics: Aggregate CPU %, Memory %, Network In/Out, per-instance breakdown toggle
- Timespan selector: 1h / 6h / 24h / 7d
- Data: `GET /api/proxy/vmss/[vmssId]/metrics`

### Tab 4 — Scaling
- Autoscale rule summary: current rule set name, scale-out threshold, scale-in threshold, cooldown period
- Recent scale events table: timestamp, direction (scale-out/in), instance delta, trigger metric
- Read-only display; HITL-gated scale proposal via AI chat

### Tab 5 — AI Chat
- Polling chat (same pattern as VMDetailPanel):
  - `POST /api/proxy/vmss/[vmssId]/chat` → gets `{ thread_id, run_id }`
  - Polls `GET /api/proxy/chat/result?thread_id=...&run_id=...` every 2 seconds
- Auto-sends on open: *"Summarize this scale set's health and suggest investigation steps."*
- Resets on resource change via `useEffect([resourceId])`

---

## 6. AKSTab — List View

**File:** `components/AKSTab.tsx`

**Props:** `{ subscriptions: string[], onAKSClick?: (resourceId: string, resourceName: string) => void }`

**Columns:**

| Column | Notes |
|--------|-------|
| Cluster Name | Clickable row |
| Resource Group | |
| Location | |
| K8s Version | `K8sVersionBadge` — neutral if current, yellow if upgrade available |
| Node Pools | `NodeHealthBadge` — `ready/total` pools (e.g. "3/3"), colored by ratio |
| System Pods | `SystemPodBadge` — healthy (green) / degraded (yellow) / unknown (muted) |
| Upgrade | `UpgradeBadge` — amber "⬆ 1.29" if `latest_available_version != null`; hidden if current |
| Active Alerts | Count badge, red when >0 |

**Data fetch:** `GET /api/proxy/aks?subscriptions=...`

**Loading state:** 5 skeleton rows.

**Row click:** opens `AKSDetailPanel` as fixed right-side overlay with backdrop.

**New badges:**

```
K8sVersionBadge:  current → neutral pill "1.28"
                  outdated → yellow pill "1.28 · ⬆ available"

NodeHealthBadge:  all ready → green "3/3"
                  some not ready → yellow "10/12"
                  majority not ready → red "2/5"

UpgradeBadge:     amber pill "⬆ 1.29" (only shown when upgrade exists)
```

---

## 7. AKSDetailPanel — Tabbed Detail

**File:** `components/AKSDetailPanel.tsx`

**Props:** `{ resourceId: string, resourceName: string, onClose: () => void }`

**Tabs:**

### Tab 1 — Overview
- Summary cards: Node Pools Ready (X/Y), Nodes Ready (X/Y), K8s Version, Upgrade badge
- Metadata: FQDN, network plugin, RBAC enabled, managed identity status, location
- Active Incidents list

### Tab 2 — Node Pools
- Table: Pool Name, VM Size, Nodes (ready/total), Mode (System/User badge), OS (Linux/Windows), Autoscaler Min/Max, Provisioning State
- Rows with `ready < total` highlighted in yellow
- Data: included in `GET /api/proxy/aks/[aksId]` response

### Tab 3 — Workloads
- Summary cards: Running Pods, CrashLoopBackOff, Pending
- Namespace filter dropdown
- Deployment list: name, namespace, replicas ready/total, status
- kube-system system pods health summary (control plane indicators)
- Data: `GET /api/proxy/aks/[aksId]` workload section

### Tab 4 — Metrics
- Azure Monitor charts via `recharts`:
  - Node CPU % per pool (stacked line)
  - Node Memory % per pool (stacked line)
  - Pod count over time
  - API server request latency p99 (ms)
  - Pending pod queue depth
- Timespan selector: 1h / 6h / 24h / 7d
- Data: `GET /api/proxy/aks/[aksId]/metrics`

### Tab 5 — AI Chat
- Same polling pattern as VMSSDetailPanel
- `POST /api/proxy/aks/[aksId]/chat`
- Auto-sends on open: *"Summarize this cluster's health and suggest investigation steps."*
- Resets on cluster change via `useEffect([resourceId])`

---

## 8. Backend Proxy Routes

All routes follow the established pattern:
- `export const runtime = 'nodejs'`
- `export const dynamic = 'force-dynamic'`
- `buildUpstreamHeaders(request.headers.get('Authorization'), false)`
- `AbortSignal.timeout(15000)`
- Graceful error fallback returning empty array / null

Example skeleton (mirrors `app/api/proxy/vms/route.ts`):
```typescript
import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const upstream = `${getApiGatewayUrl()}/api/v1/vmss?${searchParams.toString()}`
  try {
    const res = await fetch(upstream, {
      headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) return NextResponse.json([], { status: 200 })
    return NextResponse.json(await res.json())
  } catch {
    return NextResponse.json([], { status: 200 })
  }
}
```

| Route file | Method | Upstream |
|------------|--------|----------|
| `app/api/proxy/vmss/route.ts` | GET | `GET /api/v1/vmss?subscriptions=...` |
| `app/api/proxy/vmss/[vmssId]/route.ts` | GET | `GET /api/v1/vmss/{vmssId}` |
| `app/api/proxy/vmss/[vmssId]/metrics/route.ts` | GET | `GET /api/v1/vmss/{vmssId}/metrics` |
| `app/api/proxy/vmss/[vmssId]/chat/route.ts` | POST | `POST /api/v1/vmss/{vmssId}/chat` |
| `app/api/proxy/aks/route.ts` | GET | `GET /api/v1/aks?subscriptions=...` |
| `app/api/proxy/aks/[aksId]/route.ts` | GET | `GET /api/v1/aks/{aksId}` |
| `app/api/proxy/aks/[aksId]/metrics/route.ts` | GET | `GET /api/v1/aks/{aksId}/metrics` |
| `app/api/proxy/aks/[aksId]/chat/route.ts` | POST | `POST /api/v1/aks/{aksId}/chat` |

The `[vmssId]` and `[aksId]` parameters are base64url-encoded ARM resource IDs, matching the `vms/[vmId]` naming convention.

---

## 9. AlertFeed Integration

`AlertFeed.tsx` "Investigate" button currently only opens `VMDetailPanel`. It should route to the appropriate detail panel based on `resource_type`:

```typescript
// In AlertFeed.tsx handleInvestigate():
if (resource_type?.includes('virtualmachinescalesets')) {
  onVMSSClick?.(resource_id, resource_name)
} else if (resource_type?.includes('managedclusters')) {
  onAKSClick?.(resource_id, resource_name)
} else {
  onVMClick?.(resource_id, resource_name)  // existing behaviour
}
```

`DashboardPanel` passes all three callbacks down to `AlertFeed`.

---

## 10. Styling Convention

All new components use **CSS custom properties** matching VMTab and VMDetailPanel:
- `var(--accent-blue)`, `var(--accent-green)`, `var(--accent-red)`, `var(--accent-yellow)`
- `var(--bg-canvas)`, `var(--bg-surface)`, `var(--border)`, `var(--text-secondary)`
- Badge backgrounds: `color-mix(in srgb, var(--accent-*) 15%, transparent)`

Do **not** use hardcoded Tailwind color classes (e.g. `bg-green-100 text-green-700`). This matches the existing compute tab convention and supports dark mode correctly.

---

## 11. New Files Summary

```
services/web-ui/
├── components/
│   ├── VMSSTab.tsx                           # NEW
│   ├── VMSSDetailPanel.tsx                   # NEW
│   ├── AKSTab.tsx                            # NEW
│   └── AKSDetailPanel.tsx                    # NEW
├── app/api/proxy/
│   ├── vmss/
│   │   ├── route.ts                          # NEW
│   │   └── [vmssId]/
│   │       ├── route.ts                      # NEW
│   │       ├── metrics/route.ts              # NEW
│   │       └── chat/route.ts                 # NEW
│   └── aks/
│       ├── route.ts                          # NEW
│       └── [aksId]/
│           ├── route.ts                      # NEW
│           ├── metrics/route.ts              # NEW
│           └── chat/route.ts                 # NEW
└── types/
    └── azure-resources.ts                    # NEW (extracted + extended)
```

**Modified files:**
```
services/web-ui/
├── components/
│   ├── DashboardPanel.tsx     # add vmss + aks tab IDs and panels
│   ├── AlertFeed.tsx          # route Investigate button to VMSS/AKS panels
│   ├── VMTab.tsx              # import VMRow from types/azure-resources.ts
│   └── VMDetailPanel.tsx      # import VMDetail etc from types/azure-resources.ts
```

---

## 12. Backend Prerequisite Note

This spec covers **frontend only**. The proxy routes call backend endpoints (`/api/v1/vmss/...`, `/api/v1/aks/...`) that need to be implemented in `services/api-gateway/`. The Phase 32 agent tools (`vmss_get_instances`, `aks_get_cluster_health`, etc.) exist and are implemented — they need corresponding REST endpoints exposed by the gateway.

The frontend can be built and proxy routes scaffolded before the backend endpoints exist; the proxy routes gracefully return empty arrays when the upstream is unavailable.
