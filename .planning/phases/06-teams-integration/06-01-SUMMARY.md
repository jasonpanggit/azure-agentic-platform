---
phase: 06-teams-integration
plan: "06-01"
subsystem: teams-bot
tags: [typescript, express, adaptive-cards, teams, vitest, botbuilder, eslint]

# Dependency graph
requires:
  - phase: 05-triage-remediation-web-ui
    provides: api-gateway approval/chat endpoints that teams-bot calls via REST

provides:
  - services/teams-bot/ TypeScript Container App scaffold (package.json, tsconfig.json, Dockerfile)
  - 4 Adaptive Card v1.5 builder functions (alert, approval, outcome, reminder)
  - POST /teams/internal/notify dispatch endpoint
  - GET /health liveness probe
  - AppConfig with env var validation (BOT_ID, API_GATEWAY_INTERNAL_URL, WEB_UI_PUBLIC_URL required)
  - proactive.ts stub for Bot Framework wiring in Plan 06-02
  - teams-bot-api-gateway-ci.yml with lint + typecheck + 80% coverage gate

affects:
  - 06-02 (bot framework wiring builds on this scaffold)
  - 06-03 (conversation handler uses notify route and card builders)

# Tech tracking
tech-stack:
  added:
    - botbuilder@^4.23.0
    - "@microsoft/teams-ai@^1.5.0"
    - express@^4.21.0
    - "@azure/identity@^4.5.0"
    - adaptivecards@^3.0.0
    - typescript@^5.6.0
    - vitest@^2.1.0
    - "@vitest/coverage-v8@^2.1.0"
    - supertest@^7.0.0
    - eslint@^9.0.0 (flat config)
    - "@typescript-eslint/eslint-plugin@^8.0.0"
  patterns:
    - Adaptive Card v1.5 builder functions returning plain Record<string, unknown>
    - Action.Execute for approval/reminder cards (NOT Action.Http)
    - Action.OpenUrl for alert/outcome deep links to Web UI
    - Express Router factory pattern (createNotifyRouter(config)) for testability
    - ESLint 9 flat config via eslint.config.js (CJS)

key-files:
  created:
    - services/teams-bot/package.json
    - services/teams-bot/tsconfig.json
    - services/teams-bot/Dockerfile
    - services/teams-bot/eslint.config.js
    - services/teams-bot/src/config.ts
    - services/teams-bot/src/types.ts
    - services/teams-bot/src/index.ts
    - services/teams-bot/src/cards/alert-card.ts
    - services/teams-bot/src/cards/approval-card.ts
    - services/teams-bot/src/cards/outcome-card.ts
    - services/teams-bot/src/cards/reminder-card.ts
    - services/teams-bot/src/routes/health.ts
    - services/teams-bot/src/routes/notify.ts
    - services/teams-bot/src/services/proactive.ts
    - services/teams-bot/src/cards/__tests__/alert-card.test.ts
    - services/teams-bot/src/cards/__tests__/approval-card.test.ts
    - services/teams-bot/src/cards/__tests__/outcome-card.test.ts
    - services/teams-bot/src/cards/__tests__/reminder-card.test.ts
    - services/teams-bot/src/routes/__tests__/health.test.ts
    - services/teams-bot/src/routes/__tests__/notify.test.ts
    - services/teams-bot/src/__tests__/config.test.ts
    - .github/workflows/teams-bot-api-gateway-ci.yml
  modified: []

key-decisions:
  - "Action.Execute used for approval/reminder cards (NOT Action.Http) — Action.Http not supported for bot-sent Adaptive Cards in Teams per 06-RESEARCH.md Section 2"
  - "createNotifyRouter(config) factory pattern chosen over module-level router for Express testability without env vars at import time"
  - "ESLint 9 flat config (CJS eslint.config.js) required — ESLint 9 dropped .eslintrc.* support"
  - "proactive.ts stub returns {ok:true, messageId:'stub'} — real Bot Framework wiring deferred to Plan 06-02"
  - "API_GATEWAY_PUBLIC_URL kept in config as empty-string default — deprecated post-Action.Execute migration, retained for forward-compatibility"

patterns-established:
  - "Card builder pattern: pure function (payload, webUiPublicUrl?) -> Record<string, unknown> returning Adaptive Card v1.5 JSON"
  - "Exported color/title helper functions per card module for independent unit testing"
  - "createRouter(config) factory for Express routers that need AppConfig at runtime"

requirements-completed:
  - TEAMS-001
  - TEAMS-002
  - TEAMS-003
  - TEAMS-005
  - TEAMS-006

# Metrics
duration: 45min
completed: 2026-03-27
---

# Plan 06-01: Teams Bot Scaffold + Card Builders + CI

**TypeScript `services/teams-bot/` scaffold with 4 Adaptive Card v1.5 builders (Action.Execute for approval/reminder, Action.OpenUrl for alert/outcome), Express notify endpoint, and teams-bot-api-gateway-ci.yml enforcing 80% coverage**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-03-27T14:15:00Z
- **Completed:** 2026-03-27T14:43:00Z
- **Tasks:** 12 + 1 fix commit
- **Files modified:** 23 created + package-lock.json

## Accomplishments

- `services/teams-bot/` TypeScript Container App scaffolded with all required files (package.json, tsconfig.json, multi-stage Dockerfile, eslint.config.js)
- 4 Adaptive Card v1.5 builder functions: `buildAlertCard`, `buildApprovalCard`, `buildOutcomeCard`, `buildReminderCard` — approval/reminder correctly use `Action.Execute` (NOT `Action.Http`)
- `POST /teams/internal/notify` dispatch endpoint routes to correct card builder by `card_type`; `GET /health` returns `{status:"ok"}`
- 58 unit tests passing with 93.31% line coverage (threshold: 80%)
- `teams-bot-api-gateway-ci.yml` workflow: two parallel jobs (teams-bot TS + api-gateway Python), lint + typecheck + vitest with `--coverage.thresholds.lines=80`

