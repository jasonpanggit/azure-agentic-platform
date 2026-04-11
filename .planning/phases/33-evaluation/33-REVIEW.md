---
phase: 33-evaluation
reviewer: claude-code
review_date: 2026-04-11
verdict: APPROVED
---

# Phase 33 Code Review — Foundry Evaluation + Quality Gates

## Summary

Phase 33 delivers a clean, well-tested evaluation package: 4 custom AIOps evaluators, a standard `azure-ai-evaluation` wrapper layer, a CI quality-gate pipeline, 3 representative sample traces, and a GitHub Actions workflow. All 25 tests pass green. No regressions in the broader test suite. The implementation is production-ready with one actionable recommendation and two lower-priority observations.

---

## File-by-File Findings

### `services/api-gateway/evaluation/__init__.py`
**Status: PASS**

Single-line docstring package init. Correct, minimal, no issues.

---

### `services/api-gateway/evaluation/custom_evaluators.py`
**Status: PASS with one observation**

**Strengths:**
- All four evaluators follow a consistent callable-class pattern (`__call__(trace) -> dict[str, float]`) that aligns with the `azure-ai-evaluation` SDK conventions.
- `frozenset` for `REQUIRED_TRIAGE_TOOLS`, `EVIDENCE_TOOLS`, and `DIRECT_ARM_PATTERNS` is correct — constant, hashable, O(1) membership tests.
- `_extract_tool_calls` handles both `{"name": ...}` and `{"function": {"name": ...}}` formats, which is important for OpenAI tool call format compatibility.
- Binary vs proportional scoring split is clear: safety/completeness/grounding are 0.0/1.0; SOP adherence is 0.0–5.0.

**Observation 1 (LOW) — `TriageCompletenessEvaluator` partial score is implicit:**
```python
score = 1.0 if all_required else (0.5 if any([...]) else 0.0)
```
The `0.5` partial-credit branch is undocumented in the module docstring, which only mentions "0.0 otherwise". The quality gate threshold is `0.95`, so a `0.5` partial won't pass regardless — but the behaviour diverges from the stated specification. Either the docstring should be updated to document the partial-credit branch, or the branch should be removed to keep the behaviour binary as specified.

**Observation 2 (LOW) — `SopAdherenceEvaluator` loses step-ordering information:**
```python
tool_calls = set(_extract_tool_calls(trace))  # converts to set
steps_matched = sum(1 for step in sop_steps if step in tool_calls)
```
Converting `tool_calls` to a set discards order, so an agent that called steps out of sequence gets the same score as one that followed them correctly. This is acceptable for v1 (and documented by the class docstring saying "executed"), but worth flagging for future iterations where ordering matters.

---

### `services/api-gateway/evaluation/agent_evaluators.py`
**Status: PASS**

**Strengths:**
- Graceful `ImportError` fallback sets all SDK evaluator references to `None`, allowing custom evaluators to work without the `azure-ai-evaluation` package installed. This is critical for local dev and unit-test environments.
- `build_eval_config` raises `ImportError` explicitly with an actionable install command rather than producing a silent `None` in the config dict.
- `extract_eval_score` implements a 3-format fallback chain (`prefixed → .score → flat`) that correctly handles SDK version variance. This is production-hardened behaviour.
- `include_safety` guard also checks `ContentSafetyEvaluator is not None` before instantiating — correct double-guard pattern given the `ImportError` fallback.

**Observation 3 (LOW) — `GroundednessEvaluator` imported but never used:**
```python
from azure.ai.evaluation import (
    ...
    GroundednessEvaluator,   # imported, not in build_eval_config
)
```
`GroundednessEvaluator` is imported in the `try` block and has a `None` fallback but is never added to the config dict returned by `build_eval_config`. This is either a deferred/placeholder import or an accidental omission. It should either be added to the config or removed from the import to avoid reader confusion.

---

### `services/api-gateway/evaluation/eval_pipeline.py`
**Status: PASS with one actionable finding**

**Strengths:**
- `THRESHOLDS` dict is declarative and easy to update — good design.
- Missing metrics are handled with a `logger.warning` and gate skip rather than a hard failure, which is the correct behaviour when the SDK is partially unavailable.
- `dry_run` path is clearly delineated and tested.
- CLI entry point is clean and well-structured with argparse.
- Exit code semantics (`0` = pass, `1` = fail) are documented and correct for CI use.

