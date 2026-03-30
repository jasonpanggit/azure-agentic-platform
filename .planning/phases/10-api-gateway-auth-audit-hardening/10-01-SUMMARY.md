---
phase: 10-api-gateway-auth-audit-hardening
plan: "01"
subsystem: api-gateway
tags: [security, auth, audit, remediation]

requires:
  - phase: 08-azure-validation-incident-simulation
    provides: validation findings, backlog context, operator-only blockers still open
provides:
  - explicit API gateway auth mode with fail-closed default
  - audit filter validation before KQL generation
  - local/test bootstrap updated to opt into insecure auth explicitly
affects: [api-gateway, local-dev, test-harness]

tech-stack:
  added: []
  patterns: [fail-closed-auth, validated-query-boundary, explicit-local-bypass]

key-files:
  created:
    - .planning/phases/10-api-gateway-auth-audit-hardening/10-01-SUMMARY.md
    - .planning/phases/10-api-gateway-auth-audit-hardening/10-01-PLAN.md
    - services/api-gateway/tests/test_auth_security.py
  modified:
    - services/api-gateway/auth.py
    - services/api-gateway/audit.py
    - services/api-gateway/main.py
    - services/api-gateway/tests/conftest.py
    - services/api-gateway/tests/test_audit_trail.py
    - scripts/run-mock.sh
    - .planning/ROADMAP.md
    - .planning/STATE.md

key-decisions:
  - "API gateway auth now fails closed by default; local bypass requires API_GATEWAY_AUTH_MODE=disabled"
  - "Audit filters are validated before any KQL is built, and invalid values return HTTP 400"
  - "Local mock and pytest harnesses opt into disabled auth explicitly instead of relying on missing AZURE_CLIENT_ID"

patterns-established:
  - "Explicit insecure mode over implicit dev-mode by omission"
  - "Validate and reject unsafe observability query inputs at the request boundary"

requirements-completed: []

duration: 1 session
completed: 2026-03-30
---

# Phase 10 Plan 01: API Gateway Auth & Audit Hardening Summary

**Auth now fails closed unless `API_GATEWAY_AUTH_MODE=disabled` is set explicitly; audit query filters are validated before KQL generation; focused gateway security tests pass.**

## Accomplishments

- Replaced the API gateway's implicit auth bypass with an explicit auth mode contract in `services/api-gateway/auth.py`
- Added 503 configuration errors for misconfigured enabled auth instead of silently authorizing requests
- Added validation for `agent`, `action`, `incident_id`, `resource`, `from_time`, `to_time`, and `limit` in `services/api-gateway/audit.py`
- Updated `/api/v1/audit` in `services/api-gateway/main.py` to translate audit validation failures into HTTP 400 responses
- Added `services/api-gateway/tests/test_auth_security.py` for fail-closed auth regressions
- Extended `services/api-gateway/tests/test_audit_trail.py` to prove invalid audit filters are rejected
- Updated `services/api-gateway/tests/conftest.py` and `scripts/run-mock.sh` so local/test workflows opt into insecure auth explicitly

## Verification

- Focused test run passed:
  - `pytest services/api-gateway/tests/test_auth_security.py services/api-gateway/tests/test_audit_trail.py -q`
- Result: `11 passed`

## Remaining Work Outside This Plan

- Phase 8 operator blockers remain open: Foundry RBAC (F-01) and prod runbook search 500 (F-02)
- Teams bot auth still uses its legacy dev-token fallback and no longer mirrors the gateway contract
- CORS hardening, approvals 404 handling, and Foundry/MCP wiring gaps remain in backlog