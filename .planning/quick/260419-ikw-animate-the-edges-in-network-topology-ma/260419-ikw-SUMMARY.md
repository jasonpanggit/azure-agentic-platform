# Summary: Animate edges in Network Topology map tab

**Task ID:** 260419-ikw  
**Status:** ✅ Complete  
**Commit:** e749ba7

## What was done

Implemented a `requestAnimationFrame`-based edge animation loop in `NetworkTopologyTab.tsx`.

### Changes in `services/web-ui/components/NetworkTopologyTab.tsx`

1. **`animFrameRef`** — Added `useRef<number | null>(null)` to store the RAF handle.

2. **Stylesheet** — Added explicit `'line-dash-pattern': [6, 3]` to all 11 dashed membership edge selectors (`subnet-vm`, `subnet-vmss`, `subnet-nsg`, `subnet-aks`, `subnet-lb`, `subnet-appgw`, `subnet-pe`, `subnet-gateway`, `subnet-firewall`, `subnet-routetable`, `subnet-natgw`). Cytoscape requires this for `line-dash-offset` to produce a marching-ants effect.

3. **Animation loop** — Inside the `cy={...}` callback (after `cyRef.current = cy`), a RAF loop runs:
   - `offset` increments by 0.4/frame and wraps at 20; applied as `line-dash-offset` to all dashed edges.
   - `tick` increments by 0.04/frame; `width = 1.5 + Math.sin(tick) * 0.4` applied to solid traffic edges (peering, vpn-connection, lb-backend, resource-publicip, firewall-policy).
   - All style writes are batched via `cy.batch()` each frame.

4. **Cleanup `useEffect`** — Cancels the RAF on component unmount via `cancelAnimationFrame(animFrameRef.current)`.

## Acceptance criteria

- [x] Dashed edges visibly march (arrows appear to flow)
- [x] Solid traffic/peering edges have a subtle width pulse
- [x] `cy.batch()` used — no per-element style writes outside batch
- [x] RAF cancelled on unmount via cleanup `useEffect`
- [x] `tsc --noEmit` passes (no errors in NetworkTopologyTab.tsx)
