---
phase: 33-evaluation
plan: 01
subsystem: testing
tags: [azure-ai-evaluation, evaluators, quality-gates, ci-pipeline, aiops]

# Dependency graph
requires:
  - phase: 29-observability
    provides: OTel traces in App Insights
  - phase: 30-sop
    provides: SOP metadata available
provides:
  - 4 custom AIOps evaluators (SopAdherence, TriageCompleteness, RemediationSafety, DiagnosisGrounding)
  - Standard azure-ai-evaluation wrapper with safe score extraction
  - CI eval pipeline with 4 quality gates
  - GitHub Actions weekly + PR evaluation workflow
  - Sample agent trace data (3 representative scenarios)
affects: [phase-34, ci-cd, agent-quality]

# Tech tracking
tech-stack:
  added: [azure-ai-evaluation]
  patterns: [callable-evaluator-class, quality-gate-thresholds, metric-key-fallback-chain]

key-files:
  created:
    - services/api-gateway/evaluation/__init__.py
    - services/api-gateway/evaluation/custom_evaluators.py
    - services/api-gateway/evaluation/agent_evaluators.py
    - services/api-gateway/evaluation/eval_pipeline.py
    - services/api-gateway/tests/evaluation/__init__.py
    - services/api-gateway/tests/evaluation/test_custom_evaluators.py
    - services/api-gateway/tests/evaluation/test_agent_evaluators.py
    - services/api-gateway/tests/evaluation/test_eval_pipeline.py
    - services/api-gateway/tests/evaluation/test_phase33_smoke.py
    - tests/eval/agent_traces_sample.jsonl
    - .github/workflows/agent-eval.yml
  modified: []

key-decisions:
  - "Callable class pattern for evaluators -- each evaluator is __call__-able, matching azure-ai-evaluation SDK conventions"
  - "Binary scoring (0.0 or 1.0) for safety, completeness, grounding; proportional (0.0-5.0) for SOP adherence"
  - "Graceful ImportError handling -- custom evaluators work without azure-ai-evaluation SDK installed"
  - "Quality gate thresholds: TaskAdherence>=4.0, TriageCompleteness>=0.95, RemediationSafety>=1.0, SopAdherence>=3.5"

patterns-established:
  - "Callable evaluator class: __call__(trace) -> dict[str, float] with single score key"
  - "extract_eval_score() fallback chain: prefixed > .score suffix > flat key"
  - "THRESHOLDS dict for declarative quality gate configuration"

requirements-completed: []

# Metrics
duration: 12min
completed: 2026-04-11
---

# Phase 33: Foundry Evaluation + Quality Gates Summary

**4 custom AIOps evaluators with CI quality gate pipeline scoring SOP adherence, triage completeness, remediation safety, and diagnosis grounding**

## Performance

- **Duration:** 12 min
- **Started:** 2026-04-11
- **Completed:** 2026-04-11
- **Tasks:** 8
- **Files created:** 11

## Accomplishments
- Built 4 custom AIOps evaluators: SopAdherenceEvaluator (proportional 0-5 scoring), TriageCompletenessEvaluator (TRIAGE-002/003 compliance), RemediationSafetyEvaluator (HITL propose_* enforcement), DiagnosisGroundingEvaluator (>=2 evidence signals)
- Created agent_evaluators.py wrapping standard azure-ai-evaluation SDK evaluators with graceful ImportError fallback and safe metric key extraction (3-format fallback chain)
- Implemented eval_pipeline.py with 4 quality gates (task_adherence>=4.0, triage_completeness>=0.95, remediation_safety>=1.0, sop_adherence>=3.5) and CLI entry point
- Added GitHub Actions workflow running weekly + on PR to main, with eval-results artifact upload
- 25 Phase 33 tests pass. 760 total api-gateway tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Tasks 1-2: Custom AIOps Evaluators** - `bed1a81` (feat: 4 evaluators + 9 tests)
2. **Tasks 3-4: Standard Evaluator Wrappers** - `e019896` (feat: agent_evaluators.py + 6 tests)
3. **Tasks 5-6: CI Eval Pipeline** - `369e1b1` (feat: eval_pipeline.py + 4 tests)
4. **Task 7: Sample Traces + Workflow** - `03e5c10` (feat: JSONL traces + agent-eval.yml)
5. **Task 8: Smoke Tests** - `ed50cf5` (test: 6 smoke tests)

## Files Created/Modified
- `services/api-gateway/evaluation/__init__.py` - Package init
- `services/api-gateway/evaluation/custom_evaluators.py` - 4 AIOps evaluator classes
- `services/api-gateway/evaluation/agent_evaluators.py` - Standard evaluator wrappers + score extraction
- `services/api-gateway/evaluation/eval_pipeline.py` - CI quality gate pipeline runner
- `services/api-gateway/tests/evaluation/__init__.py` - Test package init
- `services/api-gateway/tests/evaluation/test_custom_evaluators.py` - 9 custom evaluator tests
- `services/api-gateway/tests/evaluation/test_agent_evaluators.py` - 6 wrapper tests
- `services/api-gateway/tests/evaluation/test_eval_pipeline.py` - 4 pipeline tests
- `services/api-gateway/tests/evaluation/test_phase33_smoke.py` - 6 smoke tests
- `tests/eval/agent_traces_sample.jsonl` - 3 representative agent traces
- `.github/workflows/agent-eval.yml` - Weekly + PR evaluation workflow

## Decisions Made
- Callable class pattern for evaluators matching azure-ai-evaluation SDK conventions
- Binary scoring (0.0/1.0) for safety, completeness, grounding; proportional (0.0-5.0) for SOP adherence
- Graceful ImportError handling so custom evaluators work without azure-ai-evaluation SDK installed
- Quality gate thresholds set conservatively: TaskAdherence>=4.0, RemediationSafety>=1.0 (must be perfect)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required. The GitHub Actions workflow requires `AZURE_PROJECT_ENDPOINT`, `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET` secrets to be configured in the `production-readonly` environment.

## Next Phase Readiness
- Evaluation package ready for production use
- CI workflow will activate on next PR to main touching agents/** or evaluation/** paths
- Weekly scheduled runs begin automatically

---
*Phase: 33-evaluation*
*Completed: 2026-04-11*
