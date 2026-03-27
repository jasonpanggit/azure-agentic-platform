---
phase: 06-teams-integration
plan: "02"
subsystem: teams-bot
tags: [botbuilder, teams, adaptive-cards, bot-framework, express, managed-identity, azure-identity]

# Dependency graph
requires:
  - phase: 06-01
    provides: Teams bot scaffold (project, card builders, notify endpoint, CI)
  - phase: 02-03
    provides: API Gateway with POST /api/v1/chat, approval endpoints, Entra auth
provides:
  - AapTeamsBot TeamsActivityHandler with message handling and Action.Execute invoke
  - GatewayClient HTTP client for api-gateway with managed identity auth
  - Conversation state tracker for thread_id mapping per Teams conversation
  - Proactive messaging via ConversationReference + continueConversationAsync
  - Bot Framework CloudAdapter wired into /api/messages endpoint
affects: [06-04-escalation-scheduler, 06-05-integration, 07-quality-hardening]

# Tech tracking
tech-stack:
  added: ["@azure/identity (DefaultAzureCredential)", "botbuilder (CloudAdapter, ConfigurationBotFrameworkAuthentication)"]
  patterns: [constructor-based-event-registration, gateway-client-with-bearer-auth, in-memory-conversation-state-with-ttl]

key-files:
  created:
    - services/teams-bot/src/bot.ts
    - services/teams-bot/src/services/auth.ts
    - services/teams-bot/src/services/gateway-client.ts
    - services/teams-bot/src/services/conversation-state.ts
    - services/teams-bot/src/services/__tests__/auth.test.ts
    - services/teams-bot/src/services/__tests__/gateway-client.test.ts
    - services/teams-bot/src/services/__tests__/conversation-state.test.ts
    - services/teams-bot/src/__tests__/bot.test.ts
  modified:
    - services/teams-bot/src/index.ts
    - services/teams-bot/src/services/proactive.ts

key-decisions:
  - "Constructor-based event registration for Bot Framework type safety"
  - "handleMessage/handleInstallationUpdate as public methods for testability; onAdaptiveCardInvoke as protected override"
  - "In-memory conversation state with 24h TTL — acceptable for Phase 6 MVP"
  - "Dev-mode auth fallback (no AZURE_CLIENT_ID = dev-token) matching api-gateway pattern"
  - "Promise.race for 120s timeout; setTimeout for 30s interim message"

patterns-established:
  - "Gateway client pattern: class with authHeaders() + method per endpoint"
  - "Dev-mode auth: isDevelopmentMode() check before token acquisition"
  - "Conversation state: Map<teamsConversationId, {threadId, incidentId, lastUsed}>"
  - "Proactive messaging: initializeProactive(adapter, appId) → setConversationReference → sendProactiveCard"

requirements-completed: [TEAMS-001, TEAMS-004]

# Metrics
duration: 18min
completed: 2026-03-27
---

# Plan 06-02: Bot Framework Integration + Conversational Flow Summary

**TeamsBot activity handler wired to api-gateway with managed identity auth, Action.Execute approve/reject, 30s/120s timeout handling, and proactive messaging via ConversationReference**

## Performance

- **Duration:** 18 min
- **Tasks:** 6
- **Files created:** 8
- **Files modified:** 2
- **Tests added:** 26 new (84 total, 80.12% coverage)

## Accomplishments

- Full TeamsBot activity handler with message routing, typing indicator, and timeout handling (D-05, D-06)
- Gateway HTTP client calling all api-gateway endpoints with managed identity Bearer token
- Action.Execute invoke handler for approve/reject remediation proposals with in-place card update (TEAMS-003)
- In-memory conversation state tracking Foundry thread_id per Teams conversation (D-13, TEAMS-004)
- Proactive messaging implementation with ConversationReference capture and continueConversationAsync
- Bot Framework CloudAdapter wired into Express with /api/messages endpoint

## Task Commits

Each task was committed atomically (TDD: tests first → implementation):

