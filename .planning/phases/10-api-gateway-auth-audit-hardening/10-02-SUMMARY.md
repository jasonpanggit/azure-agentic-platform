---
phase: 10-api-gateway-auth-audit-hardening
plan: "02"
subsystem: runbook-rag
tags: [availability, postgres, pgvector, remediation]

requires:
  - phase: 10-api-gateway-auth-audit-hardening
    provides: gateway hardening baseline, explicit auth/test bootstrap contract
provides:
  - explicit runbook DB DSN resolution
  - typed runbook availability error boundary
  - 503 endpoint behavior for runbook DB outages/misconfiguration
affects: [api-gateway, runbook-rag, startup-migrations]

tech-stack:
  added: []
  patterns: [explicit-dsn-resolution, typed-availability-error, truthful-503]

key-files:
  created:
    - .planning/phases/10-api-gateway-auth-audit-hardening/10-02-PLAN.md
    - .planning/phases/10-api-gateway-auth-audit-hardening/10-02-SUMMARY.md
    - services/api-gateway/tests/test_runbook_search_availability.py
  modified:
    - services/api-gateway/runbook_rag.py
    - services/api-gateway/main.py
    - services/api-gateway/tests/test_runbook_rag.py
    - .planning/ROADMAP.md
    - .planning/STATE.md

key-decisions:
  - "Runbook search now resolves PGVECTOR_CONNECTION_STRING, POSTGRES_DSN, or explicit POSTGRES_* settings"
  - "Runbook DB misconfiguration or availability failures now surface as HTTP 503, not generic 500s"
  - "Runbook module tests now provide an explicit DSN instead of relying on the old implicit localhost fallback"

patterns-established:
  - "Shared connection-resolution helper reused by request path and startup migrations"
  - "Availability problems should fail truthfully at the API boundary"

requirements-completed: []

duration: 1 session
completed: 2026-03-30
---

# Phase 10 Plan 02: Runbook Search Availability Hardening Summary

**Runbook search no longer depends on an implicit localhost fallback, accepts `PGVECTOR_CONNECTION_STRING` explicitly, and returns HTTP 503 when the runbook DB is unavailable.**

## Accomplishments

- Added `RunbookSearchUnavailableError` in `services/api-gateway/runbook_rag.py`
- Added a public DSN resolver that understands `PGVECTOR_CONNECTION_STRING`, `POSTGRES_DSN`, and explicit `POSTGRES_*` settings
- Removed the hidden localhost fallback when no runbook DB configuration is present
- Updated `services/api-gateway/main.py` so startup migrations and `/api/v1/runbooks/search` share the same runbook DB resolution logic
- Added `services/api-gateway/tests/test_runbook_search_availability.py` for DSN alias and 503-path coverage
- Updated `services/api-gateway/tests/test_runbook_rag.py` so existing module tests use an explicit test DSN and run under the local AnyIO test plugin

## Verification

- Focused runbook test run passed:
  - `pytest services/api-gateway/tests/test_runbook_search_availability.py services/api-gateway/tests/test_runbook_rag.py -q`
- Combined gateway regression run passed:
  - `pytest services/api-gateway/tests/test_auth_security.py services/api-gateway/tests/test_audit_trail.py services/api-gateway/tests/test_runbook_search_availability.py services/api-gateway/tests/test_runbook_rag.py -q`
- Result: `19 passed`

## Remaining Work Outside This Plan

- Prod still needs deployment and verification before Phase 8 F-02 can be claimed closed
- Prod seeding remains an operator/runtime concern if the runbooks table is empty