# Summary: Add Structured Logging to Web UI Next.js API Routes

**ID:** 260401-o1l
**Status:** COMPLETE
**Branch:** `quick/260401-o1l-web-ui-structured-logging`
**Date:** 2026-04-01

---

## What Changed

### New Files
- `services/web-ui/lib/logger.ts` — Server-side only structured JSON logger
- `services/web-ui/lib/__tests__/logger.test.ts` — 8 unit tests for the logger

### Modified Files (13 API routes)
| Route | Logging Added |
|---|---|
| `app/api/stream/route.ts` | SSE connect, poll status transitions, poll transient errors, poll network errors, timeout, abort, close |
| `app/api/proxy/chat/route.ts` | Request start (has_thread_id), upstream error, gateway unreachable, response |
| `app/api/proxy/chat/result/route.ts` | Poll request (thread_id, run_id), upstream error, gateway unreachable, response (run_status) |
| `app/api/proxy/incidents/route.ts` | Request start (query), upstream error, gateway unreachable, response (count) |
| `app/api/proxy/patch/assessment/route.ts` | Request start (query), upstream error, gateway unreachable, response |
| `app/api/proxy/patch/installations/route.ts` | Request start (query), upstream error, gateway unreachable, response |
| `app/api/proxy/patch/installed/route.ts` | Request start (query), upstream error, gateway unreachable, response |
| `app/api/proxy/approvals/[id]/approve/route.ts` | Approval action (approvalId), upstream error, gateway unreachable, response |
| `app/api/proxy/approvals/[id]/reject/route.ts` | Rejection action (approvalId), upstream error, gateway unreachable, response |
| `app/api/observability/route.ts` | Query start (timeRange), missing config warning, query success/failure |
| `app/api/resources/route.ts` | Request start (subscriptions, type filter), ARM error, success (count) |
| `app/api/subscriptions/route.ts` | Request start, ARM error, success (count) |
| `app/api/topology/route.ts` | Request start (subscriptions), ARM error, success (node/edge counts) |

## Design Decisions

- **Zero npm dependencies** — uses `console.log` (stdout) and `console.error` (stderr) only, which Azure Container Apps captures into `ContainerAppConsoleLogs_CL`
- **JSON-per-line format** — `{ timestamp, level, msg, service: "aap-web-ui", ...ctx }` for machine-readable Log Analytics queries
- **LOG_LEVEL env var** — default `"info"`, supports debug/info/warn/error; aligns with Python agent `LOG_LEVEL` pattern
- **child() helper** — `logger.child({ route })` returns a scoped logger to reduce per-route boilerplate
- **No sensitive data** — no auth headers, tokens, or full request bodies logged
- **Server-side only** — header comment `// Server-side only` prevents accidental client import; verified no `components/` files import it

## Verification

- [x] `npx tsc --noEmit` exits 0
- [x] Logger tests pass (8/8): JSON format, level filtering, stderr routing, child context, parent isolation
- [x] `grep -r "import.*logger" components/` returns nothing (no client imports)
- [x] All 13 route files import `{ logger }` from `@/lib/logger`
- [x] No new npm dependencies added

## Commits

1. `49c1e77` — `feat(web-ui): add structured JSON logger for server-side API routes`
2. `4d0b2e6` — `feat(web-ui): instrument all 13 API routes with structured logging`
3. `70c1d81` — `test(web-ui): add unit tests for structured JSON logger`
