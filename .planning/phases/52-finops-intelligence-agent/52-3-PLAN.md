---
wave: 2
depends_on: [52-1-PLAN.md]
files_modified:
  - services/web-ui/components/CostTab.tsx
  - services/web-ui/components/DashboardPanel.tsx
  - services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts
  - services/web-ui/app/api/proxy/finops/resource-cost/route.ts
  - services/web-ui/app/api/proxy/finops/idle-resources/route.ts
  - services/web-ui/app/api/proxy/finops/ri-utilization/route.ts
  - services/web-ui/app/api/proxy/finops/cost-forecast/route.ts
  - services/web-ui/app/api/proxy/finops/top-cost-drivers/route.ts
autonomous: true
---

# Plan 52-3: Frontend FinOps Tab

## Goal

Extend the existing `CostTab.tsx` with a rich FinOps UI: current-month spend KPI, cost breakdown vertical bar chart (Recharts), budget burn rate gauge, idle resource waste list with HITL approve/reject buttons, RI utilisation card, and top cost drivers. Create 6 Next.js proxy routes under `app/api/proxy/finops/`. Update `DashboardPanel.tsx` to rename the "Cost" tab to "FinOps" with a `DollarSign` icon. Use CSS semantic tokens throughout — no hardcoded Tailwind color classes.

## Context

The `cost` TabId already exists in `DashboardPanel.tsx` — no new TabId or tab registration needed (only label + icon update). The existing `CostTab.tsx` shows Advisor cost recommendations (Phases 28/39) and must be **extended** (not replaced) by adding new sections above the existing card grid. Recharts `^3.8.1` is already in `services/web-ui/package.json`. Proxy route pattern is identical to all existing proxy routes (`getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout(15000)`). The `impactBadgeStyle()`, `formatCurrency()`, and `cleanServiceType()` helpers in `CostTab.tsx` must be reused — never duplicated.

<threat_model>
## Security Threat Assessment

**1. `subscription_id` in proxy URLs**: Forwarded as a query parameter to the API gateway. The Next.js proxy reads `searchParams.toString()` and appends verbatim — no transformation, no injection risk since it's a URL-encoded query string passed through.

**2. API gateway auth bypass**: The `buildUpstreamHeaders()` function handles Authorization header forwarding. Auth is controlled at the gateway layer (`API_GATEWAY_AUTH_MODE`). UI proxy routes do not add or modify auth credentials.

**3. `AbortSignal.timeout(15000)`**: Hard 15-second timeout on all upstream fetches — prevents connection-hang DoS.

**4. Error handling**: All proxy routes catch exceptions and return `NextResponse.json({ error: message }, { status: 502 })` — no raw exception objects, no stack traces, no internal URLs leaked to the browser.

**5. HITL approve/reject buttons**: Call existing `/api/v1/remediation/approve|reject` endpoints via the existing `approvals` proxy — no new auth surface. These buttons are already present in the `PatchTab` and `OpsTab` with identical patterns.

**6. CSS semantic tokens**: No inline `style={{ background: '#ff0000' }}` hardcoded values — only `var(--accent-*)` tokens. No XSS vector since values are compile-time constants in TSX.
</threat_model>

---

## Tasks

### Task 1: Create 6 Next.js proxy routes under `app/api/proxy/finops/`

<read_first>
- `services/web-ui/app/api/proxy/vms/cost-summary/route.ts` — FULL FILE — exact proxy pattern: `getApiGatewayUrl`, `buildUpstreamHeaders`, `AbortSignal.timeout(15000)`, error handling, `logger.child` pattern
- `52-RESEARCH.md` Section 7 — exact upstream paths for each finops route
</read_first>

<action>
Create 6 proxy route files. All follow the exact same pattern as `vms/cost-summary/route.ts`. The only differences per file are the route label, log child name, upstream path, and error fallback shape.

