# Plan 28-2: Pattern Analyzer — SUMMARY

**Status:** COMPLETE
**Completed:** 2026-04-04
**Branch:** gsd/phase-28-platform-intelligence
**Requirements satisfied:** PLATINT-001, PLATINT-002, PLATINT-003

---

## What Was Built

A pure-Python incident pattern analysis engine for the Azure Agentic Platform. No external ML dependencies (no numpy/sklearn/scipy) — uses only stdlib `collections.Counter` and `collections.defaultdict`.

### Files Modified / Created

| File | Change |
|------|--------|
| `services/api-gateway/models.py` | Extended `ApprovalAction` with `feedback_text`/`feedback_tags`; added 5 new Pydantic models |
| `services/api-gateway/approvals.py` | Extended `process_approval_decision()` to accept and persist feedback fields |
| `services/api-gateway/pattern_analyzer.py` | **NEW** — full pattern analysis engine |
| `services/api-gateway/tests/test_pattern_analyzer.py` | **NEW** — 21 unit tests, all passing |

---

## Task Outcomes

### Task 1: ApprovalAction feedback fields (models.py)
- Added `feedback_text: Optional[str]` with PLATINT-003 description
- Added `feedback_tags: Optional[list[str]]` with `default=None` (not `[]` — avoids Pydantic mutable default trap)
- Docstring updated to include `PLATINT-003` reference

### Task 2: process_approval_decision feedback capture (approvals.py)
- Added `feedback_text: Optional[str] = None` parameter
- Added `feedback_tags: Optional[list[str]] = None` parameter
- Conditionally writes both to `updated_record` dict before Cosmos upsert
- Backward-compatible: existing callers work without changes

### Task 3: New Pydantic models (models.py)
All 5 models added to end of `models.py` after `RemediationResult`:
- `BusinessTier` — revenue tier config for FinOps (PLATINT-004)
- `IncidentPattern` — single recurring pattern (PLATINT-001)
- `PatternAnalysisResult` — weekly analysis output (PLATINT-001)
- `PlatformHealth` — platform-wide health metrics (PLATINT-004)
- `BusinessTiersResponse` — GET endpoint response wrapper (PLATINT-004)

### Task 4: pattern_analyzer.py (NEW)
8 functions implemented as specified:

| Function | Purpose |
|----------|---------|
| `_severity_score(severity)` | Maps Sev0=4.0, Sev1=3.0, Sev2=2.0, Sev3=1.0, default=1.5 |
| `_group_incidents_by_pattern(incidents)` | Groups by (domain, resource_type, detection_rule) using `defaultdict(list)` |
| `_score_pattern(incidents)` | Returns `count × avg_severity_score` |
| `_extract_top_words(incidents, top_n=5)` | Counter-based word extraction, filters words < 4 chars |
| `_compute_finops_summary(incidents, remediations)` | `wasted_compute_usd` + `automation_savings_usd` |
| `_aggregate_feedback(approvals, pattern_key)` | Returns `(operator_flagged, common_feedback)` |
| `analyze_patterns(cosmos_client)` | Async orchestrator — reads Cosmos, writes result doc |
| `run_pattern_analysis_loop(cosmos_client, interval)` | Background asyncio task (weekly, mirrors forecaster.py) |

7 env vars: `PATTERN_ANALYSIS_ENABLED`, `PATTERN_ANALYSIS_INTERVAL_SECONDS`, `PATTERN_ANALYSIS_LOOKBACK_DAYS`, `FINOPS_SAVINGS_PER_REMEDIATION_MINUTES`, `FINOPS_HOURLY_RATE_USD`, `COSMOS_DATABASE`, `COSMOS_PATTERN_ANALYSIS_CONTAINER`

### Task 5: test_pattern_analyzer.py (NEW)
21 tests across 6 test classes — all passing:

| Class | Tests |
|-------|-------|
| `TestSeverityScore` | 5 tests — Sev0/1/2/3 mapping + unknown default |
| `TestGroupIncidents` | 2 tests — tuple grouping + empty list |
| `TestScorePattern` | 3 tests — math, mixed severity, empty |
| `TestExtractTopWords` | 3 tests — word extraction, short word filtering, empty |
| `TestComputeFinopsSummary` | 3 tests — keys, savings math, wasted compute |
| `TestAnalyzePatterns` | 1 test — top_patterns <= 5 with mocked Cosmos |
| `TestFeedbackAggregation` | 4 tests — operator_flagged, single FP, no match, top-3 tags |

---

## Key Decisions

- `_MIN_WORD_LENGTH = 4` filters short words ("cpu" = 3 chars is excluded; tests use "disk"/"high"/"usage" instead)
- `operator_flagged = True` when ≥ 2 approvals have `"false_positive"` OR `"not_useful"` in tags
- `top_patterns` capped at `_TOP_PATTERNS_LIMIT = 5`
- All Cosmos calls wrapped in `run_in_executor` — doesn't block asyncio event loop
- Tool functions never raise — return `None` on error (consistent with forecaster.py pattern)

---

## Test Results

```
21 passed, 1 warning in 0.04s
```

All 21 tests pass. Test count (21) exceeds the required minimum of 12.
