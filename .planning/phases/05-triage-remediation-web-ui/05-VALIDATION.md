---
phase: 5
slug: triage-remediation-web-ui
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-27
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) + Playwright 1.58.2 (E2E/UI) |
| **Config file** | `pyproject.toml` (backend) · `playwright.config.ts` (E2E) — Wave 0 installs both |
| **Quick run command** | `pytest services/ agents/ --ignore=tests/integration -x -q` |
| **Full suite command** | `pytest services/ agents/ -q && npx playwright test --project=chromium` |
| **Estimated runtime** | ~45 seconds (unit) · ~120 seconds (Playwright) |

---

## Sampling Rate

- **After every task commit:** Run `pytest services/ agents/ --ignore=tests/integration -x -q`
- **After every plan wave:** Run `pytest services/ agents/ -q && npx playwright test --project=chromium`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 45 seconds (unit), 120 seconds (full)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 5-01-01 | 01 | 0 | UI-001 | unit | `pytest services/web-ui/tests/` | ❌ W0 | ⬜ pending |
| 5-01-02 | 01 | 1 | UI-001 | playwright | `npx playwright test --grep @sc1` | ❌ W0 | ⬜ pending |
| 5-01-03 | 01 | 1 | UI-002 | playwright | `npx playwright test --grep @ui-layout` | ❌ W0 | ⬜ pending |
| 5-02-01 | 02 | 1 | UI-003 | playwright | `npx playwright test --grep @sc1` | ❌ W0 | ⬜ pending |
| 5-02-02 | 02 | 1 | UI-004 | playwright | `npx playwright test --grep @ui-trace` | ❌ W0 | ⬜ pending |
| 5-02-03 | 02 | 1 | TRIAGE-007 | unit | `pytest services/api-gateway/tests/test_sse_stream.py` | ❌ W0 | ⬜ pending |
| 5-02-04 | 02 | 1 | TRIAGE-007 | playwright | `npx playwright test --grep @sc2` | ❌ W0 | ⬜ pending |
| 5-02-05 | 02 | 1 | UI-008 | unit | `pytest services/api-gateway/tests/test_sse_heartbeat.py` | ❌ W0 | ⬜ pending |
| 5-03-01 | 03 | 1 | TRIAGE-005 | unit | `pytest services/api-gateway/tests/test_runbook_rag.py` | ❌ W0 | ⬜ pending |
| 5-03-02 | 03 | 1 | TRIAGE-005 | unit | `pytest services/api-gateway/tests/test_runbook_rag.py -k similarity` | ❌ W0 | ⬜ pending |
| 5-04-01 | 04 | 2 | REMEDI-002 | unit | `pytest tests/test_approval_lifecycle.py -k park` | ❌ W0 | ⬜ pending |
| 5-04-02 | 04 | 2 | REMEDI-003 | unit | `pytest tests/test_approval_lifecycle.py -k expiry` | ❌ W0 | ⬜ pending |
| 5-04-03 | 04 | 2 | REMEDI-004 | unit | `pytest tests/test_resource_identity.py` | ❌ W0 | ⬜ pending |
| 5-04-04 | 04 | 2 | REMEDI-004 | playwright | `npx playwright test --grep @sc5` | ❌ W0 | ⬜ pending |
| 5-04-05 | 04 | 2 | REMEDI-005 | unit | `pytest tests/test_approval_lifecycle.py -k approve_from_ui` | ❌ W0 | ⬜ pending |
| 5-04-06 | 04 | 2 | REMEDI-006 | unit | `pytest tests/test_rate_limiting.py` | ❌ W0 | ⬜ pending |
| 5-04-07 | 04 | 2 | REMEDI-008 | unit | `pytest tests/test_gitops_path.py` | ❌ W0 | ⬜ pending |
| 5-04-08 | 04 | 2 | REMEDI-008 | playwright | `npx playwright test --grep @sc6` | ❌ W0 | ⬜ pending |
| 5-05-01 | 05 | 2 | UI-005 | playwright | `npx playwright test --grep @ui-proposal-card` | ❌ W0 | ⬜ pending |
| 5-05-02 | 05 | 2 | UI-006 | playwright | `npx playwright test --grep @ui-alert-feed` | ❌ W0 | ⬜ pending |
| 5-05-03 | 05 | 2 | UI-007 | playwright | `npx playwright test --grep @ui-multi-sub` | ❌ W0 | ⬜ pending |
| 5-06-01 | 06 | 3 | AUDIT-002 | unit | `pytest tests/test_audit_trail.py` | ❌ W0 | ⬜ pending |
| 5-06-02 | 06 | 3 | AUDIT-004 | playwright | `npx playwright test --grep @ui-audit-log` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `services/web-ui/tests/test_app_bootstrap.py` — stubs for UI-001, UI-002 mount/auth checks
- [ ] `services/api-gateway/tests/test_sse_stream.py` — stubs for TRIAGE-007 (SSE sequence numbers, heartbeat)
- [ ] `services/api-gateway/tests/test_sse_heartbeat.py` — stubs for UI-008 heartbeat interval check
- [ ] `services/api-gateway/tests/test_runbook_rag.py` — stubs for TRIAGE-005 (similarity threshold, latency, citation format)
- [ ] `tests/test_approval_lifecycle.py` — stubs for REMEDI-002/003/005 (all 6 status transitions)
- [ ] `tests/test_resource_identity.py` — stubs for REMEDI-004 (snapshot, stale detection, 2-signal min)
- [ ] `tests/test_rate_limiting.py` — stubs for REMEDI-006 (rate limit, protected tag, scope confirmation)
- [ ] `tests/test_gitops_path.py` — stubs for REMEDI-008 (Flux → PR path vs direct-apply)
- [ ] `tests/test_audit_trail.py` — stubs for AUDIT-002/004 (Cosmos write, Fabric OneLake write, filter query)
- [ ] `tests/conftest.py` — shared fixtures: mock Foundry client, mock Teams notifier, mock ARM client, pre-seeded pgvector embeddings, mock Cosmos DB
- [ ] `playwright.config.ts` — Playwright config targeting `http://localhost:3000` with tagged test suites (@sc1–@sc6, @ui-*)
- [ ] `package.json` for web-ui — Next.js 15, `@fluentui/react-components` v9, `@playwright/test` v1.58.2

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| MSAL PKCE browser redirect login flow | UI-001 | Cannot mock Entra B2C browser popup in headless Playwright without real credentials | Dev: load UI at `localhost:3000`, verify redirect to Entra login, complete auth, confirm bearer token in `Authorization` header via DevTools |
| Teams Adaptive Card rendered in real Teams client | REMEDI-002 | Teams client rendering requires live Teams tenant | Staging: trigger high-risk remediation, confirm card appears in Teams test channel with correct action buttons |
| Foundry thread park and resume in live agent | REMEDI-002 | Requires live Foundry instance with real thread | Staging: verify Foundry thread shows `status: waiting` after park; verify it resumes within 5s of webhook |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s (unit), < 120s (full suite)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
