# Plan: Fix VMSS and AKS Tab and Detail Panel Data Bugs

**Mode:** quick  
**Date:** 2026-04-11  
**Branch:** fix/vmss-aks-detail-panel-data-bugs

---

## Problem Summary

Three categories of bugs make the VMSS and AKS detail panels show incorrect or missing data:

1. **Error response guard (CRITICAL)** — Backend returns `{"error": "..."}` on exception; frontend does `setDetail(data)` unconditionally, so all fields become `undefined`
2. **Hardcoded stubs** — `health_state = "unknown"`, `healthy_instance_count = instance_count`, `autoscale_enabled = false` hardcoded in KQL/Python
3. **Metrics always empty** — Both metrics endpoints return bare `[]` with a "deferred" comment

---

## Tasks

### Task 1 — Frontend: Guard error responses in both detail panels
**Files:** `VMSSDetailPanel.tsx`, `AKSDetailPanel.tsx`

In `fetchDetail()` in both panels, after `const data = await res.json()`, add a guard before calling `setDetail(data)`:

```typescript
// VMSSDetailPanel.tsx — inside fetchDetail(), after const data = await res.json()
if ('error' in data && typeof data.error === 'string') {
  setError(data.error)
  return
}
setDetail(data)

// AKSDetailPanel.tsx — same pattern
if ('error' in data && typeof data.error === 'string') {
  setError(data.error)
  return
}
setDetail(data)
```

This is the #1 priority fix — it stops all "undefined" display bugs when the backend throws.

---

### Task 2 — Backend VMSS: Fix `healthy_instance_count` and `health_state` derivation
**File:** `services/api-gateway/vmss_endpoints.py`

**2a — Detail endpoint (line ~255):**  
Replace `"healthy_instance_count": int(vmss.sku.capacity or 0)` with a count of instances where `power_state` is running (derived from the already-fetched `instances` list):

```python
# Count running instances as "healthy" proxy
running_count = sum(
    1 for inst in instances
    if "running" in (inst.get("power_state") or "").lower()
)
healthy_instance_count = running_count if instances else int(vmss.sku.capacity or 0)

# Derive health_state from healthy ratio
total = int(vmss.sku.capacity or 0) if vmss.sku else 0
if total == 0:
    health_state = "unknown"
elif healthy_instance_count == total:
    health_state = "available"
elif healthy_instance_count == 0:
    health_state = "unavailable"
else:
    health_state = "degraded"
```

Then use `healthy_instance_count` and `health_state` in the returned dict (replacing the hardcoded values at lines ~255 and ~259).

**2b — List endpoint (lines ~120–121):**  
The KQL hardcodes `health_state = 'unknown'` and `autoscale_enabled = false` — these cannot be fixed with a simple KQL join (Resource Health requires a separate ARG table join that may not be available). Accept this limitation:
- Keep `health_state = "unknown"` for list view (only meaningful when viewing detail anyway)
- Keep `autoscale_enabled = false` for list view (only shown in detail Scaling tab)
- Add a log comment explaining this is a known limitation

**2c — Detail endpoint: fix silent `except: pass` on autoscale (line ~243):**
```python
except Exception as autoscale_exc:
    logger.warning("vmss_detail: autoscale query failed error=%s", autoscale_exc)
```

---

### Task 3 — Backend AKS: Ensure detail endpoint returns full shape on error; fix error guard
**File:** `services/api-gateway/aks_endpoints.py`

**3a — Detail endpoint error response (line ~264):**  
Currently returns `{"error": str(exc)}` — missing all expected fields. The frontend guard from Task 1 handles this correctly now. But also log the error with more context:

```python
except Exception as exc:
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.error("aks_detail: resource_id=%s error=%s duration_ms=%.1f", resource_id[:60], exc, duration_ms)
    return {"error": str(exc)}
```

(Already has the right shape; just ensure the log includes resource_id for debuggability — change from the current `aks_detail: error=%s duration_ms=%.1f`.)

**3b — Node counts (lines ~223–224):**  
`ready_nodes += pool_count` copies total, same as VMSS bug. Since ARM doesn't expose per-pool health, this is a known limitation — but add a code comment:

```python
ready_nodes += pool_count  # ARM does not expose per-pool node health; assumes all nodes ready
```

No logic change needed here since AKS node pool ready count from ARM is genuinely unavailable without kubectl.

---

## Acceptance Criteria

- [ ] Opening a VMSS/AKS detail panel when the backend throws shows the error message in the UI instead of rendering `undefined` values everywhere
- [ ] VMSS Instances tab shows actual instance list when backend succeeds (instances were already fetched — Bug 1 fix unblocks this)
- [ ] VMSS detail panel Overview shows correct `healthy_instance_count` (count of running instances, not copy of total)
- [ ] VMSS detail panel `health_state` shows `available`/`degraded`/`unavailable` derived from instance running count
- [ ] Autoscale fetch errors are logged as warnings (not silently swallowed)
- [ ] AKS detail error response includes `resource_id` in the log for debuggability
- [ ] `tsc --noEmit` passes (no TypeScript errors)

## Out of Scope (deferred)

- VMSS/AKS metrics implementation (Monitor SDK required — separate task)
- VMSS list `health_state` from Resource Health API (requires ARG join — separate task)
- VMSS list `autoscale_enabled` (requires Monitor API per-resource — separate task)
- AKS node ready count accuracy (requires kubectl/k8s API — not available from ARM)

---

## Execution Order

1. Task 1 (frontend guard) — highest impact, 4 lines changed
2. Task 2 (VMSS backend healthy count + health_state + autoscale log) — medium impact
3. Task 3 (AKS log improvement) — low impact, cosmetic

All changes are minimal and surgical. No new dependencies introduced.
