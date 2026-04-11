# Phase 41 Research: VMSS + AKS Web UI Tabs

> Researched: 2026-04-11
> Primary spec: `docs/superpowers/specs/2026-04-11-vmss-aks-tabs-design.md`
> Status: COMPLETE — ready for plan authoring

---

## 1. Current DashboardPanel State

### Existing TabId union (line 17 of `DashboardPanel.tsx`)
```typescript
type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'cost' | 'observability' | 'patch'
```

### Existing TABS array (lines 25–34)
```typescript
const TABS = [
  { id: 'alerts',       label: 'Alerts',       Icon: Bell },
  { id: 'audit',        label: 'Audit',        Icon: ClipboardList },
  { id: 'topology',     label: 'Topology',     Icon: Network },
  { id: 'resources',    label: 'Resources',    Icon: Server },
  { id: 'vms',          label: 'VMs',          Icon: Monitor },
  { id: 'cost',         label: 'Cost',         Icon: TrendingDown },   // Phase 39
  { id: 'observability',label: 'Observability',Icon: Activity },
  { id: 'patch',        label: 'Patch',        Icon: ShieldCheck },
]
```

**Current tab count: 8.**

### Target tab order (spec §2)
Alerts · Audit · Topology · Resources · VMs · **VMSS** · **AKS** · Observability · Patch

**Note:** The spec inserts VMSS and AKS *after VMs, before Observability* — NOT after Cost.  
The Cost tab (Phase 39) currently sits between VMs and Observability. The target order from the spec implies: VMs → VMSS → AKS → (then Observability and Patch). Cost is not mentioned in the spec's stated order, but it exists in the codebase. The safest insertion is: keep Cost where it is (after VMs) and insert VMSS → AKS after Cost, giving:  
**Alerts · Audit · Topology · Resources · VMs · Cost · VMSS · AKS · Observability · Patch**  
Alternatively, insert VMSS/AKS immediately after VMs (before Cost) to respect the spec literally. **Recommended: follow spec literally — VMs → VMSS → AKS → Cost → Observability → Patch** (Cost just moves later in the compute group).

### DashboardPanel insertion details

**Line 17 — update TabId:**
```typescript
type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch'
```

**Lines 25–34 — TABS array, insert after vms entry (after line 29, before cost):**
```typescript
{ id: 'vmss', label: 'VMSS', Icon: Scaling },    // import Scaling from lucide-react
{ id: 'aks',  label: 'AKS',  Icon: Container },  // import Container from lucide-react
```

**Import line (line 4) — add Scaling and Container:**
```typescript
import { Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown, Scaling, Container } from 'lucide-react'
```

**New state variables (after line 46):**
```typescript
const [vmssDetailOpen, setVMSSDetailOpen] = useState(false)
const [selectedVMSS, setSelectedVMSS] = useState<{ resourceId: string; resourceName: string } | null>(null)
const [aksDetailOpen, setAKSDetailOpen] = useState(false)
const [selectedAKS, setSelectedAKS] = useState<{ resourceId: string; resourceName: string } | null>(null)
```

**New handler functions (after closeVMDetail on line 61):**
```typescript
function openVMSSDetail(resourceId: string, resourceName: string) {
  setSelectedVMSS({ resourceId, resourceName })
  setVMSSDetailOpen(true)
}
function closeVMSSDetail() {
  setVMSSDetailOpen(false)
  setSelectedVMSS(null)
}
function openAKSDetail(resourceId: string, resourceName: string) {
  setSelectedAKS({ resourceId, resourceName })
  setAKSDetailOpen(true)
}
function closeAKSDetail() {
  setAKSDetailOpen(false)
  setSelectedAKS(null)
}
```

**Tab panel render section (after tabpanel-vms block, before tabpanel-cost at line 161):**
```tsx
<div id="tabpanel-vmss" role="tabpanel" aria-labelledby="tab-vmss" hidden={activeTab !== 'vmss'}>
  <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
    <VMSSTab subscriptions={selectedSubscriptions} onVMSSClick={openVMSSDetail} />
  </div>
</div>

<div id="tabpanel-aks" role="tabpanel" aria-labelledby="tab-aks" hidden={activeTab !== 'aks'}>
  <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
    <AKSTab subscriptions={selectedSubscriptions} onAKSClick={openAKSDetail} />
  </div>
</div>
```

