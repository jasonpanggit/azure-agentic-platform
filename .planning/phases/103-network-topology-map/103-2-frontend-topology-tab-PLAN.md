---
wave: 2
depends_on:
  - 103-1-backend-service-and-endpoints-PLAN.md
files_modified:
  - services/web-ui/package.json
  - services/web-ui/components/NetworkTopologyTab.tsx
  - services/web-ui/app/api/proxy/network/topology/route.ts
  - services/web-ui/app/api/proxy/network/topology/path-check/route.ts
  - services/web-ui/components/NetworkHubTab.tsx
autonomous: true
---

# Plan 103-2: Frontend — NetworkTopologyTab + Proxy Routes + Hub Wiring

## Goal

Create the React Flow network topology visualization (`NetworkTopologyTab.tsx`), proxy routes (GET topology, POST path-check), install `@xyflow/react` + `elkjs`, and wire the new tab into `NetworkHubTab.tsx`.

---

## Tasks

<task id="1">
<title>Install @xyflow/react and elkjs</title>
<read_first>
  - services/web-ui/package.json
</read_first>
<action>
Run from `services/web-ui/`:
```bash
npm install @xyflow/react elkjs
```
Verify both packages appear in `package.json` dependencies.
</action>
<acceptance_criteria>
  - grep '"@xyflow/react"' services/web-ui/package.json
  - grep '"elkjs"' services/web-ui/package.json
</acceptance_criteria>
</task>

<task id="2">
<title>Create GET proxy route for topology</title>
<read_first>
  - services/web-ui/app/api/proxy/network/peerings/route.ts (or any existing network proxy route)
  - .planning/phases/103-network-topology-map/103-PATTERNS.md
</read_first>
<action>
Create `services/web-ui/app/api/proxy/network/topology/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'
import { logger } from '@/lib/logger'

const log = logger.child({ route: '/api/proxy/network/topology' })

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl()
    const { searchParams } = request.nextUrl
    const qs = searchParams.toString()

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/network-topology${qs ? `?${qs}` : ''}`,
      {
        method: 'GET',
        headers: buildUpstreamHeaders(request),
        signal: AbortSignal.timeout(15000),
      }
    )

    const data = await res.json()
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail })
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      )
    }

    log.info('topology fetched', { nodes: data?.nodes?.length })
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    log.error('gateway unreachable', { error: message })
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    )
  }
}
```

Adjust `buildUpstreamHeaders` call to match existing proxy route signature (check if it takes `request` or `request.headers.get('Authorization'), false`).
</action>
<acceptance_criteria>
  - test -f services/web-ui/app/api/proxy/network/topology/route.ts
  - grep "getApiGatewayUrl" services/web-ui/app/api/proxy/network/topology/route.ts
  - grep "buildUpstreamHeaders" services/web-ui/app/api/proxy/network/topology/route.ts
  - grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/network/topology/route.ts
  - grep "/api/v1/network-topology" services/web-ui/app/api/proxy/network/topology/route.ts
  - grep "force-dynamic" services/web-ui/app/api/proxy/network/topology/route.ts
</acceptance_criteria>
</task>

<task id="3">
<title>Create POST proxy route for path-check</title>
<read_first>
  - services/web-ui/app/api/proxy/network/topology/route.ts (task 2)
  - .planning/phases/103-network-topology-map/103-PATTERNS.md
</read_first>
<action>
Create `services/web-ui/app/api/proxy/network/topology/path-check/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'
import { logger } from '@/lib/logger'

const log = logger.child({ route: '/api/proxy/network/topology/path-check' })

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl()
    const body = await request.json()

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/network-topology/path-check`,
      {
        method: 'POST',
        headers: {
          ...buildUpstreamHeaders(request),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    )

    const data = await res.json()
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail })
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      )
    }

    log.info('path-check complete', { verdict: data?.verdict })
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    log.error('gateway unreachable', { error: message })
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    )
  }
}
```