1. **Task 06-02-01: Auth service** — `d5d6882` (feat: managed identity token acquisition, 4 tests)
2. **Task 06-02-02: Gateway HTTP client** — `b36d19a` (feat: GatewayClient with chat/approve/reject/list, 7 tests)
3. **Task 06-02-03: Conversation state tracker** — `ad68987` (feat: thread_id mapping with 24h TTL, 5 tests)
4. **Task 06-02-04: TeamsBot activity handler** — `e8b77d0` (feat: message + invoke + installation handling, 10 tests)
5. **Task 06-02-05: Proactive messaging** — `65e7779` (feat: ConversationReference + continueConversationAsync)
6. **Task 06-02-06: Bot Framework adapter wiring** — `7bf5bea` (feat: CloudAdapter + /api/messages)

## Files Created/Modified

### Created
- `services/teams-bot/src/bot.ts` — AapTeamsBot extends TeamsActivityHandler; message handler, Action.Execute invoke, installation update
- `services/teams-bot/src/services/auth.ts` — DefaultAzureCredential token acquisition with dev-mode fallback
- `services/teams-bot/src/services/gateway-client.ts` — GatewayClient class for api-gateway HTTP calls
- `services/teams-bot/src/services/conversation-state.ts` — In-memory thread_id mapping with 24h TTL
- `services/teams-bot/src/services/__tests__/auth.test.ts` — 4 tests for auth service
- `services/teams-bot/src/services/__tests__/gateway-client.test.ts` — 7 tests for gateway client
- `services/teams-bot/src/services/__tests__/conversation-state.test.ts` — 5 tests for conversation state
- `services/teams-bot/src/__tests__/bot.test.ts` — 10 tests for TeamsBot handler

### Modified
- `services/teams-bot/src/index.ts` — Added CloudAdapter, ConfigurationBotFrameworkAuthentication, /api/messages endpoint
- `services/teams-bot/src/services/proactive.ts` — Replaced stub with real continueConversationAsync implementation

## Decisions Made

| Decision | Rationale |
|---|---|
| Constructor-based event registration | Bot Framework SDK uses `this.onMessage(handler)` pattern for TypeScript type safety; direct method override (`async onMessage()`) conflicts with the event registration signature |
| handleMessage as public method | Allows direct testing without going through the Bot Framework event pipeline; tests call `bot.handleMessage(ctx)` directly |
| In-memory conversation state | 24h TTL Map is sufficient for MVP; thread_id can be re-derived from incident records; upgrade to Cosmos DB if durability needed in Phase 7 |
| Dev-mode auth fallback | When AZURE_CLIENT_ID is not set, returns "dev-token" — matches api-gateway auth.py pattern for consistent local development |

## Deviations from Plan

### Auto-fixed Issues

**1. Bot Framework method override pattern**
- **Found during:** Task 06-02-06 (TypeScript typecheck)
- **Issue:** Plan specified `async onMessage(context)` override, but `onMessage` on ActivityHandler is an event registration method, not a handler. TypeScript type error: `BotHandler is not assignable to TurnContext`
- **Fix:** Used constructor-based event registration: `this.onMessage(async (context, next) => { await this.handleMessage(context); await next(); })`. Renamed handlers to `handleMessage` and `handleInstallationUpdate`
- **Files modified:** `services/teams-bot/src/bot.ts`, `services/teams-bot/src/__tests__/bot.test.ts`
- **Verification:** `tsc --noEmit` passes cleanly; all 10 bot tests pass
- **Committed in:** `7bf5bea` (Task 06-02-06)

---

**Total deviations:** 1 auto-fixed (method signature mismatch)
**Impact on plan:** Necessary for TypeScript type safety. No scope creep. Same behavior, correct API usage.

## Issues Encountered

- Bot Framework SDK TypeScript types for `onMessage`/`onInstallationUpdate` don't match the common "override handler" pattern shown in many examples — the `on*` methods are event registrators, not overridable handlers. Fixed by using constructor registration with `this.onMessage((context, next) => ...)`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Bot Framework adapter fully wired and operational
- All api-gateway endpoints callable via GatewayClient with managed identity auth
- Proactive messaging ready for escalation scheduler (Plan 06-04)
- Conversation state tracks thread_id for cross-surface continuity (TEAMS-004)
- Ready for Plan 06-04 (Escalation Scheduler) and Plan 06-05 (Integration)

---
*Plan: 06-02 | Phase: 06-teams-integration*
*Completed: 2026-03-27*
