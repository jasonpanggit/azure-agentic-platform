---
phase: 37
status: passed
verified_at: 2026-04-11
---
# Phase 37 Verification: VM Performance Intelligence & Forecasting

## Goal

Shift from reactive to predictive. Expose `forecaster.py` as an agent-callable `@ai_function` tool. Add `query_vm_performance_baseline` (P50/P95/P99 over 30 days) and `detect_performance_drift` (drift score + narrative vs baseline).

## Verification Results

### Tools Implemented ✓

- [x] `get_vm_forecast` — wraps `ForecasterClient`, returns `imminent_breach` bool (`time_to_breach_minutes < 60`); defined at line 2177 of `agents/compute/tools.py`
- [x] `query_vm_performance_baseline` — 30-day P50/P95/P99 via `Perf` table with `InsightsMetrics` fallback; defined at line 2289
- [x] `detect_performance_drift` — drift score formula `min(100, int((recent_p95 / baseline_p95 - 1) * 100))`, `is_drifting` flag when any metric `drift_score > 30`, human-readable narrative; defined at line 2474

### Agent Registration ✓

- [x] All 3 tools in `from compute.tools import` block (`grep -c "get_vm_forecast" agent.py` → `4`)
- [x] All 3 tools in `COMPUTE_AGENT_SYSTEM_PROMPT` allowed-tools list
- [x] All 3 tools in `ChatAgent` `tools=[...]` list (`create_compute_agent`)
- [x] All 3 tools in `PromptAgentDefinition` `tools=[...]` list (`create_compute_agent_version`)

### Tests ✓

- [x] 15/15 tests passing in `agents/tests/compute/test_compute_performance.py`
- [x] `TestGetVmForecast` — 5 tests (multi-metric, all-imminent, missing env, SDK unavailable, exception)
- [x] `TestQueryVmPerformanceBaseline` — 5 tests (Perf success, InsightsMetrics fallback, missing workspace, empty result, exception)
- [x] `TestDetectPerformanceDrift` — 5 tests (drift flagged, nominal no-flag, missing workspace, zero-baseline guard, exception)

### Test Run Output

```
======================== 15 passed, 1 warning in 0.39s =========================
```

## Status: PASSED
