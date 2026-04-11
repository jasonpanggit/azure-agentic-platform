---
plan_id: "41-2"
phase: 41
wave: 2
title: "AKS Full Stack — AKSTab, AKSDetailPanel, 4 AKS proxy routes, DashboardPanel AKS wiring + AlertFeed routing, API gateway AKS stubs"
goal: "Complete Phase 41 by delivering the full AKS tab experience: AKSTab list view with K8s-specific badges, AKSDetailPanel with 5 tabs (Overview/Node Pools/Workloads/Metrics/AI Chat), 4 AKS proxy routes, DashboardPanel AKS wiring, AlertFeed resource-type routing, and 3 api-gateway AKS stub endpoints. Result: 10-tab dashboard fully operational."
---

# Plan 41-2: AKS Full Stack

## Context

This is Wave 2 of Phase 41. Plan 41-1 (Wave 1) delivered:
- `services/web-ui/types/azure-resources.ts` (shared types including `AKSCluster`, `AKSNodePool`, `AKSWorkloadSummary`)
- `VMSSTab.tsx`, `VMSSDetailPanel.tsx`, 4 VMSS proxy routes
- `services/api-gateway/vmss_endpoints.py`
- DashboardPanel VMSS wiring (9 tabs: alerts | audit | topology | resources | vms | vmss | cost | observability | patch)

**This plan adds AKS to produce the final 10-tab configuration:**
`alerts | audit | topology | resources | vms | vmss | aks | cost | observability | patch`

**Prerequisites:** Plan 41-1 must be complete before executing this plan.

**Pattern source files to read before every task:**
- `services/web-ui/components/VMSSTab.tsx` (AKSTab is structurally identical — different badges)
- `services/web-ui/components/VMSSDetailPanel.tsx` (AKSDetailPanel follows same pattern)
- `services/web-ui/app/api/proxy/vmss/route.ts` (copy for AKS list route)
- `services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts` (copy for AKS detail route)
- `services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts` (copy for AKS metrics route)
- `services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts` (copy for AKS chat route)
- `services/api-gateway/vmss_endpoints.py` (copy pattern for AKS endpoints)
- `services/web-ui/components/DashboardPanel.tsx` (current state after Plan 41-1 — 9 tabs)

---

## Tasks

### Task 1: Create AKS proxy route — `app/api/proxy/aks/route.ts`

**Purpose:** Proxy list endpoint — forwards `GET /api/proxy/aks?subscriptions=...` to `GET /api/v1/aks?subscriptions=...`.

<read_first>
- `services/web-ui/app/api/proxy/vmss/route.ts` (exact pattern — replace `vmss` with `aks`)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/aks/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/aks' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/aks
 *
 * Proxies AKS cluster inventory requests to the API gateway.
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
    const url = new URL(`${getApiGatewayUrl()}/api/v1/aks`);
    if (subscriptions) url.searchParams.set('subscriptions', subscriptions);
    if (search) url.searchParams.set('search', search);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      log.debug('aks endpoint not ready, returning empty list', { status: res.status });
      return NextResponse.json({ clusters: [], total: 0 });
    }

    const data = await res.json();
    log.debug('aks list response', { total: data?.total });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.debug('gateway unreachable, returning empty aks list', { error: message });
    return NextResponse.json({ clusters: [], total: 0 });
  }
}
```
</action>

<acceptance_criteria>
- File exists: `services/web-ui/app/api/proxy/aks/route.ts`
- `grep "export const runtime = 'nodejs'" services/web-ui/app/api/proxy/aks/route.ts` → matches
- `grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/aks/route.ts` → matches
- `grep "clusters: \[\], total: 0" services/web-ui/app/api/proxy/aks/route.ts` → matches (graceful fallback)
- `grep "getApiGatewayUrl\|buildUpstreamHeaders" services/web-ui/app/api/proxy/aks/route.ts` → matches
</acceptance_criteria>

---

### Task 2: Create AKS proxy route — `app/api/proxy/aks/[aksId]/route.ts`

**Purpose:** Proxy detail endpoint — forwards `GET /api/proxy/aks/[aksId]` to `GET /api/v1/aks/{aksId}`.

<read_first>
- `services/web-ui/app/api/proxy/vmss/[vmssId]/route.ts` (exact pattern — replace `vmss`/`vmssId` with `aks`/`aksId`)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/aks/[aksId]/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/aks/[aksId]' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ aksId: string }> }
): Promise<NextResponse> {
  const { aksId } = await params;
  log.info('proxy request', { aksId: aksId.slice(0, 40) });

  try {
    const url = `${getApiGatewayUrl()}/api/v1/aks/${encodeURIComponent(aksId)}`;
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
- File exists: `services/web-ui/app/api/proxy/aks/[aksId]/route.ts`
- `grep "const { aksId } = await params" services/web-ui/app/api/proxy/aks/[aksId]/route.ts` → matches
- `grep "params: Promise<{ aksId: string }>" services/web-ui/app/api/proxy/aks/[aksId]/route.ts` → matches
- `grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/aks/[aksId]/route.ts` → matches
</acceptance_criteria>

---

### Task 3: Create AKS proxy route — `app/api/proxy/aks/[aksId]/metrics/route.ts`

**Purpose:** Proxy metrics endpoint — forwards `GET /api/proxy/aks/[aksId]/metrics?timespan=...` to `GET /api/v1/aks/{aksId}/metrics?timespan=...`.

<read_first>
- `services/web-ui/app/api/proxy/vmss/[vmssId]/metrics/route.ts` (exact pattern — replace `vmss`/`vmssId` with `aks`/`aksId`)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/aks/[aksId]/metrics/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/aks/[aksId]/metrics' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ aksId: string }> }
): Promise<NextResponse> {
  const { aksId } = await params;
  const searchParams = req.nextUrl.searchParams;
  const timespan = searchParams.get('timespan') ?? 'PT24H';
  const interval = searchParams.get('interval') ?? 'PT5M';

  log.info('proxy request', { aksId: aksId.slice(0, 40), timespan });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/aks/${encodeURIComponent(aksId)}/metrics`);
    url.searchParams.set('timespan', timespan);
    url.searchParams.set('interval', interval);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(30000),
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
- File exists: `services/web-ui/app/api/proxy/aks/[aksId]/metrics/route.ts`
- `grep "const { aksId } = await params" services/web-ui/app/api/proxy/aks/[aksId]/metrics/route.ts` → matches
- `grep "AbortSignal.timeout(30000)" services/web-ui/app/api/proxy/aks/[aksId]/metrics/route.ts` → matches
- `grep "metrics: \[\]" services/web-ui/app/api/proxy/aks/[aksId]/metrics/route.ts` → matches
</acceptance_criteria>

