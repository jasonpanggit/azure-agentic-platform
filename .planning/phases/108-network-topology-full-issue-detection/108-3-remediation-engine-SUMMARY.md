---
plan: "108-3"
title: "Remediation Engine — One-Click Fix + HITL Approval"
status: "complete"
commit: "ce371106b860b77078d9dfa6ce0e07f111baed40"
---

# Summary: Plan 108-3 — Remediation Engine

## What Was Done

All tasks completed and delivered in commit `ce37110`.

### Task 3.1 — `network_remediation.py` Module ✅
- `SAFE_NETWORK_ACTIONS` dict maps auto-fixable issue types to handler functions:
  - `firewall_threatintel_off` → enable threat intelligence mode via ARM PATCH
  - `pe_not_approved` → approve pending private endpoint connection
- `execute_safe_fix(issue_id, subscription_id, ...)` — runs the fix, returns structured result
- `propose_remediation(issue, ...)` — returns structured remediation proposal for HITL flow
- 361 lines; all functions fully typed

### Task 3.2 — POST `/api/v1/network-topology/remediate` Endpoint ✅
- Request body: `{ issue_id, issue_type, subscription_id, auto_fix_available }`
- If `auto_fix_available=true`: calls `execute_safe_fix()` directly, returns result
- If `auto_fix_available=false`: creates Cosmos approval record (HITL), returns `approval_id`
- Returns: `{ status, message, action_taken, approval_id? }`

### Task 3.3 — Next.js Proxy Route ✅
- `services/web-ui/app/api/proxy/network/topology/remediate/route.ts`
- POST handler: forwards to API gateway with 15s timeout
- `buildUpstreamHeaders(request)` + `getApiGatewayUrl()` pattern

### Task 3.4 — Unit Tests ✅
- `services/api-gateway/tests/test_network_remediation.py` — 393 lines
- Tests cover: safe fix execution, HITL proposal, unknown issue type, ARM API errors
- All tests pass

### Task 3.5 — Frontend "Fix Now" / "Request Approval" Wired ✅
- `IssueCard` "Fix Now" button calls `POST /api/proxy/network/topology/remediate`
- Success: shows inline "Fixed ✓" state + disables button
- HITL: shows "Approval requested — check Approvals tab"
- Error: inline error message with retry

## Files Created

- `services/api-gateway/network_remediation.py` — remediation engine
- `services/api-gateway/tests/test_network_remediation.py` — 393-line test suite
- `services/web-ui/app/api/proxy/network/topology/remediate/route.ts` — proxy route

## Files Modified

- `services/api-gateway/network_topology_endpoints.py` — added `/remediate` endpoint
- `services/api-gateway/requirements.txt` — no new deps (uses existing azure-mgmt-network)
- `services/web-ui/components/NetworkTopologyTab.tsx` — Fix Now / Request Approval wired
