# Summary 35-1: Verification Feedback to Foundry Thread (Backend)

## Result: PASS

All 7 tasks completed successfully. 29/29 tests passing.

## What Changed

### services/api-gateway/remediation_executor.py
- **`_cancel_active_runs(client, thread_id)`** — Cancels active Foundry runs on a thread before injecting a new message. Uses `client.runs.cancel` (same pattern as `chat.py`).
- **`_VERIFICATION_INSTRUCTIONS` + `_build_verification_instruction(result)`** — Pure function returning tailored re-diagnosis instructions for RESOLVED/IMPROVED/DEGRADED/TIMEOUT outcomes.
- **`_inject_verification_result(...)`** — Injects verification outcome into originating Foundry thread (LOOP-001). Checks `re_diagnosis_count` (capped at `MAX_RE_DIAGNOSIS_COUNT=3`), cancels active runs, posts AGENT-002 envelope message, creates new orchestrator run, increments count. Correct API namespaces: `client.runs.cancel` for cancellation, `client.agents.create_message` and `client.agents.create_run` for thread injection.
- **`_verify_remediation`** — Added `thread_id: str` parameter. Initialized `rollback_id = None` before DEGRADED block (prevents NameError). Calls `_inject_verification_result` at end when `thread_id` is non-empty.
- **`_delayed_verify`** — Added `thread_id: str` parameter, passes through to `_verify_remediation`.
- **`execute_remediation`** — Passes `thread_id` through to `_delayed_verify`.
- **`run_missed_verification_sweep(cosmos_client, credential)`** — Startup sweep catches WAL records with `status=complete` but no `verification_result` and `executed_at > 20 minutes ago`. Re-runs verification for each.

### services/api-gateway/models.py
- **`IncidentSummary.re_diagnosis_count`** — New integer field (default=0) tracking agent re-diagnosis count per incident.

### services/api-gateway/main.py
- **Startup sweep** — `run_missed_verification_sweep` queued as `asyncio.create_task` in lifespan, using `app.state.credential` (not a fresh `DefaultAzureCredential()`).

### services/api-gateway/tests/test_remediation_executor.py
- 10 new tests covering all new code paths (29 total, all passing).

## Requirements Satisfied

| ID | Requirement | Status |
|----|-------------|--------|
| LOOP-001 | After verification, inject outcome into Foundry thread and create new orchestrator run | DONE |
| LOOP-004 | Max re_diagnosis_count=3 per incident to prevent infinite loops | DONE |

## Commits

| # | Message |
|---|---------|
| 1 | `feat: add _cancel_active_runs helper to remediation_executor.py (35-1-1)` |
| 2 | `feat: add _build_verification_instruction helper (35-1-2)` |
| 3 | `feat: add _inject_verification_result function (35-1-3)` |
| 4 | `feat: wire _inject_verification_result into _verify_remediation (35-1-4)` |
| 5 | `feat: add re_diagnosis_count to IncidentSummary model (35-1-5)` |
| 6 | `feat: add startup sweep for missed verifications (35-1-6)` |
| 7 | `test: add 10 unit tests for verification feedback loop (35-1-7)` |
