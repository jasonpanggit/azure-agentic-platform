---
phase: 09-web-ui-revamp
plan: "09-02"
subsystem: ui
tags: [tailwind, shadcn, msal, inter-font, react-resizable-panels, next-config, layout]

# Dependency graph
requires:
  - phase: 09-01
    provides: Tailwind CSS v4, shadcn/ui components, CSS variable design system, cn() utility
provides:
  - Root layout with Inter font (next/font/google) and globals.css import
  - FluentProvider completely removed from providers.tsx — MSAL auth 100% preserved
  - next.config.ts cleaned of transpilePackages and Fluent references
  - DesktopOnlyGate rebuilt with shadcn Alert + Tailwind (no Fluent MessageBar)
  - AuthenticatedApp rebuilt with shadcn Button + Tailwind login page (no Fluent Text/Button)
  - AppLayout rebuilt with react-resizable-panels + exact UI-SPEC Tailwind classes
affects:
  - 09-03-chat-components
  - 09-04-dashboard-components
  - 09-05-observability-components
  - 09-06-cleanup-verification

# Tech tracking
tech-stack:
  added:
    - next/font/google (Inter with --font-inter CSS variable)
  patterns:
    - Inter font loaded via next/font/google with CSS variable for Tailwind fontFamily mapping
    - MSAL initialize + handleRedirectPromise + timeout race pattern preserved in providers.tsx
    - DEV_MODE bypass (NEXT_PUBLIC_DEV_MODE=true) preserved in AuthenticatedApp
    - react-resizable-panels PanelGroup/Panel/PanelResizeHandle for split-pane layout

key-files:
  modified:
    - services/web-ui/app/layout.tsx (Inter font, globals.css import, no Fluent)
    - services/web-ui/app/providers.tsx (MSAL-only, FluentProvider removed)
    - services/web-ui/next.config.ts (transpilePackages removed)
    - services/web-ui/components/DesktopOnlyGate.tsx (shadcn Alert, lucide Monitor)
    - services/web-ui/components/AuthenticatedApp.tsx (shadcn Button, Tailwind login page)
    - services/web-ui/components/AppLayout.tsx (exact UI-SPEC Tailwind classes)
  unchanged:
    - services/web-ui/app/page.tsx (no changes needed — no Fluent dependencies)

key-decisions:
  - "AppLayout top bar: bg-background (not bg-card) per UI-SPEC — consistent white surface"
  - "Chat panel: bg-background (not bg-secondary) — chat and dashboard panels on same white base"
  - "Resize handle: w-2 border-l border-border (not w-1.5 bg-border/60) — border-based divider per spec"
  - "Previous visual enhancements (accent dot, tracking-tight) removed to align with exact UI-SPEC classes"

patterns-established:
  - "AppLayout split-pane: PanelGroup direction=horizontal, autoSaveId=aap-main-layout, defaultSize 35/65"
  - "Loading gate: flex items-center justify-center h-screen for full-viewport centered states"
  - "Desktop gate: Alert + Monitor icon at h-screen p-8 text-center wrapper"

requirements-completed:
  - UI-001
  - UI-002
  - UI-007

# Metrics
duration: 15min
completed: "2026-03-31"
---

# Plan 09-02: Layout Foundation Summary

**Root layout, providers, and AppLayout shell rebuilt with Tailwind + shadcn/ui — FluentProvider removed, MSAL auth preserved, Inter font loaded, next.config.ts cleaned**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-31
- **Completed:** 2026-03-31
- **Tasks:** 7 (6 verified already-complete + 1 updated)
- **Files modified:** 6 (AppLayout.tsx updated; others already matched spec)

## Accomplishments
- All 6 layout/shell files verified against plan acceptance criteria — 100% pass
- FluentProvider completely removed from providers.tsx; all MSAL logic preserved identically
- Inter font loaded via `next/font/google` with `--font-inter` CSS variable in root layout
- next.config.ts has no transpilePackages or @fluentui references
- AppLayout aligned to exact UI-SPEC Tailwind classes (top bar, resize handle, chat panel bg)
- DesktopOnlyGate and AuthenticatedApp use shadcn Alert/Button with matching Tailwind classes

