---
phase: 20-network-security-agent-depth
plan: "20-3"
subsystem: agents
tags: [sre, azure-monitor, azure-advisor, azure-changeanalysis, servicehealth, correlation, rca]

# Dependency graph
requires:
  - phase: 20-1
    provides: network agent scaffold pattern (lazy imports, _log_sdk_availability, _extract_subscription_id)
provides:
  - SRE agent fully implemented with 6 tools (2 existing stubs + 4 new)
  - Cross-domain RCA synthesiser (correlate_cross_domain) with confidence scoring
  - Preview SDK lazy-import guard pattern for servicehealth and changeanalysis
  - 22 unit tests covering all SRE tools
affects: [orchestrator-routing, incident-correlation, remediation-proposals]

# Tech tracking
tech-stack:
  added:
    - azure-mgmt-servicehealth==1.0.0b4 (preview, pinned)
    - azure-mgmt-advisor>=9.0.0 (stable)
    - azure-mgmt-changeanalysis==1.0.0b2 (preview, pinned)
    - azure-mgmt-monitor>=6.0.0 (stable)
  patterns:
    - Lazy import guard with try/except ImportError for all 4 SDK packages
    - _log_sdk_availability() called at module level to surface missing deps at startup
    - datetime objects (not ISO strings) required for changeanalysis SDK start_time/end_time
    - correlate_cross_domain: pure Python, no SDK, confidence scoring with recency/severity bonuses
    - requires_approval=True enforced on correlate_cross_domain output (REMEDI-001)

key-files:
  modified:
    - agents/sre/tools.py
    - agents/sre/requirements.txt
  created:
    - agents/tests/sre/__init__.py
    - agents/tests/sre/test_sre_tools.py

key-decisions:
  - "ServiceHealthClient aliased from MicrosoftResourceHealth in azure-mgmt-servicehealth to avoid confusion with azure-mgmt-resourcehealth used by compute agent"
  - "AzureChangeAnalysisManagementClient constructor takes no subscription_id (SDK quirk for 1.0.0b2)"
  - "correlate_cross_domain is pure Python with no instrument_tool_call context manager — no Azure SDK call required"
  - "Availability computed as average of average values; downtime windows are consecutive intervals < 99.9% SLA threshold"
  - "p95/p99 computed by sorting values and indexing at 95%/99% position (clamped to n-1)"
  - "Tasks 2-5 were committed as a single commit (full file rewrite) to avoid partial state of tools.py"

patterns-established:
  - "Preview SDK guard: try/except ImportError at module level, set to None on ImportError, guard in function body raises ImportError if None"
  - "Pure-Python tool (correlate_cross_domain) does not need instrument_tool_call but still calls get_agent_identity()"
  - "confidence_score = min(0.3 * len(findings) + 0.2 if high_severity + 0.1 if recent, 1.0)"

requirements-completed:
  - PROD-003

# Metrics
duration: 25min
completed: 2026-04-02
---

# Plan 20-3: SRE Agent Depth Summary

**SRE agent fully implemented: 2 stubs replaced + 4 new tools added (service health, advisor, change analysis, cross-domain RCA), 22 tests all passing**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-02T00:00:00Z
- **Completed:** 2026-04-02T00:25:00Z
- **Tasks:** 6 (Tasks 1-5 in tools.py + Task 6 test files)
- **Files modified:** 4

## Accomplishments

- Replaced 2 stub tools (`query_availability_metrics`, `query_performance_baselines`) with real `MonitorManagementClient` implementations
- Added 4 new tools: `query_service_health` (preview SDK), `query_advisor_recommendations`, `query_change_analysis` (preview SDK), `correlate_cross_domain` (pure Python RCA)
- Populated `requirements.txt` with 4 packages — 2 stable, 2 preview (pinned to exact beta versions)
- Full module scaffold: lazy imports for all 4 SDKs, `logger`, `_log_sdk_availability()`, `_extract_subscription_id()`
- 22 unit tests all passing (zero failures) covering availability computation, downtime windows, p95/p99 percentiles, SDK guard patterns, datetime arg enforcement, and pure-Python correlation

## Task Commits

1. **Task 1: requirements.txt** - `b2c4804` (feat)
2. **Tasks 2-5: module scaffold + all tool implementations** - `b59360b` (feat — full file rewrite)
3. **Task 6: test files** - `a0c0704` (test)

_Note: Tasks 2-5 were committed as a single atomic commit since they all modify tools.py — splitting would have left the file in an inconsistent intermediate state._

## Files Created/Modified

- `agents/sre/requirements.txt` — 4 packages: azure-mgmt-servicehealth==1.0.0b4, azure-mgmt-advisor>=9.0.0, azure-mgmt-changeanalysis==1.0.0b2, azure-mgmt-monitor>=6.0.0
- `agents/sre/tools.py` — Full rewrite: module scaffold + 6 implemented tools (propose_remediation preserved intact)
- `agents/tests/sre/__init__.py` — Empty package marker
- `agents/tests/sre/test_sre_tools.py` — 22 tests across 8 test classes

## Decisions Made

- `MicrosoftResourceHealth` from `azure-mgmt-servicehealth` aliased to `ServiceHealthClient` to distinguish from the identically-named class in `azure-mgmt-resourcehealth` (used by compute agent)
- `AzureChangeAnalysisManagementClient` instantiated without `subscription_id` — this is a documented quirk of the `1.0.0b2` preview SDK
- `correlate_cross_domain` does not use `instrument_tool_call` context manager — it is pure Python with no Azure SDK dependency and no I/O
- Downtime windows use 99.9% SLA threshold (not 99.0%) as specified in plan context
- p95/p99 indexing: `int(n * 0.95)` clamped to `n-1`, matches sort-based percentile calculation in plan spec

## Deviations from Plan

None — plan executed exactly as written. Tasks 2-5 were logically separate (scaffold → stubs → service health/advisor → change analysis/correlation) but committed as one file since all changes are to `agents/sre/tools.py`.

## Issues Encountered

None — all 22 tests passed on first run.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SRE agent is now the platform's cross-domain incident synthesiser with full tool surface
- `correlate_cross_domain` is ready to receive structured findings from compute, network, security, storage, and arc agents
- Plan 20-2 (Security Agent) executes in parallel — no SRE dependency on it
- Phase 20 completion requires: 20-1 ✅, 20-2 (parallel), 20-3 ✅

---
*Phase: 20-network-security-agent-depth*
*Completed: 2026-04-02*
