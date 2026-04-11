---
plan_id: "41-1"
phase: 41
wave: 1
title: "VMSS Full Stack — Types, Proxy Routes, VMSSTab, VMSSDetailPanel, DashboardPanel VMSS wiring, API gateway VMSS stubs"
goal: "Deliver the complete VMSS tab experience: shared azure-resources.ts types, 4 VMSS proxy routes, VMSSTab list view with InstanceCountBadge, VMSSDetailPanel with 5 tabs (Overview/Instances/Metrics/Scaling/AI Chat), DashboardPanel VMSS wiring, and 3 api-gateway VMSS stub endpoints."
---

# Plan 41-1: VMSS Full Stack

## Context

Phase 41 adds VMSS and AKS tabs to the web UI dashboard. This Wave 1 plan delivers the complete VMSS stack. Wave 2 (Plan 41-2) delivers AKS.

**Current DashboardPanel state:** 8 tabs — `alerts | audit | topology | resources | vms | cost | observability | patch`.

**Target after this plan:** 9 tabs — VMSS inserted after `vms`, before `cost`:
`alerts | audit | topology | resources | vms | vmss | cost | observability | patch`

**Pattern source files to read before every task:**
- `services/web-ui/components/VMTab.tsx` — list view pattern
- `services/web-ui/components/VMDetailPanel.tsx` — detail panel pattern
- `services/web-ui/app/api/proxy/vms/route.ts` — GET list proxy pattern
- `services/web-ui/app/api/proxy/vms/[vmId]/route.ts` — GET detail proxy pattern
- `services/web-ui/app/api/proxy/vms/[vmId]/metrics/route.ts` — GET metrics proxy pattern
- `services/web-ui/app/api/proxy/vms/[vmId]/chat/route.ts` — POST chat proxy pattern
- `services/api-gateway/vm_inventory.py` — API gateway module pattern (APIRouter + FastAPI)
- `services/api-gateway/main.py` — router include pattern

---

## Tasks

### Task 1: Create `services/web-ui/types/azure-resources.ts`

**Purpose:** Extract existing inline VM types and add new VMSS types. This is the single source of truth for all compute resource TypeScript interfaces.

<read_first>
- `services/web-ui/components/VMTab.tsx` lines 9–31 (VMRow, EolEntry interfaces)
- `services/web-ui/components/VMDetailPanel.tsx` lines 9–74 (VMDetail, ActiveIncident, Evidence, RecentChange, MetricAnomaly, MetricSeries, ChatMessage interfaces)
- `services/web-ui/types/sse.ts` (existing types file — confirm structure)
</read_first>

<action>
Create `services/web-ui/types/azure-resources.ts` with this exact content:

```typescript
// Shared resource type definitions for all compute resource tabs.
// VMTab, VMDetailPanel, VMSSTab, VMSSDetailPanel, AKSTab, AKSDetailPanel
// all import from here instead of defining types inline.

// ── VM Types (extracted from VMTab.tsx + VMDetailPanel.tsx) ──────────────────

export interface VMRow {
  id: string
  name: string
  resource_group: string
  subscription_id: string
  location: string
  size: string
  os_type: string
  os_name: string
  power_state: string
  vm_type: string  // "Azure VM" | "Arc VM"
  health_state: string
  ama_status: string
  active_alert_count: number
}

export interface EolEntry {
  os_name: string
  eol_date: string | null
  is_eol: boolean | null
  source: string | null
}

export interface ActiveIncident {
  incident_id: string
  severity: string
  title?: string
  created_at: string
  status: string
  investigation_status?: string
}

export interface VMDetail {
  id: string
  name: string
  resource_group: string
  subscription_id: string
  location: string
  size: string
  os_type: string
  os_name: string
  power_state: string
  health_state: string
  health_summary: string | null
  ama_status: string
  vm_type?: string
  tags: Record<string, string>
  active_incidents: ActiveIncident[]
}

export interface Evidence {
  pipeline_status: 'complete' | 'partial' | 'failed' | 'pending'
  collected_at: string | null
  evidence_summary: {
    health_state: string
    recent_changes: RecentChange[]
    metric_anomalies: MetricAnomaly[]
    log_errors: { count: number; sample: string[] }
  } | null
}

export interface RecentChange {
  timestamp: string
  operation: string
  caller: string
  status: string
}

export interface MetricAnomaly {
  metric_name: string
  current_value: number
  threshold: number
  unit: string
}

export interface MetricSeries {
  name: string | null
  unit: string | null
  timeseries: { timestamp: string; average: number | null; maximum: number | null }[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  approval_id?: string
}

// ── VMSS Types ────────────────────────────────────────────────────────────────

export interface VMSSRow {
  id: string                     // ARM resource ID
  name: string
  resource_group: string
  subscription_id: string
  location: string
  sku: string                    // e.g. "Standard_D4s_v3"
  instance_count: number         // total instances
  healthy_instance_count: number
  os_type: string                // "Windows" | "Linux"
  os_image_version: string       // e.g. "Ubuntu 22.04"
  power_state: string            // "running" | "stopped" | "deallocated"
  health_state: string           // "available" | "degraded" | "unavailable" | "unknown"
  autoscale_enabled: boolean
  active_alert_count: number
}

export interface VMSSDetail extends VMSSRow {
  min_count: number
  max_count: number
  upgrade_policy: string         // "Automatic" | "Manual" | "Rolling"
  active_incidents: ActiveIncident[]
  health_summary: string | null
  instances?: VMSSInstance[]
}

export interface VMSSInstance {
  instance_id: string
  name: string
  power_state: string
  health_state: string
  provisioning_state: string
}

// ── AKS Types (stubs — populated fully in Plan 41-2) ─────────────────────────

export interface AKSCluster {
  id: string                     // ARM resource ID
  name: string
  resource_group: string
  subscription_id: string
  location: string
  kubernetes_version: string     // e.g. "1.28.5"
  latest_available_version: string | null  // null if already current
  node_pool_count: number
  node_pools_ready: number
  total_nodes: number
  ready_nodes: number
  system_pod_health: 'healthy' | 'degraded' | 'unknown'
  fqdn: string | null
  network_plugin: string         // "azure" | "kubenet"
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
  min_count: number | null
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
</action>

<acceptance_criteria>
- `grep -r "export interface VMSSRow" services/web-ui/types/azure-resources.ts` → matches
- `grep -r "export interface AKSCluster" services/web-ui/types/azure-resources.ts` → matches
- `grep -r "export interface VMRow" services/web-ui/types/azure-resources.ts` → matches
- `grep -r "export interface ActiveIncident" services/web-ui/types/azure-resources.ts` → matches
- `grep -r "healthy_instance_count" services/web-ui/types/azure-resources.ts` → matches
</acceptance_criteria>

---

### Task 2: Update `VMTab.tsx` to import from `types/azure-resources.ts`

**Purpose:** Remove inline `VMRow` and `EolEntry` definitions and import from the shared types file.

<read_first>
- `services/web-ui/components/VMTab.tsx` (full file — lines 1–347)
- `services/web-ui/types/azure-resources.ts` (just created in Task 1)
</read_first>

<action>
In `services/web-ui/components/VMTab.tsx`:

1. Remove lines 9–31 (the `interface VMRow { ... }` and `interface EolEntry { ... }` inline definitions).

2. Add this import after line 7 (after the `gatewayTokenRequest` import):
```typescript
import type { VMRow, EolEntry } from '@/types/azure-resources'
```

Everything else in the file stays identical. The component logic, badge components, and `VMTab` function are unchanged.
</action>

<acceptance_criteria>
- `grep "interface VMRow" services/web-ui/components/VMTab.tsx` → NO match (removed)
- `grep "interface EolEntry" services/web-ui/components/VMTab.tsx` → NO match (removed)
- `grep "import type { VMRow, EolEntry } from '@/types/azure-resources'" services/web-ui/components/VMTab.tsx` → matches
- `npx tsc --noEmit` (from `services/web-ui/`) exits 0 after this change
</acceptance_criteria>

---

### Task 3: Update `VMDetailPanel.tsx` to import from `types/azure-resources.ts`

**Purpose:** Remove inline `VMDetail`, `ActiveIncident`, `Evidence`, `RecentChange`, `MetricAnomaly`, `MetricSeries`, `ChatMessage` interface definitions and import from the shared types file.

<read_first>
- `services/web-ui/components/VMDetailPanel.tsx` lines 1–80 (see the interface block at lines 9–74)
- `services/web-ui/types/azure-resources.ts` (just created in Task 1)
</read_first>

<action>
In `services/web-ui/components/VMDetailPanel.tsx`:

1. Remove the `// ── Types ──` section at lines 9–74 (all seven inline interface definitions: `VMDetail`, `ActiveIncident`, `Evidence`, `RecentChange`, `MetricAnomaly`, `MetricSeries`, `ChatMessage`).

