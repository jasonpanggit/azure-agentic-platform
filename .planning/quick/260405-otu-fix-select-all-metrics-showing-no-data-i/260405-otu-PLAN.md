# Fix: Select All Metrics Showing No Data

**ID:** 260405-otu
**Type:** Bug fix
**Files:** `services/api-gateway/vm_detail.py`, `tests/api-gateway/test_vm_metrics_batching.py`

---

## Problem

When a user clicks "All" in the VM Detail Panel metric selector (selecting all 13 metrics), the chart shows **NO data**. Default 8 metrics or any subset works fine.

**Root cause:** Azure Monitor `metrics.list()` returns empty when *any* requested metric name is unsupported for the VM's SKU. Metrics like `CPU Credits Remaining/Consumed` (B-series only), `VM Availability Metric`, `OS Disk Queue Depth`, and `OS Disk Bandwidth Consumed Percentage` only exist on specific VM SKUs. Including them in a single batch request poisons the entire response.

**Current code** (`vm_detail.py:326-332`):
```python
response = client.metrics.list(
    resource_uri=resource_id,
    metricnames=",".join(metric_names),  # <-- ALL metrics in one call
    ...
)
```

---

## Fix: Per-Metric Requests with Graceful Fallback

**Strategy:** Request each metric individually via `metrics.list()`. Merge results. Unsupported metrics return empty timeseries and are simply omitted from the response. This is the most correct approach — users can select any metric, and supported ones always show data.

**Why not batch?** Azure Monitor allows batching, but a single unsupported metric in the batch silently empties the entire response. Per-metric requests isolate failures.

**Performance mitigation:** Use `asyncio.gather()` with `run_in_executor()` to fetch all metrics concurrently (same pattern as `get_vm_detail` which already parallelizes ARG + health). 13 parallel requests complete in ~1 RTT.

---

## Tasks

### Task 1: Backend — Per-metric concurrent fetching in `get_vm_metrics`

**File:** `services/api-gateway/vm_detail.py`

**Changes to `get_vm_metrics` (line 291-371):**

1. Create a helper `_fetch_single_metric(client, resource_id, metric_name, timespan, interval)` that:
   - Calls `client.metrics.list()` with a single `metricnames=metric_name`
   - Returns the parsed metric dict `{name, unit, timeseries}` or `None` on failure/empty
   - Catches exceptions per-metric (logs warning, returns `None`)

2. In `get_vm_metrics`, replace the single `client.metrics.list()` call with:
   - Create the `MonitorManagementClient` once
   - Use `asyncio.gather()` + `run_in_executor()` to call `_fetch_single_metric` for each metric concurrently
   - Filter out `None` results (unsupported/empty metrics)
   - Return merged list

**No frontend changes needed** — the frontend already handles metrics with empty timeseries gracefully (line 775: `metrics.every(m => m.timeseries.length === 0)` shows "No metrics available", individual empty metrics just don't render sparklines).

### Task 2: Tests — Verify batching behavior

**File:** `tests/api-gateway/test_vm_metrics_batching.py` (new)

1. Test that when one metric fails, others still return data (mock `client.metrics.list` to raise on specific metric names)
2. Test that empty timeseries metrics are filtered from the response
3. Test concurrent fetching returns same structure as before for valid metrics
4. Test all 13 catalog metrics requested — verify partial results returned

---

## Acceptance Criteria

- [ ] Clicking "All" in metric selector shows data for supported metrics (not blank)
- [ ] Unsupported metrics silently omitted (no error shown to user)
- [ ] Default 8 metrics behavior unchanged
- [ ] Single metric selection still works
- [ ] Existing `test_vm_detail.py` tests pass (no regression)
- [ ] New batching tests pass
- [ ] `npm run build` passes (no frontend changes needed)

---

## Estimated Scope

- ~50 lines changed in `vm_detail.py` (extract helper + refactor `get_vm_metrics`)
- ~80 lines new test file
- No frontend changes
