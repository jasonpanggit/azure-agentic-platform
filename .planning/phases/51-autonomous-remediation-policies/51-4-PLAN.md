# Plan 51-4: Settings Tab UI + Proxy Routes + DashboardPanel Wiring

---
wave: 3
depends_on: ["51-1", "51-3"]
files_modified:
  - services/web-ui/components/SettingsTab.tsx
  - services/web-ui/components/DashboardPanel.tsx
  - services/web-ui/app/api/proxy/admin/remediation-policies/route.ts
  - services/web-ui/app/api/proxy/admin/remediation-policies/[id]/route.ts
  - services/web-ui/app/api/proxy/admin/policy-suggestions/route.ts
  - services/web-ui/app/api/proxy/admin/policy-suggestions/[id]/[action]/route.ts
autonomous: true
---

<threat_model>
## Threat Model

**Assets:** Admin UI surface — policy configuration affects remediation safety

**Threat actors:**
- Unauthorized UI access to admin endpoints (MITIGATED: Entra auth on proxy + backend)
- XSS via policy name/description rendering (MITIGATED: React auto-escapes JSX; no dangerouslySetInnerHTML)

**Key risks and mitigations:**
1. **Unauthorized policy creation via UI** — MITIGATED: Proxy routes forward `Authorization` header; backend requires `Depends(verify_token)` on all admin endpoints
2. **XSS via policy fields** — MITIGATED: React auto-escapes text content; no `dangerouslySetInnerHTML` used; policy fields are plain text rendered in Table cells
3. **CSRF** — MITIGATED: POST/PUT/DELETE proxied with Bearer token authentication; no cookie-based auth
</threat_model>

## Goal

Build the Settings tab in the web UI with policy management (list, create/edit, execution history) and policy suggestion cards. Wire proxy routes from Next.js to the API gateway admin endpoints.

## Tasks

<task id="51-4-01">
<title>Scaffold shadcn/ui Sheet and Switch components</title>
<read_first>
- services/web-ui/components/ui/ (verify Sheet and Switch don't already exist)
- services/web-ui/package.json
</read_first>
<action>
Run the following commands from the `services/web-ui/` directory:

```bash
npx shadcn@latest add sheet
npx shadcn@latest add switch
```

This scaffolds `components/ui/sheet.tsx` and `components/ui/switch.tsx` into the existing shadcn/ui component library.

Verify the files exist after scaffolding.
</action>
<acceptance_criteria>
- File exists at `services/web-ui/components/ui/sheet.tsx`
- File exists at `services/web-ui/components/ui/switch.tsx`
- `services/web-ui/components/ui/sheet.tsx` contains `Sheet`
- `services/web-ui/components/ui/switch.tsx` contains `Switch`
</acceptance_criteria>
</task>

<task id="51-4-02">
<title>Create proxy routes for admin endpoints</title>
<read_first>
- services/web-ui/app/api/proxy/runbooks/route.ts (proxy route pattern)
- services/web-ui/lib/api-gateway.ts (getApiGatewayUrl, buildUpstreamHeaders)
</read_first>
<action>
Create 4 proxy route files:

**1. `services/web-ui/app/api/proxy/admin/remediation-policies/route.ts`**

Handles GET (list) and POST (create):
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/admin/remediation-policies' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'GET' });
  try {
    const url = `${getApiGatewayUrl()}/api/v1/admin/remediation-policies`;
    const res = await fetch(url, {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail ?? 'Gateway error' }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'POST' });
  try {
    const body = await req.json();
    const url = `${getApiGatewayUrl()}/api/v1/admin/remediation-policies`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...buildUpstreamHeaders(req.headers.get('Authorization'), false), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail ?? 'Gateway error' }, { status: res.status });
    }
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
```

**2. `services/web-ui/app/api/proxy/admin/remediation-policies/[id]/route.ts`**

Handles GET (single), PUT (update), DELETE:
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/admin/remediation-policies/[id]' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse> {
  const { id } = await params;
  try {
    const url = `${getApiGatewayUrl()}/api/v1/admin/remediation-policies/${id}`;
    const res = await fetch(url, {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Not found' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse> {
  const { id } = await params;
  try {
    const body = await req.json();
    const url = `${getApiGatewayUrl()}/api/v1/admin/remediation-policies/${id}`;
    const res = await fetch(url, {
      method: 'PUT',
      headers: { ...buildUpstreamHeaders(req.headers.get('Authorization'), false), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Error' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse> {
  const { id } = await params;
  try {
    const url = `${getApiGatewayUrl()}/api/v1/admin/remediation-policies/${id}`;
    const res = await fetch(url, {
      method: 'DELETE',
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    if (res.status === 204) return new NextResponse(null, { status: 204 });
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Error' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
```

**3. `services/web-ui/app/api/proxy/admin/policy-suggestions/route.ts`**

