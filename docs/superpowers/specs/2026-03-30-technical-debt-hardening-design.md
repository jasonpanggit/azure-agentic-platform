# Design Spec: Milestone v1.1 — Technical Debt & Hardening

**Date:** 2026-03-30
**Status:** Approved
**Milestone:** v1.1
**Source:** `.planning/codebase/CONCERNS.md`
**Approach:** One milestone, 4 sequential phases (Security → Reliability → Dependency Hygiene → Test Debt)

---

## Overview

This milestone closes all code-fixable gaps identified in the CONCERNS.md codebase audit. It does not touch operator-only Azure config (RBAC assignments, Bot registration, OTel rebuild) — those remain in BACKLOG.md. It does not address architectural constraints outside v1.0 scope (Foundry private networking, `botbuilder` SDK migration, detection plane enablement).

**Out of scope:**
- Operator-only Azure config (BACKLOG.md F-01 through F-11, OTel rebuild)
- Architectural migration (`botbuilder` → new Teams SDK)
- Detection plane enablement (`enable_fabric_data_plane = true`)
- Architecture diagram / conventions documentation
- Plaintext `credentials.tfvars` rotation (operator action — rotate + delete file)

---

## Phase 11: Security Hardening

**Goal:** Eliminate live security gaps — auth tokens not forwarded, rate limiter unused, hardcoded URLs, CORS-adjacent brittle config.

### 11-01: Wire Rate Limiter on API Gateway

**Source:** CONCERNS 1.5
**Files:** `services/api-gateway/main.py`, `services/api-gateway/rate_limiter.py`

The `RateLimiter` class and singleton `rate_limiter` are fully implemented but never imported or applied. Wire as a FastAPI `Depends()` on the two highest-risk endpoints.

**Changes:**
- Import `rate_limiter` in `main.py`
- Add `Depends(rate_limiter.check)` to `/api/v1/chat` router (limit: 10 req/min per client IP)
- Add `Depends(rate_limiter.check)` to `/api/v1/incidents` router (limit: 30 req/min per client IP)
- Return HTTP 429 with `{"detail": "Rate limit exceeded", "retry_after": N}` on breach
- Add unit tests: verify 429 on 11th request within window; verify 200 resets after window

**Success criteria:**
- `GET /api/v1/chat` returns 429 after exceeding rate limit in test
- `GET /api/v1/incidents` returns 429 after exceeding rate limit in test
- Existing gateway tests continue to pass

---

### 11-02: Web UI Proxy Routes Forward MSAL Auth Token

**Source:** CONCERNS 1.3
**Files:**
- `services/web-ui/app/api/proxy/chat/route.ts`
- `services/web-ui/app/api/proxy/chat/result/route.ts`
- `services/web-ui/app/api/proxy/incidents/route.ts`
- `services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts`
- `services/web-ui/app/api/proxy/approvals/[approvalId]/reject/route.ts`

All 5 proxy route handlers call the API gateway without forwarding the user's MSAL bearer token. When `API_GATEWAY_AUTH_MODE=disabled` is eventually removed from prod, all web UI calls will break.

**Changes:**
- Add `NEXT_PUBLIC_API_GATEWAY_SCOPE` env var (e.g. `api://<client-id>/.default`)
- Each route handler reads the incoming `Authorization` header from the Next.js request and forwards it to the upstream gateway call
- If `Authorization` header is absent (e.g. dev mode with `NEXT_PUBLIC_DEV_MODE=true`), fall through without header (preserves dev-mode compatibility)
- Update `.env.example` with `NEXT_PUBLIC_API_GATEWAY_SCOPE=api://<gateway-client-id>/.default`
- Add unit tests for each proxy route: mock incoming request with `Authorization: Bearer test-token`, assert upstream fetch includes same header

**Success criteria:**
- All 5 proxy routes forward `Authorization` header when present on the incoming request
- Dev mode (no auth header) still works without error
- Tests pass for all 5 routes

---

### 11-03: Remove Hardcoded Prod URL Fallbacks

**Source:** CONCERNS 2.1
**Files:** Same 5 proxy route files as 11-02

