---
wave: 3
depends_on:
  - 57-2-aks-and-api-endpoints-PLAN.md
files_modified:
  - services/web-ui/components/CapacityTab.tsx
  - services/web-ui/components/DashboardPanel.tsx
  - services/web-ui/app/api/proxy/capacity/headroom/route.ts
  - services/web-ui/app/api/proxy/capacity/quotas/route.ts
  - services/web-ui/app/api/proxy/capacity/ip-space/route.ts
  - services/web-ui/app/api/proxy/capacity/aks/route.ts
  - services/web-ui/lib/capacity-types.ts
autonomous: true
---

# Plan 57-3: Capacity Tab UI

## Goal

Build the `CapacityTab.tsx` UI component with quota headroom table (traffic-light badges), IP address space table, and 90-day Recharts forecast chart. Add 4 Next.js proxy routes. Register the new `capacity` tab in `DashboardPanel.tsx`.

## must_haves

- `CapacityTab.tsx` renders without TypeScript errors (`npx tsc --noEmit` passes)
- Traffic-light badges use CSS semantic tokens (`var(--accent-red)`, `var(--accent-yellow)`, `var(--accent-green)`) — NO hardcoded Tailwind color classes
- All proxy routes follow the pattern: `getApiGatewayUrl()` + `buildUpstreamHeaders(request.headers.get('Authorization'), false)` + `AbortSignal.timeout(15000)`
- `DashboardPanel.tsx` `TabId` union includes `'capacity'`; `capacity` tab is in "Monitoring & cost" group with `Gauge` icon from lucide-react
- `npm run build` passes (no TypeScript errors, no missing imports)

---

## Tasks

### Task 1: Create TypeScript types in `lib/capacity-types.ts`

