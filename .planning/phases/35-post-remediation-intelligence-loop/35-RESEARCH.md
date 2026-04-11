# Phase 35 Research: Post-Remediation Intelligence Loop

**Objective:** Answer "What do I need to know to PLAN this phase well?"
**Date:** 2026-04-11
**Depends on:** Phase 27 (Closed-Loop Remediation), Phase 34 (Activate Phase 32 VM Tools)

---

## Table of Contents

1. [Current Remediation Execution Flow](#1-current-remediation-execution-flow)
2. [Foundry Thread Mechanics — Can an Agent "Receive" a Verification Outcome?](#2-foundry-thread-mechanics)
3. ["Did it work?" UI Prompt — Delayed Post-Remediation Verification UX](#3-did-it-work-ui-prompt)
4. [MTTR Tracking Per Issue Type — Data Inventory and Gaps](#4-mttr-tracking)
5. [Iterative Hypothesis Testing — Orchestrator Re-Diagnosis Loop](#5-iterative-hypothesis-testing)
6. [Current Approval/Remediation Endpoints — State Tracked](#6-current-endpoints)
7. [Requirement Derivation](#7-requirement-derivation)
8. [Design Risks and Mitigations](#8-design-risks)
9. [Recommended Plan Structure](#9-recommended-plan-structure)

---

## 1. Current Remediation Execution Flow

### Flow (Phase 27, `remediation_executor.py`)

```
Incident → Triage → RCA → Proposal → Human Approval
  → POST /api/v1/approvals/{id}/execute
    → _run_preflight() (blast-radius + new-incident scan) [REMEDI-010]
    → _write_wal() status=pending [REMEDI-011]
    → _execute_arm_action() (ComputeManagementClient)
    → _write_wal() status=complete|failed
    → asyncio.create_task(_delayed_verify(...))  <-- FIRE AND FORGET
    → return RemediationResult to caller
```

### Delayed Verification (`_delayed_verify`)

```python
async def _delayed_verify(...):
    delay = VERIFICATION_DELAY_MINUTES * 60  # default 10 min
    await asyncio.sleep(delay)
    await _verify_remediation(...)
```

**`_verify_remediation` logic:**
1. Queries Azure Resource Health for the target resource
2. Calls `_classify_verification(current_status, pre_execution_status)`:
   - `Available` + previous `Unavailable/Degraded` → `RESOLVED`
   - `Available` + previous `Available` → `IMPROVED`
   - `Unavailable/Degraded` → `DEGRADED`
   - `Unknown` → `TIMEOUT`
3. Updates WAL record with `verification_result` and `verified_at`
4. If `DEGRADED` → triggers `_rollback()` automatically [REMEDI-012]

### Key Gap: After Verification Completes, Nothing Happens

**The verification result is written to the Cosmos WAL record and logged, but:**
- The originating Foundry agent thread is NOT notified
- The originating agent does NOT re-diagnose the resource
- No UI notification appears after the 5/10-minute delay
- No MTTR timestamp is captured
- The incident remains in whatever status it was before (`new` or `acknowledged`)

**This is exactly what Phase 35 must close.**

### WAL Record Schema (`RemediationAuditRecord`)

```python
{
    "id": str,                          # execution_id (UUID)
    "incident_id": str,
    "approval_id": str,
    "thread_id": str,                   # <-- KEY: Original Foundry thread_id
    "action_type": "execute" | "rollback",
    "proposed_action": str,             # "restart_vm" | "deallocate_vm" | ...
    "resource_id": str,
    "executed_by": str,                 # UPN from approval record
    "executed_at": str,                 # ISO 8601
    "status": "pending" | "complete" | "failed",
    "verification_result": None | "RESOLVED" | "IMPROVED" | "DEGRADED" | "TIMEOUT",
    "verified_at": None | str,
    "rolled_back": bool,
    "rollback_execution_id": None | str,
    "preflight_blast_radius_size": int,
    "wal_written_at": str,
}
```

**Critical:** `thread_id` is already stored in the WAL record. This means we can resume the original Foundry thread after verification without any schema changes.

---

## 2. Foundry Thread Mechanics

### Can an Agent "Receive" an Outcome and Continue Reasoning?

**Yes.** The platform already does this for approval callbacks. The pattern in `approvals.py` -> `_resume_foundry_thread()`:

```python
async def _resume_foundry_thread(thread_id, approval_id, decided_by):
    client = _get_foundry_client()
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")

    # 1. Inject result as a new message
    approval_message = {
        "message_type": "approval_response",
        "approval_id": approval_id,
        "status": "approved",
        "decided_by": decided_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    client.agents.create_message(
        thread_id=thread_id,
        role="user",
        content=json.dumps(approval_message),
    )

    # 2. Create a new run to resume processing
    client.agents.create_run(
        thread_id=thread_id,
        assistant_id=orchestrator_agent_id,
    )
```

**This is the exact pattern Phase 35 needs.** After verification completes, inject a `verification_result` message into the thread and create a new run. The orchestrator will route to the appropriate domain agent, which will re-diagnose.

### Key Considerations

1. **Thread may be stale:** 10+ minutes have passed since the last agent interaction. Active runs from earlier must be cancelled first (see `create_chat_thread` which already cancels active runs).

2. **The agent has full context:** Foundry threads preserve all prior messages. The domain agent will see:
   - Original incident
   - Previous triage and diagnosis
   - The remediation proposal
   - The approval
   - The new verification result message

3. **Re-diagnosis is natural:** The domain agent's system prompt (TRIAGE-002, TRIAGE-003, TRIAGE-004) already mandates querying Resource Health + Log Analytics + Activity Log. When given a verification result, it will naturally re-check these signals and produce an updated diagnosis.

4. **Message envelope pattern:** Follow `AGENT-002` (typed JSON envelope):
   ```json
   {
       "correlation_id": "<incident_id>",
       "source_agent": "api-gateway",
       "target_agent": "orchestrator",
       "message_type": "verification_result",
       "payload": {
           "execution_id": "...",
           "verification_result": "RESOLVED|IMPROVED|DEGRADED|TIMEOUT",
           "resource_id": "...",
           "proposed_action": "restart_vm",
           "verified_at": "...",
           "rolled_back": false,
           "re_diagnosis_requested": true
       }
   }
   ```

---

## 3. "Did it work?" UI Prompt

### Current UI State After Remediation

The `ProposalCard.tsx` component shows:
- **Pending:** Countdown timer + Approve/Reject buttons
- **Approved/Executed:** Badge showing "Approved" or "Executed"
- **Rejected/Expired/Aborted:** Status badge with context

**Missing:** After execution, the UI gives no feedback about whether the action actually fixed the problem. The operator must manually check the resource.

### Recommended UX Pattern: Delayed Verification Card

**Design:** A new `VerificationCard.tsx` component that appears in the chat panel 5 minutes after execution.

**Behavior:**
1. After `POST /api/v1/approvals/{id}/execute` returns `verification_scheduled: true`, the frontend stores `{execution_id, approval_id, scheduled_verify_at}` in component state.
2. A timer fires at `scheduled_verify_at` (5 minutes post-execution, configurable via env var `POST_REMEDIATION_PROMPT_DELAY_MINUTES`).
3. The component polls `GET /api/v1/approvals/{approval_id}/verification` (already exists — returns 202 with Retry-After while pending, 200 with result when ready).
4. Once verification result arrives, the card renders one of four states:

| Result | Color | Icon | Message | CTA |
|--------|-------|------|---------|-----|
| RESOLVED | green | CheckCircle | "CPU spike resolved after VM restart." | "Mark Resolved" button |
| IMPROVED | blue | TrendingDown | "Resource health improved but not fully resolved." | "Continue Investigating" |
| DEGRADED | red | AlertTriangle | "Resource degraded after action. Auto-rollback triggered." | "View Rollback Details" |
| TIMEOUT | amber | Clock | "Verification timed out. Resource health status unknown." | "Re-check Now" |

**"Did it work?" prompt flow:**
- The card includes a text prompt: "Did this remediation resolve the issue?" with Yes/No buttons.
- **Yes:** Calls `POST /api/v1/incidents/{incident_id}/resolve` with auto-generated summary.
- **No:** Injects a new chat message: "The operator reports the issue persists after {action}. Re-diagnose the problem." This triggers the iterative hypothesis loop (Section 5).

### Polling Strategy

The existing `GET /api/v1/approvals/{approval_id}/verification` endpoint already supports:
- **202 + Retry-After: 60** when verification is still pending
- **200 + RemediationAuditRecord** when verification is complete

The frontend should poll this endpoint every 30 seconds starting 5 minutes after execution, with a maximum of 10 attempts (covers up to 10 minutes of delayed verification).

### Existing API Endpoint Coverage

| Endpoint | Exists? | Purpose |
|----------|---------|---------|
| `POST /api/v1/approvals/{id}/execute` | Yes | Triggers execution + schedules verification |
| `GET /api/v1/approvals/{id}/verification` | Yes | Returns verification result |
| `POST /api/v1/incidents/{id}/resolve` | Yes | Marks incident resolved + stores in memory |
| `POST /api/v1/chat` | Yes | Sends chat message (for re-diagnosis) |

**No new API endpoints needed for the UI prompt.** The frontend assembles the experience from existing endpoints.

---

## 4. MTTR Tracking Per Issue Type

### What Data Already Exists

| Data Point | Location | Field |
|------------|----------|-------|
| Incident creation time | Cosmos `incidents` | `created_at` |
| Incident domain | Cosmos `incidents` | `domain` |
| Incident severity | Cosmos `incidents` | `severity` |
| Incident resource_type | Cosmos `incidents` | `resource_type` (from affected_resources) |
| Detection rule | Cosmos `incidents` | `detection_rule` |
| Remediation execution time | Cosmos `remediation_audit` | `executed_at` |
| Verification result | Cosmos `remediation_audit` | `verification_result` |
| Verification time | Cosmos `remediation_audit` | `verified_at` |
| Resolution time | Cosmos `incidents` | `resolved_at` (Phase 25) |
| Historical patterns | PostgreSQL `incident_memory` | `resolved_at` |

### What's Missing for MTTR

1. **`remediation_completed_at` on incidents container:** When the full remediation loop closes (verification + optional re-diagnosis), the incident needs a timestamp marking "investigation-to-resolution" completed. Currently `resolved_at` is only set by the manual `POST /api/v1/incidents/{id}/resolve` endpoint.

2. **MTTR computation function:** A pure function that calculates:
   ```
   MTTR = resolved_at - created_at  (minutes)
   ```
   Grouped by: `(domain, resource_type, detection_rule, severity)`.

3. **MTTR aggregation storage:** Options:
   - **Option A (recommended):** Compute on-the-fly from Cosmos queries. The `pattern_analyzer.py` already runs weekly; add MTTR P50/P95/mean to `PatternAnalysisResult`.
   - **Option B:** Separate `mttr_stats` container. Overkill for current scale.

4. **MTTR surfacing:** Add to `GET /api/v1/intelligence/platform-health` response (already returns `auto_remediation_success_rate`).

### MTTR Calculation Design

```python
def compute_mttr_by_issue_type(
    incidents: list[dict],
    period_days: int = 30,
) -> dict[str, dict]:
    """Group resolved incidents by (domain, detection_rule) and compute MTTR stats.

    Returns: {
        "compute:HighCPU": {"count": 12, "p50_min": 8.3, "p95_min": 25.1, "mean_min": 11.7},
        "network:NSGBlocked": {"count": 3, "p50_min": 15.0, ...},
    }
    """
```

This function should be added to `pattern_analyzer.py` (which already aggregates incident data weekly) and its output appended to `PatternAnalysisResult.finops_summary` or a new `mttr_summary` field.

---

## 5. Iterative Hypothesis Testing

### What This Means

After remediation → verification → the agent receives the result, the agent should:

1. **If RESOLVED:** Summarize what worked, record the resolution, close the incident.
2. **If IMPROVED:** Re-diagnose to check if the issue is trending toward resolution (check metrics again) or needs a follow-up action.
3. **If DEGRADED:** Auto-rollback has already been triggered (Phase 27). The agent should explain what happened, propose an alternative action, and re-enter the triage workflow.
4. **If TIMEOUT:** Re-check resource health manually. If still unknown, escalate to operator.

### Implementation Pattern

**The key insight: this is not a new orchestration pattern.** It's just a new message injected into an existing thread. The existing domain agent system prompts already mandate the full triage sequence (Activity Log → Log Analytics → Resource Health → hypothesis → proposal). By injecting the verification result as a user message and creating a new run, the agent will naturally:

1. See the verification result in its context window
2. Query current resource health again (TRIAGE-002)
3. Compare pre-remediation vs post-remediation state
4. Produce an updated hypothesis with confidence score (TRIAGE-004)
5. Optionally propose a follow-up action (REMEDI-001)

### Preventing Infinite Loops

Risk: If remediation keeps failing, the agent could enter an infinite loop of: diagnose → propose → approve → execute → verify → DEGRADED → rollback → re-diagnose → propose again.

**Mitigation: Max re-diagnosis count per incident.**
- Track `re_diagnosis_count` on the incident record
- Default max: 3 re-diagnoses per incident
- After max, escalate to operator with full timeline summary
- Session budget (AGENT-007, default $5) already caps token spend

### Thread Message Injection Pattern

```python
async def _inject_verification_result(
    thread_id: str,
    execution_id: str,
    verification_result: str,  # RESOLVED|IMPROVED|DEGRADED|TIMEOUT
    resource_id: str,
    proposed_action: str,
    rolled_back: bool,
    incident_id: str,
) -> None:
    """Inject verification result into the originating Foundry thread and create a new run."""
    client = _get_foundry_client()
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")

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
            "instruction": _build_instruction(verification_result),
        },
    }

    # Cancel any active runs on the thread first
    _cancel_active_runs(client, thread_id)

    client.agents.create_message(
        thread_id=thread_id,
        role="user",
        content=json.dumps(message),
    )

    client.agents.create_run(
        thread_id=thread_id,
        assistant_id=orchestrator_agent_id,
    )


def _build_instruction(verification_result: str) -> str:
    """Build the re-diagnosis instruction based on verification outcome."""
    instructions = {
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
    return instructions.get(verification_result, instructions["TIMEOUT"])
```

---

## 6. Current Approval/Remediation Endpoints

### Endpoint Inventory

| Endpoint | Method | Purpose | Status |
|----------|--------|---------|--------|
| `POST /api/v1/approvals` | POST | Create approval record | Exists |
| `GET /api/v1/approvals` | GET | List pending approvals | Exists |
| `GET /api/v1/approvals/{id}` | GET | Get approval record | Exists |
| `POST /api/v1/approvals/{id}/approve` | POST | Approve proposal | Exists |
| `POST /api/v1/approvals/{id}/reject` | POST | Reject proposal | Exists |
| `POST /api/v1/approvals/{id}/execute` | POST | Execute approved action | Exists |
| `GET /api/v1/approvals/{id}/verification` | GET | Get verification result | Exists |
| `POST /api/v1/incidents/{id}/resolve` | POST | Mark incident resolved | Exists |
| `GET /api/v1/intelligence/platform-health` | GET | Platform health metrics | Exists |
| `GET /api/v1/intelligence/patterns` | GET | Pattern analysis results | Exists |

### State Transitions Already Tracked

```
Approval:  pending → approved → executed → (no further transition)
Incident:  new → acknowledged → resolved  (no auto-resolve after remediation)
WAL:       pending → complete|failed → (verification_result written)
```

### State Transitions Phase 35 Adds

```
Approval:  executed → verified   (new status after verification completes)
Incident:  ... → auto_resolved   (when verification=RESOLVED and operator confirms)
WAL:       (no change — already tracks verification_result)
```

---

## 7. Requirement Derivation

Phase 35 is not explicitly mapped to REQUIREMENTS.md IDs. Derived requirements from the phase description:

| Derived ID | Requirement | Source |
|------------|-------------|--------|
| LOOP-001 | After verification completes (RESOLVED/IMPROVED/DEGRADED/TIMEOUT), inject the outcome into the originating Foundry thread and create a new orchestrator run for re-diagnosis | Phase 35 description |
| LOOP-002 | "Did it work?" UI card appears in chat panel POST_REMEDIATION_PROMPT_DELAY_MINUTES (default 5) after execution, polls verification endpoint, shows result with operator Yes/No confirmation | Phase 35 description |
| LOOP-003 | MTTR tracked per (domain, detection_rule, severity) tuple; P50/P95/mean computed in weekly pattern analysis; surfaced in platform-health endpoint | Phase 35 description |
| LOOP-004 | Iterative hypothesis testing: domain agent re-diagnoses after receiving verification result; max re_diagnosis_count=3 per incident to prevent infinite loops | Phase 35 description |
| LOOP-005 | Operator "No" response on verification card triggers re-diagnosis message injection into the same Foundry thread | Phase 35 description |

### Upstream Requirements Satisfied

- **REMEDI-009** (partially — verification fires but result is now fed back to agent)
- **V2-004** (partially — MTTR reporting per issue type)
- **PLATINT-003** (extended — verification outcome is feedback to the learning loop)

---

## 8. Design Risks and Mitigations

### Risk 1: Thread Stale After 10+ Minutes
**Problem:** Foundry threads may have active runs from approval processing.
**Mitigation:** Cancel all active runs before injecting the verification message. Pattern already exists in `create_chat_thread()`.

### Risk 2: Infinite Re-Diagnosis Loop
**Problem:** DEGRADED → rollback → re-diagnose → same bad proposal → approve → DEGRADED → ...
**Mitigation:** `re_diagnosis_count` field on incident, capped at 3. After max, inject escalation message instead of re-diagnosis request.

### Risk 3: Race Condition on Fire-and-Forget Verification
**Problem:** `_delayed_verify` runs as `asyncio.create_task`. If the api-gateway process restarts before the delay completes, verification never fires.
**Mitigation:** The WAL stale monitor (`run_wal_stale_monitor`) already catches records stuck in `pending` for >10 min and emits REMEDI_WAL_ALERT incidents. Phase 35 should add a complementary check: records with `status=complete` but `verification_result=None` and `executed_at > 20 minutes ago` should be re-verified on startup. This is a lightweight startup sweep.

### Risk 4: Verification Result Arrives Before UI Polls
**Problem:** The `VERIFICATION_DELAY_MINUTES` (10 min) is longer than the UI prompt delay (5 min). The UI will show "pending_verification" until the actual verification fires.
**Mitigation:** Acceptable behavior — the 202 response with Retry-After: 60 is already handled. The UI shows a "Checking..." spinner with the message "We're verifying the remediation result..." until the 200 arrives. Alternatively, reduce `POST_REMEDIATION_PROMPT_DELAY_MINUTES` to match `VERIFICATION_DELAY_MINUTES` so they align.

### Risk 5: Multiple Remediations on Same Incident
**Problem:** If multiple remediation actions are approved for the same incident (e.g., restart VM then resize VM), multiple verification cards could appear.
**Mitigation:** Each execution has a unique `execution_id`. The verification card is tied to a specific `execution_id`, not the `incident_id`. Multiple cards can coexist.

---

## 9. Recommended Plan Structure

### Plan 35-1: Verification Feedback to Foundry Thread (Backend)

**Scope:**
- Create `_inject_verification_result()` in `remediation_executor.py`
- Call it from `_verify_remediation()` after classification
- Implement `_cancel_active_runs()` utility
- Add `re_diagnosis_count` field to Cosmos incident documents
- Add max re-diagnosis guard (cap at 3)
- Add startup sweep for missed verifications
- Unit tests for all new functions

**Files:**
- `services/api-gateway/remediation_executor.py` (modify)
- `services/api-gateway/models.py` (add `re_diagnosis_count` to `IncidentSummary`)
- `services/api-gateway/tests/test_remediation_executor.py` (extend)

### Plan 35-2: MTTR Tracking and Intelligence

**Scope:**
- Add `compute_mttr_by_issue_type()` to `pattern_analyzer.py`
- Add `mttr_summary` field to `PatternAnalysisResult` model
- Extend `GET /api/v1/intelligence/platform-health` with MTTR P50/P95
- Add `resolved_at` auto-set when verification_result=RESOLVED (if operator hasn't already resolved)
- Unit tests

**Files:**
- `services/api-gateway/pattern_analyzer.py` (modify)
- `services/api-gateway/models.py` (modify `PatternAnalysisResult`, `PlatformHealth`)
- `services/api-gateway/main.py` (modify platform-health endpoint)
- `services/api-gateway/tests/test_pattern_analyzer.py` (extend)

### Plan 35-3: "Did it work?" UI Verification Card

**Scope:**
- Create `VerificationCard.tsx` component
- Polling logic: start polling `GET /api/v1/approvals/{id}/verification` after delay
- Four result states (RESOLVED/IMPROVED/DEGRADED/TIMEOUT) with appropriate UI
- "Yes" button → `POST /api/v1/incidents/{id}/resolve`
- "No" button → `POST /api/v1/chat` with re-diagnosis message
- Wire into chat panel message flow (appears after execution response)
- New proxy route: `app/api/proxy/approvals/[approvalId]/verification/route.ts`
- TypeScript tests

**Files:**
- `services/web-ui/components/VerificationCard.tsx` (create)
- `services/web-ui/components/ChatPanel.tsx` (modify — render VerificationCard)
- `services/web-ui/app/api/proxy/approvals/[approvalId]/verification/route.ts` (create)
- Tests

### Dependency Order

```
Plan 35-1 (Backend: thread injection + re-diagnosis guard)
  ↓
Plan 35-2 (MTTR tracking — depends on resolved_at auto-set from 35-1)
  ↓ (parallel with 35-2)
Plan 35-3 (UI: verification card — depends on backend from 35-1)
```

Plans 35-2 and 35-3 can run in parallel after 35-1 completes.

---

## Appendix: Key Code References

| Component | File Path | Key Functions/Classes |
|-----------|-----------|----------------------|
| Remediation executor | `services/api-gateway/remediation_executor.py` | `execute_remediation()`, `_delayed_verify()`, `_verify_remediation()`, `_classify_verification()`, `_rollback()` |
| Approval endpoints | `services/api-gateway/approvals.py` | `process_approval_decision()`, `_resume_foundry_thread()` |
| Foundry client | `services/api-gateway/foundry.py` | `_get_foundry_client()`, `dispatch_to_orchestrator()` |
| Chat thread creation | `services/api-gateway/chat.py` | `create_chat_thread()` (cancel active runs pattern) |
| Execute endpoint | `services/api-gateway/main.py:1387` | `execute_approval()` |
| Verification endpoint | `services/api-gateway/main.py:1476` | `get_verification_result()` |
| Resolve endpoint | `services/api-gateway/main.py:1050` | `resolve_incident()` |
| Pattern analyzer | `services/api-gateway/pattern_analyzer.py` | `analyze_patterns()`, `run_pattern_analysis_loop()` |
| Platform health | `services/api-gateway/main.py:1752` | Platform health endpoint |
| ProposalCard UI | `services/web-ui/components/ProposalCard.tsx` | `ProposalCard` component |
| Pydantic models | `services/api-gateway/models.py` | `RemediationAuditRecord`, `RemediationResult`, `PatternAnalysisResult`, `PlatformHealth`, `IncidentSummary` |
| Cosmos containers | `terraform/modules/databases/cosmos.tf` | `remediation_audit` (partition `/incident_id`), `incidents`, `approvals` |
| Teams outcome card | `services/teams-bot/src/cards/outcome-card.ts` | `buildOutcomeCard()` |
| Teams notify route | `services/teams-bot/src/routes/notify.ts` | `outcome` card_type handler |

---

## Summary: Planning Readiness Checklist

- [x] `remediation_executor.py` WAL pattern fully understood (fire-and-forget `_delayed_verify`)
- [x] Foundry thread resume mechanism confirmed (same pattern as `_resume_foundry_thread`)
- [x] WAL record already stores `thread_id` — no schema change needed for thread injection
- [x] Verification endpoint already exists (`GET /api/v1/approvals/{id}/verification`)
- [x] Incident resolve endpoint exists (`POST /api/v1/incidents/{id}/resolve`)
- [x] Cosmos `remediation_audit` container partitioned by `/incident_id` — MTTR queries feasible
- [x] `PatternAnalysisResult` model already has `finops_summary` dict — can add `mttr_summary`
- [x] `PlatformHealth` model already has `auto_remediation_success_rate` — can add MTTR fields
- [x] ProposalCard UI pattern understood — VerificationCard follows same component pattern
- [x] Teams `outcome` card type already exists — can be extended for verification results
- [x] Infinite loop risk identified — `re_diagnosis_count` cap is the mitigation
- [x] Race condition risk identified — startup sweep for missed verifications needed
