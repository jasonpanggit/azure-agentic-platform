---
wave: 1
depends_on: []
files_modified:
  - services/api-gateway/remediation_executor.py
  - services/api-gateway/models.py
  - services/api-gateway/main.py
  - services/api-gateway/tests/test_remediation_executor.py
autonomous: true
---

# Plan 35-1: Verification Feedback to Foundry Thread (Backend)

## Goal

After `_verify_remediation()` classifies the post-execution resource health as RESOLVED/IMPROVED/DEGRADED/TIMEOUT, inject the verification outcome into the originating Foundry agent thread and create a new orchestrator run. This triggers automatic re-diagnosis by the domain agent. Add a `re_diagnosis_count` field on incident documents (capped at 3) to prevent infinite loops. Add a startup sweep to catch verifications missed due to process restarts.

## Derived Requirements

- **LOOP-001:** After verification completes, inject outcome into originating Foundry thread and create a new orchestrator run for re-diagnosis.
- **LOOP-004:** Domain agent re-diagnoses after receiving verification result; max `re_diagnosis_count=3` per incident.

<threat_model>

### Authentication/Authorization Risks
- **LOW:** Thread injection uses the same `_get_foundry_client()` pattern as `_resume_foundry_thread()` in `approvals.py`. Foundry client authenticates via `DefaultAzureCredential` (system-assigned managed identity). No new auth surface introduced.

### Input Validation Risks
- **LOW:** `verification_result` is constrained to one of four string literals (RESOLVED/IMPROVED/DEGRADED/TIMEOUT) from `_classify_verification()`. No user-supplied input flows into the thread message beyond these controlled values.
- **LOW:** `re_diagnosis_count` is an integer field incremented server-side. Never set from external input.

### Data Exposure Risks
- **LOW:** Verification result messages contain `execution_id`, `resource_id`, `proposed_action` — all already present in the WAL record which is stored in Cosmos. No new sensitive data introduced.

### High-Severity Threats
- **MEDIUM (mitigated):** Infinite re-diagnosis loop risk. Mitigated by `re_diagnosis_count` cap at 3, plus existing session budget cap (AGENT-007, $5 default).
- **MEDIUM (mitigated):** Race condition on fire-and-forget verification. Mitigated by startup sweep for missed verifications (records with `status=complete` but `verification_result=None` and `executed_at > 20 minutes ago`).

**Verdict:** No blocking threats. All medium risks have explicit mitigations built into the plan.

</threat_model>

## Tasks

<task id="35-1-1">
<title>Add _cancel_active_runs helper to remediation_executor.py</title>
<read_first>
- services/api-gateway/remediation_executor.py (current code — understand imports and structure)
- services/api-gateway/chat.py (lines 199-223 — existing cancel active runs pattern to replicate)
- services/api-gateway/foundry.py (_get_foundry_client function signature)
</read_first>
<action>
Add a new async function `_cancel_active_runs(client: Any, thread_id: str) -> None` to `remediation_executor.py`.

**API namespace note:** Run listing uses `client.runs.list(...)` and cancellation uses `client.runs.cancel(...)` — these are on the `runs` namespace, NOT `client.agents.*`. This matches the pattern in `chat.py`.

Implementation:
```python
async def _cancel_active_runs(client: Any, thread_id: str) -> None:
    """Cancel all active runs on a Foundry thread before injecting a new message.

    Follows the same pattern as chat.py create_chat_thread:
    - Lists runs on the thread
    - Cancels any with status in {"queued", "in_progress", "requires_action", "cancelling"}
    - Sleeps 1s if any were cancelled to allow propagation

    Uses client.runs.* namespace (not client.agents.*).
    """
    try:
        runs = list(client.runs.list(thread_id=thread_id))
        active_statuses = {"queued", "in_progress", "requires_action", "cancelling"}
        cancelled_any = False
        for run in runs:
            if run.status in active_statuses:
                logger.info(
                    "_cancel_active_runs: cancelling run %s (status=%s) on thread %s",
                    run.id, run.status, thread_id,
                )
                try:
                    client.runs.cancel(thread_id=thread_id, run_id=run.id)
                    cancelled_any = True
                except Exception as cancel_exc:
                    logger.warning("_cancel_active_runs: failed to cancel run %s: %s", run.id, cancel_exc)
        if cancelled_any:
            await asyncio.sleep(1)
    except Exception as exc:
        logger.warning("_cancel_active_runs: failed to list/cancel runs on thread %s: %s", thread_id, exc)
```