2. Add this import after line 7 (after the `gatewayTokenRequest` import):
```typescript
import type {
  VMDetail,
  ActiveIncident,
  Evidence,
  RecentChange,
  MetricAnomaly,
  MetricSeries,
  ChatMessage,
} from '@/types/azure-resources'
```

All component logic, state, handlers, and JSX remain unchanged.
</action>

<acceptance_criteria>
- `grep "^interface VMDetail" services/web-ui/components/VMDetailPanel.tsx` → NO match (removed)
- `grep "^interface ActiveIncident" services/web-ui/components/VMDetailPanel.tsx` → NO match (removed)
- `grep "import type {" services/web-ui/components/VMDetailPanel.tsx` → matches (new import)
- `grep "from '@/types/azure-resources'" services/web-ui/components/VMDetailPanel.tsx` → matches
- `npx tsc --noEmit` exits 0 after this change
</acceptance_criteria>

---

### Task 4: Create VMSS proxy route — `app/api/proxy/vmss/route.ts`

**Purpose:** Proxy list endpoint — forwards `GET /api/proxy/vmss?subscriptions=...` to `GET /api/v1/vmss?subscriptions=...` on the API gateway.

<read_first>
- `services/web-ui/app/api/proxy/vms/route.ts` (exact pattern to replicate)
- `services/web-ui/lib/api-gateway.ts` (confirm `getApiGatewayUrl` and `buildUpstreamHeaders` signatures)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/vmss/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vmss' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/vmss
 *
 * Proxies VMSS inventory requests to the API gateway.
 * Returns an empty list gracefully when the backend endpoint is unavailable.
 *
 * Query params forwarded: subscriptions, search
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptions = searchParams.get('subscriptions') ?? '';
  const search = searchParams.get('search') ?? '';

  log.info('proxy request', { method: 'GET', subscriptions, search });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/vmss`);
    if (subscriptions) url.searchParams.set('subscriptions', subscriptions);
    if (search) url.searchParams.set('search', search);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      log.debug('vmss endpoint not ready, returning empty list', { status: res.status });
      return NextResponse.json({ vmss: [], total: 0 });
    }

    const data = await res.json();
    log.debug('vmss list response', { total: data?.total });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.debug('gateway unreachable, returning empty vmss list', { error: message });
    return NextResponse.json({ vmss: [], total: 0 });
  }
}
```
</action>

<acceptance_criteria>
- File exists: `services/web-ui/app/api/proxy/vmss/route.ts`
- `grep "export const runtime = 'nodejs'" services/web-ui/app/api/proxy/vmss/route.ts` → matches
- `grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/vmss/route.ts` → matches
- `grep "getApiGatewayUrl" services/web-ui/app/api/proxy/vmss/route.ts` → matches
- `grep "buildUpstreamHeaders" services/web-ui/app/api/proxy/vmss/route.ts` → matches
- `grep "vmss: \[\], total: 0" services/web-ui/app/api/proxy/vmss/route.ts` → matches (graceful fallback)
</acceptance_criteria>

---

### Task 5: Create VMSS proxy route — `app/api/proxy/vmss/[vmssId]/route.ts`

**Purpose:** Proxy detail endpoint — forwards `GET /api/proxy/vmss/[vmssId]` to `GET /api/v1/vmss/{vmssId}`.

<read_first>
- `services/web-ui/app/api/proxy/vms/[vmId]/route.ts` (exact pattern to replicate)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vmss/[vmssId]' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ vmssId: string }> }
): Promise<NextResponse> {
  const { vmssId } = await params;
  log.info('proxy request', { vmssId: vmssId.slice(0, 40) });

  try {
    const url = `${getApiGatewayUrl()}/api/v1/vmss/${encodeURIComponent(vmssId)}`;
    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url, {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
```
</action>

<acceptance_criteria>
- File exists: `services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts`
- `grep "const { vmssId } = await params" services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts` → matches
- `grep "params: Promise<{ vmssId: string }>" services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts` → matches
- `grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts` → matches
</acceptance_criteria>

---

### Task 6: Create VMSS proxy route — `app/api/proxy/vmss/[vmssId]/metrics/route.ts`

**Purpose:** Proxy metrics endpoint — forwards `GET /api/proxy/vmss/[vmssId]/metrics?timespan=...` to `GET /api/v1/vmss/{vmssId}/metrics?timespan=...`.

<read_first>
- `services/web-ui/app/api/proxy/vms/[vmId]/metrics/route.ts` (exact pattern to replicate)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vmss/[vmssId]/metrics' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ vmssId: string }> }
): Promise<NextResponse> {
  const { vmssId } = await params;
  const searchParams = req.nextUrl.searchParams;
  const timespan = searchParams.get('timespan') ?? 'PT24H';
  const interval = searchParams.get('interval') ?? 'PT5M';

  log.info('proxy request', { vmssId: vmssId.slice(0, 40), timespan });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/vmss/${encodeURIComponent(vmssId)}/metrics`);
    url.searchParams.set('timespan', timespan);
    url.searchParams.set('interval', interval);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(30000), // metrics can be slow
    });

    if (!res.ok) {
      log.warn('metrics fetch failed', { status: res.status });
      return NextResponse.json({ resource_id: '', timespan, interval, metrics: [] });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.warn('metrics unavailable', { error: message });
    return NextResponse.json({ resource_id: '', timespan, interval, metrics: [] });
  }
}
```
</action>

<acceptance_criteria>
- File exists: `services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts`
- `grep "const { vmssId } = await params" services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts` → matches
- `grep "AbortSignal.timeout(30000)" services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts` → matches
- `grep "metrics: \[\]" services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts` → matches (graceful fallback)
</acceptance_criteria>

---

### Task 7: Create VMSS proxy route — `app/api/proxy/vmss/[vmssId]/chat/route.ts`

**Purpose:** Proxy chat endpoint — forwards `POST /api/proxy/vmss/[vmssId]/chat` to `POST /api/v1/vmss/{vmssId}/chat`.

<read_first>
- `services/web-ui/app/api/proxy/vms/[vmId]/chat/route.ts` (exact pattern to replicate)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vmss/[vmssId]/chat' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ vmssId: string }> }
): Promise<NextResponse> {
  const { vmssId } = await params;
  log.info('proxy request', { vmssId: vmssId.slice(0, 40) });

  try {
    const url = `${getApiGatewayUrl()}/api/v1/vmss/${encodeURIComponent(vmssId)}/chat`;
    const body = await req.json();
    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url, {
      method: 'POST',
      headers: { ...upstreamHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
```
</action>

