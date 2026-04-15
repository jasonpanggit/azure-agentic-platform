---
wave: 4
depends_on: [55-2, 55-3]
files_modified:
  - services/web-ui/components/SLATab.tsx                         # new — SLA dashboard tab
  - services/web-ui/app/api/proxy/sla/compliance/route.ts         # new — compliance proxy
  - services/web-ui/app/api/proxy/sla/definitions/route.ts        # new — definitions proxy
  - services/web-ui/app/api/proxy/sla/report/[slaId]/route.ts     # new — report trigger proxy
  - services/web-ui/components/DashboardPanel.tsx                  # add 'sla' tab
autonomous: true
---

## Goal

Add the **SLA** tab to the operational dashboard with:
- Per-SLA attainment gauge (SVG radial progress, no extra library).
- 12-month trend sparkline (recharts `BarChart` — already in project from `CostTab.tsx`).
- Contributing incidents table (shadcn `Table`).
- Manual report trigger button per SLA definition.
- Three Next.js proxy routes wiring the tab to the API gateway.

---

## Tasks

<task id="55-4-1">
### Create proxy route: `GET /api/proxy/sla/compliance/route.ts`

<read_first>
- `services/web-ui/app/api/proxy/vms/route.ts` — exact proxy pattern:
  `getApiGatewayUrl()`, `buildUpstreamHeaders()`, `AbortSignal.timeout(15000)`,
  graceful fallback on non-OK upstream.
- `services/web-ui/lib/api-gateway.ts` — `getApiGatewayUrl` + `buildUpstreamHeaders`.
</read_first>

<action>
Create `services/web-ui/app/api/proxy/sla/compliance/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/sla/compliance' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'GET' });
  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/sla/compliance`);
    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) {
      log.warn('upstream error', { status: res.status });
      return NextResponse.json(
        { results: [], computed_at: new Date().toISOString(), error: `upstream ${res.status}` },
        { status: res.status },
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error';
    log.warn('gateway unreachable', { error: message });
    return NextResponse.json(
      { results: [], computed_at: new Date().toISOString(), error: message },
      { status: 503 },
    );
  }
}
```
</action>

<acceptance_criteria>
1. File exists at `services/web-ui/app/api/proxy/sla/compliance/route.ts`.
2. `grep -n "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/sla/compliance/route.ts`
   shows the timeout guard.
3. `grep -n "results: \[\]" services/web-ui/app/api/proxy/sla/compliance/route.ts`
   shows the graceful empty fallback.
</acceptance_criteria>
</task>

<task id="55-4-2">
### Create proxy route: `GET /api/proxy/sla/definitions/route.ts`

<read_first>
- Same proxy pattern as Task 55-4-1.
</read_first>