<read_first>
- services/web-ui/lib/api-gateway.ts (check if there's a types directory pattern)
- services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts (proxy route pattern to confirm import paths)
- .planning/phases/57-capacity-planning-engine/57-RESEARCH.md (section 4 — API response shapes)
</read_first>

<action>
Create `services/web-ui/lib/capacity-types.ts`:

```typescript
// Capacity Planning — shared TypeScript types

export type TrafficLight = 'red' | 'yellow' | 'green'

export interface CapacityQuotaItem {
  resource_category: string
  name: string
  quota_name: string
  current_value: number
  limit: number
  usage_pct: number
  available: number
  days_to_exhaustion: number | null
  confidence: string | null
  traffic_light: TrafficLight
  growth_rate_per_day: number | null
  projected_exhaustion_date: string | null
}

export interface CapacityHeadroomResponse {
  subscription_id: string
  location: string
  top_constrained: CapacityQuotaItem[]
  generated_at: string
  snapshot_count: number
  data_note: string | null
}

export interface SubnetHeadroomItem {
  vnet_name: string
  resource_group: string
  subnet_name: string
  address_prefix: string
  total_ips: number
  reserved_ips: number
  ip_config_count: number
  available_ips: number
  usage_pct: number
  traffic_light: TrafficLight
  note: string | null
}

export interface IPSpaceHeadroomResponse {
  subscription_id: string
  subnets: SubnetHeadroomItem[]
  generated_at: string
  duration_ms: number
  note: string | null
}

export interface AKSNodePoolHeadroomItem {
  cluster_name: string
  resource_group: string
  location: string
  pool_name: string
  vm_size: string
  quota_family: string
  current_nodes: number
  max_nodes: number
  available_nodes: number
  usage_pct: number
  traffic_light: TrafficLight
}

export interface AKSHeadroomResponse {
  subscription_id: string
  clusters: AKSNodePoolHeadroomItem[]
  generated_at: string
  duration_ms: number
}
```
</action>

<acceptance_criteria>
- `grep -n "export interface CapacityQuotaItem" services/web-ui/lib/capacity-types.ts` returns the interface
- `grep -n "TrafficLight" services/web-ui/lib/capacity-types.ts` shows type definition and usage
- `grep -n "export interface SubnetHeadroomItem" services/web-ui/lib/capacity-types.ts` returns the interface
- `grep -n "export interface AKSNodePoolHeadroomItem" services/web-ui/lib/capacity-types.ts` returns the interface
</acceptance_criteria>

---

### Task 2: Create 4 proxy routes

<read_first>
- services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts (exact pattern to replicate)
- services/web-ui/lib/api-gateway.ts (verify `getApiGatewayUrl` and `buildUpstreamHeaders` exports)
</read_first>

<action>
Create the following 4 files, each following the exact pattern from `finops/cost-breakdown/route.ts`:

**File 1:** `services/web-ui/app/api/proxy/capacity/headroom/route.ts`
- Route path child logger: `{ route: '/api/proxy/capacity/headroom' }`
- Upstream URL: `${apiGatewayUrl}/api/v1/capacity/headroom${query ? '?' + query : ''}`
- Empty fallback: `{ error: ..., top_constrained: [], snapshot_count: 0 }`

**File 2:** `services/web-ui/app/api/proxy/capacity/quotas/route.ts`
- Logger: `{ route: '/api/proxy/capacity/quotas' }`
- Upstream URL: `${apiGatewayUrl}/api/v1/capacity/quotas${query ? '?' + query : ''}`
- Empty fallback: `{ error: ..., quotas: [] }`

**File 3:** `services/web-ui/app/api/proxy/capacity/ip-space/route.ts`
- Logger: `{ route: '/api/proxy/capacity/ip-space' }`
- Upstream URL: `${apiGatewayUrl}/api/v1/capacity/ip-space${query ? '?' + query : ''}`
- Empty fallback: `{ error: ..., subnets: [] }`

**File 4:** `services/web-ui/app/api/proxy/capacity/aks/route.ts`
- Logger: `{ route: '/api/proxy/capacity/aks' }`
- Upstream URL: `${apiGatewayUrl}/api/v1/capacity/aks${query ? '?' + query : ''}`
- Empty fallback: `{ error: ..., clusters: [] }`

All 4 must include:
```typescript
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
```
And use `AbortSignal.timeout(15000)`.
</action>

<acceptance_criteria>
- `ls services/web-ui/app/api/proxy/capacity/` shows 4 directories: `headroom/`, `quotas/`, `ip-space/`, `aks/`
- `grep -rn "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/capacity/` returns 4 matches
- `grep -rn "buildUpstreamHeaders" services/web-ui/app/api/proxy/capacity/` returns 4 matches
- `grep -rn "export const runtime = 'nodejs'" services/web-ui/app/api/proxy/capacity/` returns 4 matches
- `grep -n "/api/v1/capacity/headroom" services/web-ui/app/api/proxy/capacity/headroom/route.ts` shows the upstream URL
</acceptance_criteria>

---

### Task 3: Create `CapacityTab.tsx`

<read_first>
- services/web-ui/components/SLATab.tsx (traffic-light badge pattern using CSS semantic tokens)
- services/web-ui/components/CostTab.tsx (Recharts usage pattern, subscription selector pattern)
- services/web-ui/components/DashboardPanel.tsx (how tabs receive `subscriptions` props — check what props are passed)
- services/web-ui/lib/capacity-types.ts (Task 1)
- services/web-ui/components/ui/ (check available shadcn components: table, badge, card, skeleton, select)
</read_first>

<action>
Create `services/web-ui/components/CapacityTab.tsx`:

**Structure:**
```
CapacityTab
├── Header: title "Capacity Planning" + Refresh button + Location select (eastus default)
├── Summary cards row (4 cards using shadcn Card):
│   - "Total Quotas" — count of all quota items
│   - "Critical" — count with traffic_light="red" (accent-red color)
│   - "Warning" — count with traffic_light="yellow" (accent-yellow color)  
│   - "Healthy" — count with traffic_light="green" (accent-green color)
├── Section "Quota Headroom" (Table)
│   - Columns: Category | Name | Used | Limit | Usage % | Days Left | Status
│   - Rows sorted by days_to_exhaustion ASC (nulls last)
│   - Loading state: Skeleton rows
│   - Empty state: "No quota constraints detected"
├── Section "IP Address Space" (Table)
│   - Columns: VNet | Subnet | CIDR | Used IPs | Available | Usage % | Status
│   - Loading state: Skeleton rows
│   - Empty state: "No subnets found"
└── Section "90-Day Forecast" (Recharts LineChart)
    - Only rendered if snapshot_count >= 3 (else show "Insufficient history — projections activate after 3 daily snapshots")
    - X-axis: dates from today to today+90 days
    - Y-axis: 0-100 (usage %)
    - Lines: top 5 items from top_constrained with non-null growth_rate
    - ReferenceLine at y=100 (stroke="#ef4444", label="Exhaustion")
    - ReferenceLine at y=90 (stroke="#f97316", strokeDasharray="4 2", label="90% threshold")
```

**Traffic-light badge implementation (use CSS tokens, NOT hardcoded Tailwind):**
```tsx
const TRAFFIC_LIGHT_COLORS: Record<TrafficLight, string> = {
  red:    'var(--accent-red)',
  yellow: 'var(--accent-yellow)',
  green:  'var(--accent-green)',
}

function TrafficBadge({ status }: { status: TrafficLight }) {
  const color = TRAFFIC_LIGHT_COLORS[status]
  return (
    <span
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 40%, transparent)`,
      }}
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
    >
      {status === 'red' ? 'Critical' : status === 'yellow' ? 'Warning' : 'Healthy'}
    </span>
  )
}
```

**State:**
```typescript
const [headroom, setHeadroom] = useState<CapacityHeadroomResponse | null>(null)
const [ipSpace, setIPSpace] = useState<IPSpaceHeadroomResponse | null>(null)
const [loading, setLoading] = useState(false)
const [error, setError] = useState<string | null>(null)
const [location, setLocation] = useState('eastus')
```

**Data fetching:**
```typescript
async function fetchCapacityData() {
  if (!subscriptionId) return
  setLoading(true)
  setError(null)
  try {
    const [headroomRes, ipRes] = await Promise.all([
      fetch(`/api/proxy/capacity/headroom?subscription_id=${subscriptionId}&location=${location}`),
      fetch(`/api/proxy/capacity/ip-space?subscription_id=${subscriptionId}`),
    ])
    const [headroomData, ipData] = await Promise.all([headroomRes.json(), ipRes.json()])
    setHeadroom(headroomData)
    setIPSpace(ipData)
  } catch (err) {
    setError(err instanceof Error ? err.message : 'Failed to load capacity data')
  } finally {
    setLoading(false)
  }
}
```

**90-day forecast projection data** — compute inside the component before rendering the chart:
```typescript
const topItems = (headroom?.top_constrained ?? [])
  .filter(item => item.growth_rate_per_day != null)
  .slice(0, 5)