Place it after `_classify_verification` and before `_verify_remediation`.
</action>
<acceptance_criteria>
- grep -n "_cancel_active_runs" services/api-gateway/remediation_executor.py returns at least 2 lines (definition + docstring)
- grep "active_statuses" services/api-gateway/remediation_executor.py matches {"queued", "in_progress", "requires_action", "cancelling"}
- grep "client.runs.cancel" services/api-gateway/remediation_executor.py returns at least 1 match
- grep "client.runs.list" services/api-gateway/remediation_executor.py returns at least 1 match
- grep "await asyncio.sleep(1)" services/api-gateway/remediation_executor.py returns at least 1 match
- remediation_executor.py contains `client.runs.cancel` (NOT `client.agents.cancel`)
</acceptance_criteria>
</task>

<task id="35-1-2">
<title>Add _build_verification_instruction helper</title>
<read_first>
- services/api-gateway/remediation_executor.py (current code)
- .planning/phases/35-post-remediation-intelligence-loop/35-RESEARCH.md (Section 5 — _build_instruction specification with exact text for each result)
</read_first>
<action>
Add `_build_verification_instruction(verification_result: str) -> str` to `remediation_executor.py`.

This is a pure function returning a tailored instruction string for each verification outcome:

```python
_VERIFICATION_INSTRUCTIONS: dict[str, str] = {
    "RESOLVED": (
        "The remediation action has RESOLVED the issue. "
        "Confirm the resource is healthy, summarize the root cause and fix, "
        "and recommend this incident be closed."
    ),
    "IMPROVED": (
        "The remediation action has IMPROVED the resource health but the issue "
        "is not fully resolved. Re-diagnose the current state and determine if "
        "a follow-up action is needed."
    ),
    "DEGRADED": (
        "The remediation action has DEGRADED the resource. Auto-rollback has been triggered. "
        "Re-diagnose the issue with fresh signals and propose an alternative approach. "
        "Do NOT re-propose the same action that caused degradation."
    ),
    "TIMEOUT": (
        "Verification timed out — resource health status is unknown. "
        "Re-check the resource health manually and report the current state. "
        "If the resource is healthy, recommend closure. If not, propose next steps."
    ),
}


def _build_verification_instruction(verification_result: str) -> str:
    """Build the re-diagnosis instruction based on verification outcome."""
    return _VERIFICATION_INSTRUCTIONS.get(verification_result, _VERIFICATION_INSTRUCTIONS["TIMEOUT"])
```

Place it after `_cancel_active_runs` and before `_verify_remediation`.
</action>
<acceptance_criteria>
- grep -c "_VERIFICATION_INSTRUCTIONS" services/api-gateway/remediation_executor.py returns at least 1
- grep "_build_verification_instruction" services/api-gateway/remediation_executor.py returns at least 2 lines (definition + usage in dict)
- grep "RESOLVED.*root cause" services/api-gateway/remediation_executor.py returns 1 match
- grep "DEGRADED.*Do NOT re-propose" services/api-gateway/remediation_executor.py returns 1 match
</acceptance_criteria>
</task>

<task id="35-1-3">
<title>Add _inject_verification_result function</title>
<read_first>
- services/api-gateway/remediation_executor.py (current code — place after _build_verification_instruction)
- services/api-gateway/approvals.py (lines 260-296 — _resume_foundry_thread pattern to replicate: create_message + create_run with foundry_span + agent_span)
- services/api-gateway/foundry.py (_get_foundry_client import)
- services/api-gateway/instrumentation.py (foundry_span, agent_span imports)
</read_first>
<action>
Add async function `_inject_verification_result()` to `remediation_executor.py`. This follows the exact `_resume_foundry_thread` pattern from `approvals.py`.

