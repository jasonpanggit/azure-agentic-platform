# Phase 103: Network Topology Map - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the current `TopologyTab.tsx` (a resource hierarchy tree) with an interactive visual network topology map. The map shows real Azure network topology — VNets, peerings, NSGs, LBs, private endpoints, and ExpressRoute/VPN — as a live, navigable graph. NSG health is surfaced automatically (badges on each NSG node). An interactive path checker lets operators select source + destination + port to trace exactly where NSG rules block traffic.

The existing `TopologyTab.tsx` resource hierarchy is NOT discarded — it is relocated to the Resources main tab where a resource-hierarchy view belongs.

</domain>

<decisions>
## Implementation Decisions

### Visualization Library
- **D-01:** Use **React Flow** (`@xyflow/react`) for the network graph canvas. It supports custom nodes, zooming, panning, animated edges, and is production-grade/future-proof for interactive diagrams in React.

### Topology Scope
- **D-02:** Include all five network domains in the map:
  1. Virtual Networks & Peerings (VNet nodes, peering edges)
  2. Load Balancers & Public IPs (LB nodes with associated public IP labels)
  3. Private Endpoints & DNS (PE nodes linked to their parent VNet)
  4. ExpressRoute / VPN Gateways (gateway nodes with circuit/tunnel labels)
  5. Network Security Groups (NSG nodes attached to subnets/NICs)

### NSG Health Analysis
- **D-03:** **Both** pre-computed health badges AND an interactive path checker:
  - **Health badges:** Each NSG node gets a badge (🟢 green / 🟡 yellow / 🔴 red) computed from rule analysis at load time. Red = asymmetric block (one side allows, other denies). Yellow = overly permissive (Any/Any allow rules). Green = clean.
  - **Interactive path checker:** Side panel where the user picks source resource, destination resource, port, and protocol. The backend evaluates the NSG rule chain and returns a step-by-step verdict: which NSG in the path is blocking (or allowing) the traffic. The map highlights the blocking NSG node in red.

### Issue Auto-Highlighting
- **D-04:** On initial load, the map automatically flags NSG asymmetry issues (source allows but destination blocks). Blocked paths are shown with a red dashed edge between the two affected nodes. This surfaces problems without requiring any user action.

### Data Loading Pattern
- **D-05:** Follow the ARG-backed tab pattern (no scan button):
  - `useEffect` calls `fetchTopology()` on mount
  - `setInterval` polls every 10 minutes (`REFRESH_INTERVAL_MS`)
  - Backend calls ARG directly via `arg_cache.get_cached()` with 900s TTL (resource inventory tier)
  - Path check (`POST /api/v1/network-topology/path-check`) is on-demand, not cached

### Layout
- **D-06:** Hierarchical left-to-right layout grouping by subscription → VNet. Use React Flow's `dagre` or `elkjs` auto-layout so the graph positions itself rather than requiring manual node placement. User can still drag nodes and pan/zoom freely.

### Current TopologyTab Migration
- **D-07:** Move the existing `TopologyTab.tsx` (resource hierarchy tree) to the Resources main tab. It renders a collapsible subscription → resource group → resource tree, which fits naturally there. The Network section "Topology" tab is replaced entirely by the new `NetworkTopologyTab.tsx`.

### Claude's Discretion
- Visual styling of nodes (colors, icons, shape) — follow the existing CSS semantic token system (`var(--accent-*)`, `var(--bg-canvas)`, etc.)
- Exact node grouping / clustering approach (VNet as container node vs standalone with child edges)
- Whether to use elkjs or dagre for auto-layout — pick whichever integrates more cleanly with React Flow v12+
- Path checker UX details (drawer vs side panel, exact form layout)
- NSG rule scoring thresholds for yellow vs red badges

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Topology Backend (Phase 22)
- `.planning/phases/22-resource-topology-graph/` — Phase 22 built Cosmos DB adjacency-list graph, ARG bootstrap, and topology API endpoints (blast-radius, path query, snapshot). Reuse ARG query patterns and the topology service structure.

