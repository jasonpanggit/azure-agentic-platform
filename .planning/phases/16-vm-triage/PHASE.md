---
phase: 16
name: vm-triage
status: active
plans:
  - id: 16-01
    name: VM Inventory API
    wave: 1
    status: pending
  - id: 16-02
    name: VM Detail + Metrics API
    wave: 1
    status: pending
  - id: 16-03
    name: VMDetailPanel + Investigate CTA
    wave: 2
    status: pending
waves:
  1:
    - 16-01
    - 16-02
  2:
    - 16-03
---

# Phase 16: VM Triage Path

## Goal

Operator can click any alert, open a VM detail panel, and see pre-fetched evidence in under 2 seconds. This closes the loop from "alert fired" → "operator understands what happened and can act".

## Roadmap Reference

Corresponds to Phase 2 (VM Inventory & Detail) in `docs/roadmap/PLATFORM-ROADMAP.md`.

## What This Phase Delivers

1. **VM Inventory API** (`GET /api/v1/vms`) — ARG-backed VM fleet listing with power state, health, active alert count
2. **VM Detail API** (`GET /api/v1/vms/{id}`) — Full VM profile from ARG + Resource Health + active incidents
3. **VM Metrics API** (`GET /api/v1/vms/{id}/metrics`) — Time-series metrics via azure-mgmt-monitor
4. **VMDetailPanel** — Slide-over drawer: health badge, evidence summary, sparkline charts, active incidents
5. **Investigate CTA wired** — AlertFeed and VMTab row clicks open VMDetailPanel (replaces console.log stubs)

## Wave Execution

- **Wave 1** (parallel): 16-01 (VM Inventory API) + 16-02 (VM Detail + Metrics API)
- **Wave 2** (after Wave 1): 16-03 (VMDetailPanel + frontend wiring)

## Success Criteria for Phase

- [ ] VMTab shows real VM data when subscriptions are selected
- [ ] Clicking "Investigate" on any alert row with resource_name opens VMDetailPanel
- [ ] VMDetailPanel shows VM health, evidence summary, sparkline metrics
- [ ] `npm run build` passes
- [ ] `python -m pytest services/api-gateway/tests/ -q` passes (incl. new VM tests)