**Detail panel + backdrop section (after VM Detail Panel block at line 180+):**
```tsx
{vmssDetailOpen && selectedVMSS && (
  <>
    <div className="fixed inset-0 z-30" style={{ background: 'rgba(0,0,0,0.3)' }} onClick={closeVMSSDetail} />
    <VMSSDetailPanel resourceId={selectedVMSS.resourceId} resourceName={selectedVMSS.resourceName} onClose={closeVMSSDetail} />
  </>
)}
{aksDetailOpen && selectedAKS && (
  <>
    <div className="fixed inset-0 z-30" style={{ background: 'rgba(0,0,0,0.3)' }} onClick={closeAKSDetail} />
    <AKSDetailPanel resourceId={selectedAKS.resourceId} resourceName={selectedAKS.resourceName} onClose={closeAKSDetail} />
  </>
)}
```

**New imports at top of DashboardPanel.tsx:**
```typescript
import { VMSSTab } from './VMSSTab'
import { VMSSDetailPanel } from './VMSSDetailPanel'
import { AKSTab } from './AKSTab'
import { AKSDetailPanel } from './AKSDetailPanel'
```

---

## 2. AlertFeed Integration

**File:** `services/web-ui/components/AlertFeed.tsx`

**Current behavior (line 264):**
```typescript
onInvestigate?.(incident.incident_id, incident.resource_id, incident.resource_name)
```
`onInvestigate` goes directly to DashboardPanel which always opens VMDetailPanel.

**Current `onInvestigate` prop signature (line 39):**
```typescript
onInvestigate?: (incidentId: string, resourceId: string | undefined, resourceName: string | undefined) => void;
```

**Required change — spec §9:**
In `DashboardPanel.tsx`, the `onInvestigate` handler passed to `AlertFeed` must be updated. The resource routing logic should be in `DashboardPanel.tsx`, not in `AlertFeed.tsx` itself. Update the `openVMDetail` call on line 133:

```typescript
// In DashboardPanel.tsx, replace the AlertFeed onInvestigate inline handler:
onInvestigate={(incidentId, resourceId, resourceName) => {
  const resourceType = (resourceId ?? '').toLowerCase()
  if (resourceType.includes('virtualmachinescalesets')) {
    if (resourceId && resourceName) openVMSSDetail(resourceId, resourceName)
  } else if (resourceType.includes('managedclusters')) {
    if (resourceId && resourceName) openAKSDetail(resourceId, resourceName)
  } else {
    openVMDetail(incidentId, resourceId ?? null, resourceName ?? null)
  }
}}
```

**No changes needed to AlertFeed.tsx itself** — the routing decision lives in DashboardPanel, which already controls the handler. This is simpler and consistent with the existing pattern.

> **Gotcha:** The spec §9 shows AlertFeed handling the `if` check itself via `onVMSSClick?` / `onAKSClick?` optional callbacks. However, looking at the actual code, AlertFeed only receives one `onInvestigate` prop and DashboardPanel provides the routing logic inline. The cleaner approach (and less change) is keeping AlertFeed untouched and updating DashboardPanel's inline handler. No prop changes to AlertFeed.

---

## 3. Types File — `types/azure-resources.ts`

**Current types directory:** Only `services/web-ui/types/sse.ts` exists.

**New file:** `services/web-ui/types/azure-resources.ts`

**What to extract vs add:**
- `VMRow` and `EolEntry` are currently defined inline in `VMTab.tsx` (lines 9–23) — extract to shared types  
- `VMDetail`, `ActiveIncident`, `Evidence`, `RecentChange`, `MetricAnomaly`, `MetricSeries`, `ChatMessage` are defined inline in `VMDetailPanel.tsx` (lines 11–74) — extract selectively (at minimum `VMRow`, `EolEntry`, `ActiveIncident`)  
- `VMSSRow`, `VMSSDetail`, `VMSSInstance` — NEW  
- `AKSCluster`, `AKSNodePool`, `AKSWorkloadSummary` — NEW

**Full type file per spec §3 (see design spec for complete definitions).**

