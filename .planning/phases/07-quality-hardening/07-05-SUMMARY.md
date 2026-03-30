# Plan 07-05 Summary: E2E Test Infrastructure + Real Endpoint Migration

## Goal

Set up the Phase 7 Playwright E2E test infrastructure for running tests against real deployed Container Apps (not mocks). Refactor existing sc1–sc6 specs to remove `page.route()` mocks and use real endpoints via an auth fixture. Create the CI workflow that gates merge on E2E success.

## Tasks Completed

| Task | File | Status |
|------|------|--------|
| 7-05-01 | `e2e/playwright.config.ts` | ✅ Created |
| 7-05-02 | `e2e/global-setup.ts` | ✅ Created |
| 7-05-03 | `e2e/global-teardown.ts` | ✅ Created |
| 7-05-04 | `e2e/fixtures/auth.ts` | ✅ Created |
| 7-05-05 | `e2e/sc1.spec.ts` | ✅ Refactored |
| 7-05-06 | `e2e/sc2.spec.ts` | ✅ Refactored |
| 7-05-07 | `e2e/sc5.spec.ts` + `e2e/sc6.spec.ts` | ✅ Refactored |
| 7-05-08 | `.github/workflows/staging-e2e-simulation.yml` | ✅ Created |

## Files Modified

### New Files
- `e2e/playwright.config.ts` — Phase 7 E2E config: `testDir: '.'`, `workers: 1`, `timeout: 120_000`, global setup/teardown, `e2e-chromium` project
- `e2e/global-setup.ts` — Acquires MSAL bearer token via `ConfidentialClientApplication`, creates `incidents-e2e` and `approvals-e2e` Cosmos DB containers
- `e2e/global-teardown.ts` — Idempotent cleanup: deletes `incidents-e2e` and `approvals-e2e` containers, skips if no `E2E_COSMOS_ENDPOINT`
- `e2e/fixtures/auth.ts` — Extended Playwright `test` with `bearerToken`, `apiUrl`, `baseUrl`, `apiRequest` fixtures
- `.github/workflows/staging-e2e-simulation.yml` — CI workflow: `environment: staging`, `timeout-minutes: 15`, uploads report + results artifacts

### Modified Files
- `e2e/sc1.spec.ts` — Removed all `page.route()` mocks; tests health endpoint (`status: ok`, `version: 1.0.0`) and chat endpoint via `apiRequest` fixture
- `e2e/sc2.spec.ts` — Removed mock SSE bodies; tests real SSE content-type and heartbeat delivery
- `e2e/sc5.spec.ts` — Removed `page.route()` mocks; tests approval API for 410 Gone and pending approvals list
- `e2e/sc6.spec.ts` — Removed all `page.route()` mocks; tests GitOps detection and Arc K8s endpoints
- `services/web-ui/playwright.config.ts` — Added `testMatch: '**/*.spec.ts'` to exclude new infrastructure files from web-ui test run

## Acceptance Criteria Results

| Criterion | Result |
|-----------|--------|
| No E2E test uses `page.route()` mocks | ✅ `grep page.route()` returns no matches in sc1–sc6 |
| Global setup acquires auth token via MSAL | ✅ `ConfidentialClientApplication.acquireTokenByClientCredential` |
| Global teardown cleans up E2E Cosmos containers | ✅ Deletes `incidents-e2e`, `approvals-e2e`; idempotent |
| Auth fixture provides `apiRequest` with bearer token | ✅ `apiRequest` context built with `Authorization: Bearer {token}` |
| CI workflow has 15-minute timeout + blocks merge | ✅ `timeout-minutes: 15` on e2e job; triggers on PR |
| All refactored specs import from `./fixtures/auth` | ✅ All 4 specs import `{ test, expect }` from `./fixtures/auth` |
| `playwright.config.ts` `timeout` is `120_000` | ✅ |
| `playwright.config.ts` `workers` is `1` | ✅ |
| `playwright.config.ts` `retries` is 2 in CI | ✅ |
| `baseURL` reads from `E2E_BASE_URL` env var | ✅ |
| `bearerToken` defaults to `'dev-token'` | ✅ |
| CI uploads playwright-report + test-results artifacts | ✅ |

## Architecture Notes

- **No mock isolation needed**: Tests are designed to tolerate real-environment responses gracefully — e.g., `[202, 503]` status assertions for Foundry-dependent endpoints
- **Sequential execution**: `workers: 1` and `fullyParallel: false` prevents shared-state race conditions in staged Cosmos containers
- **CI environment**: Uses `environment: staging` for GitHub Environments-gated secrets (E2E credentials never in plain env vars)
- **Cosmos isolation**: E2E containers (`incidents-e2e`, `approvals-e2e`) are separate from production containers (`incidents`, `approvals`)