**File 1: `services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts`**
- Log child: `{ route: '/api/proxy/finops/cost-breakdown' }`
- Upstream: `${apiGatewayUrl}/api/v1/finops/cost-breakdown${query ? '?' + query : ''}`
- Error fallback: `{ error: message, breakdown: [], total_cost: 0 }`

**File 2: `services/web-ui/app/api/proxy/finops/resource-cost/route.ts`**
- Log child: `{ route: '/api/proxy/finops/resource-cost' }`
- Upstream: `${apiGatewayUrl}/api/v1/finops/resource-cost${query ? '?' + query : ''}`
- Error fallback: `{ error: message, total_cost: 0 }`

**File 3: `services/web-ui/app/api/proxy/finops/idle-resources/route.ts`**
- Log child: `{ route: '/api/proxy/finops/idle-resources' }`
- Upstream: `${apiGatewayUrl}/api/v1/finops/idle-resources${query ? '?' + query : ''}`
- Error fallback: `{ error: message, idle_count: 0, idle_resources: [] }`

**File 4: `services/web-ui/app/api/proxy/finops/ri-utilization/route.ts`**
- Log child: `{ route: '/api/proxy/finops/ri-utilization' }`
- Upstream: `${apiGatewayUrl}/api/v1/finops/ri-utilization${query ? '?' + query : ''}`
- Error fallback: `{ error: message, ri_benefit_estimated_usd: null }`

**File 5: `services/web-ui/app/api/proxy/finops/cost-forecast/route.ts`**
- Log child: `{ route: '/api/proxy/finops/cost-forecast' }`
- Upstream: `${apiGatewayUrl}/api/v1/finops/cost-forecast${query ? '?' + query : ''}`
- Error fallback: `{ error: message, forecast_month_end_usd: null }`

**File 6: `services/web-ui/app/api/proxy/finops/top-cost-drivers/route.ts`**
- Log child: `{ route: '/api/proxy/finops/top-cost-drivers' }`
- Upstream: `${apiGatewayUrl}/api/v1/finops/top-cost-drivers${query ? '?' + query : ''}`
- Error fallback: `{ error: message, drivers: [], total_cost_usd: 0 }`

Each file must include:
```typescript
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
```
</action>

<acceptance_criteria>
- `services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts` exists
- `services/web-ui/app/api/proxy/finops/resource-cost/route.ts` exists
- `services/web-ui/app/api/proxy/finops/idle-resources/route.ts` exists
- `services/web-ui/app/api/proxy/finops/ri-utilization/route.ts` exists
- `services/web-ui/app/api/proxy/finops/cost-forecast/route.ts` exists
- `services/web-ui/app/api/proxy/finops/top-cost-drivers/route.ts` exists
- `grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts` exits 0
- `grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/finops/cost-forecast/route.ts` exits 0
- `grep "/api/v1/finops/cost-breakdown" services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts` exits 0
- `grep "/api/v1/finops/idle-resources" services/web-ui/app/api/proxy/finops/idle-resources/route.ts` exits 0
- `grep "export const runtime = 'nodejs'" services/web-ui/app/api/proxy/finops/cost-forecast/route.ts` exits 0
- `grep "buildUpstreamHeaders" services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts` exits 0
</acceptance_criteria>

---

### Task 2: Update `services/web-ui/components/DashboardPanel.tsx` — rename Cost tab to FinOps

<read_first>
- `services/web-ui/components/DashboardPanel.tsx` lines 1–46 — current `TABS` array, imports; the `cost` tab entry is `{ id: 'cost', label: 'Cost', Icon: TrendingDown }` at around line 41
</read_first>

<action>
Make 2 targeted changes to `services/web-ui/components/DashboardPanel.tsx`:

**Change 1 — Import**: Add `DollarSign` to the lucide-react import (it may already be partially imported — check the existing import line first):
```typescript
import { Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown, Scaling, Container, BookOpen, LayoutDashboard, Settings, DollarSign } from 'lucide-react'
```