**API namespace note:** Message creation uses `client.agents.create_message(...)` and run creation uses `client.agents.create_run(...)` — these are on the `agents` namespace (not `client.runs.*`). Run cancellation (task 35-1-1) uses `client.runs.cancel(...)`. These are different namespaces in the Foundry SDK.

```python
MAX_RE_DIAGNOSIS_COUNT: int = int(os.environ.get("MAX_RE_DIAGNOSIS_COUNT", "3"))


async def _inject_verification_result(
    thread_id: str,
    execution_id: str,
    verification_result: str,
    resource_id: str,
    proposed_action: str,
    rolled_back: bool,
    incident_id: str,
    cosmos_client: Optional[Any],
) -> None:
    """Inject verification result into the originating Foundry thread and create a new run (LOOP-001).

    1. Check re_diagnosis_count on the incident — if >= MAX_RE_DIAGNOSIS_COUNT, log escalation and return
    2. Cancel active runs on the thread (client.runs.cancel)
    3. Post a verification_result message following AGENT-002 envelope format (client.agents.create_message)
    4. Create a new orchestrator run for re-diagnosis (client.agents.create_run)
    5. Increment re_diagnosis_count on the incident
    """
    # --- Guard: check re_diagnosis_count ---
    current_count = 0
    if cosmos_client is not None:
        try:
            db_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
            incidents_container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
            inc_docs = list(incidents_container.query_items(
                query="SELECT c.re_diagnosis_count FROM c WHERE c.incident_id = @iid",
                parameters=[{"name": "@iid", "value": incident_id}],
                enable_cross_partition_query=True,
            ))
            if inc_docs:
                current_count = inc_docs[0].get("re_diagnosis_count", 0) or 0
        except Exception as exc:
            logger.warning("_inject_verification_result: failed to read re_diagnosis_count | %s", exc)

    if current_count >= MAX_RE_DIAGNOSIS_COUNT:
        logger.warning(
            "_inject_verification_result: max re-diagnosis reached | "
            "incident_id=%s count=%d max=%d — escalating to operator",
            incident_id, current_count, MAX_RE_DIAGNOSIS_COUNT,
        )
        return

    # --- Inject message and create run ---
    try:
        from services.api_gateway.foundry import _get_foundry_client
        from services.api_gateway.instrumentation import foundry_span, agent_span
        import json

        client = _get_foundry_client()
        orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID", "")
        if not orchestrator_agent_id:
            logger.error("_inject_verification_result: ORCHESTRATOR_AGENT_ID not set")
            return

        # Cancel active runs first (uses client.runs.cancel)
        await _cancel_active_runs(client, thread_id)

        # Build AGENT-002 typed JSON envelope
        message = {
            "correlation_id": incident_id,
            "source_agent": "api-gateway",
            "target_agent": "orchestrator",
            "message_type": "verification_result",
            "payload": {
                "execution_id": execution_id,
                "verification_result": verification_result,
                "resource_id": resource_id,
                "proposed_action": proposed_action,
                "rolled_back": rolled_back,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "instruction": _build_verification_instruction(verification_result),
            },
        }

        # Post message to thread (uses client.agents.create_message)
        with foundry_span("post_message", thread_id=thread_id) as span:
            span.set_attribute("foundry.message_type", "verification_result")
            client.agents.create_message(
                thread_id=thread_id,
                role="user",
                content=json.dumps(message),
            )

        # Create new orchestrator run (uses client.agents.create_run)
        with agent_span("orchestrator", correlation_id=execution_id) as span:
            with foundry_span("create_run", thread_id=thread_id):
                client.agents.create_run(
                    thread_id=thread_id,
                    assistant_id=orchestrator_agent_id,
                )

        # Increment re_diagnosis_count
        if cosmos_client is not None:
            try:
                db_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
                incidents_container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
                incidents_container.patch_item(
                    item=incident_id,
                    partition_key=incident_id,
                    patch_operations=[
                        {"op": "incr", "path": "/re_diagnosis_count", "value": 1},
                    ],
                )
            except Exception as exc:
                logger.warning("_inject_verification_result: failed to increment re_diagnosis_count | %s", exc)

        logger.info(
            "_inject_verification_result: injected | thread_id=%s execution_id=%s result=%s count=%d",
            thread_id, execution_id, verification_result, current_count + 1,
        )

    except Exception as exc:
        logger.error(
            "_inject_verification_result: failed | thread_id=%s execution_id=%s error=%s",
            thread_id, execution_id, exc,
        )
```
</action>
<acceptance_criteria>
- grep -n "_inject_verification_result" services/api-gateway/remediation_executor.py returns at least 3 lines (definition, docstring reference, call site)
- grep "MAX_RE_DIAGNOSIS_COUNT" services/api-gateway/remediation_executor.py returns at least 2 matches
- grep "message_type.*verification_result" services/api-gateway/remediation_executor.py returns 1 match
- grep "foundry_span.*post_message" services/api-gateway/remediation_executor.py returns 1 match
- grep "client.agents.create_run" services/api-gateway/remediation_executor.py returns at least 1 match
- grep "client.agents.create_message" services/api-gateway/remediation_executor.py returns at least 1 match
- grep "re_diagnosis_count" services/api-gateway/remediation_executor.py returns at least 3 matches
- grep "incr.*re_diagnosis_count" services/api-gateway/remediation_executor.py returns 1 match
- remediation_executor.py contains `client.runs.cancel` (task 35-1-1) AND `client.agents.create_run` (this task) — both namespaces used correctly
</acceptance_criteria>
</task>

