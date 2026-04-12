# Summary: Fix VMSS and AKS Tab and Detail Panel Data Bugs

**Task:** 260411-wyg  
**Branch:** fix/vmss-aks-detail-panel-data-bugs  
**Date:** 2026-04-11  
**Status:** Complete

---

## Changes Made

### Task 1 — Frontend: Guard error responses (2 files, 8 lines added)

**VMSSDetailPanel.tsx** and **AKSDetailPanel.tsx** — added error-in-data guard before `setDetail(data)` in `fetchDetail()`:

```typescript
if ('error' in data && typeof data.error === 'string') {
  setError(data.error)
  return
}
setDetail(data)
```

**Impact:** Eliminates all "undefined" field rendering when backend throws. The error message now surfaces in the red error banner at the top of the panel instead of setting every field to `undefined`.

---

### Task 2 — Backend VMSS: Fix healthy_instance_count and health_state derivation (vmss_endpoints.py)

- **`healthy_instance_count`**: Now counts instances where `power_state` contains `"running"` (was a copy of total instance count)
- **`health_state`**: Derived from healthy/total ratio → `available` / `degraded` / `unavailable` / `unknown` (was hardcoded `"unknown"`)
- **Autoscale except**: Promoted from silent `except: pass` to `logger.warning(...)` with error context

**Logic:**
```python
running_count = sum(1 for inst in instances if "running" in (inst.get("power_state") or "").lower())
healthy_instance_count = running_count if instances else total
# total==0 → unknown, all healthy → available, none healthy → unavailable, partial → degraded
```

---

### Task 3 — Backend AKS: Debuggability improvements (aks_endpoints.py)

- Error log now includes `resource_id[:60]` for identification in Container App log streams
- Clarified code comment on `ready_nodes += pool_count` to make the ARM limitation explicit

---

## Verification

- `npm run build` → zero TypeScript errors, zero warnings
- `python3 -m pytest services/api-gateway/tests/ -x -q` → **797 passed, 2 skipped, 0 failures**

---

## Commits

| Commit | Description |
|--------|-------------|
| `438e46c` | fix: guard error responses in VMSSDetailPanel and AKSDetailPanel fetchDetail |
| `11c0f83` | fix: derive healthy_instance_count and health_state from instance power states in VMSS detail |
| `0295f3c` | fix: improve AKS detail error log with resource_id and clarify ready_nodes limitation |

---

## Acceptance Criteria Met

- [x] Opening a VMSS/AKS detail panel when backend throws shows error in UI instead of `undefined` values
- [x] VMSS Instances tab shows actual instance list when backend succeeds (unblocked by Task 1)
- [x] VMSS detail Overview shows correct `healthy_instance_count` (count of running instances)
- [x] VMSS detail `health_state` shows `available`/`degraded`/`unavailable` derived from instance running count
- [x] Autoscale fetch errors logged as warnings (not silently swallowed)
- [x] AKS detail error response includes `resource_id` in log for debuggability
- [x] `tsc --noEmit` passes (zero TypeScript errors, confirmed via `npm run build`)

## Out of Scope (deferred per plan)

- VMSS/AKS metrics implementation (Monitor SDK — Phase 36)
- VMSS list `health_state` from Resource Health API (ARG join — separate task)
- VMSS list `autoscale_enabled` (Monitor API per-resource — separate task)
- AKS node ready count accuracy (requires kubectl/k8s API)
