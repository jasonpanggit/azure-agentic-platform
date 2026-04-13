# Quick Task 260413-ubf — Fix Container Insights Metrics Not Loading in AKS Detail Panel

**Status:** COMPLETE
**Branch:** `main` (3 atomic commits)
**Date:** 2026-04-13

---

## Summary

Fixed three bugs preventing Container Insights (Log Analytics) metrics from loading in the AKS detail panel.

## Changes

### Task 1 — Fix Python backend KQL + PARTIAL handling
**File:** `services/api-gateway/aks_endpoints.py`
**Commit:** `cf1731e`

1. **Removed `Computer has "{cluster_name}"` filter** from the KQL query — the `Perf` table `Computer` field contains node hostnames (e.g., `aks-nodepool1-12345678-vmss000000`), not the cluster name. The workspace is already scoped to this cluster, so the filter was redundant and caused zero-row results.
2. **Added PARTIAL result handling** — replaced the `if result.status == SUCCESS and result.tables:` check with the established SUCCESS/PARTIAL pattern (extract data from `.partial_data` for PARTIAL results). This matches the pattern already used in `_fetch_aks_workload_summary` and `_fetch_system_pod_health_batch`.

### Task 2 — Surface `fetch_error` in AKS detail panel frontend
**File:** `services/web-ui/components/AKSDetailPanel.tsx`
**Commit:** `7594f5d`

1. Added `metricsError` state variable
2. Updated `fetchMetrics()` to check `data.fetch_error` from the backend response and store it in state (for both `logs` and `platform` sources)
3. Updated the metrics empty-state section to display `metricsError` when present, falling back to the generic omsagent message otherwise

### Task 3 — Add tests
**File:** `services/api-gateway/tests/test_aks_la_metrics.py` (new)
**Commit:** `0f64c6f`

5 new tests:
- `test_partial_result_returns_metrics` — PARTIAL results produce valid metrics from `partial_data`
- `test_success_result_returns_metrics` — standard SUCCESS path works
- `test_empty_result_returns_empty_metrics` — zero rows return empty metrics list
- `test_no_workspace_returns_fetch_error` — missing workspace returns `fetch_error` in response
- `test_kql_does_not_filter_by_computer` — source-level verification that `Computer has` filter is removed

## Verification

- [x] `Computer has` filter removed from KQL
- [x] PARTIAL results produce metrics (not empty array)
- [x] Backend `fetch_error` displayed in UI when present
- [x] Generic omsagent message still shows when no `fetch_error`
- [x] `tsc --noEmit` passes
- [x] `npm run build` passes
- [x] All 5 new tests pass
- [x] All 16 existing AKS tests pass (no regressions)