<task id="35-1-4">
<title>Wire _inject_verification_result into _verify_remediation (required fix to avoid NameError at runtime)</title>
<read_first>
- services/api-gateway/remediation_executor.py (_verify_remediation function — lines 288-371)
</read_first>
<action>
Modify `_verify_remediation` to call `_inject_verification_result` after writing the WAL update and after potential rollback. Add `thread_id` parameter to `_verify_remediation` and `_delayed_verify`.

**Critical: `rollback_id` must be initialized to `None` before the `if classification == "DEGRADED":` block.** Without this, the variable is undefined in non-DEGRADED paths, causing a `NameError` at runtime when `rolled_back = classification == "DEGRADED" and rollback_id is not None` is evaluated. This is a required fix to avoid NameError at runtime, not just a style improvement.

1. **Add `thread_id: str` parameter** to `_verify_remediation` signature (after `incident_id`):
   ```python
   async def _verify_remediation(
       execution_id: str,
       resource_id: str,
       incident_id: str,
       thread_id: str,  # NEW
       proposed_action: str,
       credential: Any,
       cosmos_client: Optional[Any],
   ) -> str:
   ```

2. **Add `thread_id: str` parameter** to `_delayed_verify` signature (after `incident_id`):
   ```python
   async def _delayed_verify(
       execution_id: str,
       resource_id: str,
       incident_id: str,
       thread_id: str,  # NEW
       proposed_action: str,
       credential: Any,
       cosmos_client: Optional[Any],
   ) -> None:
   ```
   And pass it through to `_verify_remediation`:
   ```python
   await _verify_remediation(
       execution_id=execution_id,
       resource_id=resource_id,
       incident_id=incident_id,
       thread_id=thread_id,
       proposed_action=proposed_action,
       credential=credential,
       cosmos_client=cosmos_client,
   )
   ```

3. **Initialize `rollback_id = None` BEFORE the `if classification == "DEGRADED":` block** to prevent NameError on the non-DEGRADED code paths:
   ```python
   rollback_id = None
   if classification == "DEGRADED":
       # ... existing rollback code ...
       rollback_id = await _rollback(...)
   ```