> **Gotcha on VMTab/VMDetailPanel extraction:** The spec calls for extracting existing VM types into `azure-resources.ts` and updating VMTab.tsx and VMDetailPanel.tsx to import from there. This is correct but must be done carefully — the existing interface names in VMDetailPanel.tsx use `MetricSeries` (not `VMMetricSeries` as the spec labels it). Match the actual names. The import-from refactor of existing files is low-risk but is a modified file, not a new file — plan this explicitly.

---

## 4. CSS Token System (from `globals.css`)

All custom properties available for badge styling:

### Color tokens
| Token | Light value | Dark value | Use for |
|-------|-------------|-----------|---------|
| `var(--accent-blue)` | `#0969DA` | `#388BFD` | primary actions, Azure type |
| `var(--accent-green)` | `#1A7F37` | `#3FB950` | healthy/running states |
| `var(--accent-yellow)` | `#9A6700` | `#D29922` | warning/stopped/degraded |
| `var(--accent-red)` | `#CF222E` | `#F85149` | error/unavailable/unhealthy |
| `var(--accent-orange)` | `#BC4C00` | `#DB6D28` | degraded (moderate), alerts |
| `var(--accent-purple)` | `#8250DF` | `#A371F7` | low severity |
| `var(--text-muted)` | `#8C959F` | `#6E7681` | unknown/neutral |
| `var(--text-secondary)` | `#57606A` | `#8B949E` | secondary text |
| `var(--text-primary)` | `#0D1117` | `#E6EDF3` | primary text |
| `var(--bg-subtle)` | `#F0F2F5` | `#21262D` | subtle backgrounds |
| `var(--bg-canvas)` | `#F4F5F7` | `#0D1117` | page canvas |
| `var(--bg-surface)` | `#FFFFFF` | `#161B22` | card/panel surface |
| `var(--border)` | `#DDE1E7` | `#30363D` | standard borders |
| `var(--border-subtle)` | `#EBEDF0` | `#21262D` | row separators |

### Badge background formula (ALWAYS use this, NEVER hardcoded Tailwind colors)
```
background: color-mix(in srgb, var(--accent-*) 15%, transparent)
color: var(--accent-*)
```

### Badge color assignments by badge type

**InstanceCountBadge (VMSS):**
- All healthy (`healthy_instance_count === instance_count`): `var(--accent-green)`
- Some unhealthy: `var(--accent-yellow)`
- >20% unhealthy (`(instance_count - healthy_instance_count) / instance_count > 0.2`): `var(--accent-red)`

**PowerStateBadge (reused from VMTab):**
- `running`: `var(--accent-green)`
- `stopped`: `var(--accent-yellow)`
- `deallocated`: `var(--text-muted)`

**HealthBadge (reused from VMTab):**
- `available`: `var(--accent-green)`
- `degraded`: `var(--accent-orange)`
- `unavailable`: `var(--accent-red)`
- `unknown`: `var(--text-muted)`

**K8sVersionBadge (AKS):**
- Current (no upgrade): `var(--text-muted)` — neutral pill
- Outdated: `var(--accent-yellow)` — "1.28 · ⬆ available"

**NodeHealthBadge (AKS):**
- All ready: `var(--accent-green)` — "3/3"
- Some not ready: `var(--accent-yellow)` — "10/12"
- Majority not ready (>50% down): `var(--accent-red)` — "2/5"

**SystemPodBadge (AKS):**
- `healthy`: `var(--accent-green)`
- `degraded`: `var(--accent-yellow)`
- `unknown`: `var(--text-muted)`

**UpgradeBadge (AKS):**
- Amber pill with "⬆ 1.29" when `latest_available_version !== null`
- Color: `var(--accent-yellow)` (amber/warning)
- Hidden when `latest_available_version === null`

**Active Alerts count badge:**
- `> 0`: `var(--accent-red)` circle  
- `=== 0`: `var(--text-muted)` "—"

---

## 5. Component Interface Shapes

### VMSSTab
```typescript
// File: services/web-ui/components/VMSSTab.tsx
interface VMSSTabProps {
  subscriptions: string[]
  onVMSSClick?: (resourceId: string, resourceName: string) => void
}
```

