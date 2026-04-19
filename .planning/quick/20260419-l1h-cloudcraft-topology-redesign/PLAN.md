---
id: 20260419-l1h
slug: cloudcraft-topology-redesign
description: Implement Cloudcraft Canvas Light redesign for NetworkTopologyTab
date: 2026-04-19
---

# Quick Task: Cloudcraft Canvas Light Topology Redesign

## Goal

Redesign the NetworkTopologyTab to match the "Cloudcraft Canvas Light" aesthetic chosen by the user:
- Light dot-grid canvas (#f8fafc bg)
- White node cards with colored left-border gradient accent per resource type
- Colored edges per relationship type
- White pill toolbar with shadow
- High contrast, presentation-ready look

## File to Edit

`services/web-ui/components/NetworkTopologyTab.tsx`

## Must-Haves

1. Canvas background: `#f8fafc` with dot-grid (`radial-gradient(circle, #cbd5e1 1px, transparent 1px)` at 24x24px)
2. Node base style: white bg `#ffffff`, light gray border `#e2e8f0`, dark label text `#1e293b`
3. Per-type left-border accent: gradient stops `0 3 3 100` (accent at 3% from left), giving a sharp 3px colored left band
4. VNet node: light blue fill `#eff6ff`, blue border `#bfdbfe`, dark blue label `#1e40af`
5. Subnet node: `#f8fafc` bg, dashed `#94a3b8` border, muted label `#475569`
6. External node: `#f1f5f9` bg, dashed `#cbd5e1` border
7. Selected node: `#3b82f6` border, 2.5px
8. Edges: default `#cbd5e1`, all colored edges keep their accent colors
9. Zoom/fit toolbar buttons: `#ffffff` bg, `#e2e8f0` border, subtle shadow `0 1px 3px rgba(0,0,0,0.12)`, icon color `#475569`
10. Minimap: `#f8fafc` bg, `#e2e8f0` border, node dots `#94a3b8`, viewport rect `#3b82f6`
11. Legend popup: white bg, `#e2e8f0` border, shadow, dark text
12. Refreshing indicator: white bg, muted text
13. CytoscapeComponent `background: 'transparent'`

## Steps

1. Replace `cytoscapeStylesheet` const:
   - Base node: white bg, light border, dark text
   - Per-type gradient stops for left accent
   - VNet, Subnet, External special overrides
   - Selected, health, highlight, dimmed selectors adjusted for light bg
   
2. Update canvas wrapper div style:
   - Remove `background: 'var(--bg-canvas)'`
   - Add `background: '#f8fafc'` + dot-grid `backgroundImage` + `backgroundSize: '24px 24px'`
   
3. Update CytoscapeComponent `style` background to `'transparent'`

4. Update zoom/fit toolbar buttons to white/shadow style

5. Update minimap canvas style to white/light, update renderMinimap dot/viewport colors

6. Update LegendOverlay styles to white/light bg with shadow

7. Update "refreshing" indicator to white/light style