## Task Commits

1. **Task 06-01-01: TypeScript project scaffold** — `e8ea4c3`
2. **Task 06-01-02: config.ts** — `79f0d9c`
3. **Task 06-01-03: types.ts** — `8c90e4d`
4. **Task 06-01-04: alert-card.ts** — `27fce9d`
5. **Task 06-01-05: approval-card.ts** — `bde81e7`
6. **Task 06-01-06: outcome-card.ts** — `a472fb2`
7. **Task 06-01-07: reminder-card.ts** — `2b3f627`
8. **Task 06-01-08: health + notify routes + proactive stub** — `61294c1`
9. **Task 06-01-09: index.ts** — `7ca68b0`
10. **Task 06-01-10: Card builder unit tests** — `c911134`
11. **Task 06-01-11: Route + config unit tests** — `9169340`
12. **Task 06-01-12: teams-bot-api-gateway-ci.yml** — `c09df53`
13. **Fix: ESLint 9 flat config + unused import** — `ac76ca0`
14. **Chore: package-lock.json for CI** — `14072e8`

## Files Created/Modified

- `services/teams-bot/package.json` — Node 20 project with botbuilder, express, @azure/identity, vitest
- `services/teams-bot/tsconfig.json` — strict ES2022, commonjs output
- `services/teams-bot/Dockerfile` — multi-stage build, EXPOSE 3978, HEALTHCHECK
- `services/teams-bot/eslint.config.js` — ESLint 9 flat config (CJS)
- `services/teams-bot/src/config.ts` — AppConfig interface, loadConfig() with required/optional validation
- `services/teams-bot/src/types.ts` — CardType union, all payload interfaces per UI-SPEC
- `services/teams-bot/src/index.ts` — Express app entry point, exports app for testing
- `services/teams-bot/src/cards/alert-card.ts` — buildAlertCard, getSeverityColor
- `services/teams-bot/src/cards/approval-card.ts` — buildApprovalCard with Action.Execute, getRiskColor
- `services/teams-bot/src/cards/outcome-card.ts` — buildOutcomeCard, getOutcomeColor, getOutcomeTitle
- `services/teams-bot/src/cards/reminder-card.ts` — buildReminderCard with Action.Execute + EXPIRING SOON logic, computeRemainingMinutes
- `services/teams-bot/src/routes/health.ts` — GET /health
- `services/teams-bot/src/routes/notify.ts` — POST /teams/internal/notify (createNotifyRouter factory)
- `services/teams-bot/src/services/proactive.ts` — sendProactiveCard stub
- `services/teams-bot/src/cards/__tests__/*.test.ts` — 4 card builder test files (39 tests)
- `services/teams-bot/src/routes/__tests__/*.test.ts` — health + notify route tests (8 tests)
- `services/teams-bot/src/__tests__/config.test.ts` — config validation tests (6 tests)
- `.github/workflows/teams-bot-api-gateway-ci.yml` — Phase 6 CI with TS + Python jobs

## Decisions Made

- **Action.Execute (not Action.Http):** Per 06-RESEARCH.md Section 2, Action.Http is not supported for bot-sent Adaptive Cards in Teams. Both approval and reminder cards use `Action.Execute` with `verb` + `data` payload. Alert and outcome cards use `Action.OpenUrl` for Web UI deep links (this is correct and supported).
- **createNotifyRouter(config) factory:** Using a factory function instead of a module-level router allows tests to inject mock AppConfig without setting process.env. This is the clean Express testability pattern.
- **ESLint 9 flat config:** ESLint 9 dropped `.eslintrc.*` support entirely. Added `eslint.config.js` (CJS format to match package.json `"main": "commonjs"`) with `@typescript-eslint` rules.

## Deviations from Plan

### Auto-fixed Issues

**1. ESLint 9 flat config required**
- **Found during:** Verification (lint step)
- **Issue:** ESLint 9 requires `eslint.config.js` flat config; no `.eslintrc.*` support
- **Fix:** Added `services/teams-bot/eslint.config.js` with CJS format and `@typescript-eslint` rules
- **Files modified:** `services/teams-bot/eslint.config.js`, `services/teams-bot/src/__tests__/config.test.ts` (unused import removed)
- **Verification:** `npm run lint` exits 0
- **Committed in:** `ac76ca0`

---

**Total deviations:** 1 auto-fixed (ESLint config format)
**Impact on plan:** Necessary for lint step to work. No scope creep.

## Issues Encountered

None beyond the ESLint 9 flat config requirement (auto-fixed above).

## User Setup Required

None — no external service configuration required for this plan. Bot registration (Azure AD app + Bot Channel Registration) is a deployment concern addressed in later plans.

## Next Phase Readiness

- **Plan 06-02** can immediately build on this scaffold: wire `sendProactiveCard` in `proactive.ts` to the Bot Framework BotFrameworkAdapter for real proactive card posting to Teams channels
- `/api/messages` Bot Framework endpoint placeholder is in `index.ts` (commented) ready to be uncommented and wired
- All 4 card builders tested and producing correct Adaptive Card JSON — ready for real Teams posting
- `teams-bot-api-gateway-ci.yml` is in place and will gate all subsequent Phase 6 changes

---
*Phase: 06-teams-integration*
*Completed: 2026-03-27*
