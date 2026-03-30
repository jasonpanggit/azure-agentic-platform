---
status: complete
phase: 07-quality-hardening
source:
  - 07-01-SUMMARY.md
  - 07-02-SUMMARY.md
  - 07-03-SUMMARY.md
  - 07-04-SUMMARY.md
  - 07-05-SUMMARY.md
  - 07-06-SUMMARY.md
started: "2026-03-27T15:21:10Z"
updated: "2026-03-27T15:45:00Z"
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running server/service. Clear ephemeral state. Start the api-gateway from scratch (e.g. `uvicorn main:app`). The server boots without errors. OTel init logs a warning if APPLICATIONINSIGHTS_CONNECTION_STRING is absent but does NOT crash. A request to GET /health (or equivalent) returns a live response.
result: pass

### 2. Observability Tab Visible in Dashboard
expected: Open the web UI and navigate to the Dashboard. A 5th tab labelled "Observability" appears alongside the existing tabs. Clicking it renders the Observability view — you see four metric cards (Agent Latency, Pipeline Lag, Approval Queue, Active Errors) in a 2×2 grid. A time-range dropdown (1h / 6h / 24h / 7d) is visible.
result: pass

### 3. Observability Tab — Loading and Error States
expected: When Application Insights / LOG_ANALYTICS_WORKSPACE_ID is not configured, the Observability tab shows an error MessageBar (not a blank screen, not a crash). While data is loading, skeleton placeholders appear in place of the cards.
result: pass

### 4. Observability Tab — Health Colours
expected: Each metric card shows a coloured left border and a health badge. Healthy = green border, warning = yellow, critical = red. The health state changes based on thresholds (e.g. P95 latency > 3 000 ms → warning, > 5 000 ms → critical; approval queue > 10 → warning).
result: skipped
reason: requires live Application Insights data

### 5. Time Range Selector Updates Data
expected: Changing the time-range dropdown (e.g. from 1h to 24h) triggers a new fetch to /api/observability?timeRange=24h and the cards update. The tab auto-refreshes every ~30 seconds without any manual action.
result: skipped
reason: requires live Application Insights data

### 6. Export Audit Report Button
expected: Open the Remediation / AuditLogViewer section of the UI. An "Export Report" button with a document icon is visible in the toolbar. Clicking it triggers a download of a JSON file named remediation-report-{from}-{to}.json. While downloading, the button is disabled (prevents double-click).
result: skipped
reason: requires live Cosmos DB / OneLake data

### 7. Audit Export API — Structure
expected: Calling GET /api/v1/audit/export?from_time=...&to_time=... (with a valid bearer token) returns JSON with two top-level keys: report_metadata (containing generated_at, period, total_events) and remediation_events (an array). An unauthenticated call returns 401/403.
result: skipped
reason: requires live Cosmos DB data

### 8. Runbook Files Exist — 60 Files, 6 Domains
expected: Running `ls scripts/seed-runbooks/runbooks/*.md | wc -l` returns 60. Each domain (compute, network, storage, security, arc, sre) has exactly 10 files. Every file has YAML frontmatter with title, domain, version, tags and the five required sections: Symptoms, Root Causes, Diagnostic Steps, Remediation Commands, Rollback Procedure.
result: pass

### 9. Seed Script is Idempotent
expected: `scripts/seed-runbooks/seed.py` exists and contains an `ON CONFLICT (title) DO UPDATE` clause (idempotent upsert). Running it twice against the same database should not produce duplicate rows.
result: pass

### 10. Terraform agent-apps — web-ui and teams-bot Ports
expected: In terraform/modules/agent-apps/main.tf, the local.services block contains web-ui with target_port = 3000 and teams-bot with target_port = 3978. The ingress block uses each.value.target_port (not hardcoded 8000).
result: pass

### 11. CORS Configurable via Env Var
expected: services/api-gateway/main.py reads CORS_ALLOWED_ORIGINS from the environment. When the env var is not set, the default is * (allow all). When set to a specific origin, only that origin is allowed. No hardcoded ["*"] in the CORS middleware call.
result: pass

### 12. Security CI Workflow Exists
expected: .github/workflows/security-review.yml exists with three jobs: python-security (runs bandit), typescript-security (runs npm audit on web-ui and teams-bot), and secrets-scan (greps for hardcoded credentials). The workflow triggers on push to main and on PRs that touch services/.
result: pass

### 13. E2E Infrastructure — Auth Fixture + Global Setup
expected: e2e/global-setup.ts exists and acquires a bearer token via MSAL ConfidentialClientApplication. e2e/fixtures/auth.ts exports an extended test object with bearerToken, apiUrl, baseUrl, and apiRequest fixtures. e2e/playwright.config.ts has timeout: 120_000, workers: 1, and retries: 2 in CI.
result: pass

### 14. E2E Specs — No Mocks, Real Endpoints
expected: The refactored sc1, sc2, sc5, sc6 specs contain zero page.route() calls. The five new specs (e2e-incident-flow, e2e-hitl-approval, e2e-rbac, e2e-sse-reconnect, e2e-audit-export) all import from ./fixtures/auth and make real HTTP calls via apiRequest.
result: pass

### 15. E2E CI Gate
expected: .github/workflows/staging-e2e-simulation.yml exists with timeout-minutes: 15. It triggers on PRs and uploads playwright-report + test-results as artifacts. It uses environment: staging so secrets are GitHub Environments-gated.
result: pass

## Summary

total: 15
passed: 10
issues: 0
skipped: 5
blocked: 0
pending: 0

## Gaps

[none yet]