**Change 2 — TABS array entry** (the `cost` entry at line ~41): Change from:
```typescript
{ id: 'cost', label: 'Cost', Icon: TrendingDown },
```
to:
```typescript
{ id: 'cost', label: 'FinOps', Icon: DollarSign },
```

No other changes to `DashboardPanel.tsx` — the `TabId` type does not change, the tab rendering logic does not change, and `CostTab` remains the component rendered for the `cost` tab.
</action>

<acceptance_criteria>
- `grep 'DollarSign' services/web-ui/components/DashboardPanel.tsx` exits 0
- `grep "label: 'FinOps'" services/web-ui/components/DashboardPanel.tsx` exits 0
- `grep "id: 'cost'" services/web-ui/components/DashboardPanel.tsx` exits 0 (tab id unchanged)
- `grep "label: 'Cost'" services/web-ui/components/DashboardPanel.tsx` exits 1 (old label removed)
</acceptance_criteria>

---

### Task 3: Extend `services/web-ui/components/CostTab.tsx` with FinOps sections

<read_first>
- `services/web-ui/components/CostTab.tsx` — FULL FILE — existing `CostRecommendation`, `CostSummaryResponse`, `CostTabProps` types; `impactBadgeStyle()`, `formatCurrency()`, `cleanServiceType()` helpers; `fetchCostData` fetch pattern; loading/error/empty state renders; the card grid section is the existing content to be PRESERVED below the new sections
- `52-RESEARCH.md` Section 4 — budget gauge pattern, Recharts vertical bar chart pattern
- `52-RESEARCH.md` Section 10 — Recharts exact import and `layout="vertical"` bar chart config
- `52-CONTEXT.md` `<specifics>` — current month total spend prominently at top; HITL proposals always show estimated monthly savings in dollars
</read_first>

<action>
Extend `services/web-ui/components/CostTab.tsx`. The existing content is **preserved** — new FinOps sections are added ABOVE the existing Advisor recommendations card grid.

**New TypeScript types** (add after existing interfaces):
```typescript
// FinOps-specific types
interface CostBreakdownItem {
  name: string;
  cost: number;
  currency: string;
}

interface CostBreakdownResponse {
  subscription_id: string;
  total_cost: number;
  currency: string;
  breakdown: CostBreakdownItem[];
  data_lag_note?: string;
  query_status: string;
}

interface CostForecastResponse {
  subscription_id: string;
  current_spend_usd: number;
  forecast_month_end_usd: number;
  budget_amount_usd: number | null;
  burn_rate_pct: number | null;
  days_elapsed: number;
  days_in_month: number;
  over_budget: boolean;
  over_budget_pct: number;
  data_lag_note?: string;
  query_status: string;
}

interface IdleResource {
  resource_id: string;
  vm_name: string;
  resource_group: string;
  avg_cpu_pct: number;
  avg_network_mbps: number;
  monthly_cost_usd: number;
  approval_id?: string | null;
}

interface IdleResourcesResponse {
  subscription_id: string;
  vms_evaluated: number;
  idle_count: number;
  idle_resources: IdleResource[];
  query_status: string;
}

interface RiUtilisationResponse {
  subscription_id: string;
  method: string;
  actual_cost_usd: number;
  amortized_cost_usd: number;
  ri_benefit_estimated_usd: number;
  utilisation_note: string;
  data_lag_note?: string;
  query_status: string;
}

interface TopCostDriver {
  service_name: string;
  cost_usd: number;
  currency: string;
  rank: number;
}

interface TopCostDriversResponse {
  subscription_id: string;
  n: number;
  days: number;
  drivers: TopCostDriver[];
  total_cost_usd: number;
  data_lag_note?: string;
  query_status: string;
}
```

