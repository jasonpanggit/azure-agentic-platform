# Plan 54-3: ComplianceTab UI + Proxy Routes + Dashboard Registration

---
wave: 3
depends_on: ["54-2"]
files_modified:
  - services/web-ui/components/ComplianceTab.tsx
  - services/web-ui/app/api/proxy/compliance/posture/route.ts
  - services/web-ui/app/api/proxy/compliance/export/route.ts
  - services/web-ui/components/DashboardPanel.tsx
autonomous: true
---

## Goal

Build the ComplianceTab component with heat-map of controls (passing/failing/not-assessed), score cards per framework, findings click-through via Sheet, and export buttons. Wire proxy routes and register the tab in DashboardPanel.

## Tasks

<task id="54-3-1" title="Create posture proxy route">
<read_first>
- services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts (exact proxy pattern)
- services/web-ui/lib/api-gateway.ts (getApiGatewayUrl, buildUpstreamHeaders)
</read_first>
<action>
Create `services/web-ui/app/api/proxy/compliance/posture/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/compliance/posture' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    log.info('proxy request', { method: 'GET', query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/compliance/posture${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, frameworks: {} },
        { status: res.status }
      );
    }

    log.debug('proxy response', { frameworks: Object.keys(data?.frameworks ?? {}) });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, frameworks: {} },
      { status: 502 }
    );
  }
}
```
</action>
<acceptance_criteria>
- File exists at `services/web-ui/app/api/proxy/compliance/posture/route.ts`
- `grep "getApiGatewayUrl" services/web-ui/app/api/proxy/compliance/posture/route.ts` succeeds
- `grep "buildUpstreamHeaders" services/web-ui/app/api/proxy/compliance/posture/route.ts` succeeds
- `grep "/api/v1/compliance/posture" services/web-ui/app/api/proxy/compliance/posture/route.ts` succeeds
- `grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/compliance/posture/route.ts` succeeds
</acceptance_criteria>
</task>

<task id="54-3-2" title="Create export proxy route">
<read_first>
- services/web-ui/app/api/proxy/compliance/posture/route.ts (created in 54-3-1)
- services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts
</read_first>
<action>
Create `services/web-ui/app/api/proxy/compliance/export/route.ts`:

This route differs from other proxy routes because it returns binary content (PDF) or CSV text, not JSON. It must pass through the response body directly.

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/compliance/export' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    const format = searchParams.get('format') ?? 'csv';
    log.info('proxy request', { method: 'GET', format, query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/compliance/export${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(30000), // PDF generation may take longer
      }
    );

    if (!res.ok) {
      const errorText = await res.text().catch(() => 'Unknown error');
      log.error('upstream error', { status: res.status, detail: errorText });
      return NextResponse.json(
        { error: `Export failed: ${errorText}` },
        { status: res.status }
      );
    }

    // Pass through binary/text response with correct headers
    const contentType = res.headers.get('content-type') ?? 'application/octet-stream';
    const contentDisposition = res.headers.get('content-disposition') ?? '';
    const body = await res.arrayBuffer();

    return new NextResponse(body, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        ...(contentDisposition ? { 'Content-Disposition': contentDisposition } : {}),
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
```
</action>
<acceptance_criteria>
- File exists at `services/web-ui/app/api/proxy/compliance/export/route.ts`
- `grep "getApiGatewayUrl" services/web-ui/app/api/proxy/compliance/export/route.ts` succeeds
- `grep "/api/v1/compliance/export" services/web-ui/app/api/proxy/compliance/export/route.ts` succeeds
- `grep "arrayBuffer" services/web-ui/app/api/proxy/compliance/export/route.ts` succeeds
- `grep "Content-Disposition" services/web-ui/app/api/proxy/compliance/export/route.ts` succeeds
- `grep "AbortSignal.timeout" services/web-ui/app/api/proxy/compliance/export/route.ts` succeeds
</acceptance_criteria>
</task>

<task id="54-3-3" title="Create ComplianceTab component with heat-map">
<read_first>
- services/web-ui/components/CostTab.tsx (tab component pattern: types, state, fetch, render)
- services/web-ui/components/DashboardPanel.tsx (how tabs receive subscriptions prop)
- .planning/phases/54-compliance-framework-mapping/54-RESEARCH.md (Section 7 UI design)
</read_first>
<action>
Create `services/web-ui/components/ComplianceTab.tsx` as a `'use client'` component.

**TypeScript interfaces:**
```typescript
interface ComplianceControl {
  framework: string;
  control_id: string;
  control_title: string;
  status: 'passing' | 'failing' | 'not_assessed';
  findings: ComplianceFinding[];
}

interface ComplianceFinding {
  finding_type: string;
  defender_rule_id: string;
  display_name: string;
  severity: string;
}

interface FrameworkScore {
  score: number;
  total_controls: number;
  passing: number;
  failing: number;
  not_assessed: number;
}

interface PostureResponse {
  subscription_id: string;
  generated_at: string;
  cache_hit?: boolean;
  frameworks: {
    asb?: FrameworkScore;
    cis?: FrameworkScore;
    nist?: FrameworkScore;
  };
  controls: ComplianceControl[];
  error?: string;
}

interface ComplianceTabProps {
  subscriptions: string[];
}
```

**Component structure:**

State:
- `posture: PostureResponse | null`
- `loading: boolean`
- `error: string | null`
- `selectedFramework: 'all' | 'asb' | 'cis' | 'nist'`
- `selectedControl: ComplianceControl | null` (for Sheet click-through)
- `sheetOpen: boolean`

Fetch: `useCallback` + `useEffect` on `[subscriptions]`. Fetch from `/api/proxy/compliance/posture?subscription_id=${subscriptions[0]}`. Set loading/error states.

**Layout (top to bottom):**

1. **Header row** — between `px-4 py-3` with border-bottom:
   - `FileCheck` lucide icon (h-4 w-4, color: `var(--accent-blue)`)
   - Title "Compliance Posture" (text-[13px] font-medium)
   - Framework selector: 4 buttons (All / ASB / CIS / NIST) using shadcn `Button` variant="ghost" or "outline" depending on active state
   - Refresh button (same pattern as CostTab)
   - Export buttons: "Export PDF" (Button variant="outline" size="sm") and "Export CSV" (Button variant="ghost" size="sm") with `Download` lucide icon
   - Export handler: `window.open('/api/proxy/compliance/export?subscription_id=...&format=pdf', '_blank')`

2. **Score cards** — `grid grid-cols-3 gap-3 px-4 pt-4`:
   - One `Card` per framework (ASB, CIS, NIST)
   - Each card shows: framework name, score as large number (text-[24px] font-semibold), color-coded (green >= 70, orange >= 40, red < 40 using `var(--accent-green/orange/red)`)
   - Below score: `{passing} passing · {failing} failing · {not_assessed} not assessed` (text-[11px])

3. **Heat-map grid** — `px-4 pt-4`:
   - Section title: "Control Status Heat Map" (text-[13px] font-medium)
   - CSS Grid: `grid gap-1` with `gridTemplateColumns: repeat(auto-fill, minmax(48px, 1fr))`
   - Each cell = one control, `h-8 rounded text-[9px] flex items-center justify-center font-mono cursor-pointer`
   - Colors (using project `color-mix` pattern):
     - passing: `background: color-mix(in srgb, var(--accent-green) 60%, transparent)`
     - failing: `background: color-mix(in srgb, var(--accent-red) 60%, transparent)`
     - not_assessed: `background: color-mix(in srgb, var(--border) 60%, transparent)`
   - Hover: add `hover:opacity-80 hover:ring-1 hover:ring-foreground/20` classes
   - onClick: `setSelectedControl(ctrl); setSheetOpen(true)`
   - Show `ctrl.control_id` as cell text, `title={ctrl.control_title}` for tooltip
   - Filter by `selectedFramework` (if not 'all')

4. **Findings Sheet** — shadcn `Sheet` component (side="right"):
   - Triggered by clicking a heat-map cell
   - Shows control_id, control_title, status badge, framework
   - Findings list as shadcn `Table`: columns = Finding Name, Type, Severity
   - Severity badges using `color-mix` pattern (High=red, Medium=orange, Low=blue)

**Loading state:** Same skeleton pattern as CostTab (`<Skeleton className="h-10 w-full" />` × 5)
**Error state:** shadcn `Alert variant="destructive"` with error message
**Empty state:** No subscriptions → "Select a subscription to view compliance posture" with `FileCheck` icon

**Imports:**
```typescript
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { FileCheck, RefreshCw, Download } from 'lucide-react';
```
</action>
<acceptance_criteria>
- File exists at `services/web-ui/components/ComplianceTab.tsx`
- `grep "ComplianceTab" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "use client" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "color-mix" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "var(--accent-green)" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "var(--accent-red)" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "/api/proxy/compliance/posture" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "/api/proxy/compliance/export" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "Sheet" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "grid" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "ComplianceControl" services/web-ui/components/ComplianceTab.tsx` succeeds
- `grep "FrameworkScore" services/web-ui/components/ComplianceTab.tsx` succeeds
</acceptance_criteria>
</task>

<task id="54-3-4" title="Register ComplianceTab in DashboardPanel">
<read_first>
- services/web-ui/components/DashboardPanel.tsx (TabId type, TABS array, component rendering)
</read_first>
<action>
Modify `services/web-ui/components/DashboardPanel.tsx`:

1. **Add import** (after the `RunbookTab` import):
```typescript
import { ComplianceTab } from './ComplianceTab'
```

2. **Extend TabId type** — add `'compliance'` to the union:
```typescript
type TabId = 'ops' | 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch' | 'compliance' | 'runbooks' | 'settings'
```

3. **Add tab entry to TABS array** — insert AFTER `patch` and BEFORE `runbooks`:
```typescript
{ id: 'compliance', label: 'Compliance', Icon: FileCheck },
```

4. **Add `FileCheck` to the lucide imports** at the top of the file (add to the existing destructured import from `lucide-react`).

5. **Add tab content rendering** — in the tab content switch/conditional section, add:
```typescript
{activeTab === 'compliance' && <ComplianceTab subscriptions={selectedSubscriptions} />}
```

Place this after the `patch` tab rendering and before the `runbooks` tab rendering.
</action>
<acceptance_criteria>
- `grep "ComplianceTab" services/web-ui/components/DashboardPanel.tsx` succeeds
- `grep "'compliance'" services/web-ui/components/DashboardPanel.tsx` succeeds
- `grep "FileCheck" services/web-ui/components/DashboardPanel.tsx` succeeds
- `grep "import { ComplianceTab }" services/web-ui/components/DashboardPanel.tsx` succeeds
- `cd services/web-ui && npx tsc --noEmit` exits 0 (no TypeScript errors)
</acceptance_criteria>
</task>

<task id="54-3-5" title="Build verification">
<read_first>
- services/web-ui/components/ComplianceTab.tsx
- services/web-ui/components/DashboardPanel.tsx
</read_first>
<action>
Run the full Next.js build to verify zero TypeScript errors and successful compilation:

```bash
cd services/web-ui && npm run build
```

If TypeScript errors occur, fix them in the ComplianceTab or DashboardPanel files. Common issues:
- Missing Sheet component: run `npx shadcn add sheet` if not already installed
- Import path mismatches: verify `@/components/ui/sheet` exists
- Type narrowing: ensure `posture?.frameworks?.asb` uses optional chaining
</action>
<acceptance_criteria>
- `cd services/web-ui && npx tsc --noEmit` exits with code 0
- `cd services/web-ui && npm run build` exits with code 0
- No TypeScript errors in ComplianceTab.tsx or DashboardPanel.tsx
</acceptance_criteria>
</task>

## Verification

```bash
# 1. Proxy routes exist
ls services/web-ui/app/api/proxy/compliance/posture/route.ts
ls services/web-ui/app/api/proxy/compliance/export/route.ts

# 2. ComplianceTab created
grep "ComplianceTab" services/web-ui/components/ComplianceTab.tsx

# 3. DashboardPanel wired
grep "'compliance'" services/web-ui/components/DashboardPanel.tsx
grep "ComplianceTab" services/web-ui/components/DashboardPanel.tsx

# 4. TypeScript clean
cd services/web-ui && npx tsc --noEmit

# 5. Build succeeds
cd services/web-ui && npm run build
```

## must_haves

- [ ] ComplianceTab renders heat-map grid of controls colored by status (passing=green, failing=red, not_assessed=grey)
- [ ] Heat-map cells clickable → Sheet shows findings for that control
- [ ] Score cards show ASB, CIS, NIST scores with passing/failing/not_assessed counts
- [ ] Framework selector filters heat-map to one framework
- [ ] Export PDF and Export CSV buttons trigger browser download via proxy route
- [ ] Proxy routes forward to `/api/v1/compliance/posture` and `/api/v1/compliance/export`
- [ ] `compliance` tab registered in DashboardPanel with FileCheck icon
- [ ] `npx tsc --noEmit` and `npm run build` pass with zero errors
