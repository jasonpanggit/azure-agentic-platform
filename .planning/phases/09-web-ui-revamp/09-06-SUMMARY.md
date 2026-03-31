---
phase: 09-web-ui-revamp
plan: 09-06
subsystem: ui
tags: [tailwindcss, shadcn-ui, nextjs, typescript, postcss, testing]

# Dependency graph
requires:
  - phase: 09-web-ui-revamp
    provides: All prior plans 09-01 through 09-05 — Tailwind foundation, layout, chat, dashboard, observability components
provides:
  - Zero Fluent UI remnants verified (0 @fluentui, makeStyles, FluentProvider, tokens. matches)
  - TypeScript compilation passes (npx tsc --noEmit exits 0)
  - Next.js production build passes (npm run build exits 0) — Phase 9 build-verified
  - All critical scroll layout classes confirmed in ChatPanel
  - All SSE business logic verified intact
  - @tailwindcss/postcss installed and wired for Tailwind v4
affects: [10-api-gateway-hardening, 11-patch-domain-agent, 12-eol-domain-agent]

# Tech tracking
tech-stack:
  added:
    - "@tailwindcss/postcss@^4.2.2 (devDep) — required PostCSS plugin for Tailwind v4"
  patterns:
    - "Tailwind v4: use @tailwindcss/postcss in postcss.config.mjs, not tailwindcss directly"
    - "Tailwind v4: @apply with custom color utilities (border-border, bg-background) fails at build — replace with direct CSS hsl(var(--border))"
    - "Jest + @jest/globals: use jest.MockedFunction<typeof fn> for typed mock return values"
    - "Jest + @jest/globals: import @testing-library/jest-dom/jest-globals in a .ts file to augment Matchers"

key-files:
  created:
    - services/web-ui/__tests__/jest-globals-setup.ts
  modified:
    - services/web-ui/__tests__/proxy-auth.test.ts
    - services/web-ui/__tests__/stream-poll-url.test.ts
    - services/web-ui/__tests__/stream.test.ts
    - services/web-ui/app/globals.css
    - services/web-ui/package.json
    - services/web-ui/package-lock.json
    - services/web-ui/postcss.config.mjs

key-decisions:
  - "Tailwind v4 requires @tailwindcss/postcss — cannot use tailwindcss directly as PostCSS plugin"
  - "Tailwind v4 @apply with CSS-variable-based color utilities breaks at build time — replaced with direct CSS"
  - "jest.MockedFunction<typeof fn> over jest.Mock for typed mock function arguments in @jest/globals tests"
  - "jest-globals-setup.ts augments @jest/globals with jest-dom matchers — separate from d.ts (module augmentation requires import)"

patterns-established:
  - "Pattern: Tailwind v4 globals.css — use hsl(var(--border)) directly instead of @apply border-border"
  - "Pattern: Tailwind v4 PostCSS — always use @tailwindcss/postcss, not tailwindcss, in postcss.config"

requirements-completed:
  - UI-001
  - UI-002
  - UI-003
  - UI-004
  - UI-005
  - UI-006
  - UI-007
  - UI-008

# Metrics
duration: 35min
completed: 2026-03-31
---

# Plan 09-06: Cleanup + Verification Summary

**Zero Fluent UI remnants, tsc passes, npm run build passes — Phase 9 Web UI Revamp fully verified with 2 build fixes for Tailwind v4 PostCSS + @apply semantics**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-03-31T06:00:00Z
- **Completed:** 2026-03-31T06:35:00Z
- **Tasks:** 8/8 verified
- **Files modified:** 7

## Accomplishments

- Zero `@fluentui`, `makeStyles`, `FluentProvider`, `tokens.` references in app/components/lib (09-06-01 ✅)
- `package.json` has all 30 required deps, zero Fluent deps (09-06-02 ✅)
- `next.config.ts` has `output: standalone`, `reactStrictMode: true`, no `transpilePackages` (09-06-03 ✅)
- `npx tsc --noEmit` exits 0 after fixing 16 TypeScript errors in test files (09-06-04 ✅)
- `npm run build` exits 0 after installing `@tailwindcss/postcss` and removing `@apply` in globals.css (09-06-05 ✅)
- ChatPanel confirmed: `absolute inset-0 flex flex-col overflow-hidden` + `ScrollArea flex-1 min-h-0` + `shrink-0 grow-0` (09-06-06 ✅)
- `globals.css` confirmed: `--primary: 207 90% 42%`, `--ring: 207 90% 42%`, `--radius: 0.5rem`, `@tailwind base`, `.prose table`, `prefers-reduced-motion` (09-06-07 ✅)
- All SSE functions verified: `useSSE`, `handleTokenEvent`, `handleTraceEvent`, `handleSubmit`, `handleApprove`, `handleReject`, `currentAgentRef`, `/api/proxy/chat`, `/api/proxy/approvals/`. All 5 business logic files exist. (09-06-08 ✅)

## Task Commits

Tasks 01, 02, 03, 06, 07, 08 were pure verification (no code changes needed — prior plans left the codebase clean).

1. **Task 09-06-04: TypeScript compilation** — `963a64d` (fix)
2. **Task 09-06-05: Next.js build** — `bea51fe` (fix)

## Files Created/Modified

