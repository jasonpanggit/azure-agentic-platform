---
phase: 30-sop-engine
plan: 01
subsystem: agents, api, infra, teams
tags: [sop, vector-store, foundry, asyncpg, acs-email, teams-cards, terraform, sha256]

# Dependency graph
requires:
  - phase: 29-foundry-sdk-migration
    provides: AIProjectClient pattern, project.get_openai_client(), Responses API
provides:
  - PostgreSQL sops metadata table (003_create_sops_table migration)
  - agents/shared/sop_store.py — Foundry vector store provisioning
  - agents/shared/sop_loader.py — per-incident SOP selection with tag overlap SQL
  - agents/shared/sop_notify.py — @ai_function for Teams + email notifications
  - 3 new Teams card types (sop_notification, sop_escalation, sop_summary)
  - scripts/upload_sops.py — idempotent SOP upload with SHA-256 content hash
  - Terraform notifications module (ACS Email) + SOP_VECTOR_STORE_ID env var
affects: [phase-31-sop-library, phase-32-agent-sop-integration]

# Tech tracking
tech-stack:
  added: [azure-communication-email, pyyaml, hashlib]
  patterns: [sop-grounding-instruction, tag-overlap-sql, sha256-idempotency, ai-function-never-raise]

key-files:
  created:
    - services/api-gateway/migrations/003_create_sops_table.py
    - agents/shared/sop_store.py
    - agents/shared/sop_loader.py
    - agents/shared/sop_notify.py
    - services/teams-bot/src/cards/sop-notification-card.ts
    - services/teams-bot/src/cards/sop-escalation-card.ts
    - services/teams-bot/src/cards/sop-summary-card.ts
    - scripts/upload_sops.py
    - terraform/modules/notifications/main.tf
    - terraform/modules/notifications/variables.tf
    - terraform/modules/notifications/outputs.tf
  modified:
    - services/teams-bot/src/types.ts
    - services/teams-bot/src/routes/notify.ts
    - terraform/modules/agent-apps/main.tf
    - terraform/modules/agent-apps/variables.tf

key-decisions:
  - "Migration numbered 003 — follows existing sequence (001_runbooks, 002_seed, 003_gitops, 004_eol)"
  - "Used asyncpg migration pattern (async up/down) matching existing 002_seed_runbooks.py"
  - "sop_notify uses list[Literal['teams','email']] — NO 'both' shorthand per plan spec"
  - "ACS Email provisioned as separate Terraform module (notifications/) — clean separation"
  - "SOP_VECTOR_STORE_ID injected into domain agents only (not orchestrator or services)"
  - "Used vitest (not jest) for Teams bot tests — matches existing test framework"

patterns-established:
  - "SOP grounding instruction: select SOP from PostgreSQL, inject file_search instruction into agent run"
  - "Tag overlap SQL: ARRAY(SELECT unnest(a) INTERSECT SELECT unnest(b)) for scenario matching"
  - "SHA-256 idempotency: compute hash, compare against DB, skip if unchanged"
  - "Two-layer SOP lookup: specific match first, generic fallback second"

requirements-completed: []

# Metrics
duration: 18min
completed: 2026-04-11
---

# Phase 30: SOP Engine Summary

**SOP engine with Foundry vector store provisioning, PostgreSQL metadata table, per-incident SOP selector with grounding instructions, sop_notify @ai_function for Teams/email, and idempotent upload script**

## Performance

- **Duration:** 18 min
- **Started:** 2026-04-11
- **Completed:** 2026-04-11
- **Tasks:** 8 chunks (14 tasks)
- **Files created:** 15
- **Files modified:** 4

## Accomplishments
- Built complete SOP engine pipeline: PostgreSQL metadata -> SOP selection -> grounding instruction injection -> notification dispatch
- Implemented two-layer SOP lookup (scenario-specific + generic fallback) with PostgreSQL tag overlap SQL
- Added `sop_notify` @ai_function with independent Teams/email channels (failures never raise)
- Extended Teams bot with 3 new Adaptive Card types (sop_notification, sop_escalation, sop_summary)
- Created idempotent upload script with SHA-256 content hash for SOP version management
- Provisioned ACS Email via Terraform and added SOP_VECTOR_STORE_ID to all domain agent Container Apps

## Task Commits

Each chunk was committed atomically:

1. **Chunk 1: PostgreSQL Migration** - `417d04e` (feat: sops table with content_hash, scenario_tags, indexes)
2. **Chunk 2: SOP Store** - `17171a9` (feat: Foundry vector store provisioning via get_openai_client)
3. **Chunk 3: SOP Loader** - `c4b8264` (feat: per-incident SOP selection with tag overlap SQL)
4. **Chunk 4: sop_notify Tool** - `0d165c0` (feat: @ai_function with Teams + email channels)
5. **Chunk 5: Teams Cards** - `1f128c4` (feat: 3 new card types + types.ts + notify.ts routing)
6. **Chunk 6: Upload Script** - `5f5eccd` (feat: SHA-256 idempotency + YAML front matter parsing)
7. **Chunk 7: Terraform** - `f25a6e1` (feat: ACS Email module + SOP env vars)
8. **Chunk 8: Smoke Tests** - `67bcb84` (test: 11 integration smoke tests)

## Files Created/Modified

### Created
- `services/api-gateway/migrations/003_create_sops_table.py` - PostgreSQL migration with sops table, indexes
- `services/api-gateway/tests/test_sops_migration.py` - 7 migration DDL validation tests
- `agents/shared/sop_store.py` - Foundry vector store provisioning (called only by upload script)
- `agents/tests/shared/test_sop_store.py` - 6 unit tests for vector store provisioning
- `agents/shared/sop_loader.py` - Per-incident SOP selection with grounding instruction builder
- `agents/tests/shared/test_sop_loader.py` - 8 unit tests for SOP selection and grounding
- `agents/shared/sop_notify.py` - @ai_function for Teams + email SOP notifications
- `agents/tests/shared/test_sop_notify.py` - 6 unit tests for notification dispatch
- `services/teams-bot/src/cards/sop-notification-card.ts` - SOP notification Adaptive Card builder
- `services/teams-bot/src/cards/sop-escalation-card.ts` - SOP escalation card with Acknowledge action
- `services/teams-bot/src/cards/sop-summary-card.ts` - SOP execution summary card
- `services/teams-bot/src/cards/__tests__/sop-cards.test.ts` - 10 vitest tests for all 3 card types
- `scripts/upload_sops.py` - Idempotent SOP upload with SHA-256 hash + YAML front matter
- `scripts/tests/test_upload_sops.py` - 10 unit tests for hash and front matter parsing
- `terraform/modules/notifications/{main,variables,outputs}.tf` - ACS Email module
- `agents/tests/integration/test_phase30_smoke.py` - 11 integration smoke tests

### Modified
- `services/teams-bot/src/types.ts` - Extended CardType union + 3 new payload interfaces
- `services/teams-bot/src/routes/notify.ts` - Added SOP card type routing cases
- `terraform/modules/agent-apps/variables.tf` - Added sop_vector_store_id, notification_email_from/to
- `terraform/modules/agent-apps/main.tf` - Added SOP env vars to domain agent Container Apps

## Test Results

- **New tests added:** 52 tests across 6 test files
  - 7 migration tests (Python)
  - 6 sop_store tests (Python)
  - 8 sop_loader tests (Python)
  - 6 sop_notify tests (Python)
  - 10 SOP card tests (TypeScript/vitest)
  - 10 upload_sops tests (Python)
  - 11 smoke tests (Python)
- **All new tests pass**
- **Full teams-bot suite: 112 passed, 0 failed**
- **Pre-existing failures (8) — unrelated to Phase 30:** eol_agent (5), patch_agent (1), approval_lifecycle (2)

## Decisions Made
- Migration numbered `003` following existing sequence in `migrations/`
- Used vitest (not jest) for Teams bot card tests — consistent with existing project test framework
- Created separate `terraform/modules/notifications/` module for ACS Email — clean separation of concerns
- SOP env vars injected only into domain agents (excluding orchestrator and services) per plan spec

## Deviations from Plan

None — plan executed as written with minor adaptations:
- Plan referenced `007_sops.sql` migration but existing migrations use Python format; followed convention with `003_create_sops_table.py`
- Plan referenced `services/teams-bot/src/card-builder.ts` for card builders; actual codebase uses individual files per card in `src/cards/` — followed existing pattern

## Issues Encountered
None

## User Setup Required
None — no external service configuration required for development. ACS Email connection string and notification email addresses must be configured in `terraform.tfvars` when deploying to production.

## Next Phase Readiness
- SOP engine infrastructure is complete and ready for Phase 31 (SOP Library creation)
- `scripts/upload_sops.py` is ready to be called once SOP markdown files with YAML front matter are created
- Domain agents can be wired to call `select_sop_for_incident()` in a future phase
- `sop_notify` @ai_function can be added to agent tool lists when SOP integration is enabled

---
*Phase: 30-sop-engine*
*Completed: 2026-04-11*