Adjust `buildUpstreamHeaders` call to match existing pattern.
</action>
<acceptance_criteria>
  - test -f services/web-ui/app/api/proxy/network/topology/path-check/route.ts
  - grep "async function POST" services/web-ui/app/api/proxy/network/topology/path-check/route.ts
  - grep "/api/v1/network-topology/path-check" services/web-ui/app/api/proxy/network/topology/path-check/route.ts
  - grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/network/topology/path-check/route.ts
</acceptance_criteria>
</task>

<task id="4">
<title>Create NetworkTopologyTab.tsx</title>
<read_first>
  - services/web-ui/components/VNetPeeringTab.tsx
  - services/web-ui/components/LBHealthTab.tsx
  - .planning/phases/103-network-topology-map/103-UI-SPEC.md
  - .planning/phases/103-network-topology-map/103-PATTERNS.md
  - .planning/phases/103-network-topology-map/103-RESEARCH.md
</read_first>
<action>
Create `services/web-ui/components/NetworkTopologyTab.tsx` (~400-600 lines). Structure:

**1. Imports:**
```tsx
'use client'
import { useEffect, useState, useCallback, useMemo } from 'react'
import { ReactFlow, Handle, Position, Controls, MiniMap, Background, BackgroundVariant, type Node, type Edge, type NodeProps, useNodesState, useEdgesState } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import ELK from 'elkjs/lib/elk.bundled.js'
import { Shield, Network, Scale, Lock, Globe, Waypoints, AlertTriangle, CheckCircle, XCircle, Search, RefreshCw } from 'lucide-react'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
```

**2. Constants:**
```tsx
const REFRESH_INTERVAL_MS = 10 * 60 * 1000 // 10 min
```

**3. Type interfaces:**
- `TopologyNode` — `{ id: string, type: string, label: string, data: Record<string, unknown> }`
- `TopologyEdge` — `{ id: string, source: string, target: string, type: string, data: Record<string, unknown> }`
- `TopologyData` — `{ nodes: TopologyNode[], edges: TopologyEdge[], issues: unknown[] }`
- `PathCheckResult` — `{ verdict: string, steps: PathStep[], blocking_nsg_id: string | null, source_ip: string, destination_ip: string }`
- `PathStep` — `{ nsg_id: string, nsg_name: string, direction: string, level: string, result: string, matching_rule: string, priority: number }`

**4. Custom node components (6 types, all using CSS semantic tokens per UI-SPEC.md §2):**
- `VNetNode` — container with blue border, Network icon, address space CIDR badge, subscription label
- `SubnetNode` — lighter card, subnet name + CIDR
- `NsgNode` — Shield icon + health badge pill (green/yellow/red using `color-mix` pattern). Highlighted state: red border + box-shadow when `data.highlighted`.
- `LBNode` — Scale icon + SKU badge + public IP
- `PENode` — Lock icon + target service label
- `GatewayNode` — Globe (ER) or Waypoints (VPN) icon + type/SKU

Register all in `const nodeTypes = { vnetNode: VNetNode, subnetNode: SubnetNode, nsgNode: NsgNode, lbNode: LBNode, peNode: PENode, gatewayNode: GatewayNode }`

**5. ELK layout function:**
```tsx
const elk = new ELK()
async function computeLayout(rfNodes: Node[], rfEdges: Edge[]): Promise<{ nodes: Node[], edges: Edge[] }> {
  const graph = {
    id: 'root',
    layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.spacing.nodeNode': '40', 'elk.layered.spacing.baseValue': '60' },
    children: rfNodes.map(n => ({ id: n.id, width: n.width ?? 200, height: n.height ?? 80 })),
    edges: rfEdges.map(e => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  }
  const layout = await elk.layout(graph)
  const positionedNodes = rfNodes.map(n => {
    const elkNode = layout.children?.find(c => c.id === n.id)
    return elkNode ? { ...n, position: { x: elkNode.x ?? 0, y: elkNode.y ?? 0 } } : n
  })
  return { nodes: positionedNodes, edges: rfEdges }
}
```