### VMSSDetailPanel
```typescript
// File: services/web-ui/components/VMSSDetailPanel.tsx
interface VMSSDetailPanelProps {
  resourceId: string
  resourceName: string
  onClose: () => void
}
```
Internal tabs: `'overview' | 'instances' | 'metrics' | 'scaling' | 'chat'`

### AKSTab
```typescript
// File: services/web-ui/components/AKSTab.tsx
interface AKSTabProps {
  subscriptions: string[]
  onAKSClick?: (resourceId: string, resourceName: string) => void
}
```

### AKSDetailPanel
```typescript
// File: services/web-ui/components/AKSDetailPanel.tsx
interface AKSDetailPanelProps {
  resourceId: string
  resourceName: string
  onClose: () => void
}
```
Internal tabs: `'overview' | 'nodepools' | 'workloads' | 'metrics' | 'chat'`

---

## 6. Proxy Route Patterns

### Pattern source — `services/web-ui/app/api/proxy/vms/[vmId]/chat/route.ts`

Key observations:
- `export const runtime = 'nodejs'`
- `export const dynamic = 'force-dynamic'`
- `buildUpstreamHeaders(req.headers.get('Authorization'), false)` — `false` = no Content-Type (GET)
- `buildUpstreamHeaders(req.headers.get('Authorization'), true)` — `true` = includes Content-Type (POST with body)
- Chat routes use `AbortSignal.timeout(30000)` (30s for agent calls)
- All other routes use `AbortSignal.timeout(15000)` (15s)
- Dynamic params: `{ params }: { params: Promise<{ vmId: string }> }` — **awaited** (`const { vmId } = await params`)
- On upstream error: `return NextResponse.json([], { status: 200 })` (list routes) or `{ error: ... }, { status: res.status }` (detail routes)
- Logger: `import { logger } from '@/lib/logger'` + `const log = logger.child({ route: '...' })`

### Route table

| New route file | Method | Upstream gateway path | Timeout | Returns on error |
|---|---|---|---|---|
| `app/api/proxy/vmss/route.ts` | GET | `GET /api/v1/vmss?subscriptions=...` | 15s | `[]` |
| `app/api/proxy/vmss/[vmssId]/route.ts` | GET | `GET /api/v1/vmss/{vmssId}` | 15s | `{ error }` |
| `app/api/proxy/vmss/[vmssId]/metrics/route.ts` | GET | `GET /api/v1/vmss/{vmssId}/metrics?timespan=...` | 15s | `{ metrics: [] }` |
| `app/api/proxy/vmss/[vmssId]/chat/route.ts` | POST | `POST /api/v1/vmss/{vmssId}/chat` | 30s | `{ error }` |
| `app/api/proxy/aks/route.ts` | GET | `GET /api/v1/aks?subscriptions=...` | 15s | `[]` |
| `app/api/proxy/aks/[aksId]/route.ts` | GET | `GET /api/v1/aks/{aksId}` | 15s | `{ error }` |
| `app/api/proxy/aks/[aksId]/metrics/route.ts` | GET | `GET /api/v1/aks/{aksId}/metrics?timespan=...` | 15s | `{ metrics: [] }` |
| `app/api/proxy/aks/[aksId]/chat/route.ts` | POST | `POST /api/v1/aks/{aksId}/chat` | 30s | `{ error }` |

### Encoding convention
`[vmssId]` and `[aksId]` are base64url-encoded ARM resource IDs — matching `[vmId]` convention.
`encodeResourceId()` helper from `VMDetailPanel.tsx` (btoa → replace `+`→`-`, `/`→`_`, `=`→`''`).

---

## 7. API Gateway Backend Status

**Confirmed:** No `/api/v1/vmss` or `/api/v1/aks` routes exist in `services/api-gateway/main.py`.

**Phase 32 tools exist** (`agents/compute/tools.py`): `vmss_get_instances`, `vmss_get_autoscale_settings`, `vmss_trigger_rolling_upgrade`, `vmss_propose_scale`, `aks_get_cluster_health`, `aks_get_node_pools`, `aks_get_upgrade_profile`, `aks_propose_node_pool_scale`.