All 5 routes have:
```typescript
const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL ||
  'https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io';
```

A developer without `API_GATEWAY_URL` set silently targets production.

**Changes:**
- Remove the hardcoded prod URL fallback string from all 5 files
- In non-dev environments (`NEXT_PUBLIC_DEV_MODE !== 'true'`), throw `Error('API_GATEWAY_URL is not configured')` if env var is absent
- In dev mode, fall back to `http://localhost:8000` (the correct local default)
- Update `.env.example`: document `API_GATEWAY_URL=http://localhost:8000`

**Success criteria:**
- `API_GATEWAY_URL` unset in production mode throws at startup
- Dev mode defaults to `localhost:8000`
- No prod URL appears anywhere in source code

---

### 11-04: Fix SSE Route Internal Poll URL

**Source:** CONCERNS 2.2
**File:** `services/web-ui/app/api/stream/route.ts`

The SSE streaming route polls `http://localhost:3000/api/proxy/chat/result` — hardcoded hostname and port. In Container Apps the port is 3000, but this is still brittle.

**Changes:**
- Replace `http://localhost:3000/api/proxy/chat/result?...` with `/api/proxy/chat/result?...` (relative URL)
- Next.js server-side `fetch` resolves relative URLs against the server's own base URL automatically

**Success criteria:**
- SSE route no longer contains `localhost:3000`
- Existing SSE integration tests pass

---

### 11-05: Fix Arc MCP E2E Hardcoded URL

**Source:** CONCERNS 2.3, BACKLOG F-06
**File:** `e2e/arc-mcp-server.spec.ts`

5 of 8 Arc MCP E2E tests fail in every non-local environment because `ARC_MCP_URL` is hardcoded to `localhost:8080`.

**Changes:**
```typescript
const ARC_MCP_URL = process.env.E2E_ARC_MCP_URL || 'http://localhost:8080';
```
- Document `E2E_ARC_MCP_URL` in `e2e/README.md` (or `.env.example`)
- **Closes BACKLOG F-06**

**Success criteria:**
- `E2E_ARC_MCP_URL` env var controls the Arc MCP target
- BACKLOG item F-06 marked resolved

---

## Phase 12: Reliability Hardening

**Goal:** Fix correctness gaps that silently mask failures — health endpoint that always returns OK, 500s that should be 404s, missing env vars, connection pool exhaustion.

### 12-01: Implement `/health/ready` Endpoint

**Source:** CONCERNS 5.1
**File:** `services/api-gateway/main.py` (new route), `services/api-gateway/health.py` (new module)

The existing `/health` returns `{"status": "ok"}` unconditionally. The Phase 8 chat failure was masked for weeks because the health check never caught missing config.

**Changes:**
- New `GET /health/ready` route in a dedicated `health.py` module
- Checks (all must pass for 200):
  1. `ORCHESTRATOR_AGENT_ID` env var is set and non-empty
  2. `CosmosClient` can be constructed (validates `COSMOS_ENDPOINT` set)
  3. `AzureAIProjectsClient` can be constructed (validates `AZURE_AI_PROJECT_ENDPOINT` set)
- Returns `{"status": "ready", "checks": {"orchestrator_agent_id": true, "cosmos": true, "foundry": true}}` on success (HTTP 200)
- Returns `{"status": "not_ready", "checks": {"orchestrator_agent_id": false, ...}}` on failure (HTTP 503)
- Existing `/health` endpoint preserved for backwards compatibility (liveness)
- Unit tests: verify 503 with correct check key when each env var is missing

**Success criteria:**
- `GET /health/ready` returns 503 when `ORCHESTRATOR_AGENT_ID` is unset
- `GET /health/ready` returns 200 when all three deps are configured
- `GET /health` still returns 200 (liveness unchanged)

---

### 12-02: Fix Approvals 500 → 404

**Source:** CONCERNS 5.7, BACKLOG F-07
**File:** `services/api-gateway/approvals.py`

`GET /api/v1/approvals/{approval_id}/approve` (and `/reject`) raise an unhandled exception when the approval record doesn't exist, returning HTTP 500.