4. **At the END of `_verify_remediation`**, after the DEGRADED rollback block (after line 371), add:
   ```python
   # --- Inject verification result into originating Foundry thread (LOOP-001) ---
   if thread_id:
       rolled_back = classification == "DEGRADED" and rollback_id is not None
       await _inject_verification_result(
           thread_id=thread_id,
           execution_id=execution_id,
           verification_result=classification,
           resource_id=resource_id,
           proposed_action=proposed_action,
           rolled_back=rolled_back if classification == "DEGRADED" else False,
           incident_id=incident_id,
           cosmos_client=cosmos_client,
       )
   ```

5. **Update the `execute_remediation` call to `_delayed_verify`** to pass `thread_id`:
   ```python
   asyncio.create_task(
       _delayed_verify(
           execution_id=execution_id,
           resource_id=resource_id,
           incident_id=incident_id,
           thread_id=thread_id,  # NEW — already available in execute_remediation scope
           proposed_action=proposed_action,
           credential=credential,
           cosmos_client=cosmos_client,
       )
   )
   ```
</action>
<acceptance_criteria>
- grep "thread_id: str" services/api-gateway/remediation_executor.py returns at least 2 matches (in _verify_remediation and _delayed_verify)
- grep "_inject_verification_result" services/api-gateway/remediation_executor.py returns at least 4 matches (definition + call + import-like references)
- grep "rollback_id = None" services/api-gateway/remediation_executor.py returns 1 match (initialization before if-block)
- The line `rollback_id = None` appears BEFORE the line `if classification == "DEGRADED":` in the file — verified by line number ordering
- grep "thread_id=thread_id" services/api-gateway/remediation_executor.py returns at least 2 matches
</acceptance_criteria>
</task>

<task id="35-1-5">
<title>Add re_diagnosis_count to IncidentSummary model</title>
<read_first>
- services/api-gateway/models.py (IncidentSummary class — lines 279-328)
</read_first>
<action>
Add `re_diagnosis_count` field to the `IncidentSummary` Pydantic model:

```python
re_diagnosis_count: int = Field(
    default=0,
    description=(
        "Number of times the agent has re-diagnosed this incident after remediation "
        "verification. Capped at MAX_RE_DIAGNOSIS_COUNT (default 3) to prevent infinite loops."
    ),
)
```

Place it after `slo_escalated` field (after line 328) and before the closing of the class.
</action>
<acceptance_criteria>
- grep "re_diagnosis_count" services/api-gateway/models.py returns at least 1 match
- grep "MAX_RE_DIAGNOSIS_COUNT" services/api-gateway/models.py returns 1 match (in the description string)
- grep "default=0" services/api-gateway/models.py returns at least 1 match for re_diagnosis_count line
</acceptance_criteria>
</task>

<task id="35-1-6">
<title>Add startup sweep for missed verifications</title>
<read_first>
- services/api-gateway/remediation_executor.py (run_wal_stale_monitor function — lines 647-689)
- services/api-gateway/main.py (lifespan function — search for "run_wal_stale_monitor" to see how background tasks are started; also note how `app.state.credential` is set during startup)
</read_first>
<action>
Add a new async function `run_missed_verification_sweep` to `remediation_executor.py` that runs once on startup:

```python
async def run_missed_verification_sweep(
    cosmos_client: Optional[Any],
    credential: Any,
) -> None:
    """Startup sweep: re-verify WAL records that completed execution but never got verified.

    Catches records where:
    - status = 'complete'
    - verification_result IS NULL
    - executed_at > 20 minutes ago (verification should have completed by now)

    For each missed record, runs _verify_remediation immediately.
    """
    if cosmos_client is None:
        return

    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=20)
        ).isoformat()
        container = _get_remediation_audit_container(cosmos_client)
        query = (
            "SELECT * FROM c "
            "WHERE c.status = 'complete' "
            "AND NOT IS_DEFINED(c.verification_result) "
            "AND c.executed_at < @cutoff "
            "AND c.action_type = 'execute'"
        )
        missed = list(container.query_items(
            query=query,
            parameters=[{"name": "@cutoff", "value": cutoff}],
            enable_cross_partition_query=True,
        ))

        if not missed:
            logger.info("run_missed_verification_sweep: no missed verifications found")
            return

        logger.warning(
            "run_missed_verification_sweep: found %d missed verifications", len(missed)
        )

        for record in missed:
            execution_id = record.get("id", "")
            resource_id = record.get("resource_id", "")
            incident_id = record.get("incident_id", "")
            thread_id = record.get("thread_id", "")
            proposed_action = record.get("proposed_action", "")

            logger.info(
                "run_missed_verification_sweep: re-verifying | execution_id=%s",
                execution_id,
            )
            try:
                await _verify_remediation(
                    execution_id=execution_id,
                    resource_id=resource_id,
                    incident_id=incident_id,
                    thread_id=thread_id,
                    proposed_action=proposed_action,
                    credential=credential,
                    cosmos_client=cosmos_client,
                )
            except Exception as exc:
                logger.error(
                    "run_missed_verification_sweep: failed | execution_id=%s error=%s",
                    execution_id, exc,
                )

    except Exception as exc:
        logger.error("run_missed_verification_sweep: sweep failed | %s", exc)
```

Then, in `services/api-gateway/main.py`, add the startup sweep call in the lifespan function. Search for the `run_wal_stale_monitor` call and add after it. **Use `app.state.credential` — do NOT instantiate a new `DefaultAzureCredential()`:**

```python
# Startup sweep for missed verifications (LOOP-001)
from services.api_gateway.remediation_executor import run_missed_verification_sweep
asyncio.create_task(run_missed_verification_sweep(
    cosmos_client=app.state.cosmos_client if hasattr(app.state, "cosmos_client") else None,
    credential=app.state.credential,
))
```
</action>
<acceptance_criteria>
- grep -n "run_missed_verification_sweep" services/api-gateway/remediation_executor.py returns at least 2 lines (definition + docstring)
- grep "run_missed_verification_sweep" services/api-gateway/main.py returns at least 1 match
- grep "verification_result.*NOT IS_DEFINED" services/api-gateway/remediation_executor.py returns 1 match
- grep "executed_at.*cutoff" services/api-gateway/remediation_executor.py returns at least 1 match
- grep "app.state.credential" services/api-gateway/main.py returns at least 1 match in the sweep call context
- grep "DefaultAzureCredential" services/api-gateway/main.py does NOT appear in the sweep call (must use app.state.credential instead)
</acceptance_criteria>
</task>

<task id="35-1-7">
<title>Unit tests for verification feedback loop</title>
<read_first>
- services/api-gateway/tests/test_remediation_executor.py (existing tests — understand mock patterns, fixtures, test naming)
- services/api-gateway/remediation_executor.py (all new functions)
</read_first>
<action>
Add the following tests to `services/api-gateway/tests/test_remediation_executor.py`:

1. **`test_build_verification_instruction_resolved`** — asserts `_build_verification_instruction("RESOLVED")` contains "RESOLVED the issue" and "recommend this incident be closed"

2. **`test_build_verification_instruction_degraded`** — asserts `_build_verification_instruction("DEGRADED")` contains "DEGRADED" and "Do NOT re-propose"

3. **`test_build_verification_instruction_unknown_falls_back_to_timeout`** — asserts `_build_verification_instruction("UNKNOWN")` returns the TIMEOUT instruction (contains "timed out")

4. **`test_cancel_active_runs_cancels_in_progress`** — mocks `client.runs.list()` returning 1 run with status="in_progress", asserts `client.runs.cancel` was called once

5. **`test_cancel_active_runs_skips_completed`** — mocks `client.runs.list()` returning 1 run with status="completed", asserts `client.runs.cancel` was NOT called

