# Plan 05-00 Summary: Wave 0 — Test Infrastructure & Stubs

**Status:** Complete
**Branch:** phase-5-wave-0-test-infrastructure
**Completed:** 2026-03-27

---

## What Was Built

Wave 0 scaffolds all test infrastructure for Phase 5 (Triage & Remediation + Web UI). Every subsequent plan in Phase 5 starts with pre-existing stub tests that go from skipped → passing as implementation proceeds.

---

## Tasks Completed

### Task 5-00-01: Web UI package.json and TypeScript Config
- `services/web-ui/package.json` — Next.js 15, Fluent UI v9.73.4, MSAL v3, Playwright 1.58.2, Jest 29
- `services/web-ui/tsconfig.json` — strict mode, `jsx: preserve`, bundler moduleResolution
- `services/web-ui/next.config.ts` — standalone output, transpilePackages for Fluent UI
- `services/web-ui/.env.example` — MSAL and API gateway env vars

### Task 5-00-02: Playwright Config and E2E Stub Files
- `services/web-ui/playwright.config.ts` — points to `../../e2e`, localhost:3000, chromium only
- `e2e/sc1.spec.ts` — @sc1 FMP + first token latency stubs
- `e2e/sc2.spec.ts` — @sc2 SSE reconnect continuity stubs
- `e2e/sc5.spec.ts` — @sc5 Resource Identity Certainty stale_approval stub
- `e2e/sc6.spec.ts` — @sc6 GitOps vs direct-apply path stubs

### Task 5-00-03: Shared pytest Conftest
- `services/api-gateway/tests/conftest.py` — 9 shared fixtures:
  - `client` (FastAPI TestClient)
  - `mock_foundry_client` (AIProjectClient with agents sub-client)
  - `mock_cosmos_approvals` (full D-12 approval schema mock)
  - `mock_cosmos_incidents` (incident container mock)
  - `mock_teams_notifier` (async Teams card poster)
  - `mock_arm_client` (ARM resource client)
  - `sample_approval_record` (pre-built D-12 record)
  - `sample_remediation_proposal` (RemediationProposal fixture)
  - `pre_seeded_embeddings` (3 × 1536-dim deterministic unit vectors)
- `pyproject.toml` — added 6 SC markers (sc1–sc6) + e2e marker

### Task 5-00-04: Python Test Stub Files (8 files, 42 stub tests)
- `test_chat_endpoint.py` — 3 stubs (POST /api/v1/chat)
- `test_sse_stream.py` — 5 stubs (sequence numbers, heartbeat, reconnect, ring buffer, event types)
- `test_runbook_rag.py` — 5 stubs (top-3 results, 0.75 threshold, 500ms latency, domain filter, citations)
- `test_approval_lifecycle.py` — 8 stubs (create, approve, reject, expire-410, etag, thread park/resume)
- `test_resource_identity.py` — 5 stubs (SHA-256 hash, identity match, diverged state, stale_approval abort, 2-signal minimum)
- `test_rate_limiting.py` — 4 stubs (within limit, 429 exceeded, protected tag 403, prod scope 403)
- `test_gitops_path.py` — 5 stubs (Flux detection, no-Flux, PR creation, direct-apply, branch name format)
- `test_audit_trail.py` — 5 stubs (Cosmos write, OneLake write, OneLake non-blocking, agent filter, time range filter)

### Task 5-00-05: Web UI Jest Stub Files
- `services/web-ui/__tests__/layout.test.tsx` — 7 stubs (split-pane, panel widths, default split, breakpoint, tabs, active tab)
- `services/web-ui/__tests__/auth.test.tsx` — 3 stubs (MsalProvider, Unauthenticated/Authenticated templates)

### Task 5-00-06: SSE Heartbeat Stub
- `services/api-gateway/tests/test_sse_heartbeat.py` — 2 stubs (20s interval, Container Apps 240s timeout prevention)

---

## Verification Results

```
pytest services/api-gateway/tests/ --co -q
→ 51 tests collected in 0.09s

pytest services/api-gateway/tests/ -q
→ 9 passed, 42 skipped, 1 warning in 0.52s (0 failures)

node -e "require('.../services/web-ui/package.json')"
→ package.json is valid JSON

e2e/ directory:
→ sc1.spec.ts, sc2.spec.ts, sc5.spec.ts, sc6.spec.ts ✓

pyproject.toml:
→ sc1 through sc6 markers + e2e marker ✓
```

---

## Commits

1. `ac9e4f7` — `feat(web-ui): scaffold Next.js project config — package.json, tsconfig, next.config, .env.example`
2. `0dabf60` — `feat(e2e): add Playwright config and Phase 5 E2E stub specs (sc1, sc2, sc5, sc6)`
3. `71f54da` — `feat(tests): add shared pytest conftest fixtures and Phase 5 SC markers to pyproject.toml`
4. `935eeb7` — `test(stubs): add Phase 5 Python test stub files — chat, SSE, RAG, approval, identity, rate-limit, gitops, audit`
5. `cd7cf19` — `test(stubs): add web-ui Jest stub tests — AppLayout and MSAL PKCE auth`
6. `31eba76` — `test(stub): add SSE heartbeat stub test — UI-008 20s heartbeat to prevent Container Apps timeout`

---

## Must-Haves Checklist

- [x] All VALIDATION.md Wave 0 test stubs are created
- [x] Shared conftest.py has mock fixtures for Foundry, Cosmos (approvals + incidents), Teams, ARM, pgvector embeddings
- [x] Playwright config targeting localhost:3000 with tagged test suites
- [x] Web UI package.json with exact Fluent UI v9 9.73.4, MSAL v3, Next.js 15, Playwright 1.58.2
- [x] pyproject.toml updated with SC markers
- [x] test_sse_heartbeat.py stub created for UI-008 heartbeat validation

---

## Next

**Plan 05-01** — Web UI Shell: App Router scaffold, FluentProvider, MsalProvider, ResizablePanelGroup split-pane layout, tab navigation. The `layout.test.tsx` and `auth.test.tsx` stubs go green in this plan.