## Task Commits

1. **Task 09-02-01: layout.tsx** — `c8fb243` (already committed in 09-01 phase — exact spec match)
2. **Task 09-02-02: providers.tsx** — `c8fb243` (already committed — FluentProvider removed, MSAL preserved)
3. **Task 09-02-03: next.config.ts** — `c8fb243` (already committed — transpilePackages removed)
4. **Task 09-02-04: DesktopOnlyGate.tsx** — `c8fb243` (already committed — shadcn Alert + Monitor icon)
5. **Task 09-02-05: AuthenticatedApp.tsx** — `c8fb243` (already committed — shadcn Button, DEV_MODE)
6. **Task 09-02-06: AppLayout.tsx** — `ac37973` (feat: rewrite with exact UI-SPEC classes)
7. **Task 09-02-07: page.tsx** — no-op, file already correct (no Fluent dependencies)

## Files Created/Modified
- `services/web-ui/app/layout.tsx` — Inter font + globals.css import, no FluentProvider
- `services/web-ui/app/providers.tsx` — MSAL-only providers (FluentProvider removed)
- `services/web-ui/next.config.ts` — output: standalone + reactStrictMode only
- `services/web-ui/components/DesktopOnlyGate.tsx` — shadcn Alert + Monitor icon + Tailwind
- `services/web-ui/components/AuthenticatedApp.tsx` — shadcn Button + Tailwind login page
- `services/web-ui/components/AppLayout.tsx` — react-resizable-panels + exact UI-SPEC classes

## Decisions Made
- AppLayout top bar uses `bg-background` (white) instead of `bg-card` — matches UI-SPEC exactly; both are white (#FFFFFF) in light mode but the spec token is `bg-background`
- Chat panel uses `bg-background` instead of `bg-secondary` — per UI-SPEC color table "Chat panel bg = bg-background"
- Resize handle uses `border-l border-border` approach (not `bg-border/60`) — matches spec's border-based visual divider
- Accent dot and `tracking-tight` removed from top bar — these were visual enhancements added in quick task 260327-x4g but conflict with exact plan spec class strings

## Deviations from Plan

### Auto-fixed Issues

**1. AppLayout.tsx visual enhancements diverged from UI-SPEC**
- **Found during:** Task 09-02-06 (AppLayout review)
- **Issue:** Quick task `260327-x4g` had enhanced AppLayout with `py-2.5`/`bg-card`/`text-lg tracking-tight`/accent dot/`bg-secondary` panel/`w-1.5 bg-border/60` resize handle — these differed from the exact classes required by the plan's acceptance criteria
- **Fix:** Rewrote AppLayout to match exact UI-SPEC class strings: `py-2 bg-background text-xl font-semibold bg-background w-2 bg-transparent border-l border-border`
- **Files modified:** `services/web-ui/components/AppLayout.tsx`
- **Verification:** All 9 acceptance criteria grep checks pass (confirmed with grep -c)
- **Committed in:** `ac37973`

---

**Total deviations:** 1 auto-fixed (class alignment to exact UI-SPEC)
**Impact on plan:** Necessary correction for spec compliance. All business logic (subscriptions, incidentId state) preserved identically.

## Issues Encountered
- Tasks 09-02-01 through 09-02-05 and 09-02-07 were already complete from prior work — all verified against acceptance criteria before marking done

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Layout shell complete — ChatPanel, DashboardPanel, SubscriptionSelector placeholders render
- All provider/auth wiring in place (MSAL, DEV_MODE)
- AppLayout split-pane layout ready for 09-03 ChatPanel rebuild
- `autoSaveId="aap-main-layout"` persists panel width across browser sessions

---
*Phase: 09-web-ui-revamp*
*Completed: 2026-03-31*
