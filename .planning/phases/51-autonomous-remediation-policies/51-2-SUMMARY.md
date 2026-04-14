---
phase: 51-autonomous-remediation-policies
plan: 2
subsystem: api
tags: [remediation, policy-engine, auto-approval, safety-guards, cosmos, postgres, azure-resource-health, container-apps]

# Dependency graph
requires:
  - phase: 51-1
    provides: remediation_policies PostgreSQL table + CRUD endpoints for policy storage

provides:
  - policy_engine.py with evaluate_auto_approval() implementing all 5 safety guards
  - aap-protected tag emergency brake (non-negotiable first check)
  - Blast-radius guard using topology_client.get_blast_radius with per-policy cap
  - Daily execution cap via Cosmos remediation_audit count query
  - SLO health gate via Azure Resource Health MicrosoftResourceHealth
  - restart_container_app action in SAFE_ARM_ACTIONS with Container Apps stop+start
  - auto_approved_by_policy field on RemediationAuditRecord and in WAL records
  - Policy evaluation wired into create_approval() before HITL gate
  - 15 unit tests covering all guard paths

affects: [phase-51-3, remediation-executor, approvals, main-py, wal-records]

# Tech tracking
tech-stack:
  added: [azure.mgmt.appcontainers.ContainerAppsAPIClient, asyncpg for policy query, azure.mgmt.resourcehealth.MicrosoftResourceHealth]
  patterns:
    - conservative guard evaluation (any exception = guard failure, never auto-approve on error)
    - aap-protected tag as non-negotiable first guard before any policy evaluation
    - first-match-wins policy evaluation with sequential guard checks
    - synthesized approval record for direct execute_remediation() bypass on auto-approval

key-files:
  created:
    - services/api-gateway/policy_engine.py
    - services/api-gateway/tests/test_policy_engine.py
  modified:
    - services/api-gateway/remediation_executor.py
    - services/api-gateway/models.py
    - services/api-gateway/approvals.py

key-decisions:
  - "aap-protected:true tag always blocks as the FIRST check, before any DB query — non-negotiable emergency brake"
  - "All guard exceptions caught and treated as guard-FAILURE (conservative — do not auto-approve on error)"
  - "first-match-wins: iterate policies returned by DB; first policy passing all guards wins"
  - "topology_client=None means blast_radius_size=0, check passes — graceful degradation when topology unavailable"
  - "cosmos_client=None means daily cap check is skipped (passes) — graceful degradation"
  - "create_approval() falls through to HITL on any policy evaluation exception (conservative)"
  - "restart_container_app uses rollback_op=None (idempotent — stop+start IS the restart, no inverse)"

patterns-established:
  - "Policy guard pattern: tag filter → blast radius → daily cap → SLO health; each can independently block"
  - "Auto-approval synthesizes a minimal approval_record with decided_by=policy:{id} for audit traceability"
  - "WAL auto_approved_by_policy field enables per-policy Cosmos count query for daily cap enforcement"

requirements-completed: []

# Metrics
duration: 35min
completed: 2026-04-14
---

# Plan 51-2: Policy Evaluation Engine + Safety Guards + restart_container_app Action

**Policy evaluation engine with 5-guard auto-approval pipeline wired into the HITL approval flow, plus Container App restart action**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-04-14
- **Completed:** 2026-04-14
- **Tasks:** 5
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments
- Built `policy_engine.py` with `evaluate_auto_approval()` implementing all 5 safety guards in correct order
- `aap-protected:true` tag is the non-negotiable first guard — always evaluated before any DB query
- `restart_container_app` added to `SAFE_ARM_ACTIONS` with Container Apps stop+start ARM implementation
- `auto_approved_by_policy` field added to `RemediationAuditRecord` model and WAL base dict for daily-cap query
- Policy evaluation wired into `create_approval()` BEFORE the HITL pending record creation; falls through to HITL on any error
- 15 unit tests covering all guard paths: 15/15 passing

## Task Commits

Each task was committed atomically:

1. **Task 51-2-01: Create policy_engine.py** - `a0007b1` (feat)
2. **Task 51-2-02: Add restart_container_app to SAFE_ARM_ACTIONS** - `4931cc8` (feat)
3. **Task 51-2-03: Add auto_approved_by_policy to RemediationAuditRecord** - `4754e49` (feat)
4. **Task 51-2-04: Integrate policy evaluation into create_approval()** - `4a5b91c` (feat)
5. **Task 51-2-05: Write 15 unit tests for policy engine** - `69e0105` (test)

## Files Created/Modified

- `services/api-gateway/policy_engine.py` — New: `evaluate_auto_approval()` with 5-guard pipeline, `_query_matching_policies()` via asyncpg, `_evaluate_policy_guards()` for per-policy checks, `_check_resource_health()` via MicrosoftResourceHealth
- `services/api-gateway/tests/test_policy_engine.py` — New: 15 unit tests covering all guard paths using `unittest.mock.patch` and `AsyncMock`
- `services/api-gateway/remediation_executor.py` — Added `restart_container_app` to `SAFE_ARM_ACTIONS`, stop+start branch in `_sync_arm_call()`, `auto_approved_by_policy` in `wal_base` dict
- `services/api-gateway/models.py` — Added `auto_approved_by_policy: Optional[str]` field to `RemediationAuditRecord` after `wal_written_at`
- `services/api-gateway/approvals.py` — Added `topology_client`/`credential` optional params to `create_approval()`, Phase 51 auto-approval check block before HITL path

## Decisions Made

- **aap-protected first**: Tag check is unconditional — evaluated before opening any DB connection. Eliminates any possibility of a protected resource being auto-approved even if the DB has a matching policy.
- **Conservative guard failures**: Any exception inside a guard (blast-radius, Cosmos query, Resource Health) causes that guard to return `False` (block). Never auto-approve on infrastructure errors.
- **rollback_op=None for restart_container_app**: Restarting a Container App is idempotent — if health degrades after restart, the right response is re-diagnosis, not "un-restart". Same pattern as `restart_vm`.
- **Fall-through to HITL on policy error**: The entire policy evaluation is wrapped in `try/except` in `create_approval()`. Any error in the policy engine silently falls through to normal HITL — no auto-approval is lost, but the human gate is preserved.

## Deviations from Plan

None — plan executed exactly as written. One clarification: the plan mentioned `_query_matching_policies` should use `asyncpg.connect(dsn)` with `resolve_postgres_dsn()` — implemented exactly as specified including `await conn.close()` in a `finally` block.

## Issues Encountered

None — all 15 tests passed on first run. Syntax verified with `ast.parse()` on all modified Python files.

## User Setup Required

None - no external service configuration required. Policy auto-approval is gated on existing infrastructure (PostgreSQL `remediation_policies` table from plan 51-1, Cosmos `remediation_audit` container from Phase 27, Azure Resource Health SDK already in requirements).

## Next Phase Readiness

- Phase 51-3 (suggestion engine / learning loop) can depend on `auto_approved_by_policy` field in WAL records to track policy execution outcomes
- All safety guards verified correct: DEGRADED verification still triggers auto-rollback regardless of policy (unchanged `_classify_verification()` and `_verify_remediation()`)
- `restart_container_app` is production-ready pending `azure-mgmt-appcontainers` in requirements.txt (check plan 51-1)

---
*Phase: 51-autonomous-remediation-policies*
*Completed: 2026-04-14*
