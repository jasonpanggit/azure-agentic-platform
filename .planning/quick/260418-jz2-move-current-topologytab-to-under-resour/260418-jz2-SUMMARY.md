# Summary: 260418-jz2 — Move TopologyTab to Resources Hub as Resource Hierarchy

**Status:** Complete  
**Commit:** 87c619d

## Changes Made

1. **Renamed** `TopologyTab.tsx` → `ResourceHierarchyTab.tsx`, export renamed from `TopologyTab` to `ResourceHierarchyTab`
2. **ResourcesHubTab.tsx** — added `GitBranch` icon import, `ResourceHierarchyTab` import, appended `resource-hierarchy` sub-tab, added render block
3. **NetworkHubTab.tsx** — removed `TopologyTab` import, removed `Network` icon import, removed Topology sub-tab entry, changed `initialSubTab` default from `'topology'` to `'vnet-peerings'`, removed topology render block

## Acceptance Criteria

- [x] `TopologyTab.tsx` no longer exists; `ResourceHierarchyTab.tsx` exists with renamed export
- [x] ResourcesHubTab shows "Resource Hierarchy" as last sub-tab, renders the tree
- [x] NetworkHubTab has no Topology sub-tab; defaults to `vnet-peerings`
- [x] No broken imports anywhere
