---
title: Migrate NetworkTopologyTab to Cytoscape.js
slug: migrate-network-topology-cytoscape
quick_id: 260418-wjc
created: 2026-04-18
---

## Description

Replace `@xyflow/react` + ELK in `NetworkTopologyTab.tsx` with Cytoscape.js using compound node nesting (VNet → subnet → resources) and orthogonal edge routing via `cytoscape-edge-taxi`. All reusable panels (`NodeDetailPanel`, `NsgRulesTable`, `FieldRow`, `HealthBadge`, `NetworkTopologyChatPanel`) are unchanged.

## Tasks

1. **Update `package.json`** — remove `@xyflow/react` and `elkjs`; add `cytoscape`, `react-cytoscapejs`, `cytoscape-cose-bilkent`, `cytoscape-edge-taxi`, `@types/cytoscape`; run `npm install`

2. **Write `buildCytoscapeElements(nodes, edges)`** — transforms flat backend nodes/edges into Cytoscape element array:
   - VNet nodes: no parent
   - Subnet nodes: `parent = vnetId` (derived from `contains` edges)
   - Resource nodes (vm/nsg/lb/pe/gateway/vmss/aks/firewall/appgw): `parent = subnetId` (derived from `subnet-*` edges)
   - Drop `contains` edges; keep all others (peering, peering-disconnected, asymmetry, subnet-vm, subnet-nsg, etc.)

3. **Write `cytoscapeStylesheet`** — define styles for each node type using `var(--accent-*)` / `var(--bg-*)` / `var(--border)` tokens; include `.chat-highlighted`, `.path-blocked`, `.dimmed` selector styles

4. **Register Cytoscape extensions** — module-level `cytoscape.use(coseBilkent)` and `cytoscape.use(edgeTaxi)` with safe try/catch imports for SSR compatibility

5. **Rewrite the graph render section** — replace `<ReactFlow ...>` JSX with `<CytoscapeComponent elements={elements} stylesheet={stylesheet} layout={{ name: 'cose-bilkent', animate: false, nodeDimensionsIncludeLabels: true }} cy={(cy) => { cyRef.current = cy }} style={{ width: '100%', height: '100%' }} />`

6. **Wire tap event handlers** — on `cy` ready: `cy.on('tap', 'node', ...)` opens `NodeDetailPanel` with node data; `cy.on('tap', 'edge', ...)` opens panel with edge data; `cy.on('tap', handler)` on canvas background closes panel

7. **Migrate chat highlight logic** — replace React Flow node `chatHighlighted` data mutation with `cyRef.current?.nodes().removeClass('chat-highlighted')` then `.filter(match).addClass('chat-highlighted')`

8. **Migrate path-check highlight logic** — replace React Flow edge/node style updates with `.addClass('path-blocked')` on blocking NSG nodes and `.addClass('dimmed')` on all other nodes/edges; clear on reset

9. **Remove all React Flow imports and dead code** — delete imports from `@xyflow/react`, the 11 custom node type components (VNetNode, SubnetNode, NsgNode, LBNode, PENode, GatewayNode, VMNode, VMSSNode, AKSNode, FirewallNode, AppGatewayNode), ELK layout logic, and `nodeTypes` / `edgeTypes` maps

10. **Verify build and smoke test** — run `npm run build` (zero TS errors); open topology tab in dev, confirm VNet compound nesting renders, node click opens detail panel, chat highlight applies correctly
