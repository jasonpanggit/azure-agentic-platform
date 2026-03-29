# Phase 8: Validation Report

**Date:** 2026-03-29
**Environment:** prod (rg-aap-prod)
**Subscription:** 4c727b88-12f4-4c91-9c2b-372aab3bbae9
**E2E Runner:** Local (no CI secrets); dev-mode auth (`Bearer dev-token`)
**API Gateway:** https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io
**Web UI:** https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io

---

## Severity Schema

- **BLOCKING** — Platform cannot function; Phase 8 cannot close until resolved
- **DEGRADED** — Feature broken but platform operates; logged as backlog todo
- **COSMETIC** — Minor issue; logged as backlog todo

---

## Provisioning Fix Results

Status as of 260329-qro quick task validation:

| ID | Fix | Status |
|----|-----|--------|
| P-01 | Create Foundry Orchestrator Agent | FIXED — `asst_NeBVjCA5isNrIERoGYzRpBTu` |
| P-02 | Set ORCHESTRATOR_AGENT_ID on ca-api-gateway-prod | FIXED — env var set, chat returns 202 |
| P-03 | Grant Azure AI Developer RBAC | OPEN — MI `69e05934-...` missing role on Foundry |
| P-04 | Lock CORS_ALLOWED_ORIGINS | OPEN — still `*` wildcard |
| P-05 | Register Azure Bot Service | OPEN — bot not registered |
| P-06 | Add 3 GitHub secrets (E2E_CLIENT_ID, E2E_CLIENT_SECRET, E2E_API_AUDIENCE) | OPEN |

---

## E2E Test Results

Run command:
```bash
E2E_BASE_URL=https://ca-web-ui-prod... E2E_API_URL=https://ca-api-gateway-prod... \
  npx playwright test --project=e2e-chromium
```

Total: 30 tests — **22 passed**, **8 failed**

### Phase 8 Target Tests (E2E-002 through E2E-005, AUDIT-006)

| ID | Test | File | Result | Notes |
|----|------|------|--------|-------|
| E-01 | E2E-002: Synthetic incident creates thread and dispatches to agent | e2e-incident-flow.spec.ts | **FAIL** | Triage polling timed out at 90s — `/api/v1/threads/{id}/status` not found; exception handling routes to `triageCompleted=true` branch but poll never returns true. RBAC issue on Foundry likely cause. |
| E-02 | E2E-002: Incidents list returns recently created incident | e2e-incident-flow.spec.ts | **PASS** | POST /api/v1/incidents returns 202, list returns array |
| E-03 | E2E-002: SSE stream delivers events for active thread | e2e-incident-flow.spec.ts | **PASS** | Chat 202, SSE stream connects |
| E-04 | E2E-003: List pending approvals returns valid response | e2e-hitl-approval.spec.ts | **PASS** | Returns empty array — no pending approvals |
| E-05 | E2E-003: Approve endpoint accepts valid approval | e2e-hitl-approval.spec.ts | **PASS** | Vacuous pass (no pending approvals) |
| E-06 | E2E-003: Reject endpoint returns valid response | e2e-hitl-approval.spec.ts | **PASS** | Vacuous pass (no pending approvals) |
| E-07 | E2E-003: Teams card verification via Graph API | e2e-hitl-approval.spec.ts | **PASS** | Deferred — Graph API creds not configured |
| E-08 | E2E-004: Cross-Subscription RBAC — domain routing | e2e-rbac.spec.ts | **PASS** | All 6 domains accept incidents |
| E-09 | E2E-004: Domain validation rejects invalid domain | e2e-rbac.spec.ts | **PASS** | |
| E-10 | E2E-004: Health endpoint accessible | e2e-rbac.spec.ts | **PASS** | |
| E-11 | E2E-004: Unauthenticated requests rejected | e2e-rbac.spec.ts | **PASS** | |
| E-12 | E2E-005: SSE stream delivers events with sequence IDs | e2e-sse-reconnect.spec.ts | **FAIL** | `response.ok` is the boolean property from browser Fetch API — evaluated as `false` when SSE stream not available at time of test. Auth dev-token may not trigger SSE. |
| E-13 | E2E-005: Heartbeat keeps SSE connection alive | e2e-sse-reconnect.spec.ts | **PASS** | Stream connects within 25s |
| E-14 | AUDIT-006: Export endpoint returns structured report | e2e-audit-export.spec.ts | **PASS** | |
| E-15 | AUDIT-006: Export requires authentication | e2e-audit-export.spec.ts | **PASS** | |

