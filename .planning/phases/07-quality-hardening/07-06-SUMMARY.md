---
plan: 07-06
title: "E2E Test Specs — Incident Flow, HITL Approval, RBAC, SSE Reconnect"
status: complete
completed_at: "2026-03-27"
---

# Plan 07-06 Summary

## Goal

Create 5 E2E test specs (E2E-002 through E2E-005 + AUDIT-006) that exercise real deployed Container Apps endpoints with no mocks. All tests use the auth fixture from Plan 07-05 and skip gracefully when infrastructure is unavailable.

## Tasks Completed

| # | Task | Status |
|---|------|--------|
| 7-06-01 | E2E-002 — Full Incident Flow | ✅ Complete |
| 7-06-02 | E2E-003 — HITL Approval Flow | ✅ Complete |
| 7-06-03 | E2E-004 — Cross-Subscription RBAC | ✅ Complete |
| 7-06-04 | E2E-005 — SSE Reconnect | ✅ Complete |
| 7-06-05 | AUDIT-006 Audit Export E2E | ✅ Complete |

## Files Created

| File | Tests | Coverage |
|------|-------|----------|
| `e2e/e2e-incident-flow.spec.ts` | 3 | POST /api/v1/incidents → 202 + thread_id; incidents list; SSE stream events |
| `e2e/e2e-hitl-approval.spec.ts` | 4 | GET /api/v1/approvals list; approve endpoint; reject endpoint; optional Graph API Teams card verification |
| `e2e/e2e-rbac.spec.ts` | 4 | All 6 domains route correctly; invalid domain returns 422; health auth check; unauthenticated rejection |
| `e2e/e2e-sse-reconnect.spec.ts` | 2 | Monotonic sequence IDs; no duplicate events; Last-Event-ID reconnect; heartbeat check |
| `e2e/e2e-audit-export.spec.ts` | 2 | Export returns report_metadata + remediation_events structure; unauthenticated access handling |

## Acceptance Criteria Results

### E2E-002 (Incident Flow)
- [x] `e2e/e2e-incident-flow.spec.ts` exists
- [x] Zero `page.route()` calls (no mocks)
- [x] Imports from `./fixtures/auth`
- [x] Creates synthetic incident via `POST /api/v1/incidents` with full IncidentPayload
- [x] Payload includes `incident_id`, `severity`, `domain`, `affected_resources` (with `resource_id`, `subscription_id`, `resource_type`), `detection_rule`
- [x] Verifies 202 response with `thread_id`
- [x] Uses `expect.poll` with 90-second timeout for triage completion
- [x] Tests SSE stream delivers at least one event

### E2E-003 (HITL Approval Flow)
- [x] `e2e/e2e-hitl-approval.spec.ts` exists
- [x] Zero `page.route()` calls (no mocks)
- [x] Imports from `./fixtures/auth`
- [x] Tests `GET /api/v1/approvals?status=pending` returns array with required fields
- [x] Tests `POST /api/v1/approvals/{id}/approve` with `decided_by` and `thread_id`
- [x] Tests `POST /api/v1/approvals/{id}/reject`
- [x] Graph API test skips when `E2E_GRAPH_CLIENT_ID` not set
- [x] All approve/reject tests handle 200, 400, and 410 response codes

### E2E-004 (Cross-Subscription RBAC)
- [x] `e2e/e2e-rbac.spec.ts` exists
- [x] Zero `page.route()` calls (no mocks)
- [x] Tests all 6 domains: `compute`, `network`, `storage`, `security`, `arc`, `sre`
- [x] Tests invalid domain returns 422 (Pydantic validation pattern enforcement)
- [x] Tests unauthenticated request handling (401 or 200 in dev mode)
- [x] Uses `apiRequest` fixture for authenticated calls

### E2E-005 (SSE Reconnect)
- [x] `e2e/e2e-sse-reconnect.spec.ts` exists
- [x] Zero `page.route()` calls (no mocks)
- [x] Imports from `./fixtures/auth`
- [x] Test creates a chat thread to generate SSE events
- [x] Reads SSE stream and collects events with IDs
- [x] Verifies monotonic sequence IDs: `numericIds[i] > numericIds[i-1]`
- [x] Verifies no duplicates: `new Set(numericIds).size === numericIds.length`
- [x] Reconnects with `Last-Event-ID` header
- [x] Handles Foundry unavailability gracefully (skips)

### AUDIT-006 (Audit Export)
- [x] `e2e/e2e-audit-export.spec.ts` exists
- [x] Zero `page.route()` calls (no mocks)
- [x] Imports from `./fixtures/auth`
- [x] Tests `GET /api/v1/audit/export` with `from_time` and `to_time` params
- [x] Verifies response has `report_metadata` with `generated_at`, `period`, `total_events`
- [x] Verifies `remediation_events` is an array
- [x] Each event (if any) verified to have `agentId`, `toolName`, `outcome`, `approval_chain`
- [x] Tests unauthenticated access handling

## Design Decisions

1. **No mocks**: All tests operate against real endpoints. When infrastructure is unavailable (Foundry, Cosmos, etc.) tests call `test.skip()` rather than failing hard — this prevents CI failures in environments without full Azure infra.

2. **Graceful degradation**: Tests for Foundry-dependent paths (SSE, chat threads) check the response code first and skip if the service returns non-202. This is consistent with the arc-mcp-server.spec.ts pattern.

3. **HITL Graph API optional**: Teams card verification via Microsoft Graph API is gated on `E2E_GRAPH_CLIENT_ID`. The `@azure/msal-node` import is dynamic so it doesn't break tests that don't use it.

4. **RBAC positive + negative**: E2E-004 covers both the positive path (all 6 domains accepted with 202/503/200) and the negative path (invalid domain returns 422 from Pydantic regex validation).

5. **SSE sequence verification**: The SSE reconnect test verifies monotonicity and uniqueness of numeric event IDs. It handles the case where events don't have numeric IDs (e.g., UUID-based IDs) by skipping the ordering check.

## Commit Hash

See `git log --oneline -1` after commit.
