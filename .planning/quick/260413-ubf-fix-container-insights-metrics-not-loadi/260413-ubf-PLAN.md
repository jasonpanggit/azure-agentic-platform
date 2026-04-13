# Fix Container Insights Metrics Not Loading in AKS Detail Panel

**Type:** bug-fix
**Complexity:** quick (3 bugs, 2 files)
**Branch:** `fix/aks-container-insights-metrics`

---

## Root Cause Summary

Three bugs prevent Container Insights (Log Analytics) metrics from loading in the AKS detail panel:

1. **PARTIAL result silently dropped** — `aks_endpoints.py` line 1132 only handles `SUCCESS`, ignoring `PARTIAL` results that contain valid data via `.partial_data`. All other KQL handlers in the same file handle `PARTIAL` correctly.
2. **KQL `Computer has "{cluster_name}"` filter too restrictive** — The `Perf` table `Computer` field contains node hostnames (e.g., `aks-nodepool1-12345678-vmss000000`), not the cluster name. The workspace is already scoped to this cluster, so the filter is redundant and causes zero-row results.
3. **Frontend ignores `fetch_error` from backend** — `fetchMetrics()` in `AKSDetailPanel.tsx` does `setMetrics(data.metrics ?? [])` but never checks `data.fetch_error`, so the user sees a generic omsagent message instead of the actual error (e.g., "No Log Analytics workspace configured").

## Tasks

### Task 1 — Fix Python backend KQL + PARTIAL handling (`aks_endpoints.py`)

**File:** `services/api-gateway/aks_endpoints.py`

**Changes:**
1. **Remove `Computer has "{cluster_name}"` filter** (line 1121) — the workspace is already scoped to this cluster's Log Analytics workspace, so all `Perf | where ObjectName == "K8SNode"` data belongs to this cluster's nodes. Keep `Computer` in the `summarize ... by` clause for node labeling.
2. **Handle `LogsQueryStatus.PARTIAL`** (line 1132) — replace the single `if result.status == LogsQueryStatus.SUCCESS and result.tables:` with the established pattern from lines 180-191:
   ```python
   tables = None
   if result.status == LogsQueryStatus.SUCCESS:
       tables = getattr(result, "tables", None)
   elif result.status == LogsQueryStatus.PARTIAL:
       tables = getattr(result, "partial_data", None)
       logger.warning("aks_la_metrics: partial result for cluster=%s error=%s",
                       cluster_name, getattr(result, "partial_error", "unknown"))
   if tables:
       table = tables[0]
       ...
   ```

**Acceptance:**
- [ ] `Computer has` filter removed from KQL
- [ ] PARTIAL results produce metrics (not empty array)
- [ ] Existing tests pass; add test for PARTIAL handling

### Task 2 — Surface `fetch_error` in AKS detail panel frontend (`AKSDetailPanel.tsx`)

**File:** `services/web-ui/components/AKSDetailPanel.tsx`

**Changes:**
1. Add `metricsError` state: `const [metricsError, setMetricsError] = useState<string | null>(null)`
2. In `fetchMetrics()` (line 253-261), after `setMetrics(data.metrics ?? [])`, check `data.fetch_error` and call `setMetricsError(data.fetch_error)`. Clear `setMetricsError(null)` at function entry.
3. In the empty state section (lines 1025-1053), when `metricsSource === 'logs'` and `metricsError` is set, display `metricsError` instead of the generic omsagent message.

**Acceptance:**
- [ ] Backend `fetch_error` displayed in UI when present
- [ ] Generic omsagent message still shows when no `fetch_error`
- [ ] `tsc --noEmit` passes

### Task 3 — Add/update tests

**Changes:**
1. Add unit test for PARTIAL result handling in LA metrics endpoint
2. Verify existing aks_endpoints tests still pass

**Acceptance:**
- [ ] New test covers PARTIAL result scenario
- [ ] All existing tests pass (`pytest services/api-gateway/`)
- [ ] `npm run build` passes for web-ui