**Changes:**
- In both `approve` and `reject` handlers: fetch the record first; if `None`, return `JSONResponse({"detail": "Approval not found"}, status_code=404)` before any further processing
- Add unit tests: `test_approve_missing_returns_404`, `test_reject_missing_returns_404`
- **Closes BACKLOG F-07**

**Success criteria:**
- `POST /api/v1/approvals/nonexistent-id/approve` returns 404
- `POST /api/v1/approvals/nonexistent-id/reject` returns 404
- Existing approval tests continue to pass

---

### 12-03: Add `AGENT_ENTRA_ID` to Terraform Agent Apps Module

**Source:** CONCERNS 3.6
**File:** `terraform/modules/agent-apps/main.tf`

`agents/shared/auth.py` reads `AGENT_ENTRA_ID` and raises `ValueError` if missing. The env var is documented as set from the Container App's system-assigned identity `principal_id`, but it is never injected in the Terraform module.

**Changes:**
- In `terraform/modules/agent-apps/main.tf`, add to the dynamic `env` block:
  ```hcl
  {
    name  = "AGENT_ENTRA_ID"
    value = azurerm_container_app.agent.identity[0].principal_id
  }
  ```
- This references the Container App resource's own identity, which is available post-creation
- Add output `agent_entra_id` to module outputs for traceability

**Success criteria:**
- `terraform plan` shows `AGENT_ENTRA_ID` env var on all agent Container Apps
- `terraform apply` completes without error
- `agents/shared/auth.py` no longer raises `ValueError` when `get_agent_identity()` is called

---

### 12-04: Cache `DefaultAzureCredential` and `CosmosClient` as Module Singletons

**Source:** CONCERNS 4.4
**Files:**
- `services/api-gateway/approvals.py`
- `services/api-gateway/incidents_list.py`
- `services/api-gateway/dedup_integration.py`
- `services/api-gateway/audit.py`
- `services/api-gateway/foundry.py`

Each request currently creates fresh `DefaultAzureCredential()` and `CosmosClient()` instances. This causes IMDS HTTP calls per request and Cosmos TCP connection exhaustion under load.

**Pattern** (from `agents/shared/auth.py` which already does this correctly):
```python
# Module level — created once per process
_credential: DefaultAzureCredential | None = None
_cosmos_client: CosmosClient | None = None

def get_credential() -> DefaultAzureCredential:
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential

def get_cosmos_client() -> CosmosClient:
    global _cosmos_client
    if _cosmos_client is None:
        _cosmos_client = CosmosClient(
            url=os.environ["COSMOS_ENDPOINT"],
            credential=get_credential()
        )
    return _cosmos_client
```

**Changes:**
- Extract shared `_get_credential()` and `_get_cosmos_client()` helpers into `services/api-gateway/dependencies.py` (new module)
- Replace per-request instantiation in all 5 files with calls to these helpers
- Update tests: inject mock clients via module-level patching instead of per-request patching

**Success criteria:**
- `DefaultAzureCredential` instantiated once per process (verified via mock call count in tests)
- `CosmosClient` instantiated once per process
- All existing gateway tests pass

---

## Phase 13: Dependency Hygiene

**Goal:** Eliminate unpinned dependency versions that can silently break builds.

### 13-01: Pin `azure-ai-agentserver-agentframework`

**Source:** CONCERNS 6.3
**File:** `agents/requirements-base.txt`

Currently `azure-ai-agentserver-agentframework` has no version specifier — every Docker build installs the latest available version.

**Changes:**
- Determine current installed version (read from base image build log or install and inspect)
- Pin in `requirements-base.txt`: `azure-ai-agentserver-agentframework==<current-version>`
- Add comment: `# Pinned — verify against agent-framework RC version before upgrading`

**Success criteria:**
- `requirements-base.txt` line has explicit version pin
- `pip install -r requirements-base.txt` installs deterministic version

---

### 13-02: Single Source of Truth for `@azure/mcp` Version

**Source:** CONCERNS 8.2
**Files:** `services/azure-mcp-server/Dockerfile`, `scripts/deploy-azure-mcp-server.sh`

