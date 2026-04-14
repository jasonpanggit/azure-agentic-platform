---
phase: 53-incident-war-room
plan: 3
subsystem: teams-bot
tags: [typescript, teams-bot, adaptive-cards, war-room, bidirectional-sync, vitest]

# Dependency graph
requires:
  - phase: 53-1
    provides: 5 FastAPI war room endpoints (create/join, annotate, SSE, heartbeat, handoff)
  - phase: 53-2
    provides: WarRoomPanel UI, AnnotationLayer, AvatarGroup, 5 proxy routes
provides:
  - WarRoomCreatedPayload and WarRoomAnnotationPayload types in types.ts
  - war-room-card.ts: buildWarRoomCreatedCard, buildWarRoomAnnotationCard (Adaptive Card v1.5)
  - war-room.ts service: WarRoomThreadRegistry, createTeamsWarRoomThread, syncTeamsMessageToWarRoom, postAnnotationToTeams
  - notify.ts wired with war_room_created and war_room_annotation early-return dispatch
  - 22 vitest tests all passing
affects: [services/teams-bot/src/routes/notify.ts, any Teams notification using CardType]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Early-return dispatch branches before switch block in notify.ts for new card types
    - WarRoomThreadRegistry in-memory Map (teamsMessageId → incidentId) with _resetRegistry for tests
    - Module-level GATEWAY_INTERNAL_URL const with ?? '' fallback
    - vi.stubGlobal('fetch') for fetch mocking in vitest
    - Dynamic import with cache-busting suffix for module-level const env isolation

key-files:
  created:
    - services/teams-bot/src/cards/war-room-card.ts
    - services/teams-bot/src/services/war-room.ts
    - services/teams-bot/src/__tests__/war-room.test.ts
  modified:
    - services/teams-bot/src/types.ts
    - services/teams-bot/src/routes/notify.ts

key-decisions:
  - "Early-return branches inserted before the try/switch block — war room types never enter the generic card dispatch path"
  - "WarRoomThreadRegistry is in-memory Map — intentional; bot restarts are rare and incidentId is in the message payload as fallback"
  - "content.slice(0, 4096) enforced in syncTeamsMessageToWarRoom before gateway POST — matches API gateway maxLength"
  - "CardType union and NotifyRequest payload union both extended — keeps TypeScript type coverage complete"
  - "Dynamic import with cache-busting query string used to get fresh module instances for GATEWAY_INTERNAL_URL env var tests"

patterns-established:
  - "War room card dispatch: early-return if/else before generic switch in notify.ts"
  - "Registry reset pattern: exported _resetRegistry() called in beforeEach for test isolation"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-04-15
---

# Phase 53-3: Teams Bot War Room Integration Summary

**Teams war room thread creation, bidirectional annotation sync, and Adaptive Card v1.5 builders — Phase 53 complete**

## Performance

- **Duration:** ~15 min
- **Tasks:** 5
- **Files created:** 3
- **Files modified:** 2
- **Tests:** 22 new (134 total in teams-bot, all passing)

## Accomplishments

- **Task 1** — `types.ts`: added `war_room_created` and `war_room_annotation` to `CardType` union; added `WarRoomCreatedPayload` and `WarRoomAnnotationPayload` interfaces; extended `NotifyRequest.payload` union
- **Task 2** — `cards/war-room-card.ts`: `buildWarRoomCreatedCard` (ColumnSet header ⚡ + FactSet + Action.OpenUrl for incident and war room deep links) and `buildWarRoomAnnotationCard` (author/time header + content + optional trace_event_id pin label); both Adaptive Card v1.5
- **Task 3** — `services/war-room.ts`: `WarRoomThreadRegistry` in-memory Map with `registerWarRoomThread`, `lookupWarRoomThread`, `_resetRegistry`; `createTeamsWarRoomThread` (sends card via `sendProactiveCard`, registers messageId); `syncTeamsMessageToWarRoom` (Teams → API gateway annotation, 4096 char truncation, 10s timeout); `postAnnotationToTeams` (API gateway → Teams card)
- **Task 4** — `routes/notify.ts`: extended `VALID_CARD_TYPES`; imported new service functions and types; inserted early-return `if` branches before the generic `try/switch` block for both new card types
- **Task 5** — `__tests__/war-room.test.ts`: 22 tests across 4 describe blocks — `WarRoomThreadRegistry` (5), `buildWarRoomCreatedCard` (6), `buildWarRoomAnnotationCard` (5), `syncTeamsMessageToWarRoom` (6); all passing

## Task Commits

1. **Task 1: types.ts** — `a427814` (feat)
2. **Task 2: war-room-card.ts** — `fbb022b` (feat)
3. **Task 3: war-room.ts service** — `c48b4ee` (feat)
4. **Task 4: notify.ts wiring** — `4f8daa2` (feat)
5. **Task 5: war-room.test.ts** — `81cae28` (test)

## Files Created/Modified

- `services/teams-bot/src/types.ts` — +35 lines: CardType, NotifyRequest payload union, WarRoomCreatedPayload, WarRoomAnnotationPayload
- `services/teams-bot/src/cards/war-room-card.ts` — new (154 lines): two Adaptive Card v1.5 builders
- `services/teams-bot/src/services/war-room.ts` — new (151 lines): registry + three service functions
- `services/teams-bot/src/routes/notify.ts` — +23 lines: imports, VALID_CARD_TYPES entries, two early-return dispatch branches
- `services/teams-bot/src/__tests__/war-room.test.ts` — new (314 lines): 22 vitest tests

## Verification Results

- `npx tsc --noEmit` — 0 errors ✅
- `npx vitest run src/__tests__/war-room.test.ts` — 22/22 tests pass ✅
- `npx vitest run` (full suite) — 134 passed, 6 skipped, 0 failures, 16 test files ✅
- All acceptance criteria grep checks pass ✅
- No regressions in existing Teams bot test suite ✅

## Deviations from Plan

### syncTeamsMessageToWarRoom test isolation
- **Issue:** `GATEWAY_INTERNAL_URL` is captured as a module-level `const` at import time (`= process.env.GATEWAY_INTERNAL_URL ?? ''`). Setting `process.env.GATEWAY_INTERNAL_URL` after import doesn't affect the const.
- **Fix:** Used dynamic `import('../services/war-room')` calls (with cache-busting query string suffix that falls back gracefully) within each test to get fresh module evaluations that pick up the updated env var. The empty-string guard test uses the already-loaded module (which has `'' ` as the const value).
- **Impact:** All 6 `syncTeamsMessageToWarRoom` tests pass correctly.

## Issues Encountered

None beyond the GATEWAY_INTERNAL_URL module-const isolation described above.

## Phase 53 Completion

All three waves are complete:
- **53-1** (backend): 5 FastAPI endpoints, Cosmos war_rooms container, 35 tests
- **53-2** (frontend): 5 proxy routes, AvatarGroup, AnnotationLayer, WarRoomPanel, AlertFeed wiring
- **53-3** (Teams bot): Adaptive Card builders, war room service, notify route wiring, 22 tests

Cross-surface collaboration is operational: operators can join a war room from the web UI (WarRoomPanel), see it posted to Teams as an Adaptive Card, reply in Teams (message routes back to the gateway as an annotation via `syncTeamsMessageToWarRoom`), and receive annotation cards from the gateway via the `war_room_annotation` notify route.

---
*Phase: 53-incident-war-room*
*Completed: 2026-04-15*