- `services/web-ui/__tests__/jest-globals-setup.ts` — Augments `@jest/globals` with `@testing-library/jest-dom` matchers
- `services/web-ui/__tests__/proxy-auth.test.ts` — Fixed `jest.MockedFunction<typeof fetch>` typing
- `services/web-ui/__tests__/stream-poll-url.test.ts` — Fixed `jest.MockedFunction<typeof fetch>` typing
- `services/web-ui/__tests__/stream.test.ts` — Fixed `jest.MockedFunction<typeof fetch>` typing
- `services/web-ui/app/globals.css` — Replaced `@apply border-border/bg-background/text-foreground` and `.prose` `@apply` usages with direct CSS
- `services/web-ui/package.json` — Added `@tailwindcss/postcss@^4.2.2` to devDependencies
- `services/web-ui/postcss.config.mjs` — Changed PostCSS plugin from `tailwindcss` to `@tailwindcss/postcss`

## Decisions Made

- **Tailwind v4 PostCSS plugin**: `tailwindcss` cannot be used directly as a PostCSS plugin in v4. Must use `@tailwindcss/postcss`. Installed and wired.
- **@apply removal**: In Tailwind v4, `@apply border-border` and similar custom color utility classes fail because the utility resolution order differs at CSS layer processing time. Replaced with direct `hsl(var(--border))` CSS values. This is the idiomatic Tailwind v4 approach.
- **Jest type fix**: `jest.Mock` without generic parameter types `mockResolvedValueOnce` argument as `never`. Using `jest.MockedFunction<typeof fn>` preserves the proper return type and resolves the TS2345 error.

## Deviations from Plan

### Auto-fixed Issues

**1. [Build Blocker] Tailwind v4 PostCSS plugin missing**
- **Found during:** Task 09-06-05 (Next.js build)
- **Issue:** `postcss.config.mjs` used `tailwindcss` directly as a PostCSS plugin. Tailwind v4 removed the built-in PostCSS plugin — it now ships as a separate `@tailwindcss/postcss` package.
- **Fix:** Installed `@tailwindcss/postcss`, updated `postcss.config.mjs`
- **Files modified:** `postcss.config.mjs`, `package.json`, `package-lock.json`
- **Verification:** `npm run build` exits 0
- **Committed in:** `bea51fe`

**2. [Build Blocker] `@apply` with CSS-variable-based utilities fails in Tailwind v4**
- **Found during:** Task 09-06-05 (Next.js build, after PostCSS fix)
- **Issue:** `@apply border-border` and `@apply bg-background text-foreground` in `@layer base` fail in Tailwind v4 — custom color utilities derived from CSS variables are not resolved at `@apply` processing time. Error: `Cannot apply unknown utility class 'border-border'`
- **Fix:** Replaced all `@apply` usages with direct CSS property values using `hsl(var(--border))` etc.
- **Files modified:** `services/web-ui/app/globals.css`
- **Verification:** Build passes, CSS variables still present in file, all globals.css acceptance criteria pass
- **Committed in:** `bea51fe`

**3. [TypeScript] Test mock typing with `jest.Mock` produces `never` argument type**
- **Found during:** Task 09-06-04 (TypeScript compilation)
- **Issue:** 6 TypeScript errors TS2345 in test files: `jest.Mock` without type parameter causes `mockResolvedValueOnce` argument to be typed as `never`
- **Fix:** Changed `(global.fetch as jest.Mock)` to `(global.fetch as jest.MockedFunction<typeof fetch>)` which preserves correct return type inference
- **Files modified:** `__tests__/proxy-auth.test.ts`, `__tests__/stream-poll-url.test.ts`, `__tests__/stream.test.ts`
- **Verification:** `npx tsc --noEmit` exits 0
- **Committed in:** `963a64d`

**4. [TypeScript] @testing-library/jest-dom matchers not available for @jest/globals**
- **Found during:** Task 09-06-04 (TypeScript compilation)
- **Issue:** 10 TypeScript errors TS2339 — `toBeInTheDocument`, `toHaveTextContent`, `toHaveAttribute` not found on `Matchers`. The test files import `@testing-library/jest-dom` which augments the global `jest` namespace, but these tests use `@jest/globals`, which requires augmenting `@jest/expect` via the separate `jest-globals.d.ts` export
- **Fix:** Added `__tests__/jest-globals-setup.ts` that imports `@testing-library/jest-dom/jest-globals`
- **Files modified:** `__tests__/jest-globals-setup.ts` (created)
- **Verification:** `npx tsc --noEmit` exits 0
- **Committed in:** `963a64d`

---

**Total deviations:** 4 auto-fixed (2 build blockers, 2 TypeScript errors)
**Impact on plan:** All 4 auto-fixes were required for the build and type check acceptance criteria. No scope creep — all changes directly serve plan goals.

## Issues Encountered

- Next.js build cache retained old PostCSS error after initial config fix; required `rm -rf .next` before rebuild to clear webpack module cache.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 9 Web UI Revamp is **COMPLETE** — all 6 plans done (09-01 through 09-06)
- TypeScript compiles cleanly, Next.js builds successfully, zero Fluent remnants
- Critical scroll layout intact, all SSE/MSAL business logic preserved
- 18 shadcn/ui components installed, Azure Blue design tokens in globals.css
- Ready for Phase 13 or any further platform work

---
*Phase: 09-web-ui-revamp*
*Completed: 2026-03-31*
