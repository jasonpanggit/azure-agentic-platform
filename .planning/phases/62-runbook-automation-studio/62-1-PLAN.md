# Phase 62-1: Runbook Automation Studio — Plan

## Goal
Enable operators to build, test, and publish automation runbooks directly in the platform UI, backed by the existing HITL approval and WAL execution engine.

## Deliverables

| # | File | Purpose |
|---|------|---------|
| 1 | `services/api-gateway/runbook_executor.py` | `AutomationStep`, `AutomationRunbook` models; `RunbookExecutor` with SSE streaming; Jinja2 template resolution; WAL + approval record creation; 5 built-in runbooks |
| 2 | `services/api-gateway/runbook_executor_endpoints.py` | FastAPI router: `POST /{id}/execute`, `GET /tools`, `PUT /{id}/automation-steps` |
| 3 | `services/api-gateway/main.py` | Register `runbook_executor_router` |
| 4 | `services/api-gateway/requirements.txt` | Add `Jinja2>=3.1.0` |
| 5 | `services/web-ui/components/RunbookAutomationStudio.tsx` | Visual step builder UI with dry-run, save, SSE execution overlay |
| 6 | `services/web-ui/app/api/proxy/runbooks/[id]/execute/route.ts` | POST proxy → `/api/v1/runbooks/{id}/execute` |
| 7 | `services/web-ui/app/api/proxy/runbooks/tools/route.ts` | GET proxy → `/api/v1/runbooks/tools` |
| 8 | `services/api-gateway/tests/test_runbook_executor.py` | 12 tests (9 passing, 3 skipped pending Jinja2 install) |
| 9 | `.planning/phases/62-runbook-automation-studio/62-1-PLAN.md` | This file |
| 10 | `.planning/phases/62-runbook-automation-studio/62-1-SUMMARY.md` | Summary |

## Architecture Decisions

### Executor Model
- `RunbookExecutor.execute()` is an `AsyncGenerator` that yields step event dicts, making it trivially wrappable in a `StreamingResponse` (SSE).
- Approval gates (`require_approval=True`) emit `awaiting_approval` events and create Cosmos DB approval records; the client handles the HITL resume externally (matches existing approval flow).
- `on_failure` modes: `abort` stops immediately, `rollback` reverses completed steps in reverse order, `continue` skips to next step.

### Template Resolution
- Jinja2 `StrictUndefined` with `default()` filter fallback — keeps templates safe.
- Non-string values passed through unmodified.
- Resolution errors are collected into `_template_errors` dict rather than raising.

### Built-in Runbooks
- Defined as `BUILTIN_RUNBOOKS: dict[str, dict]` — no DB seeding required, always available.
- Custom steps override built-in steps at runtime via `_CUSTOM_AUTOMATION_STEPS` in-memory store.

### UI Component
- Two-column layout: step builder (left) + step sequence preview (right, sticky).
- SSE stream consumed via `ReadableStream` reader — no Vercel AI SDK dependency.
- All colours via CSS semantic tokens (`var(--accent-*)`, `var(--bg-*)`, `var(--text-*)`).

## Key Patterns
- Lazy imports with `try/except ImportError` and `None` fallback throughout.
- Functions never raise — return structured error dicts.
- WAL writes are fire-and-forget (failures logged, never raised).
- Proxy routes follow the standard `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout()` pattern.
