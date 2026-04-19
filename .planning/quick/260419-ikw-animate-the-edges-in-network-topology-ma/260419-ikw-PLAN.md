# Plan: Animate edges in Network Topology map tab

**Task ID:** 260419-ikw  
**Type:** quick  
**File:** `services/web-ui/components/NetworkTopologyTab.tsx`

---

## Objective

Animate the edges in the Cytoscape network topology map to give a live "data flow" feel. The approach is a **marching-ants animation** using `requestAnimationFrame` to continuously increment `line-dash-offset` on all dashed edges and a subtle `opacity` pulse on solid traffic edges (peering, VPN, etc.).

---

## Approach

Cytoscape.js supports programmatic style updates via `cy.style()` and per-element `ele.style()`. A `requestAnimationFrame` loop runs after the `cy` instance is initialized, incrementing a shared offset counter each frame. Two animation tiers:

1. **Dashed membership edges** (`subnet-vm`, `subnet-nsg`, etc.) — marching ants via `line-dash-offset` cycling from 0 → 20.
2. **Solid traffic edges** (`peering`, `vpn-connection`, `lb-backend`, etc.) — subtle `width` pulse (1.5→2.5) driven by a sine wave.

The animation RAF handle is stored in a `useRef` and cancelled on component unmount.

---

## Tasks

### Task 1 — Add edge animation loop to `NetworkTopologyTab.tsx`

**Changes:**
- Add `animFrameRef = useRef<number | null>(null)` for the RAF handle.
- In the `cy(...)` callback (where `cyRef.current = cy` is set), start a `requestAnimationFrame` loop:
  - Track `offset` counter (increments by ~0.4 per frame, wraps at 20).
  - Track `tick` counter for sine-wave pulse.
  - Each frame call `cy.batch(() => { ... })` to apply:
    - `line-dash-offset: offset` on edges matching dashed membership selectors.
    - `width` animated via `1.5 + Math.sin(tick) * 0.4` on solid traffic edges.
  - Store the RAF id in `animFrameRef.current`.
- Add a `useEffect` cleanup that calls `cancelAnimationFrame(animFrameRef.current)` on unmount.
- Update the stylesheet: ensure all animated dashed edges have `line-dash-pattern: [6, 3]` explicitly (Cytoscape needs this for `line-dash-offset` to have effect).

**Acceptance:**
- [ ] Dashed edges visibly march (arrows appear to flow).
- [ ] Solid traffic/peering edges have a subtle width pulse.
- [ ] No performance degradation (use `cy.batch()` to batch style writes).
- [ ] RAF cancelled on component unmount (no memory leak).
- [ ] `tsc --noEmit` passes.
