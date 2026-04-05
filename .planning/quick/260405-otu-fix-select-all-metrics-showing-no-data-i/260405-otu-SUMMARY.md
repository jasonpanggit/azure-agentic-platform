# Summary — 260405-otu: Fix Select All Metrics Showing No Data

**Status:** Complete
**Commit:** `696d69a`
**Branch:** `fix/patchdetailpanel-remove-overlay`

---

## What Was Done

### Task 1: Backend — Per-metric concurrent fetching (`vm_detail.py`)

Extracted a new `_fetch_single_metric(client, resource_id, metric_name, timespan, interval)` helper that:
- Calls `client.metrics.list()` with a **single** metric name
- Returns the parsed `{name, unit, timeseries}` dict, or `None` on empty response (unsupported SKU) or exception
- Catches exceptions per-metric so one bad metric never affects others

Replaced the single batched `client.metrics.list(metricnames=",".join(metric_names), ...)` call in `get_vm_metrics` with `asyncio.gather()` + `run_in_executor()` fan-out, one task per metric. `None` results are filtered before the response is returned.

**Root cause fixed:** Azure Monitor silently returns an empty response when any unsupported metric (CPU Credits Remaining, VM Availability Metric, OS Disk Queue Depth, OS Disk Bandwidth Consumed Percentage — all SKU-specific) is included in a batched request. Per-metric isolation eliminates this failure mode entirely.

### Task 2: Tests — `test_vm_metrics_batching.py` (new, 13 tests)

**Unit tests (`TestFetchSingleMetric`, 5 tests):**
- Returns metric dict on success
- Returns `None` when `response.value` is empty (unsupported SKU)
- Returns `None` on exception (never propagates)
- Calls SDK with single metric name (not comma-joined batch)
- Handles metric with no data points (empty timeseries)

**Integration tests (`TestGetVmMetricsEndpoint`, 8 tests):**
- All metrics supported → all returned
- One unsupported metric → filtered out, others still returned
- All 13 catalog metrics → only 8 supported ones returned (5 SKU-specific filtered)
- All metrics unsupported → empty list returned (not 502)
- Single metric selection still works
- Default 8 metrics behaviour unchanged; `_fetch_single_metric` called once per metric
- Bad resource ID → 400
- `MonitorManagementClient` instantiation failure → 502

---

## Results

| Check | Result |
|---|---|
| New tests (`test_vm_metrics_batching.py`) | 13/13 passed |
| Existing tests (`test_vm_detail.py`) | 28/28 passed (no regressions) |
| Frontend changes needed | None — frontend already handles empty timeseries |

---

## Files Changed

| File | Change |
|---|---|
| `services/api-gateway/vm_detail.py` | +80 / -27 — extracted `_fetch_single_metric`, refactored `get_vm_metrics` |
| `services/api-gateway/tests/test_vm_metrics_batching.py` | +392 (new file) |
