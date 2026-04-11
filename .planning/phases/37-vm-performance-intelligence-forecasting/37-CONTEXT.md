# Phase 37: VM Performance Intelligence & Forecasting - Context

**Gathered:** 2026-04-11
**Status:** Ready for planning
**Mode:** Auto-generated (smart discuss — infrastructure/backend phase)

<domain>
## Phase Boundary

Phase 37 exposes forecaster.py as an agent-callable tool and adds new compute agent tools for performance baselines and drift detection.

Deliverables:
1. **`get_vm_forecast`** — Wrap `ForecasterClient.get_forecasts()` as `@ai_function`. Returns time-to-breach minutes, confidence level, MAPE score, and current level/trend for CPU, memory, disk queue depth.
2. **`query_vm_performance_baseline`** — P50/P95/P99 statistics over 30 days via Log Analytics (`Perf` or `InsightsMetrics`). Returns per-metric percentile buckets with trend direction.
3. **`detect_performance_drift`** — Compare recent 24h window against 30-day baseline. Produce drift score (0–100) and narrative string. Flag when recent P95 > 1.5× baseline P95.
4. **Agent registration** — Register all 3 tools in `agents/compute/agent.py`.
5. **Unit tests** — 15+ tests covering all 3 tools.

Out of scope: UI changes (Phase 41), cost tools (Phase 39), SOP engine changes.

</domain>

<decisions>
## Implementation Decisions

### Forecaster Integration
- Import `ForecasterClient` from `services.api_gateway.forecaster` inside the tool function (lazy import guarded with try/except ImportError)
- Tool receives `resource_id` (ARM resource ID) and `subscription_id` as parameters
- ForecasterClient requires `cosmos_client` and `credential` — instantiate using `DefaultAzureCredential` and `CosmosClient` from env vars (`COSMOS_ENDPOINT`)
- If Cosmos env var missing or SDK import fails: return structured error dict (never raise)
- Tool name: `get_vm_forecast(resource_id, subscription_id, thread_id)`

### Performance Baseline Query
- Use Log Analytics `Perf` table (available on VMs with MMA/AMA) for 30-day baseline
- KQL: filter `ObjectName == "Processor"` for CPU, `ObjectName == "Memory"` for memory
- Fall back to `InsightsMetrics` if Perf table returns no rows
- Return: `{metric: {p50, p95, p99, sample_count, trend_direction}}`
- Tool name: `query_vm_performance_baseline(resource_group, vm_name, subscription_id, workspace_id, thread_id)`

### Drift Detection
- Compare last 24h avg/P95 against 30-day P95 baseline
- Drift score formula: `min(100, int((recent_p95 / baseline_p95 - 1) * 100))` — 0 = no drift, 100 = 2× baseline
- Narrative: "CPU P95 is 87% (baseline 52%) — 67% above normal. Memory within normal range."
- Flag as drifting when drift_score > 30 for any metric
- Tool name: `detect_performance_drift(resource_group, vm_name, subscription_id, workspace_id, thread_id)`

### Claude's Discretion
- Exact KQL queries for Perf vs InsightsMetrics table structure
- Whether to use single combined KQL or separate queries per metric
- Error message wording for missing workspace_id

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/api-gateway/forecaster.py` — `ForecasterClient.get_forecasts(resource_id)` returns `List[Dict]` with time_to_breach_minutes, confidence, mape, level, trend, metric_name
- `agents/compute/tools.py` — 25 existing `@ai_function` tools; Pattern established with `instrument_tool_call`, `start_time = time.monotonic()`, `duration_ms` in both try/except, structured error dicts
- `agents/compute/tools.py` — `query_ama_guest_metrics` (Phase 36) as pattern for Log Analytics `InsightsMetrics` queries
- `agents/compute/tools.py` — `_safe_float` helper for KQL null handling

### Established Patterns
- Module-level lazy imports: `try: from azure.xxx import YYY; except ImportError: YYY = None`
- Tool functions follow: `start_time → instrument_tool_call context manager → try/except → return dict`
- KQL queries via `LogsQueryClient` with `workspace_id` param
- `_extract_subscription_id(resource_id)` helper already exists in tools.py

### Integration Points
- `agents/compute/agent.py` — import block, COMPUTE_TOOLS list, ChatAgent tools list, PromptAgentDefinition tools list (4 locations to update)
- `agents/tests/compute/` — test directory; follow `test_compute_guest_diagnostics.py` pattern from Phase 36

</code_context>

<specifics>
## Specific Ideas

- `get_vm_forecast` should return ALL forecasts for the VM (CPU, memory, disk), not just the most urgent one — the agent decides which to surface
- Include `imminent_breach` boolean (time_to_breach < 60min) for quick LLM filtering
- `detect_performance_drift` should return per-metric drift scores, not just an aggregate

</specifics>

<deferred>
## Deferred Ideas

- Fleet-level performance digest SOP (weekly) — deferred to SOP engine phase
- UI panel showing forecast charts — deferred to Phase 41 (VMSS/AKS UI adds compute UI too)

</deferred>
