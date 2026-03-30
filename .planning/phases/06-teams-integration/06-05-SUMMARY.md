---
phase: 06-teams-integration
plan: 05
subsystem: teams-bot
tags: [teams, adaptive-cards, manifest, vitest, ci, integration-tests]

# Dependency graph
requires:
  - phase: 06-02
    provides: Bot Framework integration, AapTeamsBot, GatewayClient
  - phase: 06-03
    provides: API Gateway thread continuation, GET /api/v1/approvals, notify refactor
provides:
  - Teams app manifest (v1.17) with bot registration and /investigate command
  - Environment variable documentation (.env.example)
  - 6 integration test stubs covering all Phase 6 success criteria
  - vitest.config.ts with v8 coverage and integration test exclusion
  - CI workflow updated to exclude integration tests
  - 06-UI-SPEC.md cleaned of all Action.Http references
  - Full verification pass (typecheck, lint, 100 tests at 92.34%, Docker build)
affects: [07-quality-hardening]

# Tech tracking
tech-stack:
  added: []
  patterns: [vitest-config-exclusion, teams-manifest-v1.17, integration-test-stubs]

key-files:
  created:
    - services/teams-bot/appPackage/manifest.json
    - services/teams-bot/appPackage/outline.png
    - services/teams-bot/appPackage/color.png
    - services/teams-bot/.env.example
    - services/teams-bot/src/__tests__/integration/teams-e2e-stubs.test.ts
    - services/teams-bot/vitest.config.ts
  modified:
    - .github/workflows/teams-bot-api-gateway-ci.yml
    - .planning/phases/06-teams-integration/06-UI-SPEC.md

key-decisions:
  - "Placeholder PNG icons (32x32 outline, 192x192 color) — real icons deferred to pre-production design"
  - "describe.skip for integration stubs — Phase 7 implements real integration tests"
  - "vitest.config.ts + CI --exclude double-guard for integration test exclusion"

patterns-established:
  - "Integration test stubs: describe.skip with documented test plans and requirement traceability"
  - "vitest.config.ts exclusion pattern for test directories"

requirements-completed: [TEAMS-001, TEAMS-002, TEAMS-003, TEAMS-004, TEAMS-005, TEAMS-006]

# Metrics
duration: 15min
completed: 2026-03-27
---

# Plan 06-05: Teams App Manifest + Integration Tests + Deployment Config Summary

**Teams app manifest, env var docs, 6 integration test stubs, vitest config, CI integration exclusion, and full Phase 6 verification (100 tests at 92.34% coverage)**

## Performance

- **Duration:** 15 min
- **Tasks:** 6
- **Files created:** 6
- **Files modified:** 2

## Accomplishments
- Teams app manifest (v1.17 schema) ready for org deployment with bot registration, /investigate command, team + personal scopes
- Complete .env.example documenting all 11 environment variables with descriptions and deprecation notes
- 6 integration test stubs (describe.skip) mapping 1:1 to Phase 6 success criteria SC-1 through SC-6
- vitest.config.ts with v8 coverage provider and integration/** exclusion
- Full verification pass: 0 type errors, 0 lint errors, 100 tests passing at 92.34% line coverage, Docker build succeeds, api-gateway 71 tests pass

## Task Commits

Each task was committed atomically:

1. **Task 06-05-01: Create Teams app manifest and icons** - `366d031` (feat)
2. **Task 06-05-02: Create .env.example** - `0b2a95c` (docs)
3. **Task 06-05-03: Create integration test stubs** - `4cf495b` (test)
4. **Task 06-05-04: Update CI + create vitest.config.ts** - `ffa8295` (ci)
5. **Task 06-05-05: Update 06-UI-SPEC.md** - `441fb47` (docs)
6. **Task 06-05-06: Final verification** - all checks pass (no separate commit needed; fixes were already applied by 06-04 work)

## Files Created/Modified
- `services/teams-bot/appPackage/manifest.json` - Teams v1.17 app manifest with bot registration
- `services/teams-bot/appPackage/outline.png` - 32x32 placeholder outline icon
- `services/teams-bot/appPackage/color.png` - 192x192 placeholder color icon (Azure blue)
- `services/teams-bot/.env.example` - All environment variables documented with descriptions
- `services/teams-bot/src/__tests__/integration/teams-e2e-stubs.test.ts` - 6 integration test stubs
- `services/teams-bot/vitest.config.ts` - Vitest config with v8 coverage and exclusions
- `.github/workflows/teams-bot-api-gateway-ci.yml` - Added --exclude for integration tests
- `.planning/phases/06-teams-integration/06-UI-SPEC.md` - Removed residual Action.Http references

## Decisions Made
- **Placeholder icons**: Minimal single-color PNGs (white outline, Azure blue color) — real icons will be designed before production deployment
- **describe.skip for integration stubs**: Stubs define the full test plan but require live Teams environment; Phase 7 Quality & Hardening will implement the real tests
- **Double-guard exclusion**: Both vitest.config.ts `exclude` and CI `--exclude` flag ensure integration stubs never run in unit test CI

## Deviations from Plan

None - plan executed exactly as written. The 06-UI-SPEC.md already had Action.Execute in card schemas (updated in prior plans); only 2 residual text references to Action.Http needed cleanup.

## Issues Encountered
- The 06-04 plan commits interleaved with 06-05 commits because both were in progress — no conflicts, files remained clean
- No actual code fixes needed in task 06-05-06; the fixes that the plan anticipated (type errors, lint errors) had already been resolved by 06-04 work

## User Setup Required

None - no external service configuration required. The .env.example documents what operators need to configure at deployment time.

## Next Phase Readiness
- Phase 6 is now complete: all 5 plans delivered, 100 tests passing at 92.34% coverage
- All 6 TEAMS-* requirements have corresponding implementation code
- Phase 7 (Quality & Hardening) can proceed with real integration tests using the stubs as templates
- Teams app manifest ready for Azure Bot Service registration and org deployment

---
*Phase: 06-teams-integration*
*Plan: 06-05*
*Completed: 2026-03-27*