**6. Transform functions:**
- `transformToReactFlowNodes(apiNodes: TopologyNode[]): Node[]` — maps API nodes to React Flow nodes with `type` matching nodeTypes keys, `data` containing label + all node-specific fields, `position: { x: 0, y: 0 }` (ELK sets real positions). For VNet nodes, set `style` with blue border per UI-SPEC. For subnet nodes, set `parentId` to VNet node ID.
- `transformToReactFlowEdges(apiEdges: TopologyEdge[], issues: unknown[]): Edge[]` — maps to React Flow edges with styles per UI-SPEC §3 edge table. Asymmetry issues get red dashed animated edges.

**7. Main component `NetworkTopologyTab`:**
- Props: none (uses global subscription context or query param)
- State: `nodes/setNodes` via `useNodesState`, `edges/setEdges` via `useEdgesState`, `loading`, `error`, `topologyData` (raw API response for path checker resource list)
- Path checker state: `pathSheetOpen`, `pathSource`, `pathDest`, `pathPort` (default "443"), `pathProtocol` (default "TCP"), `pathResult`, `pathLoading`

- `fetchData` callback: GET `/api/proxy/network/topology`, transform nodes/edges, run `computeLayout`, setNodes/setEdges. Wrapped in try/catch/finally with loading/error state.
- `useEffect`: calls `fetchData()` on mount + `setInterval(fetchData, REFRESH_INTERVAL_MS)` with cleanup.

- `handlePathCheck` callback: POST `/api/proxy/network/topology/path-check` with `{ source_resource_id: pathSource, destination_resource_id: pathDest, port: parseInt(pathPort), protocol: pathProtocol }`. On result:
  - If blocking_nsg_id: highlight that node (red border + glow via setNodes), dim non-path nodes to 30% opacity, highlight path edges.
  - If allowed: highlight all path edges green.
  - Store result in `pathResult`.

- `handleClearPathCheck`: reset all node/edge styles, clear pathResult.

- **Render:**
  - Header bar: Network icon + "Network Topology" + Refresh button (calls fetchData) + Sheet trigger "Path Checker" button
  - Summary pills: VNets count, NSGs count, Issues count (red if > 0)
  - Loading state: centered spinner + "Loading network topology..." text
  - Error state: inline error banner (AlertTriangle icon, red color-mix background per UI-SPEC §6)
  - Empty state: centered Network icon 40px + "No network resources found in the current subscriptions." — NO "Run a scan" text
  - Canvas: `<ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView>` with `<Controls />`, `<MiniMap />`, `<Background variant={BackgroundVariant.Dots} />`
  - Sheet (right side): Source select (populated from topologyData nodes), Destination select, Port input, Protocol select (TCP/UDP/ICMP), "Check Path" button, verdict banner (green allowed / red blocked per UI-SPEC §5.3), step-by-step timeline (per UI-SPEC §5.4), "Clear" button

**All styling uses CSS semantic tokens only.** No hardcoded Tailwind color classes like `bg-green-100`. Use `var(--accent-*)`, `var(--bg-canvas)`, `var(--text-primary)`, `color-mix(in srgb, var(--accent-*) 15%, transparent)` for badges.
</action>
<acceptance_criteria>
  - grep "useEffect" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "REFRESH_INTERVAL_MS" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "setInterval" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "ReactFlow" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "elkjs" services/web-ui/components/NetworkTopologyTab.tsx || grep "ELK" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "/api/proxy/network/topology" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "path-check" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "var(--accent-" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "var(--bg-canvas)" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "color-mix" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "No network resources found" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "SheetContent" services/web-ui/components/NetworkTopologyTab.tsx
  - grep "nodeTypes" services/web-ui/components/NetworkTopologyTab.tsx
  - No occurrences of "scan" (case-insensitive scan button) in the file: grep -i "handleScan\|Run a scan\|scanning" services/web-ui/components/NetworkTopologyTab.tsx returns nothing
  - No hardcoded Tailwind colors: grep "bg-green-\|bg-red-\|bg-yellow-\|text-green-\|text-red-" services/web-ui/components/NetworkTopologyTab.tsx returns nothing
