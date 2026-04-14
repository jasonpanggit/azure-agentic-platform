---
phase: 53-incident-war-room
plan: 2
subsystem: web-ui
tags: [next.js, react, sse, war-room, presence, annotations, proxy-routes]

# Dependency graph
requires:
  - phase: 53-1
    provides: 5 FastAPI war room endpoints + Cosmos war_rooms container
provides:
  - 5 Next.js proxy routes under app/api/proxy/war-room/
  - AvatarGroup component (presence badges, online threshold 60s)
  - AnnotationLayer component (annotation list + Ctrl+Enter submit)
  - WarRoomPanel component (480px slide-over, 3 tabs, SSE stream, 30s heartbeat)
  - AlertFeed.tsx "War Room" button (Sev0/Sev1 only)
affects: [AlertFeed.tsx, any phase embedding AnnotationLayer in TraceTree]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - SSE ReadableStream passthrough proxy (no AbortSignal.timeout on stream route)
    - 30s setInterval heartbeat with useEffect cleanup
    - AbortController abort() on SSE fetch in useEffect cleanup
    - color-mix(in srgb, var(--accent-*) N%, var(--bg-canvas)) for dark-mode-safe badges
    - Optimistic annotation dedup (SSE push vs local submit — check by id)

key-files:
  created:
    - services/web-ui/app/api/proxy/war-room/join/route.ts
    - services/web-ui/app/api/proxy/war-room/annotations/route.ts
    - services/web-ui/app/api/proxy/war-room/stream/route.ts
    - services/web-ui/app/api/proxy/war-room/heartbeat/route.ts
    - services/web-ui/app/api/proxy/war-room/handoff/route.ts
    - services/web-ui/components/AvatarGroup.tsx
    - services/web-ui/components/AnnotationLayer.tsx
    - services/web-ui/components/WarRoomPanel.tsx
  modified:
    - services/web-ui/components/AlertFeed.tsx

key-decisions:
  - "SSE stream proxy: no AbortSignal.timeout — streams are long-lived by design"
  - "Heartbeat proxy: AbortSignal.timeout(5000) — must be fast"
  - "Handoff proxy: AbortSignal.timeout(45000) — GPT-4o latency allowance"
  - "Optimistic dedup: check annotation.id before appending from SSE to avoid duplicates from local submit + push"
  - "WarRoomPanel renders inside AlertFeed return (not a portal) — consistent with PatchDetailPanel pattern"

requirements-completed: []

# Metrics
duration: 20min
completed: 2026-04-15
---

# Phase 53-2: War Room Frontend Summary

**War room UI: 5 proxy routes, AvatarGroup (presence), AnnotationLayer (investigation notes), WarRoomPanel (480px slide-over, SSE, 30s heartbeat), AlertFeed "War Room" button for Sev0/Sev1**

## Performance

- **Duration:** ~20 min
- **Tasks:** 5
- **Files created:** 8 (5 proxy routes + 3 components)
- **Files modified:** 1 (AlertFeed.tsx)

## Accomplishments

- **Task 1** — 5 proxy routes under `app/api/proxy/war-room/`: join (15s), annotations (15s), stream (SSE passthrough, no timeout), heartbeat (5s), handoff (45s)
- **Task 2** — `AvatarGroup.tsx`: exports `WarRoomParticipant` interface; initials badges with online dot; lead gets gold ring; `color-mix` dark-mode-safe backgrounds; zero hardcoded Tailwind colors
- **Task 3** — `AnnotationLayer.tsx`: exports `Annotation` interface; `maxLength={4096}`; Ctrl+Enter submit; pinned-to-trace-event badge; `var(--accent-*)` tokens throughout
- **Task 4** — `WarRoomPanel.tsx`: `HEARTBEAT_INTERVAL_MS = 30_000`; SSE via `ReadableStream` + `TextDecoder`; `AbortController` abort + `clearInterval` in `useEffect` cleanup; 3 tabs (Notes, Team, Handoff); "End my shift — generate handoff" button; optimistic annotation dedup
- **Task 5** — `AlertFeed.tsx`: added `Shield` + `WarRoomPanel` imports; `warRoomIncidentId`/`warRoomTitle` state; War Room button visible only on Sev0/Sev1; `WarRoomPanel` rendered conditionally at bottom of return

## Task Commits

1. **Task 1: 5 proxy routes** — `a359621`
2. **Task 2: AvatarGroup** — `a81e89f`
3. **Task 3: AnnotationLayer** — `d1f567c`
4. **Task 4: WarRoomPanel** — `cb2ae7a`
5. **Task 5: AlertFeed wiring** — `bc27d13`

## Verification Results

- All 5 proxy routes exist ✅
- All 3 components exist ✅
- `stream/route.ts` returns `Content-Type: text/event-stream` with `ReadableStream` passthrough ✅
- `heartbeat/route.ts` uses `AbortSignal.timeout(5000)` ✅
- `handoff/route.ts` uses `AbortSignal.timeout(45000)` ✅
- `HEARTBEAT_INTERVAL_MS = 30_000` in WarRoomPanel ✅
- `abortRef.current?.abort()` + `clearInterval` in cleanup ✅
- Zero hardcoded Tailwind color classes in AvatarGroup, AnnotationLayer, WarRoomPanel ✅
- `npx tsc --noEmit` — 0 errors in war room files; 4 pre-existing errors in OpsTab.tsx (unrelated, unchanged) ✅

## Deviations from Plan

None — all 5 tasks implemented exactly as specified.

## Issues Encountered

None.

## Next Phase Readiness

- War room UI is fully wired to the backend API
- `AnnotationLayer` accepts `traceEventId` prop — ready for future embedding in `TraceTree.tsx` (Phase 53-3 or later)
- No blockers

---
*Phase: 53-incident-war-room*
*Completed: 2026-04-15*