**Frontend proxy routes gracefully return empty arrays when upstream is unavailable** — this is the established pattern. All 8 new proxy routes must follow this: return `[]` (list routes) or appropriate fallback on error.

**The backend REST endpoints (`/api/v1/vmss/...`, `/api/v1/aks/...`) are a separate work item** — either in this phase (Plan 1 or Plan 2 backend sections) or deferred. The spec says "frontend can be built and proxy routes scaffolded before the backend endpoints exist."

**Decision for planning:** Include minimal backend endpoints in the phase. They are simple REST wrappers around existing agent tool calls — analogous to `/api/v1/vms` which already exists. Otherwise VMSS/AKS tabs will always show empty — useful for testing the frontend skeleton but poor UX for the demo.

---

## 8. Files to Create / Modify

### New files (14 total)

#### Types
```
services/web-ui/types/azure-resources.ts
```

#### Components
```
services/web-ui/components/VMSSTab.tsx
services/web-ui/components/VMSSDetailPanel.tsx
services/web-ui/components/AKSTab.tsx
services/web-ui/components/AKSDetailPanel.tsx
```

#### Proxy routes — VMSS
```
services/web-ui/app/api/proxy/vmss/route.ts
services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts
services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts
services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts
```

#### Proxy routes — AKS
```
services/web-ui/app/api/proxy/aks/route.ts
services/web-ui/app/api/proxy/aks/[aksId]/route.ts
services/web-ui/app/api/proxy/aks/[aksId]/metrics/route.ts
services/web-ui/app/api/proxy/aks/[aksId]/chat/route.ts
```

#### Backend gateway routes (if included in phase)
```
services/api-gateway/routers/vmss.py       (NEW)
services/api-gateway/routers/aks.py        (NEW)
```

### Modified files (4 core + optional VM refactors)

| File | What changes | Insertion point |
|------|-------------|-----------------|
| `services/web-ui/components/DashboardPanel.tsx` | TabId union, TABS array, imports, state, handlers, panel renders, detail panels | Lines 4, 17, 25–34, 46, 53–61, 155–160, 180+ |
| `services/web-ui/components/AlertFeed.tsx` | Investigate button routing — **no changes if routing is done in DashboardPanel** | N/A |
| `services/web-ui/components/VMTab.tsx` | Import `VMRow`, `EolEntry` from `types/azure-resources.ts` | Lines 9–23 |
| `services/web-ui/components/VMDetailPanel.tsx` | Import `VMDetail`, `ActiveIncident` etc. from `types/azure-resources.ts` | Lines 11–74 |

> **Plan note:** The VMTab/VMDetailPanel type extraction is optional cleanup. It can be done in the same wave as types/azure-resources.ts creation (Plan 1), or deferred. If deferred, VMSSTab and AKSTab simply define their own types locally and azure-resources.ts only has the NEW VMSS/AKS types. The spec says to do the extraction — do it in Plan 1.

---

## 9. Lucide React Icons

From the spec:
- `Scaling` — for VMSS tab (lucide-react)
- `Container` — for AKS tab (lucide-react)

**Verify:** Both `Scaling` and `Container` are valid lucide-react exports. The project already uses lucide-react (Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown, RefreshCw, X, AlertTriangle, CheckCircle, XCircle, HelpCircle, Server). Both Scaling and Container are in the lucide-react v0.400+ library.

---

## 10. Chat Pattern — VM → VMSS/AKS

The chat pattern in `VMDetailPanel.tsx` is:
1. User clicks "Investigate with AI" → `openChat()` called
2. Auto-sends initial summary message
3. `POST /api/proxy/vms/[vmId]/chat` → returns `{ thread_id, run_id }`
4. Polls `GET /api/proxy/chat/result?thread_id=...&run_id=...` every 2s
5. Terminal states: `['completed', 'failed', 'cancelled', 'expired']`
6. `useEffect([resourceId])` resets chat when resource changes

**VMSSDetailPanel + AKSDetailPanel** use the same pattern verbatim, with:
- Chat route: `POST /api/proxy/vmss/[vmssId]/chat` / `POST /api/proxy/aks/[aksId]/chat`
- Auto-send message: `"Summarize this scale set's health and suggest investigation steps."` / `"Summarize this cluster's health and suggest investigation steps."`
- Chat detail panels are embedded as one of 5 tabs (not always-visible as in VMDetailPanel) — tab switch shows/hides the chat section

