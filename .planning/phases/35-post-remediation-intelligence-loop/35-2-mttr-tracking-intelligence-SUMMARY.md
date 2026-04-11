---
plan: 35-2-mttr-tracking-intelligence-PLAN.md
status: complete
completed_at: "2026-04-11"
commits:
  - 3685a2b feat: auto-set resolved_at when verification returns RESOLVED (35-2-1)
  - 2f005ee feat: add compute_mttr_by_issue_type to pattern_analyzer (35-2-2)
  - 7762b8d feat: add mttr_summary to PatternAnalysisResult and wire into _run_analysis_sync (35-2-3)
  - 7b93699 feat: add MTTR fields to PlatformHealth and surface in platform-health endpoint (35-2-4)
  - 3210c6f test: add 7 unit tests for MTTR tracking and auto-resolve (35-2-5)
---

# Plan 35-2: MTTR Tracking and Intelligence — COMPLETE

## What Was Built

LOOP-003: Mean Time To Resolution (MTTR) tracking per issue type, computed in the weekly
pattern analysis and surfaced in the `GET /api/v1/intelligence/platform-health` endpoint.

## Tasks Completed

### 35-2-1: Auto-set resolved_at when verification returns RESOLVED
- In `_inject_verification_result` (remediation_executor.py), after incrementing
  `re_diagnosis_count`, added auto-resolution patch when `verification_result == "RESOLVED"`:
  sets `status=resolved`, `resolved_at` (UTC ISO timestamp), `auto_resolved=True`, and
  a `resolution` message. Enables MTTR computation from `created_at` to `resolved_at`.

### 35-2-2: Add compute_mttr_by_issue_type to pattern_analyzer.py
- Pure function added after `_aggregate_feedback` in `pattern_analyzer.py`.
- Groups resolved incidents by `"domain:detection_rule:severity"` key.
- Computes P50, P95, mean MTTR in minutes using sorted index arithmetic.
- Skips incidents missing `created_at`/`resolved_at`, non-resolved status, or negative MTTR.
- Uses already-imported `collections.defaultdict`.

### 35-2-3: Add mttr_summary to PatternAnalysisResult and wire into _run_analysis_sync
- Added `mttr_summary: dict` field to `PatternAnalysisResult` model with LOOP-003
  description in Field metadata.
- Wired `compute_mttr_by_issue_type(incidents)` call in `_run_analysis_sync` after
  FinOps summary, inserting `mttr_summary` into the Cosmos result document.

### 35-2-4: Add MTTR fields to PlatformHealth model and platform-health endpoint
- Added three fields to `PlatformHealth` model (all with LOOP-003 descriptions):
  - `mttr_p50_minutes: Optional[float]` — aggregate P50 across issue types
  - `mttr_p95_minutes: Optional[float]` — aggregate P95 (max of per-type P95s)
  - `mttr_by_issue_type: dict` — full breakdown by domain:rule:severity key
- In `get_platform_health` handler, added section 6 that:
  - Queries the `pattern_analysis` Cosmos container for the latest analysis doc
  - Extracts `mttr_summary` from it
  - Computes aggregate P50 (mean of per-issue-type P50s — approximation documented
    in code comment) and P95 (max of per-issue-type P95s)
  - Returns all three MTTR fields in `PlatformHealth` response

### 35-2-5: Unit tests for MTTR tracking
- 6 tests in `test_pattern_analyzer.py::TestComputeMttrByIssueType`:
  - `test_compute_mttr_empty_incidents` — returns `{}`
  - `test_compute_mttr_no_resolved_incidents` — 3 non-resolved → `{}`
  - `test_compute_mttr_single_resolved` — 30-min MTTR → p50=p95=mean=30.0
  - `test_compute_mttr_multiple_resolved` — [10,20,30,60] → p50=30.0, p95=60.0, mean=30.0
  - `test_compute_mttr_groups_by_issue_type` — compute + network → 2 keys
  - `test_compute_mttr_skips_negative_mttr` — resolved_at < created_at → `{}`
- 1 test in `test_remediation_executor.py::TestAutoResolveOnVerification`:
  - `test_auto_resolve_sets_resolved_at` — RESOLVED verification → patch_item called
    with `/resolved_at` and `/auto_resolved=True`

## Test Results

```
57 passed (27 test_pattern_analyzer + 30 test_remediation_executor)
0 failures, 0 errors
```

## must_haves Verification

- [x] `compute_mttr_by_issue_type()` exists in `pattern_analyzer.py`, returns P50/P95/mean grouped by issue type
- [x] `defaultdict` is in the import block of `pattern_analyzer.py` (via `from collections import Counter, defaultdict`)
- [x] `mttr_summary` field added to `PatternAnalysisResult` model
- [x] `mttr_p50_minutes`, `mttr_p95_minutes`, `mttr_by_issue_type` fields added to `PlatformHealth` model
- [x] `GET /api/v1/intelligence/platform-health` returns MTTR metrics
- [x] `latest_analysis` variable confirmed in scope (Cosmos query added in handler) before MTTR computation
- [x] Approximation comment present: `# approximation: mean of per-issue-type P50s, not true population P50`
- [x] Auto-resolve logic sets `resolved_at` and `auto_resolved=True` when verification returns RESOLVED
- [x] 7 new unit tests pass covering MTTR computation and auto-resolve
</content>
</invoke>