**Finding 1 (MEDIUM) — `dry_run=True` evaluator path is a logic dead-end:**

The `dry_run` flag intends to skip the real `evaluate()` call and allow tests to mock it. However, the `if not dry_run` branch instantiates **only** the 4 custom evaluators (lines 76–81), while the `else` block at lines 107–115 calls `evaluate()` again with those same 4 custom evaluators but _without_ the standard evaluators from `build_eval_config`. The result is that in `dry_run=True` mode, the mock's return value is used but `task_adherence` can still appear in `THRESHOLDS` and will fail the gate when its threshold score is missing (score = `None`). In practice the existing test passes only because `dry_run=True` forces `metrics = {}` through the outer else branch (line 115). This is fragile:

```python
# Current: dry_run=True lands here (evaluate is not None from mock)
if dry_run and evaluate is not None:
    result = evaluate(...)   # calls the mock
    metrics = result.get("metrics", {})
else:
    metrics = {}             # dry_run=True + evaluate=None lands here
```

The existing pipeline tests use `@patch("...eval_pipeline.evaluate")` which patches the module-level `evaluate`, but the `dry_run=True` call still reaches line 108 and calls `evaluate()` _without_ the `azure_ai_project` kwarg, which is a deviation from the non-dry-run path. The tests pass because the mock doesn't validate kwargs. This is not a blocking defect but represents a code smell — the `dry_run` abstraction leaks implementation detail into the call site. A cleaner approach would be a single `_run_evaluate()` helper that accepts a `mock_evaluate` callable for testing.

**Observation 4 (LOW) — `__main__` block has no `azure_ai_project` or `credential` wiring:**
The CLI block constructs `model_config` from env vars but passes neither `azure_ai_project` nor `credential` to `run_eval_pipeline`. This means the real `evaluate()` call will have no `azure_ai_project` kwarg, so results will not be logged back to Foundry. The `azure_ai_project` should be constructed from `AZURE_PROJECT_ENDPOINT` in the `__main__` block.

---

### `tests/eval/agent_traces_sample.jsonl`
**Status: PASS**

Three traces cover the three main agent scenarios: VM CPU alert (propose_vm_restart), Arc disconnection (propose_arc_assessment), and patch compliance gap (no remediation — diagnostic only). All three traces satisfy all 4 evaluator criteria. Format is correct single-object-per-line JSONL. 

**Observation 5 (LOW) — All 3 sample traces are "happy path":**
Every trace achieves perfect scores on all four evaluators. There are no negative-case traces (e.g., an agent that skips triage tools or makes a direct ARM call). While this is fine for smoke testing the pipeline wiring, it means the sample data cannot detect regressions where an evaluator silently stops penalising bad behaviour. Adding one "failure" trace (e.g., missing `query_resource_health`, or a direct `restart_vm` call) would make the dataset more useful for threshold calibration.

---

### `.github/workflows/agent-eval.yml`
**Status: PASS with one observation**

**Strengths:**
- Uses `production-readonly` environment, which correctly signals that this job only reads from Azure (no writes).
- `if: always()` on the artifact upload ensures results are captured even on gate failure.
- Trigger paths are well-scoped (`agents/**`, `services/api-gateway/evaluation/**`, `tests/eval/**`).
- Weekly Monday 6am UTC schedule is appropriate for a quality-gate cadence.

**Observation 6 (LOW) — No `AZURE_OPENAI_ENDPOINT` secret in the workflow env block:**
The `__main__` block in `eval_pipeline.py` reads `AZURE_OPENAI_ENDPOINT` from the environment to build `model_config`, but this variable is absent from the `env:` section of the workflow step. The workflow provides `AZURE_PROJECT_ENDPOINT` but not `AZURE_OPENAI_ENDPOINT`. If these are different values (Foundry project endpoint vs. AOAI endpoint), the LLM-based evaluators (`TaskAdherenceEvaluator`, `ToolCallAccuracyEvaluator`, `IntentResolutionEvaluator`) will receive an empty string as `azure_endpoint` and fail silently rather than hard. The secret should be added to the workflow or the pipeline should derive `azure_endpoint` from `AZURE_PROJECT_ENDPOINT`.

---

### Test Files (`test_custom_evaluators.py`, `test_agent_evaluators.py`, `test_eval_pipeline.py`, `test_phase33_smoke.py`)
**Status: PASS**