---

### Task 4: Create AKS proxy route — `app/api/proxy/aks/[aksId]/chat/route.ts`

**Purpose:** Proxy chat endpoint — forwards `POST /api/proxy/aks/[aksId]/chat` to `POST /api/v1/aks/{aksId}/chat`.

<read_first>
- `services/web-ui/app/api/proxy/vmss/[vmssId]/chat/route.ts` (exact pattern — replace `vmss`/`vmssId` with `aks`/`aksId`)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/aks/[aksId]/chat/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/aks/[aksId]/chat' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ aksId: string }> }
): Promise<NextResponse> {
  const { aksId } = await params;
  log.info('proxy request', { aksId: aksId.slice(0, 40) });

  try {
    const url = `${getApiGatewayUrl()}/api/v1/aks/${encodeURIComponent(aksId)}/chat`;
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
- File exists: `services/web-ui/app/api/proxy/aks/[aksId]/chat/route.ts`
- `grep "export async function POST" services/web-ui/app/api/proxy/aks/[aksId]/chat/route.ts` → matches
- `grep "'Content-Type': 'application/json'" services/web-ui/app/api/proxy/aks/[aksId]/chat/route.ts` → matches
- `grep "AbortSignal.timeout(30000)" services/web-ui/app/api/proxy/aks/[aksId]/chat/route.ts` → matches
</acceptance_criteria>

---

### Task 5: Create `services/web-ui/components/AKSTab.tsx`

**Purpose:** AKS cluster list view. Same structure as VMSSTab but with AKS-specific badges: K8sVersionBadge, NodeHealthBadge, SystemPodBadge, UpgradeBadge.

<read_first>
- `services/web-ui/components/VMSSTab.tsx` (full file — structural template)
- `services/web-ui/types/azure-resources.ts` (AKSCluster type)
</read_first>

<action>
Create `services/web-ui/components/AKSTab.tsx`:

**Badge implementations (all use CSS token formula — no hardcoded Tailwind colors):**

```typescript
'use client'

import { useState, useEffect, useCallback } from 'react'
import { Container, RefreshCw } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type { AKSCluster } from '@/types/azure-resources'

interface AKSTabProps {
  subscriptions: string[]
  onAKSClick?: (resourceId: string, resourceName: string) => void
}

function K8sVersionBadge({ version, latestAvailable }: { version: string; latestAvailable: string | null }) {
  const isOutdated = latestAvailable !== null
  const color = isOutdated ? 'var(--accent-yellow)' : 'var(--text-muted)'
  const label = isOutdated ? `${version} · ⬆ available` : version
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {label}
    </span>
  )
}

function NodeHealthBadge({ ready, total }: { ready: number; total: number }) {
  const notReady = total - ready
  const ratio = total > 0 ? notReady / total : 0
  let color: string
  if (notReady === 0) {
    color = 'var(--accent-green)'
  } else if (ratio > 0.5) {
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
      {ready}/{total}
    </span>
  )
}

function SystemPodBadge({ health }: { health: 'healthy' | 'degraded' | 'unknown' }) {
  const config = {
    healthy: { label: 'Healthy', color: 'var(--accent-green)' },
    degraded: { label: 'Degraded', color: 'var(--accent-yellow)' },
    unknown: { label: 'Unknown', color: 'var(--text-muted)' },
  }[health]
  return (
    <span className="text-[11px] font-medium" style={{ color: config.color }}>
      {config.label}
    </span>
  )
}

function UpgradeBadge({ latestVersion }: { latestVersion: string | null }) {
  if (!latestVersion) return null
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
        color: 'var(--accent-yellow)',
      }}
    >
      ⬆ {latestVersion}
    </span>
  )
}

export function AKSTab({ subscriptions, onAKSClick }: AKSTabProps) {
  const { instance, accounts } = useMsal()
  const [clusters, setClusters] = useState<AKSCluster[]>([])
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

  async function fetchClusters() {
    if (subscriptions.length === 0) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ subscriptions: subscriptions.join(',') })
      if (search) params.set('search', search)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/aks?${params}`, { headers })
      const data = await res.json()
      setClusters(data.clusters ?? [])
    } catch {
      setError('Failed to load AKS clusters')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchClusters() }, [subscriptions]) // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = clusters.filter(c =>
    !search || c.name.toLowerCase().includes(search.toLowerCase())
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
            AKS Clusters
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
            placeholder="Search clusters…"
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
            onClick={fetchClusters}
            disabled={loading}
            className="p-1.5 rounded cursor-pointer transition-colors"
            style={{ color: 'var(--text-secondary)' }}
            title="Refresh AKS clusters"
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
          <Container className="h-8 w-8 mx-auto mb-3" style={{ color: 'var(--text-muted)' }} />
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {subscriptions.length === 0
              ? 'Select a subscription to view AKS clusters'
              : 'No AKS clusters found in selected subscriptions'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Cluster', 'Resource Group', 'Location', 'K8s Version', 'Nodes', 'System Pods', 'Upgrade', 'Alerts'].map(col => (
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
              {filtered.map(cluster => (
                <tr
                  key={cluster.id}
                  className="cursor-pointer transition-colors"
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-subtle)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                  onClick={() => onAKSClick?.(cluster.id, cluster.name)}
                >
                  <td className="px-4 py-3 font-mono text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                    {cluster.name}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {cluster.resource_group}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {cluster.location}
                  </td>
                  <td className="px-4 py-3">
                    <K8sVersionBadge version={cluster.kubernetes_version} latestAvailable={cluster.latest_available_version} />
                  </td>
                  <td className="px-4 py-3">
                    <NodeHealthBadge ready={cluster.ready_nodes} total={cluster.total_nodes} />
                  </td>
                  <td className="px-4 py-3">
                    <SystemPodBadge health={cluster.system_pod_health} />
                  </td>
                  <td className="px-4 py-3">
                    <UpgradeBadge latestVersion={cluster.latest_available_version} />
                  </td>
                  <td className="px-4 py-3">
                    {cluster.active_alert_count > 0 ? (
                      <span
                        className="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold"
                        style={{
                          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                          color: 'var(--accent-red)',
                        }}
                      >
                        {cluster.active_alert_count}
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
- File exists: `services/web-ui/components/AKSTab.tsx`
- `grep "export function AKSTab" services/web-ui/components/AKSTab.tsx` → matches
- `grep "K8sVersionBadge\|NodeHealthBadge\|SystemPodBadge\|UpgradeBadge" services/web-ui/components/AKSTab.tsx` → all 4 match (defined and used)
- `grep "color-mix(in srgb, var(--accent-yellow) 15%, transparent)" services/web-ui/components/AKSTab.tsx` → matches
- `grep "color-mix(in srgb, var(--accent-green) 15%, transparent)" services/web-ui/components/AKSTab.tsx` → matches
- `grep "bg-green-100\|text-green-700\|bg-red-100\|bg-yellow-100" services/web-ui/components/AKSTab.tsx` → NO match
- `grep "onAKSClick\?.(cluster.id, cluster.name)" services/web-ui/components/AKSTab.tsx` → matches
- `grep "animate-pulse" services/web-ui/components/AKSTab.tsx` → matches (skeleton)
- `grep "import type { AKSCluster } from '@/types/azure-resources'" services/web-ui/components/AKSTab.tsx` → matches
</acceptance_criteria>

---

### Task 6: Create `services/web-ui/components/AKSDetailPanel.tsx`

**Purpose:** Tabbed AKS detail panel — 5 tabs: Overview, Node Pools, Workloads, Metrics, AI Chat. Same resize pattern as VMSSDetailPanel. Chat auto-fires on Chat tab open.

<read_first>
- `services/web-ui/components/VMSSDetailPanel.tsx` (full file — structural template; adapt for AKS tabs)
- `services/web-ui/types/azure-resources.ts` (AKSCluster, AKSNodePool, AKSWorkloadSummary types)
</read_first>

<action>
Create `services/web-ui/components/AKSDetailPanel.tsx`:

Key implementation requirements:
1. **Resize handle:** Same as VMSSDetailPanel. LocalStorage key: `'aksDetailPanelWidth'`. Constants: `PANEL_MIN_WIDTH = 380`, `PANEL_MAX_WIDTH = 1200`, `PANEL_DEFAULT_WIDTH = 560`.
2. **5 internal tabs:** `'overview' | 'nodepools' | 'workloads' | 'metrics' | 'chat'`
3. **Chat pattern:** Auto-fires on Chat tab open. `POST /api/proxy/aks/[aksId]/chat` with `{ message: "Summarize this cluster's health and suggest investigation steps.", thread_id: null }`. Polls `GET /api/proxy/chat/result?...` every 2s. `useEffect([resourceId])` resets on resource change.
4. **CSS tokens only** — no hardcoded Tailwind colors.

```typescript
'use client'

import { useState, useEffect, useCallback, useRef, MouseEvent as ReactMouseEvent } from 'react'
import { X, RefreshCw, Activity } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type {
  AKSCluster,
  AKSNodePool,
  AKSWorkloadSummary,
  ActiveIncident,
  MetricSeries,
  ChatMessage,
} from '@/types/azure-resources'

// ── Constants ────────────────────────────────────────────────────────────────

const PANEL_MIN_WIDTH = 380
const PANEL_MAX_WIDTH = 1200
const PANEL_DEFAULT_WIDTH = 560

type DetailTab = 'overview' | 'nodepools' | 'workloads' | 'metrics' | 'chat'

interface AKSDetailPanelProps {
  resourceId: string
  resourceName: string
  onClose: () => void
}

// Detail response shape (extends AKSCluster with nested data)
interface AKSDetail extends AKSCluster {
  node_pools: AKSNodePool[]
  workload_summary: AKSWorkloadSummary | null
  active_incidents: ActiveIncident[]
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

function NodePoolModeBadge({ mode }: { mode: 'System' | 'User' }) {
  const color = mode === 'System' ? 'var(--accent-blue)' : 'var(--text-muted)'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {mode}
    </span>
  )
}

function NodeReadyBadge({ ready, total }: { ready: number; total: number }) {
  const notReady = total - ready
  const color = notReady === 0 ? 'var(--accent-green)' : notReady / total > 0.5 ? 'var(--accent-red)' : 'var(--accent-yellow)'
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {ready}/{total}
    </span>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function AKSDetailPanel({ resourceId, resourceName, onClose }: AKSDetailPanelProps) {
  const { instance, accounts } = useMsal()
  const [activeTab, setActiveTab] = useState<DetailTab>('overview')
  const [detail, setDetail] = useState<AKSDetail | null>(null)
  const [metrics, setMetrics] = useState<MetricSeries[]>([])
  const [metricsTimespan, setMetricsTimespan] = useState('PT24H')
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      const stored = localStorage.getItem('aksDetailPanelWidth')
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

  async function fetchDetail() {
    if (!resourceId) return
    setLoadingDetail(true)
    setError(null)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/aks/${encoded}`, { headers })
      if (!res.ok) throw new Error(`Status ${res.status}`)
      const data = await res.json()
      setDetail(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(`Failed to load cluster details: ${msg}`)
    } finally {
      setLoadingDetail(false)
    }
  }

  async function fetchMetrics(timespan: string) {
    if (!resourceId) return
    setLoadingMetrics(true)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/aks/${encoded}/metrics?timespan=${timespan}`, { headers })
      if (res.ok) {
        const data = await res.json()
        setMetrics(data.metrics ?? [])
      }
    } catch {
      // Non-fatal
    } finally {
      setLoadingMetrics(false)
    }
  }

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
      const res = await fetch(`/api/proxy/aks/${encoded}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message, thread_id: chatThreadId }),
      })
      if (!res.ok) throw new Error(`Status ${res.status}`)
      const { thread_id, run_id } = await res.json()
      if (thread_id) setChatThreadId(thread_id)
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
        if (data.response) setChatMessages(prev => [...prev, { role: 'assistant', content: data.response }])
        return
      }
    }
  }

  useEffect(() => {
    setChatMessages([])
    setChatThreadId(null)
    chatAutoFired.current = false
    setActiveTab('overview')
    fetchDetail()
  }, [resourceId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeTab === 'chat' && !chatAutoFired.current && !chatLoading) {
      chatAutoFired.current = true
      sendChatMessage("Summarize this cluster's health and suggest investigation steps.")
    }
    if (activeTab === 'metrics') fetchMetrics(metricsTimespan)
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeTab === 'metrics') fetchMetrics(metricsTimespan)
  }, [metricsTimespan]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

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
    localStorage.setItem('aksDetailPanelWidth', String(panelWidth))
  }

  const DETAIL_TABS: { id: DetailTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'nodepools', label: 'Node Pools' },
    { id: 'workloads', label: 'Workloads' },
    { id: 'metrics', label: 'Metrics' },
    { id: 'chat', label: 'AI Chat' },
  ]

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
                    { label: 'Nodes Ready', value: `${detail.ready_nodes}/${detail.total_nodes}`, color: detail.ready_nodes === detail.total_nodes ? 'var(--accent-green)' : 'var(--accent-yellow)' },
                    { label: 'Node Pools', value: `${detail.node_pools_ready}/${detail.node_pool_count}`, color: detail.node_pools_ready === detail.node_pool_count ? 'var(--accent-green)' : 'var(--accent-yellow)' },
                    { label: 'K8s Version', value: detail.kubernetes_version, color: 'var(--text-primary)' },
                    { label: 'System Pods', value: detail.system_pod_health, color: detail.system_pod_health === 'healthy' ? 'var(--accent-green)' : detail.system_pod_health === 'degraded' ? 'var(--accent-yellow)' : 'var(--text-muted)' },
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
                    Cluster Configuration
                  </p>
                  {[
                    ['Location', detail.location],
                    ['FQDN', detail.fqdn ?? '—'],
                    ['Network Plugin', detail.network_plugin || '—'],
                    ['RBAC Enabled', detail.rbac_enabled ? 'Yes' : 'No'],
                    ['Latest K8s Available', detail.latest_available_version ?? 'Up to date'],
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

        {/* Node Pools tab */}
        {activeTab === 'nodepools' && (
          <div className="p-4">
            {loadingDetail ? (
              <div className="animate-pulse space-y-2">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-12 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : !detail?.node_pools?.length ? (
              <p className="text-sm text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                No node pool data available
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Pool', 'VM Size', 'Nodes', 'Mode', 'OS', 'Scale Range'].map(col => (
                      <th key={col} className="text-left px-2 py-2 text-[11px] uppercase tracking-wide font-semibold" style={{ color: 'var(--text-muted)' }}>
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {detail.node_pools.map((pool: AKSNodePool) => (
                    <tr
                      key={pool.name}
                      style={{
                        borderBottom: '1px solid var(--border-subtle)',
                        background: pool.ready_node_count < pool.node_count
                          ? 'color-mix(in srgb, var(--accent-yellow) 5%, transparent)'
                          : 'transparent',
                      }}
                    >
                      <td className="px-2 py-2 font-mono font-medium" style={{ color: 'var(--text-primary)' }}>
                        {pool.name}
                      </td>
                      <td className="px-2 py-2" style={{ color: 'var(--text-secondary)' }}>
                        {pool.vm_size}
                      </td>
                      <td className="px-2 py-2">
                        <NodeReadyBadge ready={pool.ready_node_count} total={pool.node_count} />
                      </td>
                      <td className="px-2 py-2">
                        <NodePoolModeBadge mode={pool.mode} />
                      </td>
                      <td className="px-2 py-2" style={{ color: 'var(--text-secondary)' }}>
                        {pool.os_type}
                      </td>
                      <td className="px-2 py-2" style={{ color: 'var(--text-secondary)' }}>
                        {pool.min_count !== null && pool.max_count !== null
                          ? `${pool.min_count}–${pool.max_count}`
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Workloads tab */}
        {activeTab === 'workloads' && (
          <div className="p-4 space-y-4">
            {loadingDetail ? (
              <div className="animate-pulse space-y-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-16 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : detail?.workload_summary ? (
              <>
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: 'Running Pods', value: String(detail.workload_summary.running_pods), color: 'var(--accent-green)' },
                    { label: 'CrashLoopBackOff', value: String(detail.workload_summary.crash_loop_pods), color: detail.workload_summary.crash_loop_pods > 0 ? 'var(--accent-red)' : 'var(--text-muted)' },
                    { label: 'Pending Pods', value: String(detail.workload_summary.pending_pods), color: detail.workload_summary.pending_pods > 0 ? 'var(--accent-yellow)' : 'var(--text-muted)' },
                    { label: 'Namespaces', value: String(detail.workload_summary.namespace_count), color: 'var(--text-primary)' },
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
                <p className="text-xs text-center py-2" style={{ color: 'var(--text-muted)' }}>
                  Use AI Chat for detailed workload investigation.
                </p>
              </>
            ) : (
              <p className="text-sm text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                No workload data available
              </p>
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

        {/* Chat tab */}
        {activeTab === 'chat' && (
          <div className="flex flex-col h-full">
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {chatMessages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
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
                placeholder="Ask about this cluster…"
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
                style={{ background: 'var(--accent-blue)', color: '#fff' }}
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
- File exists: `services/web-ui/components/AKSDetailPanel.tsx`
- `grep "export function AKSDetailPanel" services/web-ui/components/AKSDetailPanel.tsx` → matches
- `grep "aksDetailPanelWidth" services/web-ui/components/AKSDetailPanel.tsx` → matches (localStorage key)
- `grep "PANEL_DEFAULT_WIDTH = 560" services/web-ui/components/AKSDetailPanel.tsx` → matches
- `grep "Summarize this cluster's health" services/web-ui/components/AKSDetailPanel.tsx` → matches (auto-fire message)
- `grep "type DetailTab = 'overview' | 'nodepools' | 'workloads' | 'metrics' | 'chat'" services/web-ui/components/AKSDetailPanel.tsx` → matches
- `grep "NodePoolModeBadge\|NodeReadyBadge" services/web-ui/components/AKSDetailPanel.tsx` → matches
- `grep "color-mix(in srgb" services/web-ui/components/AKSDetailPanel.tsx` → multiple matches
- `grep "bg-green-100\|text-green-700\|bg-red-100" services/web-ui/components/AKSDetailPanel.tsx` → NO match
- `grep "onDragStart\|onDragMove\|onDragEnd" services/web-ui/components/AKSDetailPanel.tsx` → matches (resize handlers)
</acceptance_criteria>

---

### Task 7: Create `services/api-gateway/aks_endpoints.py`

**Purpose:** FastAPI router for AKS stub endpoints. Same lazy-import + try/except pattern as `vmss_endpoints.py`. Routes: `GET /api/v1/aks`, `GET /api/v1/aks/{id}`, `GET /api/v1/aks/{id}/metrics`, `POST /api/v1/aks/{id}/chat`.

<read_first>
- `services/api-gateway/vmss_endpoints.py` (full file — copy structure, replace VMSS with AKS)
- `services/api-gateway/main.py` lines 97–121 (router include pattern)
</read_first>

<action>
Create `services/api-gateway/aks_endpoints.py`:

```python
"""AKS cluster inventory and chat endpoints.

GET  /api/v1/aks                           — list AKS clusters in subscriptions via ARG
GET  /api/v1/aks/{resource_id_base64}      — AKS cluster detail including node pools
GET  /api/v1/aks/{resource_id_base64}/metrics  — Azure Monitor metrics for AKS
POST /api/v1/aks/{resource_id_base64}/chat     — resource-scoped chat for AKS investigation

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

router = APIRouter(prefix="/api/v1/aks", tags=["aks"])

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]
    _ARG_AVAILABLE = True
except ImportError:
    _ARG_AVAILABLE = False
    logger.warning("azure-mgmt-resourcegraph not available — AKS list returns empty")


def _log_sdk_availability() -> None:
    logger.info("aks_endpoints: azure-mgmt-resourcegraph available=%s", _ARG_AVAILABLE)


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

class AKSChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None


class AKSChatResponse(BaseModel):
    thread_id: str
    run_id: str
    status: str = "created"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_aks_clusters(
    subscriptions: str = Query(..., description="Comma-separated subscription IDs"),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """List AKS clusters across subscriptions via Azure Resource Graph.

    Returns structured empty response when ARG SDK unavailable.
    """
    start_time = time.monotonic()
    subscription_ids = [s.strip() for s in subscriptions.split(",") if s.strip()]

    if not _ARG_AVAILABLE or not subscription_ids:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_list: sdk_unavailable duration_ms=%.1f", duration_ms)
        return {"clusters": [], "total": 0}

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        credential = DefaultAzureCredential()
        client = ResourceGraphClient(credential)

        kql = """Resources
| where type =~ 'microsoft.containerservice/managedclusters'
| project id, name, resourceGroup, subscriptionId, location,
    kubernetes_version = tostring(properties.kubernetesVersion),
    latest_available_version = tostring(properties.currentKubernetesVersion),
    fqdn = tostring(properties.fqdn),
    network_plugin = tostring(properties.networkProfile.networkPlugin),
    rbac_enabled = tobool(properties.enableRBAC),
    node_pool_count = array_length(properties.agentPoolProfiles),
    total_nodes = 0,
    ready_nodes = 0,
    node_pools_ready = 0,
    system_pod_health = 'unknown',
    active_alert_count = 0"""

        if search:
            search_safe = search.replace("'", "")
            kql += f"\n| where name contains '{search_safe}'"

        kql += f"\n| limit {limit}"

        request = QueryRequest(subscriptions=subscription_ids, query=kql)
        response = client.resources(request)
        rows = response.data or []

        clusters = [
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "resource_group": r.get("resourceGroup", ""),
                "subscription_id": r.get("subscriptionId", ""),
                "location": r.get("location", ""),
                "kubernetes_version": r.get("kubernetes_version", ""),
                "latest_available_version": None,  # Simplified — same as current means up to date
                "node_pool_count": r.get("node_pool_count", 0),
                "node_pools_ready": r.get("node_pool_count", 0),
                "total_nodes": 0,
                "ready_nodes": 0,
                "system_pod_health": "unknown",
                "fqdn": r.get("fqdn") or None,
                "network_plugin": r.get("network_plugin", ""),
                "rbac_enabled": r.get("rbac_enabled", False),
                "active_alert_count": 0,
            }
            for r in rows
        ]

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_list: total=%d duration_ms=%.1f", len(clusters), duration_ms)
        return {"clusters": clusters, "total": len(clusters)}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_list: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"clusters": [], "total": 0}


@router.get("/{resource_id_base64}")
async def get_aks_detail(
    resource_id_base64: str,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get AKS cluster detail including node pools and workload summary."""
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    if not _ARG_AVAILABLE:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_detail: sdk_unavailable resource_id=%s duration_ms=%.1f", resource_id[:60], duration_ms)
        return {
            "id": resource_id,
            "name": resource_id.split("/")[-1],
            "resource_group": "",
            "subscription_id": _extract_subscription_id(resource_id),
            "location": "",
            "kubernetes_version": "",
            "latest_available_version": None,
            "node_pool_count": 0,
            "node_pools_ready": 0,
            "total_nodes": 0,
            "ready_nodes": 0,
            "system_pod_health": "unknown",
            "fqdn": None,
            "network_plugin": "",
            "rbac_enabled": False,
            "active_alert_count": 0,
            "node_pools": [],
            "workload_summary": None,
            "active_incidents": [],
        }

    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore[import]
        credential = DefaultAzureCredential()
        subscription_id = _extract_subscription_id(resource_id)
        parts = resource_id.split("/")
        rg_index = next((i for i, p in enumerate(parts) if p.lower() == "resourcegroups"), -1)
        resource_group = parts[rg_index + 1] if rg_index >= 0 else ""
        cluster_name = parts[-1]

        aks_client = ContainerServiceClient(credential, subscription_id)
        cluster = aks_client.managed_clusters.get(resource_group, cluster_name)

        node_pools = []
        total_nodes = 0
        ready_nodes = 0
        pools_ready = 0

        for pool in (cluster.agent_pool_profiles or []):
            pool_count = pool.count or 0
            total_nodes += pool_count
            ready_nodes += pool_count  # Simplified — no per-pool health available via ARM
            pools_ready += 1
            node_pools.append({
                "name": pool.name or "",
                "vm_size": pool.vm_size or "",
                "node_count": pool_count,
                "ready_node_count": pool_count,
                "mode": str(pool.mode or "User"),
                "os_type": str(pool.os_type or "Linux"),
                "min_count": pool.min_count,
                "max_count": pool.max_count,
                "provisioning_state": pool.provisioning_state or "unknown",
            })

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_detail: resource_id=%s node_pools=%d duration_ms=%.1f", resource_id[:60], len(node_pools), duration_ms)
        return {
            "id": resource_id,
            "name": cluster.name or cluster_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "location": cluster.location or "",
            "kubernetes_version": cluster.kubernetes_version or "",
            "latest_available_version": None,
            "node_pool_count": len(node_pools),
            "node_pools_ready": pools_ready,
            "total_nodes": total_nodes,
            "ready_nodes": ready_nodes,
            "system_pod_health": "unknown",
            "fqdn": cluster.fqdn,
            "network_plugin": (cluster.network_profile.network_plugin if cluster.network_profile else ""),
            "rbac_enabled": cluster.enable_rbac or False,
            "active_alert_count": 0,
            "node_pools": node_pools,
            "workload_summary": None,
            "active_incidents": [],
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_detail: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"error": str(exc)}


@router.get("/{resource_id_base64}/metrics")
async def get_aks_metrics(
    resource_id_base64: str,
    timespan: str = Query("PT24H"),
    interval: str = Query("PT5M"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Get Azure Monitor metrics for an AKS cluster."""
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"resource_id": "", "timespan": timespan, "interval": interval, "metrics": []}

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("aks_metrics: resource_id=%s timespan=%s duration_ms=%.1f", resource_id[:60], timespan, duration_ms)
    return {"resource_id": resource_id, "timespan": timespan, "interval": interval, "metrics": []}


@router.post("/{resource_id_base64}/chat")
async def aks_chat(
    resource_id_base64: str,
    request: AKSChatRequest,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Resource-scoped chat for AKS cluster investigation.

    Routes to the compute agent directly (AKS tools are in the compute agent).
    """
    start_time = time.monotonic()
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError:
        return {"error": "Invalid resource ID"}

    try:
        from services.api_gateway.chat import create_chat_thread  # type: ignore[import]

        agent_id = os.environ.get("COMPUTE_AGENT_ID", "")
        if not agent_id:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning("aks_chat: COMPUTE_AGENT_ID not set duration_ms=%.1f", duration_ms)
            return {"error": "COMPUTE_AGENT_ID not configured"}

        context = f"AKS Cluster: {resource_id}\nMessage: {request.message}"
        thread_id, run_id = await create_chat_thread(
            agent_id=agent_id,
            message=context,
            thread_id=request.thread_id,
        )
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("aks_chat: thread_id=%s run_id=%s duration_ms=%.1f", thread_id, run_id, duration_ms)
        return {"thread_id": thread_id, "run_id": run_id, "status": "created"}

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("aks_chat: error=%s duration_ms=%.1f", exc, duration_ms)
        return {"error": str(exc)}
```
</action>

<acceptance_criteria>
- File exists: `services/api-gateway/aks_endpoints.py`
- `grep "router = APIRouter(prefix=\"/api/v1/aks\"" services/api-gateway/aks_endpoints.py` → matches
- `grep "start_time = time.monotonic()" services/api-gateway/aks_endpoints.py` → matches (3+ times)
- `grep "duration_ms" services/api-gateway/aks_endpoints.py` → multiple matches in both try and except
- `grep "def _log_sdk_availability" services/api-gateway/aks_endpoints.py` → matches
- `grep "\"clusters\": \[\], \"total\": 0" services/api-gateway/aks_endpoints.py` → matches (graceful fallback)
- `grep "@router.get(\"\")$\|@router.get(\"/{resource_id_base64}\")$\|@router.get(\"/{resource_id_base64}/metrics\")$\|@router.post(\"/{resource_id_base64}/chat\")$" services/api-gateway/aks_endpoints.py` → 4 matches
</acceptance_criteria>

---

### Task 8: Wire AKS router into `services/api-gateway/main.py`

**Purpose:** Register the AKS router alongside the VMSS router.

<read_first>
- `services/api-gateway/main.py` lines 97–130 (current state after Plan 41-1 — vmss_router already present)
</read_first>

<action>
In `services/api-gateway/main.py`:

1. Add import immediately after the `vmss_router` import:
```python
from services.api_gateway.aks_endpoints import router as aks_router
```

2. Add include_router call immediately after `app.include_router(vmss_router)`:
```python
app.include_router(aks_router)
```
</action>

<acceptance_criteria>
- `grep "from services.api_gateway.aks_endpoints import router as aks_router" services/api-gateway/main.py` → matches
- `grep "app.include_router(aks_router)" services/api-gateway/main.py` → matches
</acceptance_criteria>

---

### Task 9: Complete `DashboardPanel.tsx` — add AKS tab + AlertFeed routing

**Purpose:** Add AKS to the tab system (10 tabs total) and update the AlertFeed `onInvestigate` handler to route VMSS/AKS incidents to their respective detail panels.

<read_first>
- `services/web-ui/components/DashboardPanel.tsx` (full file — current state after Plan 41-1 with VMSS already wired, 9 tabs)
</read_first>

<action>
Make these targeted edits to `services/web-ui/components/DashboardPanel.tsx`:

**1. Line 4 — add `Container` to lucide-react import (after `Scaling`):**
```typescript
import { Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown, Scaling, Container } from 'lucide-react'
```

**2. After VMSSDetailPanel import — add AKS component imports:**
```typescript
import { AKSTab } from './AKSTab'
import { AKSDetailPanel } from './AKSDetailPanel'
```

**3. TabId union — add `'aks'` after `'vmss'`:**
```typescript
type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch'
```

**4. TABS array — insert AKS entry after VMSS entry:**
```typescript
  { id: 'aks', label: 'AKS', Icon: Container },
```
(Between `{ id: 'vmss', ... }` and `{ id: 'cost', ... }`)

**5. After the `closeVMSSDetail` function — add AKS state and handlers:**
```typescript
  const [aksDetailOpen, setAKSDetailOpen] = useState(false)
  const [selectedAKS, setSelectedAKS] = useState<{ resourceId: string; resourceName: string } | null>(null)

  function openAKSDetail(resourceId: string, resourceName: string) {
    setSelectedAKS({ resourceId, resourceName })
    setAKSDetailOpen(true)
  }

  function closeAKSDetail() {
    setAKSDetailOpen(false)
    setSelectedAKS(null)
  }
```

**6. Update AlertFeed `onInvestigate` inline handler to route by resource type:**

Find the current AlertFeed `onInvestigate` handler:
```tsx
onInvestigate={(incidentId, resourceId, resourceName) => openVMDetail(incidentId, resourceId ?? null, resourceName ?? null)}
```

Replace with:
```tsx
onInvestigate={(incidentId, resourceId, resourceName) => {
  const resId = (resourceId ?? '').toLowerCase()
  if (resId.includes('virtualmachinescalesets')) {
    if (resourceId && resourceName) openVMSSDetail(resourceId, resourceName)
  } else if (resId.includes('managedclusters')) {
    if (resourceId && resourceName) openAKSDetail(resourceId, resourceName)
  } else {
    openVMDetail(incidentId, resourceId ?? null, resourceName ?? null)
  }
}}
```

**7. Add AKS tab panel after the VMSS tabpanel div:**
```tsx
        <div id="tabpanel-aks" role="tabpanel" aria-labelledby="tab-aks" hidden={activeTab !== 'aks'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <AKSTab subscriptions={selectedSubscriptions} onAKSClick={openAKSDetail} />
          </div>
        </div>
```

**8. After the VMSS Detail Panel + backdrop section — add AKS detail panel:**
```tsx
      {/* AKS Detail Panel + backdrop */}
      {aksDetailOpen && selectedAKS && (
        <>
          <div
            className="fixed inset-0 z-30"
            style={{ background: 'rgba(0,0,0,0.3)' }}
            onClick={closeAKSDetail}
          />
          <AKSDetailPanel
            resourceId={selectedAKS.resourceId}
            resourceName={selectedAKS.resourceName}
            onClose={closeAKSDetail}
          />
        </>
      )}
```
</action>

<acceptance_criteria>
- `grep "'aks'" services/web-ui/components/DashboardPanel.tsx` → matches (TabId union + TABS array)
- `grep "Container" services/web-ui/components/DashboardPanel.tsx` → matches (lucide import + TABS entry)
- `grep "AKSTab\|AKSDetailPanel" services/web-ui/components/DashboardPanel.tsx` → matches (imports + usage)
- `grep "aksDetailOpen\|selectedAKS\|openAKSDetail\|closeAKSDetail" services/web-ui/components/DashboardPanel.tsx` → matches (state + handlers)
- `grep "tabpanel-aks" services/web-ui/components/DashboardPanel.tsx` → matches
- `grep "hidden={activeTab !== 'aks'}" services/web-ui/components/DashboardPanel.tsx` → matches
- `grep "managedclusters" services/web-ui/components/DashboardPanel.tsx` → matches (AlertFeed routing)
- `grep "virtualmachinescalesets" services/web-ui/components/DashboardPanel.tsx` → matches (AlertFeed routing)
</acceptance_criteria>

---

## Verification

After completing all 9 tasks, run these checks in order:

```bash
# 1. TypeScript compilation — must be clean
cd services/web-ui && npx tsc --noEmit
# Expected: exits 0, zero errors

# 2. Python tests — full suite, no regressions
cd /path/to/repo && python -m pytest services/api-gateway/tests/ -q --tb=short
# Expected: all existing tests pass; 0 new failures

# 3. Verify 10 tabs registered
grep -c "'id'" services/web-ui/components/DashboardPanel.tsx
# Expected: >= 10 (one per TABS entry)

# 4. Tab order verification
grep "id: '" services/web-ui/components/DashboardPanel.tsx | head -20
# Expected: alerts, audit, topology, resources, vms, vmss, aks, cost, observability, patch

# 5. AKS router registered
grep -n "aks_router" services/api-gateway/main.py
# Expected: 2 lines (import + include_router)

# 6. No hardcoded Tailwind colors in any new compute files
grep -r "bg-green-\|bg-red-\|bg-yellow-\|text-green-\|text-red-\|text-yellow-" \
  services/web-ui/components/AKSTab.tsx \
  services/web-ui/components/AKSDetailPanel.tsx
# Expected: NO matches

# 7. AlertFeed routing present
grep "managedclusters\|virtualmachinescalesets" services/web-ui/components/DashboardPanel.tsx
# Expected: 2 matches (one per resource type)

# 8. All 8 proxy route files exist
ls services/web-ui/app/api/proxy/vmss/
ls services/web-ui/app/api/proxy/vmss/[vmssId]/
ls services/web-ui/app/api/proxy/aks/
ls services/web-ui/app/api/proxy/aks/[aksId]/
# Expected: route.ts files in each

# 9. Both api-gateway endpoint modules exist
ls services/api-gateway/vmss_endpoints.py services/api-gateway/aks_endpoints.py
# Expected: both files present
```

### Manual smoke test (dev server)
1. `npm run dev` from `services/web-ui/`
2. Navigate to dashboard → confirm 10 tabs visible: Alerts, Audit, Topology, Resources, VMs, VMSS, AKS, Cost, Observability, Patch
3. VMSS tab: renders skeleton rows → empty state message
4. AKS tab: renders skeleton rows → empty state message with Container icon
5. AlertFeed "Investigate" button on a VMSS resource type (`virtualmachinescalesets` in resource_id): opens VMSSDetailPanel
6. AlertFeed "Investigate" button on an AKS resource type (`managedclusters` in resource_id): opens AKSDetailPanel
7. VMSSDetailPanel: 5 tabs visible (Overview, Instances, Metrics, Scaling, AI Chat)
8. AKSDetailPanel: 5 tabs visible (Overview, Node Pools, Workloads, Metrics, AI Chat)
9. TypeScript dev server shows zero type errors

### API Gateway smoke test
```bash
cd services/api-gateway
python -c "from services.api_gateway.vmss_endpoints import router; print('vmss OK')"
python -c "from services.api_gateway.aks_endpoints import router; print('aks OK')"
# Expected: "vmss OK", "aks OK" — no import errors
```

---

## Phase 41 Completion Criteria

When both Plan 41-1 and Plan 41-2 are complete:

| Check | Expected |
|-------|----------|
| `npx tsc --noEmit` | Exits 0 |
| `pytest services/api-gateway/tests/ -q` | All existing tests pass |
| DashboardPanel TABS count | 10 |
| Tab order | alerts·audit·topology·resources·vms·vmss·aks·cost·observability·patch |
| New proxy route files | 8 (4 VMSS + 4 AKS) |
| New api-gateway modules | 2 (vmss_endpoints.py + aks_endpoints.py) |
| New frontend components | 4 (VMSSTab + VMSSDetailPanel + AKSTab + AKSDetailPanel) |
| Shared types file | 1 (azure-resources.ts with VM + VMSS + AKS types) |
| Hardcoded Tailwind colors in new files | 0 |
| CSS token badge formula used | Yes (all badges use `color-mix(in srgb, var(--accent-*) 15%, transparent)`) |
| AlertFeed routing | Routes VMSS/AKS incidents to correct detail panels |

---

## Files Created / Modified

| File | Status |
|------|--------|
| `services/web-ui/components/AKSTab.tsx` | CREATE |
| `services/web-ui/components/AKSDetailPanel.tsx` | CREATE |
| `services/web-ui/app/api/proxy/aks/route.ts` | CREATE |
| `services/web-ui/app/api/proxy/aks/[aksId]/route.ts` | CREATE |
| `services/web-ui/app/api/proxy/aks/[aksId]/metrics/route.ts` | CREATE |
| `services/web-ui/app/api/proxy/aks/[aksId]/chat/route.ts` | CREATE |
| `services/api-gateway/aks_endpoints.py` | CREATE |
| `services/web-ui/components/DashboardPanel.tsx` | MODIFY (AKS tab, AlertFeed routing) |
| `services/api-gateway/main.py` | MODIFY (aks_router include) |

**Total: 7 new files + 2 modified files**