### Other Tests (arc-mcp-server.spec.ts, sc*.spec.ts)

| ID | Test | File | Result | Notes |
|----|------|------|--------|-------|
| E-16 | E2E-006: arc_servers_list pagination | arc-mcp-server.spec.ts | **FAIL** | Connects to localhost:8080 — Arc MCP mock server not running locally |
| E-17 | E2E-006: arc_k8s_list pagination | arc-mcp-server.spec.ts | **FAIL** | Same — localhost:8080 |
| E-18 | E2E-006: Arc Agent triage | arc-mcp-server.spec.ts | **FAIL** | Connects to localhost:8000 — local dev mode only |
| E-19 | E2E-006: Arc MCP health check | arc-mcp-server.spec.ts | **FAIL** | Connects to localhost:8080 |
| E-20 | E2E-006: Arc MCP tools exposed | arc-mcp-server.spec.ts | **FAIL** | Connects to localhost:8080 |
| E-21 | sc1: Web UI FMP under 2s | sc1.spec.ts | **PASS** | |
| E-22 | sc1: Health endpoint | sc1.spec.ts | **PASS** | |
| E-23 | sc1: Chat accepts message | sc1.spec.ts | **PASS** | |
| E-24 | sc2: SSE content-type | sc2.spec.ts | **PASS** | |
| E-25 | sc2: Heartbeat events | sc2.spec.ts | **PASS** | |
| E-26 | sc5: Expired approval returns 410 | sc5.spec.ts | **FAIL** | Returns 500 for non-existent approval; test expects [400, 404, 410] |
| E-27 | sc5: List pending approvals | sc5.spec.ts | **PASS** | |
| E-28 | sc6: GitOps detection | sc6.spec.ts | **PASS** | |
| E-29 | sc6: Arc K8s list | sc6.spec.ts | **PASS** | |
| E-30 | sc6: Flux gitops_status | sc6.spec.ts | **PASS** | |

---

## Smoke Test Results

Run against prod endpoints with dev-mode auth (`Bearer dev-token`):

| ID | Service | Test | Expected | Actual | Pass? |
|----|---------|------|----------|--------|-------|
| S-01 | API Gateway | GET /health | 200 | 200 | ✅ PASS |
| S-02 | Web UI | GET / | 200 | 200 | ✅ PASS |
| S-03 | API Gateway | GET /api/v1/incidents | 200 | 200 | ✅ PASS |
| S-04 | API Gateway | GET /api/v1/runbooks/search | 200 | 500 | ❌ FAIL |
| S-05 | API Gateway | GET /api/v1/audit | 200 | 200 | ✅ PASS |
| S-06 | API Gateway | GET /api/v1/approvals | 200 | 200 | ✅ PASS |
| S-07 | API Gateway | POST /api/v1/chat | 202 | 202 | ✅ PASS |

**Smoke test detail:**
- S-04 failure: `GET /api/v1/runbooks/search?query=high+cpu` → `500 Internal Server Error` with body `Internal Server Error`. Root cause: PostgreSQL pgvector connection failure (prod runbooks not seeded; likely `PGVECTOR_CONNECTION_STRING` env var missing or PostgreSQL not reachable from prod Container App). Server logs required for full diagnosis.

---

## Findings

