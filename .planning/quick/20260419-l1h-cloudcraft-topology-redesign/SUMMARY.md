---
id: 20260419-l1h
slug: cloudcraft-topology-redesign
status: complete
date: 2026-04-19
commit: 9a4b813
---

# Summary: Cloudcraft Canvas Light Topology Redesign

## What was done

Redesigned `NetworkTopologyTab.tsx` to use the Cloudcraft Canvas Light aesthetic chosen in the previous session.

## Changes

**`services/web-ui/components/NetworkTopologyTab.tsx`**

- **Canvas background**: `#f8fafc` with `radial-gradient(circle, #cbd5e1 1px, transparent 1px)` dot-grid at 24×24px
- **Node base style**: white `#ffffff` bg, `#e2e8f0` border, dark `#1e293b` text
- **Per-type accent**: kept colored border per resource type, updated to darker accessible shades for light bg
- **VNet special**: `#eff6ff` fill, `#3b82f6` border, `#1e40af` bold label
- **Subnet**: `#f8fafc` bg, dashed `#94a3b8` border, `#475569` label
- **External**: `#f1f5f9` bg, dashed `#cbd5e1` border
- **All edge colors**: shifted to darker accessible variants for light canvas
- **Zoom/fit toolbar**: white `#ffffff` buttons with `0 1px 3px rgba(0,0,0,0.12)` shadow
- **Minimap**: `#f8fafc` bg, `#94a3b8` node dots, `#2563eb` viewport rect, shadow
- **Legend**: white bg, `#e2e8f0` border, `0 4px 16px rgba(0,0,0,0.10)` shadow
- **Refreshing indicator**: white bg, muted text
- **CytoscapeComponent**: `background: 'transparent'` (canvas shows through)

## Verification

- `tsc --noEmit` passes for `NetworkTopologyTab.tsx` (no new errors)
- Pre-existing test type errors unrelated to this change