<acceptance_criteria>
- File exists: `services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts`
- `grep "export async function POST" services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts` → matches
- `grep "'Content-Type': 'application/json'" services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts` → matches
- `grep "AbortSignal.timeout(30000)" services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts` → matches
</acceptance_criteria>

---

### Task 8: Create `services/web-ui/components/VMSSTab.tsx`

**Purpose:** VMSS list view component. Follows the VMTab pattern exactly — skeleton loading, search bar, sortable table with badge components, row click → detail panel.

<read_first>
- `services/web-ui/components/VMTab.tsx` (full file — copy structure exactly)
- `services/web-ui/types/azure-resources.ts` (VMSSRow type)
</read_first>

<action>
Create `services/web-ui/components/VMSSTab.tsx`:

```typescript
'use client'

import { useState, useEffect, useCallback } from 'react'
import { Scaling, RefreshCw } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type { VMSSRow } from '@/types/azure-resources'

interface VMSSTabProps {
  subscriptions: string[]
  onVMSSClick?: (resourceId: string, resourceName: string) => void
}

function InstanceCountBadge({ total, healthy }: { total: number; healthy: number }) {
  const unhealthy = total - healthy
  const ratio = total > 0 ? unhealthy / total : 0
  let color: string
  if (unhealthy === 0) {
    color = 'var(--accent-green)'
  } else if (ratio > 0.2) {
    color = 'var(--accent-red)'
  } else {
    color = 'var(--accent-yellow)'
  }
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {healthy}/{total}
    </span>
  )
}

function PowerStateBadge({ state }: { state: string }) {
  const config = {
    running: { label: 'Running', color: 'var(--accent-green)' },
    stopped: { label: 'Stopped', color: 'var(--accent-yellow)' },
    deallocated: { label: 'Deallocated', color: 'var(--text-muted)' },
  }[state.toLowerCase()] ?? { label: state, color: 'var(--text-muted)' }
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${config.color} 15%, transparent)`,
        color: config.color,
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: config.color }} />
      {config.label}
    </span>
  )
}

function HealthBadge({ state }: { state: string }) {
  const config = {
    available: { label: 'Healthy', color: 'var(--accent-green)' },
    degraded: { label: 'Degraded', color: 'var(--accent-orange)' },
    unavailable: { label: 'Unavailable', color: 'var(--accent-red)' },
    unknown: { label: 'Unknown', color: 'var(--text-muted)' },
  }[state.toLowerCase()] ?? { label: state, color: 'var(--text-muted)' }
  return (
    <span className="text-[11px] font-medium" style={{ color: config.color }}>
      {config.label}
    </span>
  )
}

export function VMSSTab({ subscriptions, onVMSSClick }: VMSSTabProps) {
  const { instance, accounts } = useMsal()
  const [vmssList, setVMSSList] = useState<VMSSRow[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const account = accounts[0]
    if (!account) return null
    try {
      const result = await instance.acquireTokenSilent({ ...gatewayTokenRequest, account })
      return result.accessToken
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ ...gatewayTokenRequest, account })
      }
      return null
    }
  }, [instance, accounts])

  async function fetchVMSS() {
    if (subscriptions.length === 0) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ subscriptions: subscriptions.join(',') })
      if (search) params.set('search', search)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vmss?${params}`, { headers })
      const data = await res.json()
      setVMSSList(data.vmss ?? [])
    } catch {
      setError('Failed to load scale sets')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchVMSS() }, [subscriptions]) // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = vmssList.filter(vmss =>
    !search || vmss.name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div>
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Virtual Machine Scale Sets
          </span>
          {!loading && (
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}
            >
              {filtered.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Search scale sets…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-md outline-none"
            style={{
              background: 'var(--bg-canvas)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              width: '200px',
            }}
          />
          <button
            onClick={fetchVMSS}
            disabled={loading}
            className="p-1.5 rounded cursor-pointer transition-colors"
            style={{ color: 'var(--text-secondary)' }}
            title="Refresh VMSS list"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Content */}
      {error ? (
        <div className="p-8 text-center text-sm" style={{ color: 'var(--accent-red)' }}>
          {error}
        </div>
      ) : loading ? (
        <div className="p-8">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="flex gap-4 mb-3 animate-pulse">
              <div className="h-4 rounded flex-1" style={{ background: 'var(--bg-subtle)' }} />
              <div className="h-4 rounded w-24" style={{ background: 'var(--bg-subtle)' }} />
              <div className="h-4 rounded w-20" style={{ background: 'var(--bg-subtle)' }} />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="p-12 text-center">
          <Scaling className="h-8 w-8 mx-auto mb-3" style={{ color: 'var(--text-muted)' }} />
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {subscriptions.length === 0
              ? 'Select a subscription to view scale sets'
              : 'No scale sets found in selected subscriptions'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Name', 'Resource Group', 'SKU', 'Instances', 'Power State', 'Health', 'Alerts'].map(col => (
                  <th
                    key={col}
                    className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wide"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(vmss => (
                <tr
                  key={vmss.id}
                  className="cursor-pointer transition-colors"
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-subtle)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                  onClick={() => onVMSSClick?.(vmss.id, vmss.name)}
                >
                  <td className="px-4 py-3 font-mono text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                    {vmss.name}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {vmss.resource_group}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {vmss.sku || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <InstanceCountBadge total={vmss.instance_count} healthy={vmss.healthy_instance_count} />
                  </td>
                  <td className="px-4 py-3">
                    <PowerStateBadge state={vmss.power_state} />
                  </td>
                  <td className="px-4 py-3">
                    <HealthBadge state={vmss.health_state} />
                  </td>
                  <td className="px-4 py-3">
                    {vmss.active_alert_count > 0 ? (
                      <span
                        className="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold"
                        style={{
                          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                          color: 'var(--accent-red)',
                        }}
                      >
                        {vmss.active_alert_count}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```
</action>

<acceptance_criteria>
- File exists: `services/web-ui/components/VMSSTab.tsx`
- `grep "color-mix(in srgb, var(--accent-green) 15%, transparent)" services/web-ui/components/VMSSTab.tsx` → matches (NOT hardcoded Tailwind colors)
- `grep "bg-green-100\|text-green-700\|bg-red-100\|text-red-700" services/web-ui/components/VMSSTab.tsx` → NO match
- `grep "InstanceCountBadge" services/web-ui/components/VMSSTab.tsx` → matches (badge defined and used)
- `grep "onVMSSClick\?.(vmss.id, vmss.name)" services/web-ui/components/VMSSTab.tsx` → matches
- `grep "animate-pulse" services/web-ui/components/VMSSTab.tsx` → matches (skeleton loading)
- `grep "export function VMSSTab" services/web-ui/components/VMSSTab.tsx` → matches
</acceptance_criteria>

---

### Task 9: Create `services/web-ui/components/VMSSDetailPanel.tsx`

**Purpose:** Tabbed VMSS detail panel — 5 tabs: Overview, Instances, Metrics, Scaling, AI Chat. Follows VMDetailPanel pattern with drag-to-resize handle.