</acceptance_criteria>
</task>

<task id="5">
<title>Wire NetworkTopologyTab into NetworkHubTab</title>
<read_first>
  - services/web-ui/components/NetworkHubTab.tsx
  - services/web-ui/components/NetworkTopologyTab.tsx (task 4)
</read_first>
<action>
Modify `services/web-ui/components/NetworkHubTab.tsx`:

1. Add import:
   ```tsx
   import NetworkTopologyTab from './NetworkTopologyTab'
   ```

2. Add to `subTabs` array (as the FIRST entry, since topology is the primary network view):
   ```tsx
   { id: 'topology', label: 'Topology Map', icon: Network },
   ```
   Import `Network` from lucide-react (add to existing import line).

3. In the render section where sub-tab content is conditionally rendered, add:
   ```tsx
   {activeSubTab === 'topology' && <NetworkTopologyTab />}
   ```

4. Change `initialSubTab` default from `'vnet-peerings'` to `'topology'` so the topology map is the default view when opening the Network hub.
</action>
<acceptance_criteria>
  - grep "NetworkTopologyTab" services/web-ui/components/NetworkHubTab.tsx
  - grep "'topology'" services/web-ui/components/NetworkHubTab.tsx
  - grep "Topology Map" services/web-ui/components/NetworkHubTab.tsx
  - grep "initialSubTab = 'topology'" services/web-ui/components/NetworkHubTab.tsx
</acceptance_criteria>
</task>

---

## Verification

```bash
# Packages installed
grep "@xyflow/react" services/web-ui/package.json
grep "elkjs" services/web-ui/package.json

# Proxy routes exist
test -f services/web-ui/app/api/proxy/network/topology/route.ts && echo "GET proxy exists"
test -f services/web-ui/app/api/proxy/network/topology/path-check/route.ts && echo "POST proxy exists"

# Component created and wired
grep "NetworkTopologyTab" services/web-ui/components/NetworkHubTab.tsx

# No scan pattern violations
grep -ri "handleScan\|Run a scan\|scanning" services/web-ui/components/NetworkTopologyTab.tsx || echo "PASS: no scan references"

# No hardcoded Tailwind colors
grep "bg-green-\|bg-red-\|text-green-\|text-red-" services/web-ui/components/NetworkTopologyTab.tsx || echo "PASS: no hardcoded colors"

# Build check
cd services/web-ui && npx next build 2>&1 | tail -5
```

## must_haves

- [ ] React Flow canvas renders VNet, Subnet, NSG, LB, PE, Gateway nodes with custom components
- [ ] ELK.js auto-layout positions nodes hierarchically (left-to-right)
- [ ] NSG nodes show health badges (green OK / yellow WARN / red BLOCK) using color-mix semantic tokens
- [ ] Asymmetry issues auto-highlighted with red dashed animated edges on load
- [ ] Path checker side panel (shadcn Sheet): source/dest/port/protocol form → POST path-check → verdict display + canvas highlighting of blocking NSG
- [ ] `useEffect` fetches on mount, `setInterval` polls every 10 min — NO scan button
- [ ] Empty state says "No network resources found" — never "Run a scan"
- [ ] All styling uses CSS semantic tokens (`var(--accent-*)`, `var(--bg-canvas)`, `color-mix`) — no hardcoded Tailwind colors
- [ ] Proxy routes use `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout(15000)`
- [ ] NetworkHubTab wired with topology as default sub-tab
- [ ] `@xyflow/react` and `elkjs` in package.json
