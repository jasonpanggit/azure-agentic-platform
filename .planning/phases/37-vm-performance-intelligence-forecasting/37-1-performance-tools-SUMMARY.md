---
plan: 37-1
status: complete
completed_at: "2026-04-11"
commits:
  - 3752c77
  - 5748f2f
  - 49cd330
  - 36f42a1
  - 1f8a510
---

# Summary: Plan 37-1 — Performance Intelligence Tools

## What Was Done

Added three new `@ai_function` tools to `agents/compute/tools.py` and updated
`agents/compute/requirements.txt`. All tasks executed as 5 atomic commits.

### Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 37-1-A | Lazy imports: `CosmosClient` + `ForecasterClient` + `import os` | 3752c77 |
| 37-1-B | `get_vm_forecast` tool | 5748f2f |
| 37-1-C | `query_vm_performance_baseline` tool | 49cd330 |
| 37-1-D | `detect_performance_drift` tool | 36f42a1 |
| 37-1-E | `azure-cosmos>=4.0.0` in requirements.txt | 1f8a510 |

## Files Modified

- `agents/compute/tools.py` — +530 lines (3 new tools + lazy imports + `import os`)
- `agents/compute/requirements.txt` — +1 line (`azure-cosmos>=4.0.0`)

## Tool Implementations

### `get_vm_forecast(resource_id, subscription_id, thread_id)`
- Reads `COSMOS_ENDPOINT` from env, instantiates `CosmosClient` + `ForecasterClient`
- Wraps `ForecasterClient.get_forecasts(resource_id)`
- Returns full forecast list with `imminent_breach` bool (`time_to_breach_minutes < 60`)
- Three structured early-exit paths: missing env var, missing SDK, missing ForecasterClient
- Returns `imminent_breach_count` for quick LLM filtering

### `query_vm_performance_baseline(resource_group, vm_name, subscription_id, workspace_id, thread_id)`
- Queries `Perf` table (30-day P50/P95/P99) via `LogsQueryClient`
- Falls back to `InsightsMetrics` when Perf returns zero rows (AMA without DCR)
- Returns `{metric: {p50, p95, p99, sample_count, trend_direction}}`
- `workspace_id` guard returns `query_status=skipped` with explanatory reason
- Metrics: `cpu_pct`, `memory_available_mb`, `disk_reads_per_sec`

### `detect_performance_drift(resource_group, vm_name, subscription_id, workspace_id, thread_id)`
- Runs two KQL queries: 30-day baseline P95 + 24h recent avg/P95
- Drift score formula: `min(100, int((recent_p95 / baseline_p95 - 1) * 100))`
- Zero-baseline guard prevents division errors
- Flags `is_drifting=True` when any metric `drift_score > 30`
- Returns per-metric `drift_metrics` dict and human-readable `narrative` string
- Example narrative: `"CPU P95 is 87.0 (baseline 52.0) — 67% above normal. Memory within normal range."`

## Verification Results

```
✅ def get_vm_forecast          — line 2177
✅ def query_vm_performance_baseline — line 2289
✅ def detect_performance_drift — line 2474
✅ CosmosClient = None          — line 74
✅ ForecasterClient = None      — line 80
✅ imminent_breach field        — 5 matches (docstring, flag assignment, sum, return key)
✅ min(100 formula              — 2 matches (docstring + implementation)
✅ azure-cosmos>=4.0.0          — requirements.txt confirmed
✅ @ai_function decorators      — all 3 new tools decorated (lines 2176, 2288, 2473)
✅ COSMOS_ENDPOINT env read     — line 2211
✅ workspace_id guards          — skipped status at lines 2329, 2516
```

## Pattern Compliance

All three tools follow the established `query_ama_guest_metrics` pattern:
- `start_time = time.monotonic()` at entry
- `instrument_tool_call` context manager with `tracer`, `agent_name`, `agent_id`
- `try/except Exception` — never raises, always returns structured dict
- `duration_ms` recorded in both success and exception paths
- Module-level lazy imports with `= None` fallback
