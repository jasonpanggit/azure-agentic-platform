---
plan: 17-01
status: complete
commit: 3c18b4c
branch: gsd/phase-17-resource-chat
completed: 2026-04-02
---

# Summary: Plan 17-01 — Resource-Scoped Chat API Endpoint

## What Was Built

Added `POST /api/v1/vms/{resource_id_base64}/chat` — a new FastAPI endpoint that routes VM investigation conversations directly to the compute agent (bypassing the orchestrator), with pre-fetched diagnostic evidence injected as context on thread creation.

## Files Modified

| File | Change |
|------|--------|
| `services/api-gateway/vm_chat.py` | **New** — full endpoint implementation |
| `services/api-gateway/main.py` | Added `vm_chat_router` import + registration (after `vm_detail_router`) |
| `services/api-gateway/tests/test_vm_chat.py` | **New** — 10 unit/integration tests |

## Implementation Details

### vm_chat.py

- **`_decode_resource_id()`** — base64url decode with padding normalization (copied from vm_detail.py, not imported, to avoid coupling)
- **`_load_evidence()`** — loads evidence doc from Cosmos `evidence` container by incident_id
- **`_load_latest_evidence_for_resource()`** — fallback: queries `incidents` container for most-recent `evidence_ready` incident for the resource, then loads that evidence
- **`_build_evidence_context()`** — formats health state, recent activity (capped at 5, truncation note for 6+), metric anomalies, log error count/samples into a markdown context message
- **`_create_or_continue_vm_thread()`** — core async function:
  - New thread: `client.threads.create()` → inject evidence context message → append user message → `client.runs.create(agent_id=COMPUTE_AGENT_ID)`
  - Continuing thread: cancel active runs → append user message → create new run
  - Graceful degradation: if `cosmos_client` is None, skips evidence injection but still works
- **`start_vm_chat()`** — route handler with 400 (bad base64), 503 (missing COMPUTE_AGENT_ID), 502 (Foundry error) error handling

### main.py changes

Router registration order preserved:
1. `vm_inventory_router` — GET /api/v1/vms
2. `vm_detail_router` — GET /api/v1/vms/{id}, GET /api/v1/vms/{id}/metrics
3. `vm_chat_router` — POST /api/v1/vms/{id}/chat ← added

POST method prevents any conflict with vm_detail_router's GET routes.

## Test Results

```
10 passed in test_vm_chat.py
329 passed, 2 skipped in full suite (0 regressions)
```

### Test Coverage

| Test | What it validates |
|------|-------------------|
| `test_decode_resource_id` | Round-trip encode/decode |
| `test_decode_resource_id_invalid` | ValueError on bad base64 |
| `test_build_evidence_context_no_evidence` | Fallback message when evidence=None |
| `test_build_evidence_context_with_evidence` | Health, CPU anomaly, activity, log errors all present |
| `test_build_evidence_context_no_anomalies` | "No activity log events" branch |
| `test_build_evidence_context_truncates_long_change_list` | "and 3 more events" for 8-item list |
| `test_start_vm_chat_success` | 200 + correct thread_id/run_id/status="created" |
| `test_start_vm_chat_continue_thread` | status="continued" when thread_id provided |
| `test_start_vm_chat_503_when_no_compute_agent` | ValueError → 503 |
| `test_start_vm_chat_400_bad_encoding` | Invalid base64 → 400 |

## Success Criteria Check

- [x] `POST /api/v1/vms/{base64_id}/chat` returns `{ thread_id, run_id, status }`
- [x] New thread: evidence context injected as first message when Cosmos is available
- [x] Continuing thread: no context injection, just appends message
- [x] Returns 503 when `COMPUTE_AGENT_ID` is not set
- [x] Returns 400 for invalid base64 encoding
- [x] 10 unit tests pass (plan required 8+)
- [x] All existing API gateway tests still pass (329 passed, 0 regressions)

## One Implementation Note

The plan's integration tests used bare `TestClient(app)` without initializing `app.state`. This fails because `get_credential` reads `request.app.state.credential`. Fixed by following the existing pattern from `test_vm_detail.py`: set `app.state.credential = MagicMock()` and `app.state.cosmos_client = None` before constructing each `TestClient`. This is consistent with all other integration tests in the suite.