<read_first>
- `services/web-ui/components/VMDetailPanel.tsx` (full file — read ALL of it for panel structure, resize handle, chat pattern)
- `services/web-ui/types/azure-resources.ts` (VMSSDetail, VMSSInstance, ActiveIncident types)
</read_first>

<action>
Create `services/web-ui/components/VMSSDetailPanel.tsx`:

Key implementation requirements:
1. **Resize handle:** Same drag-to-resize as VMDetailPanel. Use `localStorage.getItem('vmssDetailPanelWidth')` as key. Constants: `PANEL_MIN_WIDTH = 380`, `PANEL_MAX_WIDTH = 1200`, `PANEL_DEFAULT_WIDTH = 520`.
2. **5 internal tabs:** `'overview' | 'instances' | 'metrics' | 'scaling' | 'chat'`
3. **Chat pattern:** Auto-fires when Chat tab opens. `POST /api/proxy/vmss/[vmssId]/chat` with `{ message: "Summarize this scale set's health and suggest investigation steps.", thread_id: null }`. Polls `GET /api/proxy/chat/result?thread_id=...&run_id=...` every 2s. `useEffect([resourceId])` resets on resource change.
4. **CSS tokens only** — no hardcoded Tailwind colors.
5. **Badge pattern** — `color-mix(in srgb, var(--accent-*) 15%, transparent)` for all badge backgrounds.

