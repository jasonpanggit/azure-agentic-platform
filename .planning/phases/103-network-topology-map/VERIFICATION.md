---
phase: 103-network-topology-map
verified: 2026-04-18
verdict: PASS
---

# Phase 103 Verification — Network Topology Map

## Phase Goal

Replace the current resource-hierarchy TopologyTab with an interactive, visual network topology map using React Flow. The map renders VNets, peerings, NSGs, load balancers, private endpoints, and ExpressRoute/VPN as a live graph. NSG health badges highlight blocks automatically (green/yellow/red). An interactive path checker lets the user select source + destination resource and port/protocol to trace exactly where traffic is blocked.

---

## Plan 103-1 Must-Haves

| # | Must-Have | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `GET /api/v1/network-topology` returns `{nodes, edges, issues}` from live ARG with 900s TTL cache | ✅ PASS | `network_topology_endpoints.py` has `async def get_topology`; `_TOPOLOGY_TTL_SECONDS = 900` in service; docstring states "queried live from ARG (15m TTL cache)" |
| 2 | `POST /api/v1/network-topology/path-check` evaluates NSG rule chain and returns verdict with blocking NSG ID | ✅ PASS | `async def path_check` with `evaluate_path_check` call; returns `{verdict, steps, blocking_nsg_id, ...}` |
| 3 | NSG health scoring: green (clean), yellow (overly permissive), red (asymmetric block) | ✅ PASS | `def _score_nsg_health` returns green/yellow; `_detect_asymmetries` sets red on affected NSGs |
| 4 | Asymmetry auto-detection on common ports (22, 80, 443, 3389) | ✅ PASS | `def _detect_asymmetries` implemented; `test_detect_asymmetries_found` confirms port 443 case |
| 5 | 7 ARG queries cover VNets, subnets, NSGs, LBs, PEs, gateways, NICs | ✅ PASS | 15 occurrences of 7 query constants (`_VNET_SUBNET_QUERY`, `_NSG_RULES_QUERY`, `_LB_QUERY`, `_PE_QUERY`, `_GATEWAY_QUERY`, `_PUBLIC_IP_QUERY`, `_NIC_NSG_QUERY`) |
| 6 | No scan button, no Cosmos intermediary — ARG-backed with TTL cache | ✅ PASS | No `/scan` reference in endpoints or service; `_get_cached_or_fetch` with TTL |
| 7 | 15+ tests passing, covering scoring, assembly, path check, caching, edge cases | ✅ PASS | **20 tests — all passing** (`20 passed, 3 warnings in 0.08s`) |
| 8 | Router registered in main.py | ✅ PASS | `from services.api_gateway.network_topology_endpoints import router as network_topology_router` + `app.include_router(network_topology_router)` |

**Plan 103-1: 8/8 PASS**

---

## Plan 103-2 Must-Haves

| # | Must-Have | Result | Evidence |
|---|-----------|--------|----------|
| 1 | React Flow canvas renders VNet, Subnet, NSG, LB, PE, Gateway nodes with custom components | ✅ PASS | `nodeTypes = { vnetNode, subnetNode, nsgNode, lbNode, peNode, gatewayNode }` defined and passed to `<ReactFlow>` |
| 2 | ELK.js auto-layout positions nodes hierarchically (left-to-right) | ✅ PASS | `import ELK from 'elkjs/lib/elk.bundled.js'`; `computeLayout` with `'elk.algorithm': 'layered'`, `'elk.direction': 'RIGHT'` |
| 3 | NSG nodes show health badges (green OK / yellow WARN / red BLOCK) using color-mix semantic tokens | ✅ PASS | `badgeLabels: { green: 'OK', yellow: 'WARN', red: 'BLOCK' }`; badge uses `color-mix(in srgb, var(--accent-${healthStatus}) 15%, transparent)` |
| 4 | Asymmetry issues auto-highlighted with red dashed animated edges on load | ✅ PASS | Edge type `asymmetry` mapped to `stroke: 'var(--accent-red)', strokeDasharray: '6 4'` in `transformToReactFlowEdges` |
| 5 | Path checker side panel (shadcn Sheet): source/dest/port/protocol form → POST path-check → verdict display + canvas highlighting of blocking NSG | ✅ PASS | `SheetContent` with form; `handlePathCheck` posts to `/api/proxy/network/topology/path-check`; `blocking_nsg_id` triggers node highlighting with red border + glow |
| 6 | `useEffect` fetches on mount, `setInterval` polls every 10 min — NO scan button | ✅ PASS | `useEffect` calls `fetchData()` on mount + `setInterval(fetchData, REFRESH_INTERVAL_MS)`; grep for `handleScan\|Run a scan\|scanning` returns nothing |
| 7 | Empty state says "No network resources found" — never "Run a scan" | ✅ PASS | `"No network resources found in the current subscriptions."` confirmed in component |
| 8 | All styling uses CSS semantic tokens — no hardcoded Tailwind colors | ✅ PASS | Zero matches for `bg-green-\|bg-red-\|bg-yellow-\|text-green-\|text-red-`; all badges use `var(--accent-*)` and `color-mix` |
| 9 | Proxy routes use `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout(15000)` | ✅ PASS | Both proxy routes confirmed with all three patterns |
| 10 | NetworkHubTab wired with topology as default sub-tab | ✅ PASS | `initialSubTab = 'topology'`; `{ id: 'topology', label: 'Topology Map', icon: Network }` as first entry |
| 11 | `@xyflow/react` and `elkjs` in package.json | ✅ PASS | `"@xyflow/react": "^12.10.2"` and `"elkjs": "^0.11.1"` |

**Plan 103-2: 11/11 PASS**

---

## Test Run

```
cd services/api-gateway && python3 -m pytest tests/test_network_topology_service.py -q
20 passed, 3 warnings in 0.08s
```

---

## Dashboard Tab Compliance

| Rule | Status |
|------|--------|
| No `scanning` state variable | ✅ |
| No `handleScan` function | ✅ |
| No `POST` to a `/scan` proxy route | ✅ |
| No "Run a scan" in empty state | ✅ |
| `useEffect` fires `fetchData()` immediately on mount | ✅ |
| Empty state says "No [items] found" | ✅ |
| Backend endpoint calls service directly (no Cosmos read) | ✅ |
| Service wrapped in TTL cache (`_get_cached_or_fetch`, 900s) | ✅ |
| No `POST /scan` route | ✅ |

---

## Overall Verdict: ✅ PASS

All 19 must-haves across both plans are satisfied. 20 backend tests pass. No scan-pattern violations. No hardcoded Tailwind colors. Phase 103 goal achieved.
