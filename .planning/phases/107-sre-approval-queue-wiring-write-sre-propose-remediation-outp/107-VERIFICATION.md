---
phase: 107
plan: "107-1"
verified: "2026-04-19"
result: PASS
---

# Verification Report — Phase 107

## Goal

Wire `SRE propose_remediation` to the Cosmos `approvals` container so SRE-initiated remediation
proposals are persisted and surfaced in the human-in-the-loop `ApprovalQueueCard` UI
(`GET /api/v1/approvals?status=pending`).

---

## Must-Have Checks

### 1. `create_approval_record` handles `container=None` via lazy Cosmos init ✅

**File:** `agents/shared/approval_manager.py` lines 48–57

```python
if container is None:
    endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    if not endpoint:
        raise ValueError("COSMOS_ENDPOINT environment variable is required.")
    if CosmosClient is None or DefaultAzureCredential is None:
        raise ImportError("azure-cosmos and azure-identity are required.")
    cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
    database = cosmos_client.get_database_client(database_name)
    container = database.get_container_client("approvals")
```

- `CosmosClient` and `DefaultAzureCredential` are lazy-imported under `try/except ImportError` at module level (lines 17–26).
- Missing `COSMOS_ENDPOINT` raises `ValueError` (not `AttributeError`).
- Container name is hardcoded as `"approvals"` — matching the API gateway read path.

---

### 2. `propose_remediation` calls `create_approval_record` on every invocation ✅

**File:** `agents/sre/tools.py` lines 432–455

```python
try:
    record = create_approval_record(
        container=None,
        thread_id=thread_id,
        incident_id=incident_id,
        agent_name="sre-agent",
        proposal=proposal,
        resource_snapshot={
            "affected_resources": affected_resources,
            "hypothesis": hypothesis,
        },
        risk_level=risk_level,
    )
    approval_id = record.get("id", "") if isinstance(record, dict) else getattr(record, "id", "")
    ...
except Exception as exc:
    logger.warning(
        "propose_remediation: cosmos write failed (returning log-only) | error=%s", exc,
    )
    approval_id = ""
```

`create_approval_record` is imported from `shared.approval_manager` at line 17 of `agents/sre/tools.py`.

---

### 3. Cosmos write failure is non-fatal ✅

The `try/except Exception` block (lines 432–455) catches all failures, logs a warning, sets
`approval_id = ""`, and continues to return the full response dict with:
- `"requires_approval": True` (REMEDI-001 preserved)
- `"status": "pending_review"` (when `approval_id` is empty)

Confirmed by `test_cosmos_write_failure_is_non_fatal` — passes with `ValueError` side effect.

---

### 4. `create_approval_record` is a sync function — no unawaited coroutine bug ✅

**Finding:** The plan originally spec'd `create_approval_record` as `async def`, but the implementation
correctly made it a plain `def` (line 33 of `approval_manager.py`). This is correct because:
- `CosmosClient.create_item()` is a synchronous call (azure-cosmos sync SDK)
- `propose_remediation` is also `def` (sync `@ai_function`)
- Tests mock `create_approval_record` as a plain `MagicMock` (not `AsyncMock`), confirming sync contract

No unawaited coroutine risk exists.

---

### 5. Tests cover happy path, failure path, and correct args ✅

**`agents/tests/sre/test_sre_tools.py` — `TestProposeRemediation` (4 tests):**

| Test | Path | Coverage |
|------|------|----------|
| `test_returns_success_with_approval_required` | Happy path | `approval_id` in result, `requires_approval=True` |
| `test_contains_all_required_fields` | Happy path | All required return fields present |
| `test_cosmos_write_called_with_correct_args` | Happy path + arg verification | `agent_name`, `incident_id`, `risk_level`, `thread_id`, `container=None` |
| `test_cosmos_write_failure_is_non_fatal` | Failure path | `approval_id=""`, `status=pending_review`, no exception raised |

**`agents/tests/shared/test_approval_manager.py` — `TestCreateApprovalRecordContainerNone` (2 tests):**

| Test | Path |
|------|------|
| `test_container_none_initialises_cosmos_from_env` | `container=None` lazy-init path, `CosmosClient` constructed from env |
| `test_container_none_missing_endpoint_raises` | Missing `COSMOS_ENDPOINT` → `ValueError` |

---

### 6. 41 tests pass ✅

```
agents/tests/sre/test_sre_tools.py    39 passed
agents/tests/shared/test_approval_manager.py   2 passed
─────────────────────────────────────────────
TOTAL                                 41 passed, 1 warning in 0.48s
```

The 1 warning is an unrelated `urllib3`/OpenSSL version notice on the macOS test runner — not a code issue.

---

## Phase Goal: ACHIEVED ✅

SRE `propose_remediation` now:
1. Persists every proposal to the Cosmos `approvals` container with `status: pending`
2. Returns `approval_id` so callers can reference the persisted record
3. Degrades gracefully when Cosmos is unavailable (log-only, `requires_approval: True` preserved)
4. Proposals are immediately visible via `GET /api/v1/approvals?status=pending` → `ApprovalQueueCard` UI

No API gateway changes were required — the existing endpoint already queries the same `approvals` container.