Version `2.0.0-beta.34` is duplicated in two places. They can drift silently.

**Changes:**
- `services/azure-mcp-server/Dockerfile`: already has `ARG AZURE_MCP_VERSION=2.0.0-beta.34` — this is the source of truth
- `scripts/deploy-azure-mcp-server.sh`: replace hardcoded version with:
  ```bash
  AZURE_MCP_VERSION=$(grep 'ARG AZURE_MCP_VERSION=' services/azure-mcp-server/Dockerfile | cut -d= -f2)
  ```
- Add `echo "Using @azure/mcp version: $AZURE_MCP_VERSION"` for visibility

**Success criteria:**
- `scripts/deploy-azure-mcp-server.sh` reads version from Dockerfile
- Changing version in Dockerfile automatically propagates to deploy script
- No hardcoded version string in the deploy script

---

### 13-03: CI Build Version Logging

**Source:** CONCERNS 6.3 (observability of pinned versions)
**File:** `.github/workflows/base-image.yml`

After the base image build completes, there is no record of which package versions were installed.

**Changes:**
- Add a post-build step to `base-image.yml` after the Docker build:
  ```yaml
  - name: Log installed agent package versions
    run: |
      docker run --rm ${{ vars.ACR_LOGIN_SERVER }}/agents/base:${{ github.sha }} \
        pip show agent-framework azure-ai-agentserver-agentframework azure-ai-projects \
        >> "$GITHUB_STEP_SUMMARY"
  ```

**Success criteria:**
- GitHub Actions job summary shows installed package versions after each base image build

---

## Phase 14: Test Debt Cleanup

**Goal:** Restore CI signal by implementing the tests that matter and cleanly marking those that genuinely require live infrastructure.

### 14-01: Implement SSE Heartbeat Tests

**Source:** CONCERNS 3.3
**File:** `services/api-gateway/tests/test_sse_heartbeat.py`

Two tests skipped since Plan 05-02:
- `test_heartbeat_sent_every_20_seconds`
- `test_heartbeat_prevents_container_app_timeout`

**Changes:**
- Use `pytest-asyncio` + `httpx.AsyncClient` to open SSE stream in test
- Mock the Foundry polling loop to not resolve (simulates long-running request)
- Assert that a `: heartbeat` SSE comment event is received within 25 seconds
- Second test: assert that events continue arriving at 20s intervals for 45s total
- Remove `@pytest.mark.skip`

**Success criteria:**
- Both heartbeat tests pass in CI without Azure credentials
- `pytest services/api-gateway/tests/test_sse_heartbeat.py` exits 0

---

### 14-02: Replace Web UI Placeholder Tests

**Source:** CONCERNS 3.4
**Files:** `services/web-ui/__tests__/layout.test.tsx`, `services/web-ui/__tests__/auth.test.tsx`

All 7 tests are empty `// TODO: Plan 05-01` bodies.

**Changes:**
- Delete `layout.test.tsx` and `auth.test.tsx` (empty stubs provide no value)
- Create `services/web-ui/__tests__/ChatPanel.test.tsx`:
  - Renders `ChatPanel` with mock messages prop — asserts messages appear in DOM
  - Types in input, presses Enter — asserts `onSend` callback fired with message text
  - Empty input does not trigger `onSend`
- Create `services/web-ui/__tests__/useAuth.test.tsx`:
  - When `NEXT_PUBLIC_DEV_MODE=true`, hook returns a dev user object
  - When `NEXT_PUBLIC_DEV_MODE=false` and no MSAL account, returns `null`

**Success criteria:**
- `npm test` has no TODO/empty tests
- `ChatPanel` and `useAuth` have meaningful coverage
- Web UI test suite passes in CI

---

### 14-03: Restore Teams Bot CI Signal

**Source:** CONCERNS 3.2
**File:** `services/teams-bot/src/__tests__/integration/teams-e2e-stubs.test.ts`

All 6 TEAMS-001–006 tests are inside `describe.skip(...)`. CI never catches Teams bot regressions.

