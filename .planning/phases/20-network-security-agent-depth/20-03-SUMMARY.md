---
phase: 20-network-security-agent-depth
plan: "03"
subsystem: agents
tags: [azure-mgmt-monitor, azure-mgmt-resourcehealth, azure-mgmt-advisor, azure-mgmt-changeanalysis, sre-agent, sdk, service-health, advisor, change-analysis, cross-domain-correlation]

# Dependency graph
requires:
  - phase: 02-agent-core
    provides: ChatAgent pattern, shared auth/otel, agent.py/tools.py scaffold
provides:
  - 7 real SDK tools in SRE agent (query_availability_metrics, query_performance_baselines, query_service_health, query_advisor_recommendations, query_change_analysis, correlate_cross_domain, propose_remediation)
  - _extract_subscription_id, _log_sdk_availability, _percentile helpers for SRE tools
  - correlate_cross_domain composite tool aggregating 4 sub-tool signals with independent fault tolerance
  - Updated triage workflow (9 steps) with service health, change analysis, and cross-domain correlation steps
affects: [orchestrator, sre-tests, detection-plane]

# Tech tracking
tech-stack:
  added: [azure-mgmt-monitor (MonitorManagementClient), azure-mgmt-resourcehealth (ResourceHealthMgmtClient), azure-mgmt-advisor (AdvisorManagementClient), azure-mgmt-changeanalysis (AzureChangeAnalysisManagementClient)]
  patterns: [composite tool pattern (correlate_cross_domain calls 4 tools internally), percentile computation (sort + index-based), lazy SDK imports with try/except, structured error dicts]

key-files:
  created: []
  modified:
    - agents/sre/requirements.txt
    - agents/sre/tools.py
    - agents/sre/agent.py

key-decisions:
  - "correlate_cross_domain wraps each sub-call in independent try/except — partial failures are captured as warnings, never fatal"
  - "p95/p99 computed via sort + index-based approach (no numpy dependency) — _percentile helper used for both"
  - "propose_remediation preserved exactly as-is — no changes to the REMEDI-001 enforcement tool"
  - "query_service_health uses getattr() for all event fields — resilient to SDK model variations in preview package"

patterns-established:
  - "Composite tool pattern: correlate_cross_domain calls 4 sub-tools, each wrapped independently, builds correlation_summary string"
  - "SRE tool pattern: subscription_id-based for health/advisor/changes, resource_id-based for metrics"
  - "Percentile helper: _percentile(sorted_data, pct) — reusable across agents"

requirements-completed: [PROD-003]

# Metrics
duration: 10min
completed: 2026-04-10
---

# Plan 20-03: SRE Agent Real SDK Tools Summary

**7 real SDK tools replacing stubs — availability metrics, performance baselines, service health, advisor recommendations, change analysis, cross-domain correlation, and remediation proposals (REMEDI-001)**

## Performance

- **Duration:** 10 min
- **Started:** 2026-04-10
- **Completed:** 2026-04-10
- **Tasks:** 4
- **Files modified:** 3

## Accomplishments

- Updated `requirements.txt` with 4 new Azure SDK packages: `azure-mgmt-monitor`, `azure-mgmt-resourcehealth` (preview), `azure-mgmt-advisor`, `azure-mgmt-changeanalysis`
- Replaced 2 stub tools (`query_availability_metrics`, `query_performance_baselines`) with real `MonitorManagementClient` SDK implementations including downtime window detection and p95/p99 percentile computation
- Added 4 new tools: `query_service_health` (MONITOR-003), `query_advisor_recommendations`, `query_change_analysis`, `correlate_cross_domain` (composite)
- `correlate_cross_domain` aggregates 4 sub-tool signals (service health, changes, availability, advisor) with independent fault tolerance per sub-call
- Preserved `propose_remediation` unchanged (REMEDI-001 enforcement)
- Updated SRE agent system prompt with 9-step triage workflow including service health, change analysis, and cross-domain correlation
- All 7 tools follow established pattern: `instrument_tool_call`, `start_time`, `duration_ms`, never raise, structured error dicts

## Task Commits

Each task was committed atomically:

1. **Task 20-03-01: Update requirements.txt** — `9d71b90` (feat)
2. **Task 20-03-02: Replace 2 stub tools with real SDK** — `f76ebf9` (feat)
3. **Task 20-03-03: Add 4 new tools** — `e7cbd44` (feat)
4. **Task 20-03-04: Register tools in agent.py, expand system prompt** — `465333d` (feat)

## Files Created/Modified

- `agents/sre/requirements.txt` — Added 4 SDK packages: `azure-mgmt-monitor>=6.0.0`, `azure-mgmt-resourcehealth==1.0.0b6`, `azure-mgmt-advisor>=9.0.0`, `azure-mgmt-changeanalysis>=1.0.0`.
- `agents/sre/tools.py` — Full rewrite: 183 lines of stubs → 1027 lines of real SDK implementations. 7 `@ai_function` tools, `_extract_subscription_id`, `_log_sdk_availability`, `_percentile`, lazy imports for 4 SDK clients.
- `agents/sre/agent.py` — Updated imports (7 tools + `ALLOWED_MCP_TOOLS`), expanded `ChatAgent(tools=[...])` to 7 entries, system prompt triage workflow expanded from 8 to 9 steps, Allowed Tools section updated to 13 entries (6 MCP + 7 SDK).

## Decisions Made

- **Independent fault tolerance in composite tool:** `correlate_cross_domain` wraps each of its 4 sub-calls in separate try/except blocks. A failure in one signal source (e.g., Change Analysis unavailable) doesn't prevent the overall correlation from completing — partial results are returned with error details in `correlation_summary`.
- **Index-based percentile computation:** Used a simple `_percentile(sorted_data, pct)` helper with sort + index approach. Avoids numpy dependency while providing sufficient accuracy for operational baselines.
- **Preview SDK pinned exactly:** `azure-mgmt-resourcehealth==1.0.0b6` is pinned to exact version since it's a preview package — API may change between beta releases.

## Deviations from Plan

None — plan executed exactly as written across all 4 tasks.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. SDK packages will be installed during container image build.

## Next Phase Readiness

- SRE agent has 7 fully implemented SDK tools ready for production
- `correlate_cross_domain` provides unified incident investigation view
- Agent system prompt covers comprehensive 9-step triage workflow
- Ready for integration testing with live Azure subscriptions
- Tests for these tools will be added in a separate test phase

---
*Phase: 20-network-security-agent-depth*
*Plan: 20-03*
*Completed: 2026-04-10*
