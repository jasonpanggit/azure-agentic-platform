# Context — Migrate NetworkTopologyTab to Cytoscape.js

## Decision Log

| Question | Decision | Rationale |
|---|---|---|
| Layout style | **Compound nesting** | VNets contain subnets, subnets contain VMs/NSGs. Matches Azure Portal spatial hierarchy. |
| Edge routing | **Taxi/orthogonal** | No overlapping lines. Cytoscape `edge-taxi` extension routes around nodes. |
| Layout algorithm | **`cose-bilkent`** | Best for compound graphs with nested nodes; respects parent boundaries. |

## Current State

- React Flow (`@xyflow/react ^12.10.2`) + ELK for layout
- `NetworkTopologyTab.tsx` — ~1470 lines, all in one file
- 11 custom node types (VNetNode, SubnetNode, NsgNode, LBNode, PENode, GatewayNode, VMNode, VMSSNode, AKSNode, FirewallNode, AppGatewayNode)
- `NodeDetailPanel` (Sheet), `NsgRulesTable`, `FieldRow`, `HealthBadge` — all reusable, no React Flow dependency
- `NetworkTopologyChatPanel` — separate component, no React Flow dependency
- Path checker, asymmetry detection, peering edges all working

## Scope

**In scope:**
- Replace `@xyflow/react` with `cytoscape` + `react-cytoscapejs`
- Add `cytoscape-cose-bilkent` for compound layout
- VNets as parent nodes containing subnet children
- Subnets as parent nodes containing VM/NSG/LB/PE/GW children
- Orthogonal edge routing via `cytoscape-edge-taxi` or straight bezier fallback
- Preserve NodeDetailPanel, NsgRulesTable, HealthBadge, FieldRow (zero changes)
- Preserve NetworkTopologyChatPanel (zero changes)
- Preserve path checker, chat highlight, asymmetry edges
- Keep semantic CSS token system (`var(--accent-*)`)
- MiniMap equivalent via Cytoscape navigator extension or built-in pan/zoom

**Out of scope:**
- Backend changes
- Changing the node data model
- Changing the API proxy routes

## Files to Modify

- `services/web-ui/components/NetworkTopologyTab.tsx` — primary migration
- `services/web-ui/package.json` — add cytoscape packages, remove @xyflow/react