**Changes:**
- Remove outer `describe.skip`
- Replace each stub body with an endpoint reachability assertion using a local `supertest` instance:
  - `GET /health` → expect 200
  - `POST /api/messages` → expect 200 or 401 (not 404/500)
- Full Teams round-trip stubs (requiring live Teams environment) stay as inner `it.skip(reason="requires live Teams environment: TEAMS-XXX")` with explicit reason
- Add `supertest` as dev dependency if not already present

**Success criteria:**
- `npm test` runs 6 reachability checks (not skipped)
- Each test verifies endpoint exists and responds
- Full integration stubs clearly marked with `requires live Teams environment`

---

### 14-04: Detection Plane Integration Test Hygiene

**Source:** CONCERNS 3.1
**Files:** `services/detection-plane/tests/integration/`

5 integration test files, all `pass` bodies with `# TODO` comments.

**Changes:**
- `test_pipeline_flow.py`: implement using existing mock patterns from unit tests
  - Mock Cosmos write → call `classify_domain()` → assert correct domain classification
  - Mock `AzureEventHubProducerClient` → assert event is sent with correct schema
- `test_round_trip.py`: inject a mock alert payload → verify `map_detection_result_to_payload()` produces valid `IncidentPayload` with all required fields
- `test_dedup_load.py`, `test_activity_log.py`, `test_state_sync.py`: replace `pass` with:
  ```python
  pytest.skip("requires Fabric deployment — enable when enable_fabric_data_plane=true")
  ```
  (explicit condition, not vague TODO)

**Success criteria:**
- `test_pipeline_flow.py` and `test_round_trip.py` pass without Azure credentials
- 3 remaining files have explicit `pytest.skip` with infra condition (not `pass`)
- Detection-plane unit coverage stays ≥ 80%

---

## Traceability Matrix

| Phase | Task | CONCERNS.md | BACKLOG.md |
|-------|------|-------------|------------|
| 11 | 11-01 | 1.5 | — |
| 11 | 11-02 | 1.3 | — |
| 11 | 11-03 | 2.1 | — |
| 11 | 11-04 | 2.2 | — |
| 11 | 11-05 | 2.3 | F-06 ✓ closes |
| 12 | 12-01 | 5.1 | — |
| 12 | 12-02 | 5.7 | F-07 ✓ closes |
| 12 | 12-03 | 3.6 | — |
| 12 | 12-04 | 4.4 | — |
| 13 | 13-01 | 6.3 | — |
| 13 | 13-02 | 8.2 | — |
| 13 | 13-03 | 6.3 | — |
| 14 | 14-01 | 3.3 | — |
| 14 | 14-02 | 3.4 | — |
| 14 | 14-03 | 3.2 | — |
| 14 | 14-04 | 3.1 | — |

**BACKLOG items closed by this milestone:** F-06, F-07
**BACKLOG items remaining (operator-only):** F-01, F-02, F-03, F-04, F-05, F-08, F-09, F-10, F-11, OTel rebuild

---

## Not In Scope (Deferred)

| CONCERNS item | Reason deferred |
|---------------|-----------------|
| 1.1 Plaintext `credentials.tfvars` | Operator action — rotate credentials, delete file |
| 1.2 Azure MCP auth disabled | Operator action — re-deploy with Entra auth enabled |
| 1.4 CORS wildcard | Operator action — `az containerapp update` (BACKLOG F-03) |
| 1.6 Dev-mode auth in prod | Resolved when operator sets `AZURE_CLIENT_ID` (BACKLOG F-01 dependency) |
| 4.1 Foundry no private networking | Architectural constraint, not fixable in code |
| 4.3 Legacy `botbuilder` SDK | Migration to new Teams SDK is a full milestone, not hardening |
| 4.5 In-memory Teams state | Cosmos persistence is a feature addition, not debt cleanup |
| 4.7 Detection plane disabled | Enablement requires operator Fabric config |
| 7.1 `sys.path` manipulation | Low risk, deferred to refactor milestone |
| 7.2 `console.log` logging | Deferred to Teams bot refactor milestone |
| 9.x Documentation gaps | Separate documentation milestone |