```typescript
'use client'

import { useState, useEffect, useCallback, useRef, MouseEvent as ReactMouseEvent } from 'react'
import { X, RefreshCw, Activity } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type { VMSSDetail, VMSSInstance, ActiveIncident, MetricSeries, ChatMessage } from '@/types/azure-resources'

// ── Constants ────────────────────────────────────────────────────────────────

const PANEL_MIN_WIDTH = 380
const PANEL_MAX_WIDTH = 1200
const PANEL_DEFAULT_WIDTH = 520

type DetailTab = 'overview' | 'instances' | 'metrics' | 'scaling' | 'chat'

interface VMSSDetailPanelProps {
  resourceId: string
  resourceName: string
  onClose: () => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function encodeResourceId(resourceId: string): string {
  return btoa(resourceId).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

function SeverityBadge({ severity }: { severity: string }) {
  const config: Record<string, { label: string; color: string }> = {
    sev0: { label: 'Sev 0', color: 'var(--accent-red)' },
    sev1: { label: 'Sev 1', color: 'var(--accent-red)' },
    sev2: { label: 'Sev 2', color: 'var(--accent-orange)' },
    sev3: { label: 'Sev 3', color: 'var(--accent-yellow)' },
    sev4: { label: 'Sev 4', color: 'var(--text-muted)' },
  }
  const c = config[severity.toLowerCase()] ?? { label: severity, color: 'var(--text-muted)' }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold"
      style={{
        background: `color-mix(in srgb, ${c.color} 15%, transparent)`,
        color: c.color,
      }}
    >
      {c.label}
    </span>
  )
}

function HealthStateBadge({ state }: { state: string }) {
  const config: Record<string, { label: string; color: string }> = {
    available: { label: 'Healthy', color: 'var(--accent-green)' },
    degraded: { label: 'Degraded', color: 'var(--accent-orange)' },
    unavailable: { label: 'Unavailable', color: 'var(--accent-red)' },
    unknown: { label: 'Unknown', color: 'var(--text-muted)' },
    running: { label: 'Running', color: 'var(--accent-green)' },
    stopped: { label: 'Stopped', color: 'var(--accent-yellow)' },
  }
  const c = config[state.toLowerCase()] ?? { label: state, color: 'var(--text-muted)' }
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${c.color} 15%, transparent)`,
        color: c.color,
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: c.color }} />
      {c.label}
    </span>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function VMSSDetailPanel({ resourceId, resourceName, onClose }: VMSSDetailPanelProps) {
  const { instance, accounts } = useMsal()
  const [activeTab, setActiveTab] = useState<DetailTab>('overview')
  const [detail, setDetail] = useState<VMSSDetail | null>(null)
  const [metrics, setMetrics] = useState<MetricSeries[]>([])
  const [metricsTimespan, setMetricsTimespan] = useState('PT24H')
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [instanceSearch, setInstanceSearch] = useState('')

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [chatThreadId, setChatThreadId] = useState<string | null>(null)
  const chatAutoFired = useRef(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Resize state
  const [panelWidth, setPanelWidth] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('vmssDetailPanelWidth')
      if (stored) return Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, parseInt(stored, 10)))
    }
    return PANEL_DEFAULT_WIDTH
  })
  const dragging = useRef(false)
  const dragStartX = useRef(0)
  const dragStartWidth = useRef(PANEL_DEFAULT_WIDTH)

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const account = accounts[0]
    if (!account) return null
    try {
      const result = await instance.acquireTokenSilent({ ...gatewayTokenRequest, account })
      return result.accessToken
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ ...gatewayTokenRequest, account })
      }
      return null
    }
  }, [instance, accounts])

  // Fetch detail data
  async function fetchDetail() {
    if (!resourceId) return
    setLoadingDetail(true)
    setError(null)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vmss/${encoded}`, { headers })
      if (!res.ok) throw new Error(`Status ${res.status}`)
      const data = await res.json()
      setDetail(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(`Failed to load scale set details: ${msg}`)
    } finally {
      setLoadingDetail(false)
    }
  }

  // Fetch metrics
  async function fetchMetrics(timespan: string) {
    if (!resourceId) return
    setLoadingMetrics(true)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const url = `/api/proxy/vmss/${encoded}/metrics?timespan=${timespan}`
      const res = await fetch(url, { headers })
      if (res.ok) {
        const data = await res.json()
        setMetrics(data.metrics ?? [])
      }
    } catch {
      // Non-fatal — metrics chart shows empty state
    } finally {
      setLoadingMetrics(false)
    }
  }

  // Chat: send message
  async function sendChatMessage(message: string) {
    if (!message.trim() || chatLoading) return
    setChatLoading(true)
    setChatMessages(prev => [...prev, { role: 'user', content: message }])
    setChatInput('')
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vmss/${encoded}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message, thread_id: chatThreadId }),
      })
      if (!res.ok) throw new Error(`Status ${res.status}`)
      const { thread_id, run_id } = await res.json()
      if (thread_id) setChatThreadId(thread_id)
      // Poll for result
      await pollChatResult(thread_id, run_id, token)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setChatMessages(prev => [...prev, { role: 'assistant', content: `Error: ${msg}` }])
    } finally {
      setChatLoading(false)
    }
  }

  async function pollChatResult(threadId: string, runId: string, token: string | null) {
    const TERMINAL = ['completed', 'failed', 'cancelled', 'expired']
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/chat/result?thread_id=${threadId}&run_id=${runId}`, { headers })
      if (!res.ok) continue
      const data = await res.json()
      if (TERMINAL.includes(data.status)) {
        if (data.response) {
          setChatMessages(prev => [...prev, { role: 'assistant', content: data.response }])
        }
        return
      }
    }
  }

  // Reset when resource changes
  useEffect(() => {
    setChatMessages([])
    setChatThreadId(null)
    chatAutoFired.current = false
    setActiveTab('overview')
    fetchDetail()
  }, [resourceId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-fire chat on first open of Chat tab
  useEffect(() => {
    if (activeTab === 'chat' && !chatAutoFired.current && !chatLoading) {
      chatAutoFired.current = true
      sendChatMessage("Summarize this scale set's health and suggest investigation steps.")
    }
    if (activeTab === 'metrics') {
      fetchMetrics(metricsTimespan)
    }
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeTab === 'metrics') fetchMetrics(metricsTimespan)
  }, [metricsTimespan]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll chat to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  // Drag resize handlers
  function onDragStart(e: ReactMouseEvent) {
    dragging.current = true
    dragStartX.current = e.clientX
    dragStartWidth.current = panelWidth
    document.addEventListener('mousemove', onDragMove)
    document.addEventListener('mouseup', onDragEnd)
    e.preventDefault()
  }
  function onDragMove(e: MouseEvent) {
    if (!dragging.current) return
    const delta = dragStartX.current - e.clientX
    const newWidth = Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, dragStartWidth.current + delta))
    setPanelWidth(newWidth)
  }
  function onDragEnd() {
    dragging.current = false
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragEnd)
    localStorage.setItem('vmssDetailPanelWidth', String(panelWidth))
  }

  const DETAIL_TABS: { id: DetailTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'instances', label: 'Instances' },
    { id: 'metrics', label: 'Metrics' },
    { id: 'scaling', label: 'Scaling' },
    { id: 'chat', label: 'AI Chat' },
  ]

  const filteredInstances = (detail?.instances ?? []).filter(inst =>
    !instanceSearch || inst.instance_id.includes(instanceSearch) || inst.name.toLowerCase().includes(instanceSearch.toLowerCase())
  )

  return (
    <div
      className="fixed top-0 right-0 h-full z-40 flex flex-col overflow-hidden"
      style={{
        width: `${panelWidth}px`,
        background: 'var(--bg-surface)',
        borderLeft: '1px solid var(--border)',
        boxShadow: '-4px 0 24px rgba(0,0,0,0.12)',
      }}
    >
      {/* Drag resize handle */}
      <div
        className="absolute top-0 left-0 h-full w-1.5 cursor-col-resize z-50 transition-colors" style={{ backgroundColor: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)' }}
        onMouseDown={onDragStart}
        title="Drag to resize"
      />

      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 flex-shrink-0"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
            {resourceName}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchDetail}
            disabled={loadingDetail}
            className="p-1.5 rounded cursor-pointer"
            style={{ color: 'var(--text-secondary)' }}
            title="Refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loadingDetail ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded cursor-pointer"
            style={{ color: 'var(--text-secondary)' }}
            title="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Detail tabs */}
      <div
        className="flex items-end flex-shrink-0 px-4"
        style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)' }}
      >
        {DETAIL_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="px-3 py-2 text-[12px] font-medium transition-colors cursor-pointer"
            style={{
              color: activeTab === tab.id ? 'var(--text-primary)' : 'var(--text-secondary)',
              borderBottom: activeTab === tab.id ? '2px solid var(--accent-blue)' : '2px solid transparent',
              marginBottom: '-1px',
              background: 'transparent',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="p-4 text-sm" style={{ color: 'var(--accent-red)' }}>{error}</div>
        )}

        {/* Overview tab */}
        {activeTab === 'overview' && (
          <div className="p-4 space-y-4">
            {loadingDetail ? (
              <div className="space-y-3 animate-pulse">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-16 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : detail ? (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: 'Healthy Instances', value: String(detail.healthy_instance_count), color: 'var(--accent-green)' },
                    { label: 'Total Instances', value: String(detail.instance_count), color: 'var(--text-primary)' },
                    { label: 'Active Alerts', value: String(detail.active_alert_count), color: detail.active_alert_count > 0 ? 'var(--accent-red)' : 'var(--text-muted)' },
                    { label: 'Autoscale', value: detail.autoscale_enabled ? 'Enabled' : 'Disabled', color: detail.autoscale_enabled ? 'var(--accent-green)' : 'var(--text-muted)' },
                  ].map(card => (
                    <div
                      key={card.label}
                      className="p-3 rounded-lg"
                      style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                    >
                      <p className="text-[11px] uppercase tracking-wide mb-1" style={{ color: 'var(--text-muted)' }}>
                        {card.label}
                      </p>
                      <p className="text-lg font-semibold" style={{ color: card.color }}>
                        {card.value}
                      </p>
                    </div>
                  ))}
                </div>

                {/* Metadata */}
                <div
                  className="rounded-lg p-3"
                  style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                >
                  <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                    Configuration
                  </p>
                  {[
                    ['SKU', detail.sku || '—'],
                    ['Location', detail.location],
                    ['OS Image', detail.os_image_version || '—'],
                    ['Upgrade Policy', detail.upgrade_policy || '—'],
                    ['Scale Range', `${detail.min_count} – ${detail.max_count}`],
                    ['Health State', detail.health_state],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1 text-xs" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>{k}</span>
                      <span style={{ color: 'var(--text-primary)' }}>{v}</span>
                    </div>
                  ))}
                </div>

                {/* Active incidents */}
                {detail.active_incidents?.length > 0 && (
                  <div
                    className="rounded-lg p-3"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                      Active Incidents
                    </p>
                    {detail.active_incidents.map((inc: ActiveIncident) => (
                      <div key={inc.incident_id} className="flex items-center justify-between py-1.5 text-xs" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <span className="font-mono" style={{ color: 'var(--text-primary)' }}>
                          {inc.title ?? inc.incident_id}
                        </span>
                        <SeverityBadge severity={inc.severity} />
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : null}
          </div>
        )}

        {/* Instances tab */}
        {activeTab === 'instances' && (
          <div className="p-4">
            <div className="mb-3">
              <input
                type="text"
                placeholder="Search instances…"
                value={instanceSearch}
                onChange={(e) => setInstanceSearch(e.target.value)}
                className="text-xs px-3 py-1.5 rounded-md outline-none w-full"
                style={{
                  background: 'var(--bg-canvas)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>
            {loadingDetail ? (
              <div className="animate-pulse space-y-2">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-10 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : filteredInstances.length === 0 ? (
              <p className="text-sm text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                No instance data available
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Instance', 'Power State', 'Health', 'Provisioning'].map(col => (
                      <th key={col} className="text-left px-2 py-2 text-[11px] uppercase tracking-wide font-semibold" style={{ color: 'var(--text-muted)' }}>
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredInstances.map((inst: VMSSInstance) => (
                    <tr
                      key={inst.instance_id}
                      style={{ borderBottom: '1px solid var(--border-subtle)' }}
                    >
                      <td className="px-2 py-2 font-mono" style={{ color: 'var(--text-primary)' }}>
                        {inst.name || inst.instance_id}
                      </td>
                      <td className="px-2 py-2">
                        <HealthStateBadge state={inst.power_state} />
                      </td>
                      <td className="px-2 py-2">
                        <HealthStateBadge state={inst.health_state} />
                      </td>
                      <td className="px-2 py-2" style={{ color: 'var(--text-secondary)' }}>
                        {inst.provisioning_state}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Metrics tab */}
        {activeTab === 'metrics' && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>Azure Monitor Metrics</p>
              <select
                value={metricsTimespan}
                onChange={(e) => setMetricsTimespan(e.target.value)}
                className="text-xs px-2 py-1 rounded outline-none"
                style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
              >
                <option value="PT1H">Last 1h</option>
                <option value="PT6H">Last 6h</option>
                <option value="PT24H">Last 24h</option>
                <option value="P7D">Last 7d</option>
              </select>
            </div>
            {loadingMetrics ? (
              <div className="animate-pulse space-y-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-24 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : metrics.length === 0 ? (
              <div className="py-8 text-center">
                <Activity className="h-8 w-8 mx-auto mb-2" style={{ color: 'var(--text-muted)' }} />
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                  No metrics available
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {metrics.map((m, i) => (
                  <div
                    key={i}
                    className="p-3 rounded-lg"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                      {m.name ?? 'Metric'} {m.unit ? `(${m.unit})` : ''}
                    </p>
                    <p className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                      {m.timeseries?.length ?? 0} data points
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Scaling tab */}
        {activeTab === 'scaling' && (
          <div className="p-4">
            {loadingDetail ? (
              <div className="animate-pulse space-y-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-16 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : detail ? (
              <div className="space-y-4">
                <div
                  className="p-3 rounded-lg"
                  style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                >
                  <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                    Autoscale Configuration
                  </p>
                  {[
                    ['Autoscale Enabled', detail.autoscale_enabled ? 'Yes' : 'No'],
                    ['Min Instances', String(detail.min_count)],
                    ['Max Instances', String(detail.max_count)],
                    ['Current Instances', String(detail.instance_count)],
                    ['Upgrade Policy', detail.upgrade_policy || '—'],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1 text-xs" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>{k}</span>
                      <span style={{ color: 'var(--text-primary)' }}>{v}</span>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>
                  Use AI Chat to propose scale adjustments via the HITL approval workflow.
                </p>
              </div>
            ) : (
              <p className="text-sm text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                Loading scale set configuration…
              </p>
            )}
          </div>
        )}

        {/* Chat tab */}
        {activeTab === 'chat' && (
          <div className="flex flex-col h-full">
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {chatMessages.map((msg, i) => (
                <div
                  key={i}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className="max-w-[85%] px-3 py-2 rounded-lg text-sm"
                    style={{
                      background: msg.role === 'user'
                        ? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)'
                        : 'var(--bg-canvas)',
                      color: 'var(--text-primary)',
                      border: msg.role === 'assistant' ? '1px solid var(--border)' : 'none',
                    }}
                  >
                    <p className="whitespace-pre-wrap text-xs leading-relaxed">{msg.content}</p>
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div className="flex justify-start">
                  <div
                    className="px-3 py-2 rounded-lg"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <div className="flex gap-1 items-center">
                      <div className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '0ms' }} />
                      <div className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '150ms' }} />
                      <div className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '300ms' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
            <div
              className="flex gap-2 p-3 flex-shrink-0"
              style={{ borderTop: '1px solid var(--border)' }}
            >
              <input
                type="text"
                placeholder="Ask about this scale set…"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(chatInput) } }}
                disabled={chatLoading}
                className="flex-1 text-xs px-3 py-2 rounded-md outline-none"
                style={{
                  background: 'var(--bg-canvas)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                }}
              />
              <button
                onClick={() => sendChatMessage(chatInput)}
                disabled={chatLoading || !chatInput.trim()}
                className="px-3 py-2 rounded-md text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
                style={{
                  background: 'var(--accent-blue)',
                  color: '#fff',
                }}
              >
                Send
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
```
</action>

<acceptance_criteria>
- File exists: `services/web-ui/components/VMSSDetailPanel.tsx`
- `grep "export function VMSSDetailPanel" services/web-ui/components/VMSSDetailPanel.tsx` → matches
- `grep "vmssDetailPanelWidth" services/web-ui/components/VMSSDetailPanel.tsx` → matches (localStorage key)
- `grep "PANEL_DEFAULT_WIDTH = 520" services/web-ui/components/VMSSDetailPanel.tsx` → matches
- `grep "Summarize this scale set's health" services/web-ui/components/VMSSDetailPanel.tsx` → matches (auto-fire message)
- `grep "color-mix(in srgb" services/web-ui/components/VMSSDetailPanel.tsx` → matches (CSS token pattern)
- `grep "bg-green-100\|text-green-700\|bg-red-100" services/web-ui/components/VMSSDetailPanel.tsx` → NO match
- `grep "type DetailTab = 'overview' | 'instances' | 'metrics' | 'scaling' | 'chat'" services/web-ui/components/VMSSDetailPanel.tsx` → matches
- `grep "onDragStart\|onDragMove\|onDragEnd" services/web-ui/components/VMSSDetailPanel.tsx` → matches (resize handlers)
</acceptance_criteria>

---

### Task 10: Create `services/api-gateway/vmss_endpoints.py`

**Purpose:** Minimal FastAPI router providing 3 VMSS stub endpoints that the proxy routes call. Returns structured empty responses with the correct shape when Azure SDK unavailable. Follows the lazy-import + try/except pattern from `vm_inventory.py`.

<read_first>
- `services/api-gateway/vm_inventory.py` lines 1–60 (APIRouter pattern, lazy imports, `from __future__ import annotations`)
- `services/api-gateway/vm_chat.py` lines 1–60 (chat endpoint pattern)
- `services/api-gateway/main.py` lines 97–120 (how routers are imported and included)
</read_first>

<action>
Create `services/api-gateway/vmss_endpoints.py`:

```python
"""VMSS inventory and chat endpoints.

GET  /api/v1/vmss                          — list VMSS in subscriptions via ARG
GET  /api/v1/vmss/{resource_id_base64}     — VMSS detail including instances
GET  /api/v1/vmss/{resource_id_base64}/metrics — Azure Monitor metrics
POST /api/v1/vmss/{resource_id_base64}/chat    — resource-scoped chat

When the Azure SDK packages are unavailable, all list endpoints return empty
structured responses matching the shape the frontend expects.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from services.api_gateway.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vmss", tags=["vmss"])

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]
    _ARG_AVAILABLE = True
except ImportError:
    _ARG_AVAILABLE = False
    logger.warning("azure-mgmt-resourcegraph not available — VMSS list returns empty")


def _log_sdk_availability() -> None:
    logger.info("vmss_endpoints: azure-mgmt-resourcegraph available=%s", _ARG_AVAILABLE)


_log_sdk_availability()


def _decode_resource_id(encoded: str) -> str:
    """Decode base64url-encoded ARM resource ID."""
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    try:
        return base64.urlsafe_b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Invalid resource ID encoding: {exc}") from exc


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from ARM resource ID."""
    parts = resource_id.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "subscriptions" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class VMSSChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None


class VMSSChatResponse(BaseModel):
    thread_id: str
    run_id: str
    status: str = "created"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_vmss(
    subscriptions: str = Query(..., description="Comma-separated subscription IDs"),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """List VMSS across subscriptions via Azure Resource Graph.

    Returns structured empty response when ARG SDK unavailable.
    """
    start_time = time.monotonic()
    subscription_ids = [s.strip() for s in subscriptions.split(",") if s.strip()]

    if not _ARG_AVAILABLE or not subscription_ids:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_list: sdk_unavailable duration_ms=%.1f", duration_ms)
        return {"vmss": [], "total": 0}

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        credential = DefaultAzureCredential()
        client = ResourceGraphClient(credential)

        kql = """Resources
| where type =~ 'microsoft.compute/virtualmachinescalesets'
| extend instanceCount = toint(properties.singlePlacementGroup == false
    ? properties.uniqueId
    : properties.provisioningState)
| project id, name, resourceGroup, subscriptionId, location,
    sku = tostring(sku.name),
    instance_count = toint(properties.sku.capacity),
    os_type = tostring(properties.virtualMachineProfile.storageProfile.osDisk.osType),
    os_image_version = strcat(
        tostring(properties.virtualMachineProfile.storageProfile.imageReference.offer),
        ' ',
        tostring(properties.virtualMachineProfile.storageProfile.imageReference.sku)
    ),
    power_state = 'running',
    health_state = 'unknown',
    autoscale_enabled = false,
    active_alert_count = 0"""

        if search:
            search_safe = search.replace("'", "")
            kql += f"\n| where name contains '{search_safe}'"

        kql += f"\n| limit {limit}"

        request = QueryRequest(subscriptions=subscription_ids, query=kql)
        response = client.resources(request)
        rows = response.data or []

        vmss_list = [
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "resource_group": r.get("resourceGroup", ""),
                "subscription_id": r.get("subscriptionId", ""),
                "location": r.get("location", ""),
                "sku": r.get("sku", ""),
                "instance_count": r.get("instance_count", 0),
                "healthy_instance_count": r.get("instance_count", 0),
                "os_type": r.get("os_type", ""),
                "os_image_version": (r.get("os_image_version") or "").strip(),
                "power_state": r.get("power_state", "running"),
                "health_state": r.get("health_state", "unknown"),
                "autoscale_enabled": r.get("autoscale_enabled", False),
                "active_alert_count": r.get("active_alert_count", 0),
            }
            for r in rows
        ]

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_list: total=%d duration_ms=%.1f", len(vmss_list), duration_ms)
        return {"vmss": vmss_list, "total": len(vmss_list)}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("vmss_list: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"vmss": [], "total": 0}


@router.get("/{resource_id_base64}")
async def get_vmss_detail(
    resource_id_base64: str,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get VMSS detail including instances and autoscale config.

    Returns structured stub when SDK unavailable.
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    if not _ARG_AVAILABLE:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_detail: sdk_unavailable resource_id=%s duration_ms=%.1f", resource_id[:60], duration_ms)
        return {
            "id": resource_id,
            "name": resource_id.split("/")[-1],
            "resource_group": "",
            "subscription_id": _extract_subscription_id(resource_id),
            "location": "",
            "sku": "",
            "instance_count": 0,
            "healthy_instance_count": 0,
            "os_type": "",
            "os_image_version": "",
            "power_state": "unknown",
            "health_state": "unknown",
            "autoscale_enabled": False,
            "active_alert_count": 0,
            "min_count": 0,
            "max_count": 0,
            "upgrade_policy": "",
            "health_summary": None,
            "active_incidents": [],
            "instances": [],
        }

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.compute import ComputeManagementClient  # type: ignore[import]
        credential = DefaultAzureCredential()
        subscription_id = _extract_subscription_id(resource_id)
        parts = resource_id.split("/")
        rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
        resource_group = parts[rg_index + 1] if rg_index >= 0 else ""
        vmss_name = parts[-1]

        compute_client = ComputeManagementClient(credential, subscription_id)
        vmss = compute_client.virtual_machine_scale_sets.get(resource_group, vmss_name)
        instances_paged = compute_client.virtual_machine_scale_set_vms.list(resource_group, vmss_name)
        instances = [
            {
                "instance_id": inst.instance_id or "",
                "name": inst.name or "",
                "power_state": (inst.instance_view.statuses[-1].display_status if inst.instance_view and inst.instance_view.statuses else "unknown"),
                "health_state": "unknown",
                "provisioning_state": inst.provisioning_state or "unknown",
            }
            for inst in instances_paged
        ]

        autoscale_settings: Dict[str, Any] = {"min_count": 1, "max_count": 10}
        try:
            from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import]
            monitor_client = MonitorManagementClient(credential, subscription_id)
            settings = list(monitor_client.autoscale_settings.list_by_resource_group(resource_group))
            for s in settings:
                if resource_id.lower() in (s.target_resource_uri or "").lower():
                    profile = s.profiles[0] if s.profiles else None
                    if profile:
                        autoscale_settings["min_count"] = int(profile.capacity.minimum or 1)
                        autoscale_settings["max_count"] = int(profile.capacity.maximum or 10)
                    autoscale_settings["enabled"] = True
                    break
        except Exception:
            pass

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_detail: resource_id=%s instances=%d duration_ms=%.1f", resource_id[:60], len(instances), duration_ms)
        return {
            "id": resource_id,
            "name": vmss.name or vmss_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "location": vmss.location or "",
            "sku": vmss.sku.name if vmss.sku else "",
            "instance_count": int(vmss.sku.capacity or 0) if vmss.sku else 0,
            "healthy_instance_count": int(vmss.sku.capacity or 0) if vmss.sku else 0,
            "os_type": "",
            "os_image_version": "",
            "power_state": "running",
            "health_state": "unknown",
            "autoscale_enabled": autoscale_settings.get("enabled", False),
            "active_alert_count": 0,
            "min_count": autoscale_settings["min_count"],
            "max_count": autoscale_settings["max_count"],
            "upgrade_policy": (vmss.upgrade_policy.mode.value if vmss.upgrade_policy and vmss.upgrade_policy.mode else ""),
            "health_summary": None,
            "active_incidents": [],
            "instances": instances,
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("vmss_detail: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"error": str(exc)}


@router.get("/{resource_id_base64}/metrics")
async def get_vmss_metrics(
    resource_id_base64: str,
    timespan: str = Query("PT24H"),
    interval: str = Query("PT5M"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get Azure Monitor metrics for a VMSS."""
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"resource_id": "", "timespan": timespan, "interval": interval, "metrics": []}

    # Return empty metrics stub — real metrics implementation deferred to Phase 36
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("vmss_metrics: resource_id=%s timespan=%s duration_ms=%.1f", resource_id[:60], timespan, duration_ms)
    return {"resource_id": resource_id, "timespan": timespan, "interval": interval, "metrics": []}


@router.post("/{resource_id_base64}/chat")
async def vmss_chat(
    resource_id_base64: str,
    request: VMSSChatRequest,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Resource-scoped chat for VMSS investigation.

    Routes to the compute agent directly (same as VM chat).
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    try:
        from services.api_gateway.foundry import _get_foundry_client  # type: ignore[import]
        from services.api_gateway.chat import create_chat_thread  # type: ignore[import]

        agent_id = os.environ.get("COMPUTE_AGENT_ID", "")
        if not agent_id:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning("vmss_chat: COMPUTE_AGENT_ID not set duration_ms=%.1f", duration_ms)
            return {"error": "COMPUTE_AGENT_ID not configured"}

        context = f"Resource: {resource_id}\nMessage: {request.message}"
        thread_id, run_id = await create_chat_thread(
            agent_id=agent_id,
            message=context,
            thread_id=request.thread_id,
        )
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("vmss_chat: thread_id=%s run_id=%s duration_ms=%.1f", thread_id, run_id, duration_ms)
        return {"thread_id": thread_id, "run_id": run_id, "status": "created"}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("vmss_chat: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"error": str(exc)}
```
</action>

<acceptance_criteria>
- File exists: `services/api-gateway/vmss_endpoints.py`
- `grep "router = APIRouter(prefix=\"/api/v1/vmss\"" services/api-gateway/vmss_endpoints.py` → matches
- `grep "start_time = time.monotonic()" services/api-gateway/vmss_endpoints.py` → matches (3+ times, tool function pattern)
- `grep "duration_ms" services/api-gateway/vmss_endpoints.py` → multiple matches (in both try and except blocks)
- `grep "def _log_sdk_availability" services/api-gateway/vmss_endpoints.py` → matches
- `grep "_ARG_AVAILABLE" services/api-gateway/vmss_endpoints.py` → matches
- `grep "\"vmss\": \[\], \"total\": 0" services/api-gateway/vmss_endpoints.py` → matches (graceful fallback)
- `grep "@router.get(\"\")$\|@router.get(\"/{resource_id_base64}\")$\|@router.get(\"/{resource_id_base64}/metrics\")$\|@router.post(\"/{resource_id_base64}/chat\")$" services/api-gateway/vmss_endpoints.py` → 4 matches
</acceptance_criteria>

---

### Task 11: Wire VMSS router into `services/api-gateway/main.py`

**Purpose:** Register the VMSS router with the FastAPI app so the endpoints are live.

<read_first>
- `services/api-gateway/main.py` lines 97–121 (router import + `app.include_router()` calls — find the exact insertion point)
</read_first>

<action>
In `services/api-gateway/main.py`:

1. Add this import after line 120 (after `from services.api_gateway.vm_cost import router as vm_cost_router`):
```python
from services.api_gateway.vmss_endpoints import router as vmss_router
```

2. Find the `app.include_router(...)` block (search for `app.include_router(vm_cost_router)`) and add:
```python
app.include_router(vmss_router)
```
immediately after `app.include_router(vm_cost_router)`.
</action>

<acceptance_criteria>
- `grep "from services.api_gateway.vmss_endpoints import router as vmss_router" services/api-gateway/main.py` → matches
- `grep "app.include_router(vmss_router)" services/api-gateway/main.py` → matches
</acceptance_criteria>

---

### Task 12: Wire VMSS into `DashboardPanel.tsx` (partial — VMSS only)

**Purpose:** Add VMSS to the dashboard tab system. AKS wiring is completed in Plan 41-2.

<read_first>
- `services/web-ui/components/DashboardPanel.tsx` (full file — read all 199 lines)
</read_first>

<action>
Make these targeted edits to `services/web-ui/components/DashboardPanel.tsx`:

**1. Line 4 — add `Scaling` to lucide-react import:**
```typescript
import { Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown, Scaling } from 'lucide-react'
```

**2. Lines 12–13 — add VMSS component imports (after VMDetailPanel import):**
```typescript
import { VMSSTab } from './VMSSTab'
import { VMSSDetailPanel } from './VMSSDetailPanel'
```

**3. Line 17 — expand TabId union:**
```typescript
type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'cost' | 'observability' | 'patch'
```

**4. Lines 30–31 — insert VMSS entry in TABS array after the `vms` entry:**
```typescript
  { id: 'vmss', label: 'VMSS', Icon: Scaling },
```
(Insert between `{ id: 'vms', ... }` and `{ id: 'cost', ... }`)

**5. After line 61 (after `closeVMDetail` function) — add VMSS state and handlers:**
```typescript
  const [vmssDetailOpen, setVMSSDetailOpen] = useState(false)
  const [selectedVMSS, setSelectedVMSS] = useState<{ resourceId: string; resourceName: string } | null>(null)

  function openVMSSDetail(resourceId: string, resourceName: string) {
    setSelectedVMSS({ resourceId, resourceName })
    setVMSSDetailOpen(true)
  }

  function closeVMSSDetail() {
    setVMSSDetailOpen(false)
    setSelectedVMSS(null)
  }
```

**6. After the `tabpanel-vms` div (line ~159) and before `tabpanel-cost` — add VMSS tab panel:**
```tsx
        <div id="tabpanel-vmss" role="tabpanel" aria-labelledby="tab-vmss" hidden={activeTab !== 'vmss'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <VMSSTab subscriptions={selectedSubscriptions} onVMSSClick={openVMSSDetail} />
          </div>
        </div>
```

**7. After the VM Detail Panel + backdrop section (line ~195) — add VMSS detail panel:**
```tsx
      {/* VMSS Detail Panel + backdrop */}
      {vmssDetailOpen && selectedVMSS && (
        <>
          <div
            className="fixed inset-0 z-30"
            style={{ background: 'rgba(0,0,0,0.3)' }}
            onClick={closeVMSSDetail}
          />
          <VMSSDetailPanel
            resourceId={selectedVMSS.resourceId}
            resourceName={selectedVMSS.resourceName}
            onClose={closeVMSSDetail}
          />
        </>
      )}
```
</action>

<acceptance_criteria>
- `grep "'vmss'" services/web-ui/components/DashboardPanel.tsx` → matches (TabId union + TABS array)
- `grep "Scaling" services/web-ui/components/DashboardPanel.tsx` → matches (import + TABS array entry)
- `grep "VMSSTab\|VMSSDetailPanel" services/web-ui/components/DashboardPanel.tsx` → matches (imports + usage)
- `grep "vmssDetailOpen\|selectedVMSS\|openVMSSDetail\|closeVMSSDetail" services/web-ui/components/DashboardPanel.tsx` → matches (state + handlers)
- `grep "tabpanel-vmss" services/web-ui/components/DashboardPanel.tsx` → matches
- `grep "hidden={activeTab !== 'vmss'}" services/web-ui/components/DashboardPanel.tsx` → matches
</acceptance_criteria>

---

## Verification

After completing all 12 tasks, run these checks in order:

```bash
# 1. TypeScript compilation
cd services/web-ui && npx tsc --noEmit
# Expected: exits 0, no errors

# 2. Python tests (no regressions)
cd /path/to/repo && python -m pytest services/api-gateway/tests/ -q --tb=short
# Expected: all existing tests pass; 0 new failures

# 3. Verify VMSS router registered
grep -n "vmss_router" services/api-gateway/main.py
# Expected: 2 lines (import + include_router)

# 4. Verify no hardcoded Tailwind colors in new files
grep -r "bg-green-\|bg-red-\|bg-yellow-\|text-green-\|text-red-\|text-yellow-" \
  services/web-ui/components/VMSSTab.tsx \
  services/web-ui/components/VMSSDetailPanel.tsx
# Expected: NO matches

# 5. Verify CSS token pattern used
grep -c "color-mix(in srgb" services/web-ui/components/VMSSTab.tsx
# Expected: >= 3 matches

# 6. Verify proxy route files exist
ls services/web-ui/app/api/proxy/vmss/
# Expected: route.ts + [vmssId]/ directory
ls services/web-ui/app/api/proxy/vmss/[vmssId]/
# Expected: route.ts + metrics/ + chat/ directories
```

### Manual smoke test (dev server)
1. `npm run dev` from `services/web-ui/`
2. Navigate to dashboard → VMSS tab should be visible between VMs and Cost
3. Tab renders skeleton rows (empty state since backend stub returns empty list)
4. Clicking empty state shows "Select a subscription to view scale sets" message
5. TypeScript dev server shows zero type errors

---

## Files Created / Modified

| File | Status |
|------|--------|
| `services/web-ui/types/azure-resources.ts` | CREATE |
| `services/web-ui/components/VMSSTab.tsx` | CREATE |
| `services/web-ui/components/VMSSDetailPanel.tsx` | CREATE |
| `services/web-ui/app/api/proxy/vmss/route.ts` | CREATE |
| `services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts` | CREATE |
| `services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts` | CREATE |
| `services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts` | CREATE |
| `services/api-gateway/vmss_endpoints.py` | CREATE |
| `services/web-ui/components/DashboardPanel.tsx` | MODIFY |
| `services/web-ui/components/VMTab.tsx` | MODIFY (import extraction) |
| `services/web-ui/components/VMDetailPanel.tsx` | MODIFY (import extraction) |
| `services/api-gateway/main.py` | MODIFY (router include) |

**Total: 8 new files + 4 modified files**
