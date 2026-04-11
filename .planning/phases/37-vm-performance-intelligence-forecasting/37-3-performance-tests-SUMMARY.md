---
plan: 37-3
status: complete
commit: 53ca5a4
tests_added: 15
tests_passed: 15
---

# Summary: Plan 37-3 — Unit Tests for Performance Intelligence Tools

## What Was Done

Created `agents/tests/compute/test_compute_performance.py` with 15 unit tests
covering the three Phase 37 performance intelligence tool functions.

## Test File

**`agents/tests/compute/test_compute_performance.py`** — 609 lines, 15 tests, 3 classes.

## Test Classes

### TestGetVmForecast (5 tests)

| Test | Scenario | Key Assertion |
|------|----------|---------------|
| `test_get_vm_forecast_success_multiple_metrics` | 2 forecasts: 1 imminent (45m), 1 safe (120m) | `imminent_breach_count == 1`, `imminent_breach` flags correct |
| `test_get_vm_forecast_imminent_breach_all_metrics` | 3 forecasts all < 60m | `imminent_breach_count == 3`, all `imminent_breach is True` |
| `test_get_vm_forecast_missing_cosmos_env` | `COSMOS_ENDPOINT` not set | `query_status == "error"`, `"COSMOS_ENDPOINT" in error`, no SDK call |
| `test_get_vm_forecast_sdk_unavailable` | `CosmosClient = None` | `query_status == "error"`, `"not installed" in error` |
| `test_get_vm_forecast_sdk_exception` | `get_forecasts` raises `RuntimeError` | `query_status == "error"`, exception message in `error` |

### TestQueryVmPerformanceBaseline (5 tests)

| Test | Scenario | Key Assertion |
|------|----------|---------------|
| `test_baseline_perf_table_success` | Perf table returns CPU + Memory rows | `used_fallback_table is False`, `cpu_pct` p50/p95/p99 correct |
| `test_baseline_insights_metrics_fallback` | Perf empty → InsightsMetrics has data | `used_fallback_table is True`, `query_workspace.call_count == 2` |
| `test_baseline_missing_workspace_id` | `workspace_id=""` | `query_status == "skipped"`, no SDK call |
| `test_baseline_empty_result_set` | Both tables empty | `query_status == "success"`, `metric_count == 0`, `metrics == {}` |
| `test_baseline_sdk_exception` | `query_workspace` raises | `query_status == "error"`, exception message in `error` |

### TestDetectPerformanceDrift (5 tests)

| Test | Scenario | Key Assertion |
|------|----------|---------------|
| `test_drift_score_above_threshold_flagged` | baseline=50, recent=85 → score=70 | `is_drifting is True`, `drift_score == 70`, "above normal" in narrative |
| `test_drift_score_nominal_no_flag` | baseline=50, recent=55 → score=10 | `is_drifting is False`, `drift_score == 10` |
| `test_drift_missing_workspace_id` | `workspace_id=""` | `query_status == "skipped"`, no SDK call |
| `test_drift_baseline_zero_guard` | baseline_p95=0.0 | No `ZeroDivisionError`, `drift_score == 0` |
| `test_drift_sdk_exception` | `query_workspace` raises | `query_status == "error"`, exception message in `error` |

## Patterns Applied

- `_instrument_mock()` helper at module level — context-manager-compatible MagicMock
- All patches target `agents.compute.tools.*` (not source module paths)
- `@patch` decorators ordered outermost → innermost (reversed in function signature)
- `monkeypatch.setenv/delenv` used for `COSMOS_ENDPOINT` env isolation
- `CosmosClient = None` tested via `@patch("agents.compute.tools.CosmosClient", None)`
- Drift formula verified: `min(100, int((recent_p95 / baseline_p95 - 1) * 100))`

## Results

```
15 passed in 0.40s
```

All tests pass on first run with no failures or errors.
