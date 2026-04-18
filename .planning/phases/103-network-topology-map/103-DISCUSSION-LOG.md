# Phase 103: Network Topology Map - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 103-network-topology-map
**Areas discussed:** Visualization Library, Topology Scope, NSG Analysis Approach, Issue Auto-Highlighting

---

## Visualization Library

| Option | Description | Selected |
|--------|-------------|----------|
| React Flow | Production-grade interactive graph library; custom nodes, zooming, panning, animated edges; actively maintained | ✓ |
| D3.js | Low-level SVG; maximum flexibility but high implementation cost | |
| Cytoscape.js | Network/graph focused; less React-native | |

**User's choice:** Whatever is future-proof with ability to highlight network issues automatically and allow troubleshooting by drilling down  
**Notes:** React Flow selected as the library that best supports interactive highlighting and drill-down troubleshooting workflows.

---

## Topology Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Virtual Networks & Peerings | VNet nodes with peering edges | ✓ |
| Load Balancers & Public IPs | LB nodes with associated public IP labels | ✓ |
| Private Endpoints & DNS | PE nodes linked to parent VNet | ✓ |
| ExpressRoute / VPN | Gateway nodes with circuit/tunnel labels | ✓ |
| NSGs | NSG nodes attached to subnets/NICs | ✓ |

**User's choice:** All five domains  
**Notes:** User specifically called out NSG block highlighting as the primary use case — auto-detect when source NSG allows but destination NSG blocks, and visualize this on the map.

---

## NSG Analysis Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Health badges only | Pre-computed green/yellow/red on each NSG node at load time | |
| Interactive path checker only | User selects src+dst+port to trace the NSG chain | |
| Both badges + interactive checker | Health badges surface issues automatically; path checker enables drill-down | ✓ |

**User's choice:** Both badges + interactive checker  
**Notes:** User's exact framing: "highlight network issues automatically and allow me to troubleshoot any network issues by drilling down." This maps directly to: badges for automatic detection, path checker for drill-down investigation.

---

## Claude's Discretion

- Node visual styling (colors, icons)
- Whether to use dagre or elkjs for auto-layout
- Path checker UX (drawer vs side panel)
- NSG badge scoring thresholds

## Deferred Ideas

- Multi-subscription topology stitching
- ExpressRoute circuit health metrics  
- Topology change history / diff view
