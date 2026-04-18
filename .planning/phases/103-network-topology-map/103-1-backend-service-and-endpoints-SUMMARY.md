---
phase: 103-network-topology-map
plan: 103-1
title: "Backend — Network Topology Service & Endpoints"
status: complete
---

# Summary: 103-1 Backend Service & Endpoints

## What was done

1. **Created `network_topology_service.py`** — 7 ARG query constants (VNets/subnets, NSGs/rules, LBs, PEs, gateways, public IPs, NICs), in-memory TTL cache (900s), NSG health scoring (green/yellow/red), asymmetry detection on ports 22/80/443/3389, graph assembly (nodes + edges), and path-check evaluation with first-match-wins NSG rule logic.

2. **Created `network_topology_endpoints.py`** — `GET /api/v1/network-topology` (returns `{nodes, edges, issues}` from live ARG with 15m TTL cache) and `POST /api/v1/network-topology/path-check` (evaluates NSG rule chain on-demand, returns verdict with blocking NSG ID).

3. **Registered router in `main.py`** — imported and included `network_topology_router`.

4. **Created 20 tests** — covering NSG health scoring, port range matching, rule evaluation, asymmetry detection, topology assembly, caching behavior, path-check allowed/blocked/error scenarios.

## Acceptance criteria met

- [x] 7 ARG queries cover VNets, subnets, NSGs, LBs, PEs, gateways, NICs
- [x] GET endpoint returns `{nodes, edges, issues}` from live ARG with 900s TTL cache
- [x] POST path-check evaluates NSG rule chain and returns verdict
- [x] NSG health scoring: green/yellow/red with asymmetry auto-detection
- [x] No scan button, no Cosmos intermediary
- [x] 20 tests passing
- [x] Router registered in main.py
- [x] Public functions never raise

## Commits

1. `9ae1ead` — feat(103): add network topology service
2. `cd55675` — feat(103): add network topology endpoints
3. `ff825cc` — feat(103): register router in main.py
4. `c833df0` — test(103): add 20 tests
