---
phase: 15-diagnostic-pipeline
plan: 01
subsystem: agents
tags: [azure-mgmt-monitor, azure-monitor-query, azure-mgmt-resourcehealth, compute-agent, diagnostic-tools]

# Dependency graph
requires:
  - phase: 14-prod-stabilisation
    provides: structured logging patterns, compute agent skeleton with query_os_version reference implementation
provides:
  - query_activity_log calling MonitorManagementClient.activity_logs.list()
  - query_log_analytics calling LogsQueryClient.query_workspace()
  - query_resource_health calling MicrosoftResourceHealth.availability_statuses.get_by_resource()
  - query_monitor_metrics calling MonitorManagementClient.metrics.list()
  - _log_sdk_availability() SDK package logging at module import
  - _extract_subscription_id() helper for parsing ARM resource IDs
  - Graceful error handling (query_status="error") for all 4 tools
  - query_log_analytics returns query_status="skipped" when workspace_id is empty/None
  - 15 new unit tests (22 total), all passing
affects: [16-triage-pipeline, compute-agent, diagnostic-pipeline]

# Tech tracking
tech-stack:
  added:
    - azure-mgmt-monitor>=6.0.0
    - azure-monitor-query>=1.3.0
    - azure-mgmt-resourcehealth>=1.0.0
  patterns:
    - Lazy import with None fallback for optional Azure SDK packages
    - time.monotonic() for duration_ms structured logging
    - try/except all exceptions → return query_status="error" dict (never raise to LLM)
    - Skipped-status guard for missing optional configuration (workspace_id)
    - _log_sdk_availability() at module import for Container Apps health visibility

key-files:
  created: []
  modified:
    - agents/compute/tools.py
    - agents/compute/requirements.txt
    - agents/tests/compute/test_compute_tools.py

key-decisions:
  - "Lazy import pattern (try/except ImportError → None) mirrors existing ResourceGraphClient pattern — consistent with codebase convention"
  - "All 4 tools remain wrapped in instrument_tool_call context manager for OTel tracing continuity"
  - "query_log_analytics skipped (not error) for empty workspace_id — workspace is optional infra config, not an API failure"
  - "_extract_subscription_id extracted as module-level helper to avoid per-tool duplication"

patterns-established:
  - "Diagnostic tool pattern: lazy import → try/except → duration_ms logging → return status dict"
  - "Error dict shape: always include all expected keys with empty/default values + query_status=error + error=str(e)"
  - "Skipped status for missing optional configuration (distinct from error for SDK/API failures)"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-04-01
---

# Plan 15-01: Wire Compute Agent Diagnostic Tools — Summary

**Four Azure SDK-backed diagnostic tools replacing hardcoded stubs: ActivityLogs, LogsQueryClient, ResourceHealth, and Monitor Metrics — all with structured logging and graceful error handling**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-01
- **Completed:** 2026-04-01
- **Tasks:** 8 (Tasks 1–7 in one commit, per plan)
- **Files modified:** 3

## Accomplishments

- Replaced all 4 stub implementations with real Azure SDK calls — compute agent now returns live data instead of empty arrays
- Added `_log_sdk_availability()` at module import so Container App logs immediately show which SDK packages are present
- Added `_extract_subscription_id()` helper to parse ARM resource IDs, used by 3 of the 4 tools
- All 4 tools return `query_status: "error"` with `error` key on any exception — LLM never sees a Python traceback
- `query_log_analytics` returns `query_status: "skipped"` when `workspace_id` is empty/None — handles environments without Log Analytics configured
- Added 15 new unit tests across 4 test classes (22 total, 100% pass rate)

## Task Commits

1. **Tasks 1–8: Wire all 4 diagnostic tools + requirements + tests** — `4df811d` (feat)

## Files Created/Modified

- `agents/compute/tools.py` — Replaced 4 stubs with real SDK calls; added `_log_sdk_availability()`, `_extract_subscription_id()`, lazy imports for 3 new SDKs, structured logging with `duration_ms` on all tools
- `agents/compute/requirements.txt` — Added `azure-mgmt-monitor>=6.0.0`, `azure-monitor-query>=1.3.0`, `azure-mgmt-resourcehealth>=1.0.0`
- `agents/tests/compute/test_compute_tools.py` — Added `TestQueryActivityLog` (3 tests), `TestQueryLogAnalytics` (4 tests), `TestQueryResourceHealth` (2 tests), `TestQueryMonitorMetrics` (3 tests)

## Decisions Made

- **Lazy import pattern**: Used `try/except ImportError → None` for all 3 new SDK packages, matching the existing `ResourceGraphClient` pattern in the file. Keeps imports consistent and allows graceful degradation.
- **Skipped vs Error for empty workspace_id**: `query_log_analytics` returns `query_status: "skipped"` (not `"error"`) when `workspace_id` is empty — a missing workspace is a valid operational state (not all VMs have Log Analytics), not an API failure.
- **`_extract_subscription_id` as module-level helper**: Extracted rather than inlined to avoid duplication across `query_activity_log`, `query_resource_health`, and `query_monitor_metrics`.
- **`instrument_tool_call` context manager retained**: All tools keep the OTel tracing wrapper — the SDK calls happen inside the context manager body, consistent with `query_os_version`.

## Deviations from Plan

None — plan executed exactly as written. The `query_log_analytics` partial-response branch was implemented as specified, and all tool signatures match the plan verbatim.

## Issues Encountered

None — all tests passed on first run.

## User Setup Required

None — no external service configuration required. Azure SDK packages (`azure-mgmt-monitor`, `azure-monitor-query`, `azure-mgmt-resourcehealth`) must be installed in the compute agent container image via `requirements.txt`, which is handled by the existing Docker build process.

## Next Phase Readiness

- All 4 diagnostic tools are live and ready for use by the compute agent LLM
- Downstream triage workflows can now receive real Activity Log entries, Log Analytics rows, Resource Health states, and metric time series
- `requirements.txt` additions must be picked up by the next Container App image rebuild

---
*Phase: 15-diagnostic-pipeline*
*Completed: 2026-04-01*