**New state variables** (add inside `CostTab` function alongside existing state):
```typescript
const [breakdown, setBreakdown] = useState<CostBreakdownItem[]>([]);
const [forecast, setForecast] = useState<CostForecastResponse | null>(null);
const [idleResources, setIdleResources] = useState<IdleResource[]>([]);
const [riUtilisation, setRiUtilisation] = useState<RiUtilisationResponse | null>(null);
const [topDrivers, setTopDrivers] = useState<TopCostDriver[]>([]);
const [finopsLoading, setFinopsLoading] = useState(false);
const [finopsError, setFinopsError] = useState<string | null>(null);
const [approvingId, setApprovingId] = useState<string | null>(null);
```

**New `fetchFinopsData` callback** (add alongside existing `fetchCostData`):
```typescript
const fetchFinopsData = useCallback(async () => {
  if (subscriptions.length === 0) return;
  setFinopsLoading(true);
  setFinopsError(null);
  const subscriptionId = subscriptions[0];

  try {
    // Parallel fetch all 4 FinOps endpoints
    const [breakdownRes, forecastRes, idleRes, riRes] = await Promise.allSettled([
      fetch(`/api/proxy/finops/cost-breakdown?subscription_id=${encodeURIComponent(subscriptionId)}&days=30&group_by=ResourceGroup`, { signal: AbortSignal.timeout(15000) }),
      fetch(`/api/proxy/finops/cost-forecast?subscription_id=${encodeURIComponent(subscriptionId)}`, { signal: AbortSignal.timeout(15000) }),
      fetch(`/api/proxy/finops/idle-resources?subscription_id=${encodeURIComponent(subscriptionId)}`, { signal: AbortSignal.timeout(15000) }),
      fetch(`/api/proxy/finops/ri-utilization?subscription_id=${encodeURIComponent(subscriptionId)}`, { signal: AbortSignal.timeout(15000) }),
    ]);

    if (breakdownRes.status === 'fulfilled' && breakdownRes.value.ok) {
      const d: CostBreakdownResponse = await breakdownRes.value.json();
      setBreakdown(d.breakdown?.slice(0, 10) ?? []);
    }
    if (forecastRes.status === 'fulfilled' && forecastRes.value.ok) {
      const d: CostForecastResponse = await forecastRes.value.json();
      setForecast(d);
    }
    if (idleRes.status === 'fulfilled' && idleRes.value.ok) {
      const d: IdleResourcesResponse = await idleRes.value.json();
      setIdleResources(d.idle_resources ?? []);
    }
    if (riRes.status === 'fulfilled' && riRes.value.ok) {
      const d: RiUtilisationResponse = await riRes.value.json();
      setRiUtilisation(d);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    setFinopsError(`Failed to load FinOps data: ${message}`);
  } finally {
    setFinopsLoading(false);
  }
}, [subscriptions]);
```

**Update `useEffect`** to also call `fetchFinopsData`:
```typescript
useEffect(() => {
  fetchCostData();
  fetchFinopsData();
}, [fetchCostData, fetchFinopsData]);
```

**HITL approve/reject handler** (add before the return):
```typescript
const handleApprove = async (approvalId: string) => {
  setApprovingId(approvalId);
  try {
    await fetch(`/api/proxy/approvals/${encodeURIComponent(approvalId)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: 'Approved via FinOps tab' }),
      signal: AbortSignal.timeout(10000),
    });
    // Refresh idle resources after approval
    await fetchFinopsData();
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    setFinopsError(`Approval failed: ${message}`);
  } finally {
    setApprovingId(null);
  }
};