**Key difference from VMDetailPanel:** The new detail panels use an *internal tabbed layout* (5 tabs: Overview/Instances or NodePools/Metrics/Scaling or Workloads/Chat), while VMDetailPanel is a single scrolling panel. The chat in the new panels is **Tab 5**, not an overlay button. The chat auto-fires on first open of Tab 5.

---

## 11. EOL Reuse for VMSS

The spec §4 notes VMSS instances share an `os_image_version` field. The existing `/api/proxy/vms/eol` POST endpoint accepts `{ os_names: string[] }` and returns `{ results: [...] }`.

**Verdict:** Reuse the EOL endpoint for VMSS by passing `os_image_version` strings.  
**Fallback:** If the backend EOL endpoint doesn't recognize VMSS OS image version strings (which are formatted differently from VM `os_name` values like "Ubuntu 22.04"), display the raw `os_image_version` string in the column — no error, just fallback display.

---

## 12. Panel Resize (VMDetailPanel pattern)

`VMDetailPanel.tsx` has a drag-to-resize handle (lines 219–257):
- `PANEL_MIN_WIDTH = 380`, `PANEL_MAX_WIDTH = 1200`, `PANEL_DEFAULT_WIDTH = 480`
- `localStorage.getItem('vmDetailPanelWidth')` — persisted
- Drag handle on the left edge, `cursor-col-resize`

**Both VMSSDetailPanel and AKSDetailPanel should include the same resizable behavior** — using separate localStorage keys: `'vmssDetailPanelWidth'` and `'aksDetailPanelWidth'`.

---

## 13. Gotchas

### 1. CostTab tab position
CostTab (Phase 39) is currently at index 5 in the TABS array, between VMs and Observability. The spec says insert VMSS/AKS "immediately after VMs." This will push CostTab from index 5 to index 7. This is fine — no code in the application depends on the numeric index of a tab.

### 2. DashboardPanel grows to 10 tabs
The tab bar currently has 8 tabs. With VMSS and AKS it becomes 10. The tab bar uses `flex items-end` — with many short labels at 13px this fits fine on a typical 1440px+ desktop but may wrap on smaller screens. The project already has `DesktopOnlyGate` — not a concern for MVP.

### 3. Keyboard navigation in DashboardPanel
`handleTabKeyDown` uses `TABS.length` for modular arrow key navigation. This automatically works correctly with any TABS length — no changes needed.

### 4. Lucide `Container` icon name conflict
Lucide-react exports `Container` but there is also a CSS concept called "container." Ensure the import is `import { ..., Container } from 'lucide-react'` — not confused with CSS container queries. No actual conflict in TypeScript but worth noting.

### 5. `[vmssId]`/`[aksId]` param destructuring
Dynamic route params in Next.js 15 App Router are `Promise<{ param: string }>` — must be **awaited**. Pattern:
```typescript
{ params }: { params: Promise<{ vmssId: string }> }
// then:
const { vmssId } = await params
```
This matches the existing `[vmId]` routes exactly.

### 6. VMDetailPanel.tsx incidentId prop
`VMDetailPanel` has an `incidentId` prop (for evidence fetching) which `VMSSDetailPanel` and `AKSDetailPanel` do NOT need — VMSS/AKS panels don't have the evidence pipeline wired. Start without it. Active incidents come from the `GET /api/v1/vmss/{id}` response directly.

### 7. Type extraction creates a modified-file risk
When extracting `VMRow`, `EolEntry` from `VMTab.tsx` and `VMDetail`, `ActiveIncident` from `VMDetailPanel.tsx`, the inline `interface` definitions must be removed and replaced with `import { ... } from '@/types/azure-resources'`. This is a mechanical change but it modifies 2 existing production files — test that `npx tsc --noEmit` passes after extraction.

### 8. Backend endpoints not yet implemented
The 8 new proxy routes will all return graceful empty arrays until backend `/api/v1/vmss/...` and `/api/v1/aks/...` endpoints exist. If the phase scope includes backend, Plan 2 should add those routes to `services/api-gateway/main.py`. If not, document this explicitly in each plan's out-of-scope section.

