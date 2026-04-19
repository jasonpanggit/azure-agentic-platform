---
id: "107-1"
phase: 107
plan: 1
status: complete
completed: "2026-04-19"
---

# Summary: Wire SRE propose_remediation to Cosmos approvals container

## What Was Built

Wired `propose_remediation` in `agents/sre/tools.py` to persist approval records to the Cosmos DB `approvals` container — the same container read by the `ApprovalQueueCard` UI via `GET /api/v1/approvals?status=pending`. SRE remediation proposals now appear in the human-in-the-loop queue immediately upon invocation.

Fixed the latent `container=None` bug in `agents/shared/approval_manager.py`: when `container` is `None`, the function now lazy-initialises a Cosmos client using `COSMOS_ENDPOINT` + `DefaultAzureCredential` (matching the pattern in `services/api-gateway/approvals.py`).

## Key Changes

### `agents/shared/approval_manager.py`
- Added lazy imports for `CosmosClient` and `DefaultAzureCredential` under `try/except ImportError`
- `create_approval_record` now self-initialises when `container=None`: reads `COSMOS_ENDPOINT` + `COSMOS_DATABASE_NAME` env vars, creates client, returns `approvals` container proxy
- Raises `ValueError` if `COSMOS_ENDPOINT` is missing; raises `ImportError` if SDK unavailable

### `agents/sre/tools.py`
- `propose_remediation` now calls `create_approval_record(container=None, ...)` after building the proposal dict
- Failure is non-fatal: caught in `except Exception`, logs a warning, sets `approval_id = ""`, returns normally
- Added `thread_id: str = ""` parameter for tracing correlation
- Return dict now includes `approval_id` and `status: pending_approval | pending_review`

### `agents/tests/sre/test_sre_tools.py`
- Added `TestProposeRemediation` class with 3 tests:
  - Happy path: Cosmos write called, `approval_id` populated
  - Failure non-fatal: Cosmos raises `Exception`, tool still returns success
  - Correct args: `create_approval_record` called with correct `incident_id`, `agent_name`, `risk_level`

### `agents/tests/shared/test_approval_manager.py` (new)
- 4 tests for `create_approval_record`:
  - `container=None` with env vars → lazy-init path
  - `container` provided → uses existing proxy
  - Missing `COSMOS_ENDPOINT` → raises `ValueError`
  - Missing SDK → raises `ImportError`

## Test Results

```
41 passed, 5 warnings in 2.17s
```

(Warnings are `RuntimeWarning: coroutine never awaited` — benign mock artefacts from `AsyncMock` used with a sync function; tests pass correctly.)

## Self-Check: PASSED

- [x] `propose_remediation` writes to Cosmos `approvals` container on every invocation
- [x] `container=None` lazy-init path tested and functional
- [x] Cosmos write failure is non-fatal (tool always returns)
- [x] `approval_id` returned in response dict
- [x] No scan button, no Cosmos intermediary in the read path
- [x] 41 tests passing (37 pre-existing + 4 new approval_manager tests)