const today = new Date()
const projectionData = Array.from({ length: 91 }, (_, i) => {
  const date = new Date(today); date.setDate(today.getDate() + i)
  return {
    date: date.toISOString().split('T')[0],
    ...Object.fromEntries(topItems.map(item => [
      item.quota_name,
      Math.min(100, item.usage_pct + (item.growth_rate_per_day ?? 0) * i)
    ]))
  }
})
```

**Props:**
```typescript
interface CapacityTabProps {
  subscriptionId?: string
}
```

**Recharts imports:** `LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine, ResponsiveContainer` from `recharts`. Use `ResponsiveContainer` for responsive width.

**Days Left cell:** Display `"—"` if `days_to_exhaustion` is null; else display number with " days" suffix; if ≤ 7, add warning color.
</action>

<acceptance_criteria>
- `grep -n "var(--accent-red)" services/web-ui/components/CapacityTab.tsx` shows CSS token usage
- `grep -n "var(--accent-yellow)" services/web-ui/components/CapacityTab.tsx` shows CSS token usage
- `grep -n "var(--accent-green)" services/web-ui/components/CapacityTab.tsx` shows CSS token usage
- `grep -n "color-mix" services/web-ui/components/CapacityTab.tsx` shows badge background pattern
- `grep -n "AbortSignal\|AbortController\|bg-green\|bg-red\|bg-yellow" services/web-ui/components/CapacityTab.tsx` returns NO hardcoded Tailwind color class matches (bg-green, bg-red, bg-yellow must NOT appear)
- `grep -n "from 'recharts'" services/web-ui/components/CapacityTab.tsx` shows Recharts import
- `grep -n "ReferenceLine" services/web-ui/components/CapacityTab.tsx` shows reference lines at 100 and 90
- `grep -n "snapshot_count" services/web-ui/components/CapacityTab.tsx` shows the insufficient history guard
- `grep -n "CapacityTabProps" services/web-ui/components/CapacityTab.tsx` shows interface definition
- `grep -n "projectionData" services/web-ui/components/CapacityTab.tsx` returns 1+ match
</acceptance_criteria>

---

### Task 4: Update `DashboardPanel.tsx` to add the Capacity tab

<read_first>
- services/web-ui/components/DashboardPanel.tsx (full file — read all of it to understand TabId union, TAB_GROUPS, tab rendering switch/if block)
</read_first>

<action>
In `services/web-ui/components/DashboardPanel.tsx`:

1. Add `'capacity'` to the `TabId` union:
```typescript
type TabId = 'ops' | 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch' | 'compliance' | 'runbooks' | 'sla' | 'capacity' | 'settings'
```

2. Add `Gauge` to the lucide-react import:
```typescript
import { Bell, ClipboardList, ..., Gauge } from 'lucide-react'
```

3. Add `capacity` tab to the "Monitoring & cost" group in `TAB_GROUPS` (after `sla`):
```typescript
// Monitoring & cost
[
  { id: 'cost',          label: 'FinOps',        Icon: DollarSign },
  { id: 'observability', label: 'Observability', Icon: Activity },
  { id: 'sla',           label: 'SLA',           Icon: BarChart2 },
  { id: 'capacity',      label: 'Capacity',      Icon: Gauge },   // ← NEW
],
```

4. Add `CapacityTab` import:
```typescript
import { CapacityTab } from './CapacityTab'
```

5. In the tab content rendering section (the `{activeTab === '...' && <...Tab />}` block), add:
```typescript
{activeTab === 'capacity' && (
  <CapacityTab subscriptionId={selectedSubscriptions[0]} />
)}
```
Place it in logical order (after `sla` case, before `settings`).
</action>

<acceptance_criteria>
- `grep -n "'capacity'" services/web-ui/components/DashboardPanel.tsx` returns ≥ 3 matches (TabId union, TAB_GROUPS entry, render block)
- `grep -n "Gauge" services/web-ui/components/DashboardPanel.tsx` shows import and usage in TAB_GROUPS
- `grep -n "import.*CapacityTab" services/web-ui/components/DashboardPanel.tsx` shows the import
- `grep -n "activeTab === 'capacity'" services/web-ui/components/DashboardPanel.tsx` shows the render block
- Tab count in `TAB_GROUPS.flat().length` = 16 (was 15; verify: `grep -c "id:" services/web-ui/components/DashboardPanel.tsx` should increase by 1)
</acceptance_criteria>

---

### Task 5: TypeScript build verification

<read_first>
- services/web-ui/tsconfig.json (compiler options — confirm strict mode, paths)
- services/web-ui/package.json (build script)
</read_first>

<action>
Run TypeScript type-checking and build from `services/web-ui/`:

```bash
cd services/web-ui && npx tsc --noEmit 2>&1 | head -40
```

If errors exist, fix them:
- Missing imports → add import
- Type mismatches → align with `capacity-types.ts` definitions
- `recharts` not installed → check `package.json`; if missing add `npm install recharts` (it should already be present from CostTab)
- `Gauge` not in lucide-react → use `GaugeCircle` or `Activity` as fallback (check available icons)

Run `npm run build` after fixing all TypeScript errors.
</action>

<acceptance_criteria>
- `cd services/web-ui && npx tsc --noEmit 2>&1 | grep -c "error TS"` returns `0`
- `cd services/web-ui && npm run build 2>&1 | tail -3` shows build succeeded (no "Failed to compile" message)
- `grep -n "recharts" services/web-ui/package.json` shows recharts is a dependency (not devDependency only)
</acceptance_criteria>

---

## Verification

```bash
# TypeScript check
cd services/web-ui && npx tsc --noEmit && echo "TypeScript OK"

# Build
cd services/web-ui && npm run build 2>&1 | tail -5

# Proxy routes exist
ls services/web-ui/app/api/proxy/capacity/

# Tab registered
grep "'capacity'" services/web-ui/components/DashboardPanel.tsx

# No hardcoded Tailwind color classes in CapacityTab
grep -n "bg-red\|bg-yellow\|bg-green\|text-red\|text-yellow\|text-green" services/web-ui/components/CapacityTab.tsx | grep -v "//\|accent" && echo "FAIL: hardcoded colors found" || echo "PASS: no hardcoded colors"

# Projection data present
grep -n "projectionData" services/web-ui/components/capacity/CapacityTab.tsx
```

Expected: TypeScript passes, build succeeds, 4 proxy route directories exist, `'capacity'` appears ≥3 times in DashboardPanel.tsx, no hardcoded Tailwind color classes in CapacityTab.tsx, `projectionData` appears in CapacityTab.tsx.