---

## 14. Recommended 2-Plan Wave Breakdown

### Plan 41-1: Types + Proxy Routes + VMSSTab + VMSSDetailPanel

**Scope:**
1. Create `types/azure-resources.ts` — extract VM types + add VMSS types + add AKS types
2. Update `VMTab.tsx` — import `VMRow`, `EolEntry` from azure-resources.ts
3. Update `VMDetailPanel.tsx` — import `VMDetail`, `ActiveIncident`, `Evidence` etc. from azure-resources.ts
4. Create 4 VMSS proxy routes (`/api/proxy/vmss/route.ts`, `/[vmssId]/route.ts`, `/[vmssId]/metrics/route.ts`, `/[vmssId]/chat/route.ts`)
5. Create `VMSSTab.tsx` — list view with skeleton, search, InstanceCountBadge, PowerStateBadge, HealthBadge, alert count, row click
6. Create `VMSSDetailPanel.tsx` — 5 tabs: Overview, Instances, Metrics, Scaling, AI Chat (with panel resize)
7. Wire VMSS into `DashboardPanel.tsx` (partial: add vmss to TabId, TABS array, tab panel, state, handlers, detail panel)
8. Backend: add `/api/v1/vmss` list + `/api/v1/vmss/{id}` + `/api/v1/vmss/{id}/metrics` endpoints in api-gateway

**Verification:** `npx tsc --noEmit` clean. VMSS tab visible, renders skeleton then empty state. VMSSDetailPanel opens on row click.

---

### Plan 41-2: AKSTab + AKSDetailPanel + AlertFeed routing + DashboardPanel completion

**Scope:**
1. Create 4 AKS proxy routes (`/api/proxy/aks/route.ts`, `/[aksId]/route.ts`, `/[aksId]/metrics/route.ts`, `/[aksId]/chat/route.ts`)
2. Create `AKSTab.tsx` — list view with K8sVersionBadge, NodeHealthBadge, SystemPodBadge, UpgradeBadge, alert count
3. Create `AKSDetailPanel.tsx` — 5 tabs: Overview, Node Pools, Workloads, Metrics, AI Chat (with panel resize)
4. Complete `DashboardPanel.tsx` — add aks to TabId, TABS array, AKS tab panel, AKS state/handlers, AKS detail panel
5. Update `DashboardPanel.tsx` AlertFeed handler — add `resource_type` routing for VMSS/AKS investigate button
6. Backend: add `/api/v1/aks` list + `/api/v1/aks/{id}` + `/api/v1/aks/{id}/metrics` endpoints in api-gateway
7. Run `npx tsc --noEmit` + `pytest services/api-gateway/tests/ -q` full suite

**Verification:** AKS tab visible. AlertFeed Investigate button opens VMSS/AKS panels correctly. All 10 tabs render without errors.

---

## 15. Files Already Confirmed Present

| File | Status |
|------|--------|
| `services/web-ui/components/VMTab.tsx` | ✅ Exists — pattern source |
| `services/web-ui/components/VMDetailPanel.tsx` | ✅ Exists — pattern source |
| `services/web-ui/components/DashboardPanel.tsx` | ✅ Exists — 8 tabs, CostTab wired |
| `services/web-ui/components/AlertFeed.tsx` | ✅ Exists — single onInvestigate prop |
| `services/web-ui/components/CostTab.tsx` | ✅ Exists — between VMs and Observability |
| `services/web-ui/app/globals.css` | ✅ Exists — CSS token system confirmed |
| `services/web-ui/lib/api-gateway.ts` | ✅ Exists — getApiGatewayUrl + buildUpstreamHeaders |
| `services/web-ui/types/sse.ts` | ✅ Exists — only type file |
| `services/web-ui/types/azure-resources.ts` | ❌ Does not exist — create in Plan 1 |
| `/api/v1/vmss` endpoint in api-gateway | ❌ Does not exist — create in Plan 1 |
| `/api/v1/aks` endpoint in api-gateway | ❌ Does not exist — create in Plan 2 |

---

## RESEARCH COMPLETE