<action>
Create `services/web-ui/app/api/proxy/sla/definitions/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/sla/definitions' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'GET' });
  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/admin/sla-definitions`);
    const searchParams = req.nextUrl.searchParams;
    const includeInactive = searchParams.get('include_inactive');
    if (includeInactive) url.searchParams.set('include_inactive', includeInactive);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) {
      log.warn('upstream error', { status: res.status });
      return NextResponse.json(
        { items: [], total: 0, error: `upstream ${res.status}` },
        { status: res.status },
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error';
    log.warn('gateway unreachable', { error: message });
    return NextResponse.json({ items: [], total: 0, error: message }, { status: 503 });
  }
}
```
</action>

<acceptance_criteria>
1. File exists at `services/web-ui/app/api/proxy/sla/definitions/route.ts`.
2. `grep -n "AbortSignal.timeout" services/web-ui/app/api/proxy/sla/definitions/route.ts` shows timeout.
3. `grep -n "items: \[\]" services/web-ui/app/api/proxy/sla/definitions/route.ts` shows fallback.
</acceptance_criteria>
</task>

<task id="55-4-3">
### Create proxy route: `POST /api/proxy/sla/report/[slaId]/route.ts`

<read_first>
- `services/web-ui/app/api/proxy/vms/route.ts` — pattern reference.
</read_first>

<action>
Create `services/web-ui/app/api/proxy/sla/report/[slaId]/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/sla/report/[slaId]' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(
  req: NextRequest,
  { params }: { params: { slaId: string } },
): Promise<NextResponse> {
  const { slaId } = params;
  log.info('trigger report', { slaId });
  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/sla/report/${slaId}`);
    const res = await fetch(url.toString(), {
      method: 'POST',
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(60000),  // reports can take ~30s
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: body?.detail ?? `upstream ${res.status}` },
        { status: res.status },
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error';
    log.error('report trigger failed', { slaId, error: message });
    return NextResponse.json({ error: message }, { status: 503 });
  }
}
```

Note: timeout is 60 seconds (not 15 seconds) because PDF generation + GPT-4o
narrative may take up to ~30 seconds on a cold container.
</action>

<acceptance_criteria>
1. File exists at `services/web-ui/app/api/proxy/sla/report/[slaId]/route.ts`.
2. `grep -n "AbortSignal.timeout(60000)" services/web-ui/app/api/proxy/sla/report/[slaId]/route.ts`
   shows the extended timeout.
3. `grep -n "method: 'POST'" services/web-ui/app/api/proxy/sla/report/[slaId]/route.ts`
   shows POST method forwarding.
</acceptance_criteria>
</task>

<task id="55-4-4">
### Create `services/web-ui/components/SLATab.tsx`

<read_first>
- `services/web-ui/components/CostTab.tsx` lines 1–80 — import pattern, `useState`,
  `useEffect`, `useCallback`, recharts `BarChart`, shadcn `Table`, `Badge`, `Card`.
- `services/web-ui/components/DashboardPanel.tsx` — understand that `SLATab` will
  receive `subscriptions: string[]` prop (consistent with all other tabs).
- Review existing CSS token list: `var(--accent-green)`, `var(--accent-red)`,
  `var(--accent-orange)`, `var(--accent-blue)`, `var(--border)`,
  `var(--text-primary)`, `var(--text-muted)`, `var(--bg-surface)`, `var(--bg-canvas)`.
</read_first>

<action>
Create `services/web-ui/components/SLATab.tsx` with the following structure.

#### Rules
- `'use client'` directive at top.
- All colors via CSS tokens (`var(--accent-*)`) — zero hardcoded Tailwind color
  classes like `text-green-500` or `bg-red-100`.
- Badge background: `color-mix(in srgb, var(--accent-green) 15%, transparent)`.
- No new npm dependencies — use `recharts` (already installed) and SVG for gauge.

#### TypeScript types

```typescript
interface SLADefinition {
  id: string
  name: string
  target_availability_pct: number
  covered_resource_ids: string[]
  measurement_period: string
  customer_name: string | null
  report_recipients: string[]
  is_active: boolean
}

interface ResourceAttainment {
  resource_id: string
  availability_pct: number | null
  downtime_minutes: number | null
  data_source: string
}

interface SLAComplianceResult {
  sla_id: string
  sla_name: string
  target_availability_pct: number
  attained_availability_pct: number | null
  is_compliant: boolean | null
  measurement_period: string
  period_start: string
  period_end: string
  resource_attainments: ResourceAttainment[]
  data_source: string
  duration_ms: number
}

interface SLAComplianceResponse {
  results: SLAComplianceResult[]
  computed_at: string
  error?: string
}

interface SLATabProps {
  subscriptions: string[]   // passed by DashboardPanel; not used in API calls (SLA is subscription-agnostic) but must be accepted
}
```

#### Component skeleton

```tsx
'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { BarChart2, RefreshCw, FileText, CheckCircle2, XCircle, HelpCircle } from 'lucide-react'

export function SLATab({ subscriptions }: SLATabProps) {
  const [compliance, setCompliance] = useState<SLAComplianceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reportLoading, setReportLoading] = useState<Record<string, boolean>>({})
  const [reportMessage, setReportMessage] = useState<Record<string, string>>({})

  const fetchCompliance = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/proxy/sla/compliance')
      const data: SLAComplianceResponse = await res.json()
      if (data.error && !data.results?.length) {
        setError(data.error)
      }
      setCompliance(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load SLA compliance')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchCompliance() }, [fetchCompliance])

  async function triggerReport(slaId: string) {
    setReportLoading(prev => ({ ...prev, [slaId]: true }))
    setReportMessage(prev => ({ ...prev, [slaId]: '' }))
    try {
      const res = await fetch(`/api/proxy/sla/report/${slaId}`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        setReportMessage(prev => ({ ...prev, [slaId]: data.error ?? 'Report failed' }))
      } else {
        setReportMessage(prev => ({
          ...prev,
          [slaId]: `Report sent to ${data.emailed_to?.length ?? 0} recipients`,
        }))
      }
    } catch (err) {
      setReportMessage(prev => ({
        ...prev,
        [slaId]: err instanceof Error ? err.message : 'Report failed',
      }))
    } finally {
      setReportLoading(prev => ({ ...prev, [slaId]: false }))
    }
  }

  // ... render
}
```

#### Render structure

```
<div className="space-y-6">

  {/* Header row */}
  <div className="flex items-center justify-between">
    <h2>SLA Compliance</h2>
    <Button onClick={fetchCompliance} disabled={loading}>
      <RefreshCw /> Refresh
    </Button>
  </div>

  {error && <Alert><AlertDescription>{error}</AlertDescription></Alert>}

  {loading ? (
    <Skeleton grid 3 columns />
  ) : (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {compliance?.results.map(result => (
        <SLACard key={result.sla_id} result={result}
                 onTriggerReport={() => triggerReport(result.sla_id)}
                 reportLoading={reportLoading[result.sla_id] ?? false}
                 reportMessage={reportMessage[result.sla_id] ?? ''} />
      ))}
      {!compliance?.results.length && !error && (
        <EmptyState message="No SLA definitions found. Create one via the admin API." />
      )}
    </div>
  )}

</div>
```

#### `SLACard` sub-component (defined in same file)

```
Props: { result: SLAComplianceResult, onTriggerReport, reportLoading, reportMessage }

Layout (Card):
  Header: SLA name + compliance badge ("COMPLIANT" / "BREACH" / "NO DATA")
  Body:
    - AttainmentGauge (SVG radial)
    - Metric row: Attained X.XXX% vs Target Y.YYY%
    - Customer label if present
    - ResourceBreakdownTable (shadcn Table, 4 columns)
    - ReportButton + reportMessage
```

#### `AttainmentGauge` sub-component (same file)

SVG circle stroke-dasharray gauge — no external library:
```tsx
function AttainmentGauge({
  attained,
  target,
}: {
  attained: number | null
  target: number
}) {
  const size = 120
  const strokeWidth = 10
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const pct = attained ?? 0
  const dashOffset = circumference - (pct / 100) * circumference
  const isCompliant = attained !== null && attained >= target
  const color = attained === null
    ? 'var(--text-muted)'
    : isCompliant
      ? 'var(--accent-green)'
      : 'var(--accent-red)'

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke="var(--border)" strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
      </svg>
      <span
        className="text-lg font-semibold mt-1"
        style={{ color: 'var(--text-primary)' }}
      >
        {attained !== null ? `${attained.toFixed(3)}%` : 'N/A'}
      </span>
    </div>
  )
}
```

#### Badge styling (no hardcoded colors)

```tsx
function ComplianceBadge({ isCompliant }: { isCompliant: boolean | null }) {
  if (isCompliant === null) {
    return (
      <Badge style={{
        background: 'color-mix(in srgb, var(--text-muted) 15%, transparent)',
        color: 'var(--text-muted)',
        border: '1px solid var(--border)',
      }}>
        <HelpCircle className="h-3 w-3 mr-1" /> No data
      </Badge>
    )
  }
  return isCompliant ? (
    <Badge style={{
      background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
      color: 'var(--accent-green)',
      border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
    }}>
      <CheckCircle2 className="h-3 w-3 mr-1" /> Compliant
    </Badge>
  ) : (
    <Badge style={{
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
    }}>
      <XCircle className="h-3 w-3 mr-1" /> Breach
    </Badge>
  )
}
```

#### 12-month trend sparkline

The compliance endpoint returns only the current period.  The 12-month trend
section should render a placeholder sparkline using mock/stub data with a note
"Historical data available after 12 months of operation" until a history endpoint
is added in a future phase.

Use recharts `BarChart` with:
- 12 data points `[{ month: 'Jan', attained: 99.95 }, ...]` — synthetic stub values
  centered near the target.
- `Bar fill` using inline style `fill: 'var(--accent-blue)'`.
- `YAxis domain={[99, 100]}`.
- Height 80px, width 100%.

#### Empty state

```tsx
function EmptyState({ message }: { message: string }) {
  return (
    <div className="col-span-full flex flex-col items-center py-16"
         style={{ color: 'var(--text-muted)' }}>
      <BarChart2 className="h-12 w-12 mb-3 opacity-30" />
      <p>{message}</p>
    </div>
  )
}
```
</action>

<acceptance_criteria>
1. File exists at `services/web-ui/components/SLATab.tsx`.
2. `grep -n "'use client'" services/web-ui/components/SLATab.tsx` shows directive on line 1.
3. `grep -n "var(--accent-green)\|var(--accent-red)\|var(--accent-blue)" services/web-ui/components/SLATab.tsx | wc -l` ≥ 3.
4. `grep -n "color-mix" services/web-ui/components/SLATab.tsx | wc -l` ≥ 2 (badge + gauge).
5. `grep -n "stroke-dasharray\|strokeDasharray" services/web-ui/components/SLATab.tsx` shows SVG gauge.
6. `grep -n "BarChart" services/web-ui/components/SLATab.tsx` shows recharts import + usage.
7. `grep -n "triggerReport\|onTriggerReport" services/web-ui/components/SLATab.tsx` shows report button logic.
8. Zero hardcoded Tailwind color classes (`bg-green-`, `bg-red-`, `text-green-`, `text-red-`):
   `grep -n "bg-green-\|bg-red-\|text-green-\|text-red-" services/web-ui/components/SLATab.tsx`
   returns nothing.
9. TypeScript compilation: `cd services/web-ui && npx tsc --noEmit 2>&1 | grep SLATab` returns nothing (no errors).
</acceptance_criteria>
</task>

<task id="55-4-5">
### Register `SLATab` in `DashboardPanel.tsx`

<read_first>
- `services/web-ui/components/DashboardPanel.tsx` — full file.
  Key things to change:
  1. `type TabId` union — add `'sla'`.
  2. `const TABS` array — add SLA entry after `'runbooks'` and before `'settings'`.
  3. Import `SLATab`.
  4. Add `tabpanel-sla` div in the panels section.
</read_first>

<action>
Make the following four targeted edits to `DashboardPanel.tsx`:

**Edit 1 — Import `SLATab`**

After the line `import { SettingsTab } from './SettingsTab'`, add:
```typescript
import { SLATab } from './SLATab'
```

**Edit 2 — Extend `TabId` union**

Change:
```typescript
type TabId = 'ops' | 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch' | 'runbooks' | 'settings'
```
To:
```typescript
type TabId = 'ops' | 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch' | 'runbooks' | 'sla' | 'settings'
```

**Edit 3 — Add SLA entry to `TABS` array**

In the `TABS` array, insert before `{ id: 'settings', ... }`:
```typescript
{ id: 'sla', label: 'SLA', Icon: BarChart2 },
```
Also add `BarChart2` to the lucide-react import at the top of the file
(it is already imported as part of `lucide-react` — just add it to the
destructure if not already present).

**Edit 4 — Add SLA tab panel**

In the `<div className="flex-1 overflow-auto p-6">` section, after the
`tabpanel-runbooks` div and before the `tabpanel-settings` div, add:
```tsx
<div id="tabpanel-sla" role="tabpanel" aria-labelledby="tab-sla" hidden={activeTab !== 'sla'}>
  <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
    <SLATab subscriptions={selectedSubscriptions} />
  </div>
</div>
```

Do NOT change any other lines.
</action>

<acceptance_criteria>
1. `grep -n "SLATab" services/web-ui/components/DashboardPanel.tsx | wc -l` ≥ 3
   (import + TABS entry via BarChart2 reference + tabpanel usage).
2. `grep -n "'sla'" services/web-ui/components/DashboardPanel.tsx | wc -l` ≥ 3
   (TabId + TABS array + tabpanel id).
3. `grep -n "BarChart2" services/web-ui/components/DashboardPanel.tsx` shows the import.
4. `grep -n "tabpanel-sla" services/web-ui/components/DashboardPanel.tsx` shows the panel div.
5. TypeScript compilation: `cd services/web-ui && npx tsc --noEmit 2>&1 | grep DashboardPanel`
   returns nothing.
</acceptance_criteria>
</task>

---

## Verification

```bash
# 1. All new files exist
test -f services/web-ui/app/api/proxy/sla/compliance/route.ts && echo "compliance proxy OK"
test -f services/web-ui/app/api/proxy/sla/definitions/route.ts && echo "definitions proxy OK"
test -f "services/web-ui/app/api/proxy/sla/report/[slaId]/route.ts" && echo "report proxy OK"
test -f services/web-ui/components/SLATab.tsx && echo "SLATab OK"

# 2. Proxy timeout guards
grep -n "AbortSignal.timeout" services/web-ui/app/api/proxy/sla/compliance/route.ts
grep -n "AbortSignal.timeout" services/web-ui/app/api/proxy/sla/definitions/route.ts
grep -n "AbortSignal.timeout(60000)" "services/web-ui/app/api/proxy/sla/report/[slaId]/route.ts"

# 3. SLATab: no hardcoded colors
grep -n "bg-green-\|bg-red-\|text-green-\|text-red-" services/web-ui/components/SLATab.tsx && echo "FAIL: hardcoded color" || echo "PASS: no hardcoded colors"

# 4. SLATab: CSS token usage
grep -c "var(--accent" services/web-ui/components/SLATab.tsx

# 5. SVG gauge present
grep -n "strokeDasharray\|stroke-dasharray" services/web-ui/components/SLATab.tsx

# 6. DashboardPanel registration
grep -n "SLATab\|'sla'\|tabpanel-sla" services/web-ui/components/DashboardPanel.tsx

# 7. TypeScript compile (no new errors)
cd services/web-ui && npx tsc --noEmit 2>&1 | head -30

# 8. Full test suite still passes
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_sla_endpoints.py \
                  services/api-gateway/tests/test_sla_report.py \
                  services/api-gateway/tests/test_admin_endpoints.py \
                  -v --tb=short 2>&1 | tail -10
```

---

## must_haves

- [ ] Three proxy routes exist with correct path structures and `runtime = 'nodejs'`
- [ ] Report proxy uses 60s timeout (not 15s) — PDF generation is slow
- [ ] `SLATab` uses `'use client'` directive
- [ ] All colors use CSS semantic tokens — zero hardcoded Tailwind color utilities
- [ ] Badge backgrounds use `color-mix(in srgb, var(--accent-*) 15%, transparent)` pattern
- [ ] SVG radial gauge uses `stroke-dasharray` / `stroke-dashoffset` trick (no chart library)
- [ ] 12-month trend uses `recharts` `BarChart` (already installed — no new dependency)
- [ ] `SLATab` accepts `subscriptions: string[]` prop (DashboardPanel compatibility)
- [ ] `DashboardPanel.tsx` has `'sla'` in `TabId`, in `TABS` array, and in tabpanels section
- [ ] `npx tsc --noEmit` passes with no new errors in DashboardPanel or SLATab