6. **`test_inject_verification_result_respects_max_re_diagnosis`** — mocks Cosmos query returning `{"re_diagnosis_count": 3}`, calls `_inject_verification_result`, asserts `_get_foundry_client` was NOT called (because cap reached)

7. **`test_inject_verification_result_increments_count`** — mocks Cosmos query returning `{"re_diagnosis_count": 1}`, mocks Foundry client, calls `_inject_verification_result`, asserts `patch_item` was called with `{"op": "incr", "path": "/re_diagnosis_count", "value": 1}`

8. **`test_verify_remediation_calls_inject_when_thread_id_present`** — patches `_inject_verification_result`, `_get_foundry_client`, and ARM health check returning "Available", calls `_verify_remediation` with `thread_id="thread-123"`, asserts `_inject_verification_result` was called once with `verification_result="IMPROVED"`

9. **`test_verify_remediation_skips_inject_when_no_thread_id`** — same as above but `thread_id=""`, asserts `_inject_verification_result` was NOT called

10. **`test_run_missed_verification_sweep_processes_stale_records`** — mocks Cosmos query returning 1 stale record, patches `_verify_remediation`, asserts it was called once with the record's fields

All tests use `@pytest.mark.asyncio` decorator and `unittest.mock.patch` / `unittest.mock.AsyncMock` for async function mocking.
</action>
<acceptance_criteria>
- grep -c "def test_" services/api-gateway/tests/test_remediation_executor.py returns at least 29 (19 existing + 10 new)
- grep "test_build_verification_instruction_resolved" services/api-gateway/tests/test_remediation_executor.py returns 1 match
- grep "test_inject_verification_result_respects_max_re_diagnosis" services/api-gateway/tests/test_remediation_executor.py returns 1 match
- grep "test_run_missed_verification_sweep" services/api-gateway/tests/test_remediation_executor.py returns 1 match
- Running `cd /Users/jasonmba/workspace/azure-agentic-platform && python -m pytest services/api-gateway/tests/test_remediation_executor.py -x -q` exits 0
</acceptance_criteria>
</task>

## Verification

```bash
# 1. All new functions exist
grep -n "def _cancel_active_runs\|def _build_verification_instruction\|def _inject_verification_result\|def run_missed_verification_sweep" services/api-gateway/remediation_executor.py

# 2. re_diagnosis_count in models
grep "re_diagnosis_count" services/api-gateway/models.py

# 3. Thread injection is wired into _verify_remediation
grep "_inject_verification_result" services/api-gateway/remediation_executor.py | wc -l  # should be >= 4

# 4. Startup sweep wired into main.py with app.state.credential
grep "run_missed_verification_sweep\|app.state.credential" services/api-gateway/main.py

# 5. API namespace correctness: runs.cancel + agents.create_run + agents.create_message
grep "client.runs.cancel\|client.agents.create_run\|client.agents.create_message" services/api-gateway/remediation_executor.py

# 6. All tests pass
cd /Users/jasonmba/workspace/azure-agentic-platform && python -m pytest services/api-gateway/tests/test_remediation_executor.py -x -q
```

## must_haves

- [ ] `_inject_verification_result` function exists in `remediation_executor.py` and sends a `verification_result` message to the Foundry thread
- [ ] `re_diagnosis_count` field exists on `IncidentSummary` model with default=0
- [ ] `MAX_RE_DIAGNOSIS_COUNT` env var controls the re-diagnosis cap (default 3)
- [ ] `_verify_remediation` calls `_inject_verification_result` when `thread_id` is non-empty
- [ ] Startup sweep `run_missed_verification_sweep` catches stale WAL records with no verification
- [ ] Startup sweep uses `app.state.credential` (NOT a fresh `DefaultAzureCredential()` instantiation)
- [ ] API namespaces are correct: `client.runs.cancel` for cancellation, `client.agents.create_message` and `client.agents.create_run` for thread injection
- [ ] `rollback_id = None` is initialized before the `if classification == "DEGRADED":` block to prevent NameError
- [ ] 10 new unit tests pass covering all new code paths