### Dashboard Tab Conventions
- `CLAUDE.md` §"Dashboard Tab Implementation Rules" — MANDATORY. ARG-backed tabs must query live on mount, use `arg_cache.get_cached()`, no scan button, no Cosmos intermediary.
- `CLAUDE.md` §"Frontend Patterns" — proxy route pattern, CSS semantic token system, dark-mode badge pattern.

### Existing Tab Examples (pattern references)
- `services/web-ui/components/VNetPeeringTab.tsx` — canonical ARG-backed tab pattern (useEffect + setInterval + live fetch)
- `services/web-ui/components/LBHealthTab.tsx` — same pattern; second reference
- `services/web-ui/components/TopologyTab.tsx` — current file being replaced; read to understand what to migrate to Resources tab

### ARG Cache Pattern
- `services/api-gateway/app/shared/arg_cache.py` — `get_cached(key, subscription_ids, ttl_seconds, fetch_fn)` — wrap all ARG calls here

### Tech Stack
- `CLAUDE.md` §"Frontend (Next.js + Tailwind CSS + shadcn/ui)" — React Flow, Next.js App Router SSE, shadcn/ui component inventory
- `CLAUDE.md` §"Technology Stack" — full stack reference including `azure-cosmos`, `azure-ai-projects`, Tailwind v3.4.19

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/web-ui/components/VNetPeeringTab.tsx` — copy the useEffect + setInterval + fetchData() scaffold
- `services/web-ui/components/LBHealthTab.tsx` — same scaffold; LB data shapes will be reused in topology
- `services/web-ui/components/TopologyTab.tsx` — move (not delete) to Resources tab
- `services/api-gateway/app/shared/arg_cache.py` — wrap all new ARG queries here
- `services/web-ui/app/api/proxy/` — proxy route pattern with `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout(15000)`
- shadcn/ui `sheet` component (already installed) — use for the path checker side panel

### Established Patterns
- **ARG backend:** `network_vnet_peering_service.py` / `lb_health_service.py` for ARG query structure
- **Endpoint pattern:** `vnet_peering_endpoints.py` / `lb_health_endpoints.py` for FastAPI endpoint structure
- **CSS tokens:** `var(--accent-blue)`, `var(--accent-red)`, `var(--accent-yellow)`, `var(--bg-canvas)`, `var(--text-primary)`, `var(--border)` — never hardcode Tailwind colors
- **Badge backgrounds:** `color-mix(in srgb, var(--accent-*) 15%, transparent)` for dark-mode-safe badges

### Integration Points
- `services/web-ui/components/NetworkTab.tsx` (or equivalent network tab router) — replace Topology tab entry with `NetworkTopologyTab`
- `services/web-ui/components/ResourcesTab.tsx` (or equivalent) — add the existing TopologyTab here
- `services/api-gateway/app/main.py` — register new routers (`network_topology_endpoints`)
- `services/api-gateway/app/api/` — add `network_topology_endpoints.py` and `network_topology_service.py`

</code_context>

<specifics>
## Specific Ideas

- **NSG asymmetry highlight:** User's exact requirement: "if a rule in source NSG allows but nothing in destination NSG is allowing this traffic" — this is the primary issue to auto-detect and visualize on the map.
- **Drill-down troubleshooting:** Map should show the problem at a glance, then let the user click into the path checker to investigate source→destination→port without leaving the page.
- **Future-proof library:** React Flow was chosen explicitly because of interactive troubleshooting capability (highlighting specific nodes/edges in response to path-check results) — the path check result should animate/highlight the blocking node on the canvas.

</specifics>

<deferred>
## Deferred Ideas

- Multi-subscription topology stitching (cross-subscription peerings) — deferred; single subscription view first
- ExpressRoute circuit health metrics (latency, BGP state) — deferred to a future monitoring phase
- Topology change history / diff view — deferred

</deferred>

---

*Phase: 103-network-topology-map*
*Context gathered: 2026-04-18*