Handles GET (list suggestions):
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/admin/policy-suggestions' });
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  try {
    const url = `${getApiGatewayUrl()}/api/v1/admin/policy-suggestions`;
    const res = await fetch(url, {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Error' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
```

**4. `services/web-ui/app/api/proxy/admin/policy-suggestions/[id]/[action]/route.ts`**

Handles POST for dismiss and convert actions:
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/admin/policy-suggestions/[id]/[action]' });
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string; action: string }> }): Promise<NextResponse> {
  const { id, action } = await params;
  if (!['dismiss', 'convert'].includes(action)) {
    return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
  }
  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/admin/policy-suggestions/${id}/${action}`);
    // Forward query params (e.g. action_class for dismiss)
    req.nextUrl.searchParams.forEach((value, key) => url.searchParams.set(key, value));
    const bodyText = await req.text();
    const fetchOpts: RequestInit = {
      method: 'POST',
      headers: { ...buildUpstreamHeaders(req.headers.get('Authorization'), false), 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(15000),
    };
    if (bodyText) fetchOpts.body = bodyText;
    const res = await fetch(url.toString(), fetchOpts);
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Error' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
```
</action>
<acceptance_criteria>
- File exists at `services/web-ui/app/api/proxy/admin/remediation-policies/route.ts`
- File exists at `services/web-ui/app/api/proxy/admin/remediation-policies/[id]/route.ts`
- File exists at `services/web-ui/app/api/proxy/admin/policy-suggestions/route.ts`
- File exists at `services/web-ui/app/api/proxy/admin/policy-suggestions/[id]/[action]/route.ts`
- `services/web-ui/app/api/proxy/admin/remediation-policies/route.ts` contains `getApiGatewayUrl()`
- `services/web-ui/app/api/proxy/admin/remediation-policies/route.ts` contains `export async function GET`
- `services/web-ui/app/api/proxy/admin/remediation-policies/route.ts` contains `export async function POST`
- `services/web-ui/app/api/proxy/admin/remediation-policies/[id]/route.ts` contains `export async function PUT`
- `services/web-ui/app/api/proxy/admin/remediation-policies/[id]/route.ts` contains `export async function DELETE`
</acceptance_criteria>
</task>

<task id="51-4-03">
<title>Create SettingsTab.tsx component</title>
<read_first>
- services/web-ui/components/DashboardPanel.tsx (tab panel rendering pattern)
- services/web-ui/components/PatchTab.tsx (data table pattern)
- services/web-ui/components/ui/sheet.tsx (Sheet component from task 51-4-01)
- services/web-ui/components/ui/switch.tsx (Switch component from task 51-4-01)
- services/web-ui/components/ui/table.tsx (existing Table component)
- services/web-ui/components/ui/badge.tsx (existing Badge component)
- services/web-ui/components/ui/button.tsx (existing Button component)
</read_first>
<action>
Create `services/web-ui/components/SettingsTab.tsx` with the following structure:

**Component hierarchy:**
- `SettingsTab` (main component)
  - Sub-tab selector: "Remediation Policies" | "Policy Suggestions" (use simple button toggle, not nested shadcn Tabs — avoid nested tab-in-tab confusion)
  - **PolicyListPanel** (when "Remediation Policies" sub-tab active)
    - Fetch from `/api/proxy/admin/remediation-policies` on mount
    - Render shadcn `Table` with columns: Name, Action Class, Tag Filter (JSON rendered), Max Blast Radius, Daily Cap, Enabled (Switch), Executions Today, Actions
    - "Create Policy" button opens a `Sheet` slide-over from the right
    - Each row has Edit (opens Sheet) and Delete (confirm dialog) actions
    - Enabled toggle calls PUT to update the policy
  - **PolicySuggestionsPanel** (when "Policy Suggestions" sub-tab active)
    - Fetch from `/api/proxy/admin/policy-suggestions` on mount
    - Render dismissible card for each suggestion with:
      - Message text (the `message` field)
      - Approval count badge
      - "Dismiss" button (POST to dismiss endpoint)
      - "Create Policy" button (POST to convert endpoint — opens Sheet pre-filled with suggestion's action_class)

**Sheet form fields for create/edit:**
- Name (Input)
- Description (Textarea or Input)
- Action Class (Select dropdown with options from: `restart_vm`, `deallocate_vm`, `start_vm`, `resize_vm`, `restart_container_app`)
- Resource Tag Filter (simple key-value pair input — one row per tag with "Add Tag" button)
- Max Blast Radius (Input type number, min=1, max=50)
- Max Daily Executions (Input type number, min=1, max=100)
- Require SLO Healthy (Switch)
- Maintenance Window Exempt (Switch)
- Enabled (Switch)

**Styling rules:**
- Badge backgrounds: `color-mix(in srgb, var(--accent-green) 15%, transparent)` for enabled, `color-mix(in srgb, var(--accent-red) 15%, transparent)` for disabled
- Primary action buttons: `style={{ background: 'var(--accent-blue)' }}`
- Text colors: `var(--text-primary)`, `var(--text-secondary)`
- Surface backgrounds: `var(--bg-surface)`
- Borders: `var(--border)`
- Never use hardcoded Tailwind color classes like `bg-green-100` or `text-red-700`

**State management:**
- `useState` for policies list, suggestions list, loading state, selected policy for edit, sheet open state
- `useEffect` for initial data fetch
- Optimistic UI: update local state immediately on toggle/delete, revert on error

**Error handling:**
- Show error Alert when fetch fails
- Show loading Skeleton while fetching
- Show empty state message when no policies exist
</action>
<acceptance_criteria>
- File exists at `services/web-ui/components/SettingsTab.tsx`
- File contains `export function SettingsTab` or `export default function SettingsTab`
- File contains `remediation-policies` (fetch URL)
- File contains `policy-suggestions` (fetch URL)
- File contains import of `Sheet` from `@/components/ui/sheet`
- File contains import of `Switch` from `@/components/ui/switch`
- File contains import of `Table` from `@/components/ui/table`
- File contains `var(--accent-blue)` or `var(--accent-green)` (semantic tokens)
- File does NOT contain `bg-green-100` or `bg-red-100` or `text-green-700` (no hardcoded Tailwind colors)
- File contains `color-mix` (dark-mode-safe badge backgrounds)
- File contains `max_blast_radius` or `maxBlastRadius` (form field)
- File contains `action_class` or `actionClass` (form field)
- File contains `Create Policy` (button text)
</acceptance_criteria>
</task>

<task id="51-4-04">
<title>Add Settings tab to DashboardPanel</title>
<read_first>
- services/web-ui/components/DashboardPanel.tsx (TABS array, TabId type, tab panel rendering)
</read_first>
<action>
In `services/web-ui/components/DashboardPanel.tsx`:

1. Add `Settings` icon import from lucide-react (at the top, in the existing lucide import line):
```typescript
import { Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown, Scaling, Container, BookOpen, LayoutDashboard, Settings } from 'lucide-react'
```

2. Add `SettingsTab` import:
```typescript
import { SettingsTab } from './SettingsTab'
```

3. Add `'settings'` to the `TabId` union type:
```typescript
type TabId = 'ops' | 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch' | 'runbooks' | 'settings'
```

4. Add the Settings entry to the end of the `TABS` array:
```typescript
{ id: 'settings', label: 'Settings', Icon: Settings },
```

5. Add the Settings tab panel in the tab panels section (after the runbooks tab panel), following the same pattern:
```tsx
<div id="tabpanel-settings" role="tabpanel" aria-labelledby="tab-settings" hidden={activeTab !== 'settings'}>
  <SettingsTab />
</div>
```
</action>
<acceptance_criteria>
- `services/web-ui/components/DashboardPanel.tsx` contains `Settings` in the lucide-react import
- `services/web-ui/components/DashboardPanel.tsx` contains `import { SettingsTab } from './SettingsTab'`
- `services/web-ui/components/DashboardPanel.tsx` contains `'settings'` in the `TabId` union type
- `services/web-ui/components/DashboardPanel.tsx` contains `{ id: 'settings', label: 'Settings', Icon: Settings }`
- `services/web-ui/components/DashboardPanel.tsx` contains `tabpanel-settings`
- `services/web-ui/components/DashboardPanel.tsx` contains `<SettingsTab`
</acceptance_criteria>
</task>

<task id="51-4-05">
<title>Verify TypeScript compilation and build</title>
<read_first>
- services/web-ui/components/SettingsTab.tsx (from task 51-4-03)
- services/web-ui/components/DashboardPanel.tsx (from task 51-4-04)
</read_first>
<action>
Run the following verification commands from the `services/web-ui/` directory:

1. `npx tsc --noEmit` — must exit 0 with no TypeScript errors
2. `npm run build` — must exit 0 with no build errors

Fix any TypeScript compilation errors found:
- Missing imports
- Type mismatches in proxy route params (Next.js 15 uses `Promise<{ id: string }>` pattern)
- Missing type annotations

If `tsc --noEmit` fails, fix the errors in the relevant files (SettingsTab.tsx, proxy routes, DashboardPanel.tsx).
</action>
<acceptance_criteria>
- `cd services/web-ui && npx tsc --noEmit` exits 0
- `cd services/web-ui && npm run build` exits 0
</acceptance_criteria>
</task>

## Verification

After all tasks complete:
- `npx tsc --noEmit` from `services/web-ui/` — zero TypeScript errors
- `npm run build` from `services/web-ui/` — build succeeds
- `ls services/web-ui/components/ui/sheet.tsx services/web-ui/components/ui/switch.tsx` — both exist
- `grep -c "settings" services/web-ui/components/DashboardPanel.tsx` — returns ≥3 (TabId, TABS, tabpanel)

## must_haves
- [ ] shadcn/ui Sheet and Switch components scaffolded
- [ ] 4 proxy route files created for admin endpoints
- [ ] SettingsTab.tsx with policy list table, create/edit Sheet, and suggestion cards
- [ ] CSS semantic tokens used (never hardcoded Tailwind color classes)
- [ ] Dark-mode-safe badge backgrounds using `color-mix`
- [ ] Settings tab added to DashboardPanel as 13th tab
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npm run build` exits 0