const handleReject = async (approvalId: string) => {
  setApprovingId(approvalId);
  try {
    await fetch(`/api/proxy/approvals/${encodeURIComponent(approvalId)}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: 'Rejected via FinOps tab' }),
      signal: AbortSignal.timeout(10000),
    });
    await fetchFinopsData();
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    setFinopsError(`Rejection failed: ${message}`);
  } finally {
    setApprovingId(null);
  }
};
```

**New imports** (add to top of file):
```typescript
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
```

**New FinOps sections** (add INSIDE the main return, ABOVE the existing `{/* Header */}` div — or more precisely, as new sections between the existing header and the card grid):

Insert the following sections inside the main `<div>` return, after the existing header (`{/* Header */}`) and data lag note sections, but BEFORE the card grid:

```tsx
{/* ───── FinOps KPIs ───── */}
{forecast && (
  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 pt-4">
    {/* Current month spend */}
    <Card>
      <CardContent className="p-3">
        <p className="text-[11px] mb-1" style={{ color: 'var(--text-secondary)' }}>Month-to-Date Spend</p>
        <p className="text-[20px] font-semibold" style={{ color: 'var(--text-primary)' }}>
          ${forecast.current_spend_usd.toFixed(0)}
        </p>
        <p className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
          Day {forecast.days_elapsed} of {forecast.days_in_month}
        </p>
      </CardContent>
    </Card>
    {/* Forecast */}
    <Card>
      <CardContent className="p-3">
        <p className="text-[11px] mb-1" style={{ color: 'var(--text-secondary)' }}>Forecast Month-End</p>
        <p className="text-[20px] font-semibold" style={{ color: forecast.over_budget ? 'var(--accent-red)' : 'var(--text-primary)' }}>
          ${forecast.forecast_month_end_usd.toFixed(0)}
        </p>
        {forecast.over_budget && (
          <span className="text-[11px]" style={{ color: 'var(--accent-red)' }}>
            ⚠ {forecast.over_budget_pct.toFixed(0)}% over budget
          </span>
        )}
      </CardContent>
    </Card>
    {/* Budget gauge */}
    {forecast.budget_amount_usd != null && (
      <Card className="col-span-2">
        <CardContent className="p-3">
          <p className="text-[11px] mb-2" style={{ color: 'var(--text-secondary)' }}>
            Budget: ${forecast.budget_amount_usd.toFixed(0)}
          </p>
          {(() => {
            const burnPct = Math.min(((forecast.forecast_month_end_usd / forecast.budget_amount_usd!) * 100), 150);
            const barColor = burnPct > 110 ? 'var(--accent-red)' : burnPct > 90 ? 'var(--accent-orange)' : 'var(--accent-green)';
            return (
              <>
                <div className="relative h-3 rounded-full" style={{ background: 'color-mix(in srgb, var(--border) 50%, transparent)' }}>
                  <div
                    className="absolute inset-y-0 left-0 rounded-full transition-all"
                    style={{ width: `${Math.min(burnPct, 100)}%`, background: barColor }}
                  />
                </div>
                <p className="text-[11px] mt-1" style={{ color: 'var(--text-secondary)' }}>
                  Projected {burnPct.toFixed(0)}% of budget
                  {burnPct > 110 && <span style={{ color: 'var(--accent-red)' }}> — on track to exceed by {(burnPct - 100).toFixed(0)}%</span>}
                </p>
              </>
            );
          })()}
        </CardContent>
      </Card>
    )}
  </div>
)}

{/* ───── Cost Breakdown Chart ───── */}
{breakdown.length > 0 && (
  <div className="px-4 pt-4">
    <p className="text-[13px] font-medium mb-2" style={{ color: 'var(--text-primary)' }}>
      Top Resource Groups by Spend (30d)
    </p>
    <ResponsiveContainer width="100%" height={220}>
      <BarChart
        data={breakdown.map(b => ({
          name: b.name.length > 18 ? b.name.slice(0, 18) + '…' : b.name,
          cost: b.cost,
        }))}
        layout="vertical"
        margin={{ top: 4, right: 50, left: 10, bottom: 0 }}
      >
        <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
        <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={120} />
        <Tooltip
          formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, 'Cost']}
          contentStyle={{ fontSize: 11 }}
        />
        <Bar dataKey="cost" fill="var(--accent-blue)" radius={[0, 2, 2, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </div>
)}

{/* ───── Idle Resources (Waste List) ───── */}
{idleResources.length > 0 && (
  <div className="px-4 pt-4">
    <div className="flex items-center gap-2 mb-2">
      <p className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
        Idle Resources
      </p>
      <span
        className="text-[11px] px-2 py-0.5 rounded"
        style={{ background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', color: 'var(--accent-red)' }}
      >
        {idleResources.length} VMs idle 72h+
      </span>
    </div>
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="text-[11px]">VM Name</TableHead>
          <TableHead className="text-[11px]">Resource Group</TableHead>
          <TableHead className="text-[11px]">Avg CPU</TableHead>
          <TableHead className="text-[11px]">Monthly Cost</TableHead>
          <TableHead className="text-[11px]">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {idleResources.map((r) => (
          <TableRow key={r.resource_id}>
            <TableCell className="text-[12px]">{r.vm_name}</TableCell>
            <TableCell className="text-[12px]" style={{ color: 'var(--text-secondary)' }}>{r.resource_group}</TableCell>
            <TableCell className="text-[12px]">
              <span style={{ color: 'var(--accent-orange)' }}>{r.avg_cpu_pct.toFixed(1)}%</span>
            </TableCell>
            <TableCell className="text-[12px] font-medium" style={{ color: 'var(--accent-green)' }}>
              ${r.monthly_cost_usd.toFixed(0)}/mo
            </TableCell>
            <TableCell>
              {r.approval_id ? (
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-6 px-2 text-[11px]"
                    style={{ color: 'var(--accent-green)', borderColor: 'var(--accent-green)' }}
                    disabled={approvingId === r.approval_id}
                    onClick={() => r.approval_id && handleApprove(r.approval_id)}
                  >
                    {approvingId === r.approval_id ? '…' : 'Approve'}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-[11px]"
                    style={{ color: 'var(--text-secondary)' }}
                    disabled={approvingId === r.approval_id}
                    onClick={() => r.approval_id && handleReject(r.approval_id)}
                  >
                    Reject
                  </Button>
                </div>
              ) : (
                <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>No proposal</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  </div>
)}

{/* ───── RI Utilisation ───── */}
{riUtilisation && riUtilisation.query_status === 'success' && (
  <div className="px-4 pt-4">
    <Card>
      <CardContent className="p-4">
        <p className="text-[13px] font-medium mb-2" style={{ color: 'var(--text-primary)' }}>
          Reserved Instance Utilisation (30d)
        </p>
        <div className="flex items-center gap-4">
          <div>
            <p className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>RI Benefit Consumed</p>
            <p className="text-[18px] font-semibold" style={{ color: riUtilisation.ri_benefit_estimated_usd > 0 ? 'var(--accent-green)' : 'var(--text-secondary)' }}>
              ${Math.abs(riUtilisation.ri_benefit_estimated_usd).toFixed(0)}
            </p>
          </div>
          <div className="flex-1">
            <p className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>{riUtilisation.utilisation_note}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  </div>
)}

{/* ───── Divider before existing Advisor recommendations ───── */}
{(breakdown.length > 0 || idleResources.length > 0 || forecast) && (
  <div className="px-4 pt-4 pb-2">
    <p className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
      Azure Advisor Cost Recommendations
    </p>
  </div>
)}
```

Note: The existing header, data lag note, and card grid JSX from `CostTab.tsx` must remain UNCHANGED below these new sections. The `fetchFinopsData` runs in parallel with `fetchCostData` via `Promise.allSettled` — independent fetches, independent error states.
</action>

<acceptance_criteria>
- `grep "CostBreakdownItem" services/web-ui/components/CostTab.tsx` exits 0
- `grep "CostForecastResponse" services/web-ui/components/CostTab.tsx` exits 0
- `grep "IdleResource" services/web-ui/components/CostTab.tsx` exits 0
- `grep "RiUtilisationResponse" services/web-ui/components/CostTab.tsx` exits 0
- `grep "fetchFinopsData" services/web-ui/components/CostTab.tsx` exits 0
- `grep "from 'recharts'" services/web-ui/components/CostTab.tsx` exits 0
- `grep "BarChart" services/web-ui/components/CostTab.tsx` exits 0
- `grep "layout=\"vertical\"" services/web-ui/components/CostTab.tsx` exits 0
- `grep "handleApprove" services/web-ui/components/CostTab.tsx` exits 0
- `grep "handleReject" services/web-ui/components/CostTab.tsx` exits 0
- `grep "var(--accent-red)" services/web-ui/components/CostTab.tsx` exits 0
- `grep "var(--accent-green)" services/web-ui/components/CostTab.tsx` exits 0
- `grep "var(--accent-blue)" services/web-ui/components/CostTab.tsx` exits 0
- `grep "color-mix" services/web-ui/components/CostTab.tsx` exits 0
- `grep "color: 'var(--accent-orange)" services/web-ui/components/CostTab.tsx` exits 0
- Existing `impactBadgeStyle` function still present: `grep "impactBadgeStyle" services/web-ui/components/CostTab.tsx` exits 0
- Existing `formatCurrency` function still present: `grep "formatCurrency" services/web-ui/components/CostTab.tsx` exits 0
- No hardcoded Tailwind color classes: `grep -E "bg-(green|red|orange|blue|yellow)-[0-9]+" services/web-ui/components/CostTab.tsx` exits 1
- No hardcoded hex colors: `grep -E "#[0-9a-fA-F]{3,6}" services/web-ui/components/CostTab.tsx` exits 1
- `grep "Promise.allSettled" services/web-ui/components/CostTab.tsx` exits 0
</acceptance_criteria>

---

## Verification

After all tasks complete:

```bash
# 1. TypeScript compilation check
cd services/web-ui && npx tsc --noEmit 2>&1 | grep -E "error TS" | head -20

# 2. All 6 proxy routes exist
for route in cost-breakdown resource-cost idle-resources ri-utilization cost-forecast top-cost-drivers; do
  test -f "services/web-ui/app/api/proxy/finops/${route}/route.ts" && echo "OK: $route" || echo "MISSING: $route"
done

# 3. DashboardPanel tab renamed
grep "label: 'FinOps'" services/web-ui/components/DashboardPanel.tsx

# 4. CostTab has FinOps sections
grep -c "fetchFinopsData\|BarChart\|IdleResource\|CostForecastResponse" services/web-ui/components/CostTab.tsx
```

Expected: 0 TypeScript errors, all 6 routes present, label change confirmed, ≥4 FinOps markers in CostTab.

## must_haves

- [ ] 6 proxy routes created under `services/web-ui/app/api/proxy/finops/` with correct upstream paths
- [ ] All proxy routes use `AbortSignal.timeout(15000)` and `buildUpstreamHeaders()`
- [ ] `DashboardPanel.tsx` tab label changed from "Cost" to "FinOps" with `DollarSign` icon (TabId `'cost'` unchanged)
- [ ] `CostTab.tsx` extended with: new TypeScript interfaces (7), `fetchFinopsData` parallel fetch using `Promise.allSettled`, budget burn rate gauge, vertical bar chart (Recharts `layout="vertical"`), idle resource table with HITL approve/reject buttons, RI utilisation card
- [ ] Existing `impactBadgeStyle`, `formatCurrency`, `cleanServiceType` helpers and Advisor recommendations card grid preserved unchanged
- [ ] All styling uses CSS semantic tokens (`var(--accent-*)`, `var(--text-*)`, `var(--bg-canvas)`, `color-mix(...)`) — no hardcoded hex colors or Tailwind color classes
- [ ] HITL approve button calls `/api/proxy/approvals/{id}/approve` (existing endpoint)
- [ ] No TypeScript compilation errors (`tsc --noEmit` exits 0)