| ID | Service | Description | Severity | Fix | Status |
|----|---------|-------------|----------|-----|--------|
| F-01 | Foundry / API Gateway | Foundry RBAC incomplete — MI `69e05934-1feb-44d4-8fd2-30373f83ccec` missing `Azure AI Developer` role on Foundry account. Orchestrator agent created and ORCHESTRATOR_AGENT_ID set but gateway cannot call Foundry due to 403. Causes E2E-002 triage timeout. | BLOCKING | `az role assignment create --assignee 69e05934-... --role "Azure AI Developer" --scope /subscriptions/4c727b88-.../resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/foundry-aap-prod` | OPEN |
| F-02 | API Gateway / Runbook RAG | `GET /api/v1/runbooks/search` returns 500. PostgreSQL pgvector search fails — either env var `PGVECTOR_CONNECTION_STRING` not set on prod Container App, or prod runbooks not seeded. | BLOCKING | 1. Verify `PGVECTOR_CONNECTION_STRING` env var on `ca-api-gateway-prod`. 2. Run `scripts/seed-runbooks/seed.py` against prod PostgreSQL. | OPEN |
| F-03 | API Gateway | CORS policy still uses wildcard `*` on prod. Locked-origin CORS was planned (P-04); security risk if web UI credential-bearing requests go cross-origin. | DEGRADED | `az containerapp update --name ca-api-gateway-prod ... --set-env-vars "CORS_ALLOWED_ORIGINS=https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"` | OPEN |
| F-04 | Teams Bot | Bot Service not registered in Azure. Teams integration cannot receive proactive alerts or handle user messages until bot app registration is complete. Chat via web UI is unaffected. | DEGRADED | Complete steps in `MANUAL-SETUP.md` section "Teams Bot Registration": create bot channel registration, set messaging endpoint, configure bot credentials. | OPEN |
| F-05 | CI / E2E | GitHub secrets `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_API_AUDIENCE` not configured. E2E CI runs in dev-mode auth, cannot validate Entra-protected endpoints. | DEGRADED | Add secrets to GitHub Actions environment `staging` via repository settings. Values from the service principal used in `configure-orchestrator.py`. | OPEN |
| F-06 | Arc MCP Server / E2E | `arc-mcp-server.spec.ts` hardcodes `localhost:8080` as Arc MCP URL — tests fail in prod because they need `E2E_ARC_MCP_URL` env var pointing to `ca-arc-mcp-server-prod`. | DEGRADED | Update `arc-mcp-server.spec.ts` to read `process.env.E2E_ARC_MCP_URL \|\| 'http://localhost:8080'` and add `E2E_ARC_MCP_URL` to prod E2E env. | OPEN |
| F-07 | API Gateway | `sc5.spec.ts` approval 410-expired test: non-existent approval_id returns 500 instead of 404/410. `approvals.py` `GET /api/v1/approvals/{id}/approve` raises unhandled exception for missing records. | DEGRADED | Add 404 handler in `approvals.py` for approval not found case: return `JSONResponse({"detail": "Approval not found"}, status_code=404)`. | OPEN |
| F-08 | SSE Reconnect E2E | `e2e-sse-reconnect.spec.ts` test "SSE stream delivers events with sequence IDs" fails because `response.ok` (the boolean Fetch API property, not a method) evaluates to false in the test context. The dev-mode auth token does not trigger real SSE events — stream likely returns an error body. | DEGRADED | Test needs a real Foundry RBAC fix (F-01) to generate real SSE events, OR the test needs a local SSE mock for dev-mode. Also investigate if `response.ok` returns false because the stream redirects or auth is rejected at SSE level. | OPEN |

---

## Summary

- **BLOCKING:** 2 findings (F-01 Foundry RBAC, F-02 Runbook search 500)
- **DEGRADED:** 6 findings (F-03 CORS, F-04 Teams bot, F-05 CI secrets, F-06 Arc MCP E2E URL, F-07 approval 404, F-08 SSE E2E)
- **COSMETIC:** 0 findings
- **Overall:** **FAIL** (PASS requires 0 BLOCKING findings)

### Critical Path Status

| Flow | Status |
|------|--------|
| Web UI loads | ✅ PASS |
| Chat → 202 | ✅ PASS |
| Incident POST → 202 | ✅ PASS |
| Foundry agent dispatch | ❌ FAIL (F-01 RBAC) |
| HITL approvals | ✅ PASS (vacuous — no pending) |
| Teams alerts | ❌ NOT TESTED (F-04 bot unregistered) |
| Runbook RAG | ❌ FAIL (F-02 pgvector 500) |
| Audit export | ✅ PASS |
| SSE streaming | ⚠️ PARTIAL (heartbeat passes; event stream fails with dev-mode auth) |

### Required Before Phase 8 Close

1. **F-01**: Grant `Azure AI Developer` RBAC to gateway MI — unblocks Foundry dispatch, agent triage, and SSE event generation
2. **F-02**: Fix runbook search — verify PGVECTOR_CONNECTION_STRING + seed prod runbooks

All DEGRADED findings (F-03 through F-08) logged as backlog todos and do not block Phase 8 completion.
