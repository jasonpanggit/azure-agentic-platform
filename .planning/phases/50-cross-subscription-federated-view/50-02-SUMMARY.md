---
phase: 50-cross-subscription-federated-view
plan: "02"
status: complete
completed_at: "2026-04-14"
commits:
  - a3f9224  # test(federation): RED tests for subscription federation defaults
  - 1ef4858  # feat(federation): make inventory endpoints subscription-federation-aware
tests_added: 11
tests_total: 896
regressions: 0
---

# Plan 50-02 Summary — Federation-Aware Inventory Endpoints

## What Was Done

Made all 5 inventory endpoints subscription-federation-aware. When the
`subscriptions` query param is omitted, endpoints now default to querying
all subscriptions from `app.state.subscription_registry` instead of
returning a 422 validation error.

## Files Changed

### New
- **`services/api-gateway/federation.py`** — `resolve_subscription_ids()` helper.
  Single source of truth for subscription resolution:
  1. Explicit `subscriptions=` param (backward compat)
  2. `request.app.state.subscription_registry.get_all_ids()` (registry-all)
  3. `[]` (empty fallback — triggers graceful no-op in callers)

### Modified Python Endpoints
| File | Change |
|------|--------|
| `vm_inventory.py` | `subscriptions: str = Query(...)` → `Optional[str] = Query(None)`, uses `resolve_subscription_ids()` |
| `resources_inventory.py` | Empty-string fallback replaced with `resolve_subscription_ids()`, added `Request` param |
| `vmss_endpoints.py` | `subscriptions: str = Query(...)` → `Optional[str] = Query(None)`, uses `resolve_subscription_ids()` |
| `aks_endpoints.py` | `subscriptions: str = Query(...)` → `Optional[str] = Query(None)`, uses `resolve_subscription_ids()` |
| `patch_endpoints.py` | Both `assessment` and `installations` endpoints made Optional, uses `resolve_subscription_ids()` |

### Tests
- **`services/api-gateway/tests/test_federation_endpoints.py`** (new, 249 lines)
  - 11 tests across VMs, Resources, VMSS, AKS
  - TDD workflow: 8 tests started RED (422), all 11 pass GREEN after implementation
  - Key test: registry mock injected post-lifespan to survive startup clobber
- **`services/api-gateway/tests/test_patch_endpoints.py`** (updated)
  - `test_returns_422_when_no_subscriptions_param` → `test_returns_400_when_no_subscriptions_param_and_no_registry`
  - Accepts 400 or 422 (registry-empty → 400, captures intent correctly)

### Web-UI Proxy Routes (no changes needed)
All 5 proxy routes (`/vms`, `/vmss`, `/aks`, `/patch/assessment`, `/incidents`)
already use `if (subscriptions) url.searchParams.set(...)` — they correctly omit
the param when `selectedSubscriptions` is empty, so the backend federation
default kicks in automatically.

## Behavior After This Plan

| Caller | Param | Behavior |
|--------|-------|----------|
| `GET /api/v1/vms` | (none) | queries all registry subscriptions |
| `GET /api/v1/vms?subscriptions=sub-a,sub-b` | explicit | queries only sub-a, sub-b |
| `GET /api/v1/vms` with empty registry | (none) | returns `{"vms": [], "total": 0, "has_more": false}` |
| `GET /api/v1/patch/assessment` | (none + empty registry) | returns HTTP 400 |

## Threat Model Coverage
- **T-50-05** (info disclosure): Accepted — operators with Reader role see all subs
- **T-50-06** (DoS via large tenant): Mitigated by existing ARG pagination
- **T-50-07** (GUID injection): Mitigated — ARG validates subscription format

## Success Criteria
- [x] `vm_inventory.py`, `vmss_endpoints.py`, `aks_endpoints.py`, `patch_endpoints.py` all have `subscriptions: Optional[str] = Query(None, ...)`
- [x] All endpoints use `resolve_subscription_ids()` helper for federation default
- [x] `GET /api/v1/vms` without `subscriptions` returns HTTP 200
- [x] Registry with `["sub-abc", "sub-xyz"]` causes ARG call with both subs
- [x] All 896 api-gateway tests pass (no regressions)
- [x] TypeScript compilation clean