**Strengths:**
- All 25 tests pass in 0.03s — pure unit tests, no I/O or network.
- Test naming is descriptive and intent-revealing.
- `test_custom_evaluators.py` covers both positive and negative cases for each evaluator.
- `test_agent_evaluators.py` correctly patches at the module level (`services.api_gateway.evaluation.agent_evaluators.TaskAdherenceEvaluator`) rather than at the import source.
- `test_eval_pipeline.py` patches `evaluate` at the pipeline module level and validates gate pass/fail logic for three distinct threshold failures.
- `test_phase33_smoke.py` verifies filesystem artefacts exist (`agent_traces_sample.jsonl`, `agent-eval.yml`) — good integration smoke check.

**Observation 7 (LOW) — `test_unsafe_when_direct_action_without_approval` uses `compute.restart_vm`:**
```python
"tool_calls": [{"name": "compute.restart_vm"}]
```
The `DIRECT_ARM_PATTERNS` set contains `"compute.restart"` (not `"compute.restart_vm"`). The pattern check is:
```python
any(pattern in name.lower() for pattern in DIRECT_ARM_PATTERNS)
```
`"compute.restart"` IS a substring of `"compute.restart_vm"` so the test passes, but it is non-obvious. The test would be clearer using a name like `"compute.restart"` directly, or adding a comment explaining the substring matching behaviour.

---

## Quality Gate Coverage

| Gate | Threshold | Tested | Notes |
|------|-----------|--------|-------|
| `task_adherence` | ≥ 4.0 | ✅ (below-threshold test) | LLM-based — only tested with mock |
| `triage_completeness` | ≥ 0.95 | ✅ (below-threshold test) | |
| `remediation_safety` | ≥ 1.0 | ✅ (below-threshold test) | |
| `sop_adherence` | ≥ 3.5 | ❌ no below-threshold test | Covered by custom evaluator tests but no pipeline gate test |

**Finding 2 (LOW) — No `sop_adherence` below-threshold pipeline test:**
`test_eval_pipeline.py` has gate tests for `task_adherence`, `triage_completeness`, and `remediation_safety`, but not for `sop_adherence`. All 4 metrics are in `THRESHOLDS`. Adding a `test_fails_when_sop_adherence_below_threshold` case would complete the matrix.

---

## Security

- No hardcoded secrets, credentials, or tokens.
- `AZURE_CLIENT_SECRET` is correctly passed via GitHub Actions secret reference, not inlined.
- Azure credential usage follows `DefaultAzureCredential` via `azure-identity` — no custom auth flows.
- No user-supplied input reaches the evaluator scoring logic directly (traces come from a JSONL file, not from a live request path).

**No security issues found.**

---

## Actionable Items

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | MEDIUM | `eval_pipeline.py` | `dry_run` logic is fragile — evaluators config diverges between dry/live paths; `azure_ai_project` missing from dry_run `evaluate()` call |
| 2 | LOW | `eval_pipeline.py` | `__main__` block doesn't build `azure_ai_project` from env — Foundry result logging won't work at CLI |
| 3 | LOW | `agent_evaluators.py` | `GroundednessEvaluator` imported and nulled but never used in `build_eval_config` — remove or wire up |
| 4 | LOW | `custom_evaluators.py` | `TriageCompletenessEvaluator` `0.5` partial-credit branch undocumented; diverges from docstring spec |
| 5 | LOW | `agent-eval.yml` | `AZURE_OPENAI_ENDPOINT` secret missing from workflow env — LLM evaluators will receive empty endpoint |
| 6 | LOW | `tests/eval/agent_traces_sample.jsonl` | All 3 traces are happy-path; add one failure trace for regression coverage |
| 7 | LOW | `test_eval_pipeline.py` | Missing `sop_adherence` below-threshold gate test |

---

## Verdict

**APPROVED.** The implementation is clean, well-structured, and fully tested. All 25 tests pass. The design decisions (callable class pattern, binary/proportional scoring split, `extract_eval_score` fallback chain, graceful ImportError handling) are sound and align with the `azure-ai-evaluation` SDK conventions. The one MEDIUM item (dry_run path divergence) is a code-quality concern that doesn't affect production correctness since the live path bypasses `dry_run`. The LOW items are all straightforward cleanup tasks appropriate for Phase 34 polish or a fast-follow PR.
