---
wave: 1
plan: 16-01
status: complete
commit: b8af763
date: 2026-04-02
---

# Plan 16-01 Summary: VM Inventory API Endpoint

## Outcome

**All success criteria met. 20/20 tests pass. 319/319 existing tests still pass.**

## What Was Built

### `services/api-gateway/vm_inventory.py` (new — 405 lines)

Full implementation of `GET /api/v1/vms`:

| Component | Description |
|---|---|
| `_run_arg_query` | ARG pagination helper — same pattern as `patch_endpoints.py` |
| `_build_vm_kql` | KQL builder with power-state and name-contains filters; single-quote escaping |
| `_get_health_states_sync` | Sync `azure-mgmt-resourcehealth` SDK, iterates resource IDs, runs in thread-pool executor |
| `_get_alert_counts` | Cosmos incidents container query, counts open incidents per resource_id |
| `_normalize_power_state` | Maps ARG display strings → canonical short form (running/deallocated/stopped/starting/deallocating/unknown) |
| `list_vms` route | Orchestrates 3 joins with structured logging and duration_ms at each step |

**Query parameters:** `subscriptions` (required), `status`, `search`, `limit`, `offset`

**Response:** `{ vms: [...], total: int, has_more: bool }` — each VM has all 13 required fields.

**Graceful degradation:**
- ARG failure → empty list (no 500)
- Resource Health failure → `health_state: "Unknown"` per VM
- Cosmos absent/failure → `active_alert_count: 0` per VM

### `services/api-gateway/main.py` (pre-registered by Phase 15)

`vm_inventory_router` import and `app.include_router(vm_inventory_router)` were already present from Phase 15's commit (`fd55bcf`). No additional changes needed.

### `services/api-gateway/tests/test_vm_inventory.py` (new — 308 lines, 20 tests)

| Test Group | Tests | Covers |
|---|---|---|
| `_normalize_power_state` | 7 | running, deallocated, stopped, starting, deallocating, empty, unrecognized |
| `_build_vm_kql` | 6 | no filter, order-by present, no spurious powerState clause, running/deallocated filter, search, quote escaping |
| Route integration | 7 | success shape + all 13 fields, ARG failure → 200 empty, pagination has_more=True, pagination last page, empty subscriptions, Cosmos alert enrichment |

## Key Implementation Decisions

1. **Sync SDK in executor** — `azure-mgmt-resourcehealth` has no async client. Used `asyncio.get_running_loop().run_in_executor(None, _get_health_states_sync, ...)` instead of the plan's async fan-out pattern. This is the same pattern used by `patch_endpoints.py` for LAW queries.

2. **No new requirements** — `azure-mgmt-resourcehealth>=1.0.0` was already in `requirements.txt` from Phase 15 (diagnostic pipeline). No additions needed.

3. **Health join serial not parallel** — The sync SDK runs all health checks serially in a single thread. For large pages (up to 500 VMs), this could be slow. Phase 17 can parallelize with `ThreadPoolExecutor` if latency becomes an issue.

## Success Criteria Verification

- [x] `GET /api/v1/vms?subscriptions=sub1` returns `{ vms: [...], total: N, has_more: bool }`
- [x] Each VM has: id, name, resource_group, subscription_id, location, size, os_type, os_name, power_state, health_state, ama_status, active_alert_count, tags
- [x] ARG failure returns empty list (not 500) — `test_list_vms_arg_failure_returns_empty_not_500`
- [x] 20 unit tests pass: `python3 -m pytest services/api-gateway/tests/test_vm_inventory.py -v`
- [x] All existing API gateway tests still pass: `319 passed, 2 skipped`

## Files Changed

| File | Action | Lines |
|---|---|---|
| `services/api-gateway/vm_inventory.py` | Created | 405 |
| `services/api-gateway/tests/test_vm_inventory.py` | Created | 308 |
| `services/api-gateway/main.py` | Pre-registered by Phase 15 — no change needed | — |
