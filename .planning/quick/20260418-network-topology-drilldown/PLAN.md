---
id: 20260418-network-topology-drilldown
slug: network-topology-drilldown
title: "Enhance NetworkTopologyTab with click-to-drill-down details"
date: 2026-04-18
---

## Goal
Add click-to-drill-down to NetworkTopologyTab nodes and issue edges so users can see:
- NSG node click → side panel with rule list, health, blocking detail
- VNet/Subnet node click → resource details (address space, subscriptions, linked resources)
- LB/PE/Gateway node click → key properties
- Issue edge click → asymmetric block detail (which NSG, which rule, direction)

## What exists
- ReactFlow canvas with custom nodes: vnetNode, subnetNode, nsgNode, lbNode, peNode, gatewayNode
- `onNodeClick` / `onEdgeClick` hooks available from ReactFlow but NOT YET wired up
- `Sheet` component already imported (used for Path Checker)
- All node `data` objects carry the API payload fields

## Tasks
1. Add `selectedNode` and `selectedEdge` state
2. Wire `onNodeClick` and `onEdgeClick` to ReactFlow
3. Build `NodeDetailPanel` component (Sheet-based) that renders details per node type:
   - NSG: rules table (priority, name, direction, access, ports, source/dest)
   - VNet: address space, subnets, peerings
   - Subnet: CIDR, NSG association, route table
   - LB: SKU, frontend IPs, backend pools
   - PE: target service, connection state, private IP
   - Gateway: type, SKU, BGP peers
4. Build `EdgeDetailPanel` for issue edges: show blocking NSG name, direction, rule
5. Add "click any node to inspect" hint text in empty state / canvas overlay

## Files to change
- `services/web-ui/components/NetworkTopologyTab.tsx` (main)
