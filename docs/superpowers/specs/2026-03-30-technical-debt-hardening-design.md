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

> **Implementation note (B-01):** The existing `RateLimiter.check(agent_name, subscription_id)` is a per-agent *remediation* guard (REMEDI-006), not an HTTP rate limiter. It cannot be wired as a FastAPI `Depends()` as-is. The implementation must add a new HTTP-oriented rate-limiting layer alongside the existing class rather than repurposing it.

The `rate_limiter.py` module exists but is never applied to HTTP endpoints. Add a per-IP HTTP rate limiter using FastAPI middleware or a `slowapi`-style dependency.

**Changes:**
- Inspect the actual `RateLimiter` class signature in `rate_limiter.py` before writing any code
- If `RateLimiter` is remediation-scoped only: add a separate `http_rate_limiter.py` module using `slowapi` (wraps `limits` library) or a simple in-memory `collections.defaultdict` + `time` approach for per-IP limiting
- Wire as FastAPI middleware or a new `Depends(check_http_rate_limit)` dependency that extracts client IP from `Request.client.host`
- Apply to `/api/v1/chat` (limit: 10 req/min) and `/api/v1/incidents` (limit: 30 req/min)
- Return HTTP 429 with `{"detail": "Rate limit exceeded", "retry_after": N}` on breach
- Unit tests: mock client IP, assert 429 on 11th request within window; assert 200 after window resets
- Do NOT modify the existing `RateLimiter.check()` signature — it is used by agent remediation paths

**Success criteria:**
- `/api/v1/chat` returns 429 after exceeding rate limit in unit test (no Azure credentials needed)
- `/api/v1/incidents` returns 429 after exceeding rate limit in unit test
- Existing gateway tests (including remediation paths) continue to pass
- Existing `RateLimiter` class is unchanged

---

### 11-02: Web UI Proxy Routes Forward Auth Token (Pass-Through)

**Source:** CONCERNS 1.3
**Files:**
- `services/web-ui/app/api/proxy/chat/route.ts`
- `services/web-ui/app/api/proxy/chat/result/route.ts`
- `services/web-ui/app/api/proxy/incidents/route.ts`
- `services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts`
- `services/web-ui/app/api/proxy/approvals/[approvalId]/reject/route.ts`

All 5 proxy route handlers call the API gateway without forwarding the user's auth token. When `API_GATEWAY_AUTH_MODE=disabled` is eventually removed from prod, all web UI calls will break.

> **Implementation note (W-01):** Server-side Next.js route handlers cannot use MSAL's browser `acquireTokenSilent`. The correct approach is a **pass-through**: read the `Authorization` header from the *incoming* Next.js request (sent by the browser after client-side MSAL acquisition) and forward it to the upstream gateway call. The browser is responsible for acquiring and attaching the token using `NEXT_PUBLIC_API_GATEWAY_SCOPE`; the server proxy just forwards it. Invalid or expired tokens are forwarded as-is — the API gateway is responsible for validation. This is safe because the proxy routes are server-to-server calls that never touch the token.

**Changes:**
- Each route handler reads `request.headers.get('Authorization')` from the incoming Next.js `Request`
- If present, adds `Authorization` header to the upstream `fetch()` call to the gateway
- If absent (dev mode, `NEXT_PUBLIC_DEV_MODE=true`), makes the upstream call without an auth header (preserves dev-mode compatibility)
- Add `NEXT_PUBLIC_API_GATEWAY_SCOPE` to `.env.example` with comment explaining the client-side MSAL scope
- 11-02 must be completed before 11-03 (both modify the same 5 files; sequential to avoid merge conflicts)
- Unit tests: mock incoming `Request` with `Authorization: Bearer test-token`; assert upstream `fetch` call includes same header; assert missing header case makes call without Authorization

**Success criteria:**
- All 5 proxy routes forward `Authorization` header when present on the incoming request
- Dev mode (no incoming auth header) still works without error
- Tests pass for all 5 routes confirming header pass-through
- No MSAL server-side token acquisition is introduced

---

### 11-03: Remove Hardcoded Prod URL Fallbacks

**Source:** CONCERNS 2.1
**Files:** Same 5 proxy route files as 11-02
**Dependency:** Must be implemented after 11-02 (same files — sequential to avoid merge conflicts)

All 5 routes have:
```typescript
const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL ||
  'https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io';
```

A developer without `API_GATEWAY_URL` set silently targets production.

> **Implementation note (W-02):** Next.js route handlers are loaded lazily on first request, not at server startup. The failure mode for a missing `API_GATEWAY_URL` is therefore a **500 on first request**, not a startup crash. The success criterion is updated accordingly.

**Changes:**
- Remove the hardcoded prod URL fallback string from all 5 files
- If `API_GATEWAY_URL` is unset and `NEXT_PUBLIC_DEV_MODE !== 'true'`: throw `Error('API_GATEWAY_URL is not configured')` — this produces a 500 on the first request to that route, surfacing the misconfiguration immediately
- In dev mode (`NEXT_PUBLIC_DEV_MODE=true`), fall back to `http://localhost:8000`
- Update `.env.example`: document `API_GATEWAY_URL=http://localhost:8000`

**Success criteria:**
- No prod URL (`wittypebble`) appears anywhere in source code
- Unit test: calling route handler with `API_GATEWAY_URL` unset and `NEXT_PUBLIC_DEV_MODE=false` throws/returns 500
- Dev mode defaults to `localhost:8000` without error

---

### 11-04: Fix SSE Route Internal Poll URL

**Source:** CONCERNS 2.2
**File:** `services/web-ui/app/api/stream/route.ts`

The SSE streaming route polls `http://localhost:3000/api/proxy/chat/result` — hardcoded hostname and port.

> **Implementation note (B-02):** Relative URLs throw `TypeError: Failed to parse URL` in Node.js `fetch`. The correct fix is to use an absolute URL derived from an env var, not a bare relative path. Use `process.env.NEXT_PUBLIC_SITE_URL` (already set in Container Apps as the app's own FQDN) as the base, falling back to `http://localhost:3000` for local dev.

**Changes:**
- Replace `http://localhost:3000/api/proxy/chat/result?...` with:
  ```typescript
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000';
  const resultUrl = `${baseUrl}/api/proxy/chat/result?...`;
  ```
- Add `NEXT_PUBLIC_SITE_URL` to `.env.example` with comment (e.g. `NEXT_PUBLIC_SITE_URL=https://ca-web-ui-prod.xxx.azurecontainerapps.io`)
- The Container Apps deployment already has the FQDN available — wire it as a build arg in `web-ui-build.yml`

**Success criteria:**
- SSE route no longer contains the literal string `localhost:3000`
- `NEXT_PUBLIC_SITE_URL` controls the internal poll base URL
- SSE integration tests pass

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

`POST /api/v1/approvals/{approval_id}/approve` (and `/reject`) return HTTP 500 when the approval record doesn't exist.

> **Implementation note (W-04):** The Cosmos SDK's `container.read_item()` raises `azure.cosmos.exceptions.CosmosResourceNotFoundError` for missing records — it does not return `None`. The fix must catch this exception, not check for a `None` return value.

**Changes:**
- In both `approve` and `reject` handlers: wrap `container.read_item()` call in `try/except CosmosResourceNotFoundError`
- On `CosmosResourceNotFoundError`: return `JSONResponse({"detail": "Approval not found"}, status_code=404)`
- Import `CosmosResourceNotFoundError` from `azure.cosmos.exceptions`
- Unit tests: mock `read_item` to raise `CosmosResourceNotFoundError`; assert response is 404 with correct body
- **Closes BACKLOG F-07**

**Success criteria:**
- `POST /api/v1/approvals/nonexistent-id/approve` returns 404 (not 500)
- `POST /api/v1/approvals/nonexistent-id/reject` returns 404 (not 500)
- Existing approval tests continue to pass

---

### 12-03: Add `AGENT_ENTRA_ID` to Terraform Agent Apps Module

**Source:** CONCERNS 3.6
**File:** `terraform/modules/agent-apps/main.tf`

`agents/shared/auth.py` reads `AGENT_ENTRA_ID` and raises `ValueError` if missing. The env var is documented as set from the Container App's system-assigned identity `principal_id`, but it is never injected in the Terraform module.

> **Implementation note (B-03):** `terraform/modules/agent-apps/main.tf` has `lifecycle { ignore_changes = [template[0].container[0].env, ...] }`. This means new env var entries added to the Terraform template are **silently ignored on `terraform apply`** for existing Container Apps — the plan will show the change but apply will not write it. The implementation must explicitly address this conflict: either remove `env` from `ignore_changes` (risky — allows Terraform to overwrite manually-set env vars) or use `az containerapp update --set-env-vars` as a one-time migration step after the Terraform change, documented as a required operator step. Recommended approach: remove `env` from `ignore_changes` for the `AGENT_ENTRA_ID` block only by restructuring the lifecycle block, then force a redeploy.

**Changes:**
- Inspect `terraform/modules/agent-apps/main.tf` `lifecycle` block before writing any code
- Add `AGENT_ENTRA_ID = azurerm_container_app.agent.identity[0].principal_id` to the dynamic env block
- Remove `template[0].container[0].env` from `lifecycle.ignore_changes` OR document that a `terraform apply -replace` on existing Container Apps is required to actually set the env var
- Add output `agent_entra_id` to module outputs for traceability
- Add a note in the phase plan that this requires a Container App revision cycle to take effect on running apps

**Success criteria:**
- `terraform plan` shows `AGENT_ENTRA_ID` env var diff on agent Container Apps
- After `terraform apply` (or forced replace), `AGENT_ENTRA_ID` is visible in Container App environment variables
- `agents/shared/auth.py` `get_agent_identity()` no longer raises `ValueError` at runtime

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

> **Implementation note (W-05):** A lazy global `if _credential is None` pattern is not async-safe under FastAPI's asyncio event loop — multiple coroutines can race past the `None` check before the first finishes initializing. The correct pattern for FastAPI is initialization in the `lifespan` startup event (already used in `main.py`). Use the FastAPI `app.state` pattern to store singletons rather than module-level globals.

**Changes:**
- In `main.py` lifespan startup: initialize `DefaultAzureCredential()` and `CosmosClient()` once, store on `app.state`:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      app.state.credential = DefaultAzureCredential()
      app.state.cosmos_client = CosmosClient(os.environ["COSMOS_ENDPOINT"], app.state.credential)
      yield
      # teardown if needed
  ```
- Create `services/api-gateway/dependencies.py` with FastAPI dependencies that read from `request.app.state`:
  ```python
  def get_credential(request: Request) -> DefaultAzureCredential:
      return request.app.state.credential

  def get_cosmos_client(request: Request) -> CosmosClient:
      return request.app.state.cosmos_client
  ```
- Replace per-request `DefaultAzureCredential()` and `CosmosClient()` instantiation in all 5 files with `Depends(get_credential)` / `Depends(get_cosmos_client)`
- Update tests: use `app.state` injection in test client setup rather than per-call patching

**Success criteria:**
- `DefaultAzureCredential.__init__` called exactly once per process (verified via mock call count in lifespan test)
- `CosmosClient.__init__` called exactly once per process
- All existing gateway tests pass with injected mock clients

---

## Phase 13: Dependency Hygiene

**Goal:** Eliminate unpinned dependency versions that can silently break builds.

### 13-01: Pin `azure-ai-agentserver-agentframework`

**Source:** CONCERNS 6.3
**File:** `agents/requirements-base.txt`

Currently `azure-ai-agentserver-agentframework` has no version specifier — every Docker build installs the latest available version.

> **Implementation note (S-03):** Determine the current version by running `docker run --rm <base-image> pip show azure-ai-agentserver-agentframework` against the most recently pushed base image, or by building a temporary image locally. Record the version in a comment before pinning.

**Changes:**
- Build the base image locally or pull the most recent ACR base image and run `pip show azure-ai-agentserver-agentframework` to get the exact installed version
- Pin in `requirements-base.txt`: `azure-ai-agentserver-agentframework==<version>`
- Add inline comment: `# Pinned to current version — verify compatibility against agent-framework RC before upgrading`

**Success criteria:**
- `requirements-base.txt` line has explicit `==` version pin
- `pip install -r requirements-base.txt` installs the pinned version deterministically

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

> **Implementation note (W-07):** The `docker run` step requires the image to already be pushed to ACR. It must be guarded with `if: success()` and `continue-on-error: true` to handle fork PRs and push failures gracefully.

**Changes:**
- Add a post-build step to `base-image.yml` after the push step:
  ```yaml
  - name: Log installed agent package versions
    if: success()
    continue-on-error: true
    run: |
      docker run --rm ${{ vars.ACR_LOGIN_SERVER }}/agents/base:${{ github.sha }} \
        pip show agent-framework azure-ai-agentserver-agentframework azure-ai-projects \
        >> "$GITHUB_STEP_SUMMARY"
  ```

**Success criteria:**
- GitHub Actions job summary shows installed package versions after each successful base image push
- Step failure does not fail the overall workflow (non-blocking)

---

## Phase 14: Test Debt Cleanup

**Goal:** Restore CI signal by implementing the tests that matter and cleanly marking those that genuinely require live infrastructure.

### 14-01: Implement SSE Heartbeat Tests

**Source:** CONCERNS 3.3
**File:** `services/api-gateway/tests/test_sse_heartbeat.py`

Two tests skipped since Plan 05-02:
- `test_heartbeat_sent_every_20_seconds`
- `test_heartbeat_prevents_container_app_timeout`

> **Implementation note (W-03):** Before implementing, verify whether the SSE heartbeat is in the **FastAPI Python gateway** (`services/api-gateway/`) or the **Next.js web-UI** (`services/web-ui/app/api/stream/route.ts`). The test file is in `services/api-gateway/tests/` which implies a Python SSE endpoint. If the heartbeat is in the web-UI TypeScript route, these tests belong in a Jest/Playwright suite, not a pytest file. The implementer must read both `services/api-gateway/main.py` (check for SSE streaming route) and `services/web-ui/app/api/stream/route.ts` (check for heartbeat events) before writing any test code.

**Changes:**
- Read `services/api-gateway/main.py` to find the SSE endpoint (likely `/api/v1/chat/stream` or similar)
- If SSE heartbeat is in Python gateway:
  - Use `pytest-asyncio` + `httpx.AsyncClient` with `TestClient(app)` to open SSE stream
  - Mock the Foundry polling loop to not resolve (simulates long-running request)
  - Assert `event: heartbeat` or `: heartbeat` SSE comment received within 25s
  - Second test: assert events continue at 20s intervals for 45s
  - Remove `@pytest.mark.skip`
- If SSE heartbeat is in Next.js only: move test to `services/web-ui/__tests__/` using Jest with a mocked `Response` stream, and delete the Python stub file

**Success criteria:**
- Both heartbeat tests pass in CI without Azure credentials
- Tests are in the correct service for their implementation language
- `pytest services/api-gateway/tests/test_sse_heartbeat.py` (or equivalent JS test) exits 0

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

> **Implementation note (W-06):** `POST /api/messages` requires a valid Bot Framework `Activity` payload and auth headers — a bare `supertest` POST will return 401 unconditionally regardless of bot health. The reachability check should instead target the `/health` endpoint (unambiguous liveness signal) and verify the Express app starts without crashing. The `POST /api/messages` test can assert 400 or 401 (both indicate the endpoint exists; 404 or 500 indicates the route is broken).

**Changes:**
- Remove outer `describe.skip`
- Replace stub bodies with:
  - `GET /health` → expect 200 (clear liveness signal)
  - `POST /api/messages` with empty body → expect 400 or 401, NOT 404 or 500 (proves the route is wired)
- Use `supertest` against the Express app instance (not a running server) to avoid port conflicts in CI
- Full Teams round-trip tests (requiring live Teams environment) stay as inner `it.skip('TEAMS-XXX: requires live Teams environment', ...)` with explicit reason string
- Add `supertest` as dev dependency if not already present

**Success criteria:**
- `npm test` runs at minimum 2 active tests (health + messages endpoint) — not skipped
- Health check returns 200; messages endpoint returns 400/401, not 404/500
- Full integration stubs clearly marked with explicit skip reason

---

### 14-04: Detection Plane Integration Test Hygiene

**Source:** CONCERNS 3.1
**Files:** `services/detection-plane/tests/integration/`

5 integration test files, all `pass` bodies with `# TODO` comments.

> **Implementation note (W-08):** Before implementing `test_pipeline_flow.py` and `test_round_trip.py`, verify that `classify_domain()` and `map_detection_result_to_payload()` can be imported without triggering Azure SDK calls. Check `services/detection-plane/` imports for any top-level `DefaultAzureCredential()` or SDK client instantiation. If imports are safe, proceed with mock-based tests. If imports require credentials, mark those tests as `pytest.mark.skip(reason="module imports require Azure SDK initialization")` rather than producing a broken test.

**Changes:**
- Read `services/detection-plane/payload_mapper.py` and `services/detection-plane/classify_domain.py` import chains before writing tests
- If imports are credential-safe:
  - `test_pipeline_flow.py`: mock `AzureEventHubProducerClient`; call `classify_domain()` with known alert payloads; assert correct domain string returned and event schema matches `IncidentPayload` structure
  - `test_round_trip.py`: call `map_detection_result_to_payload()` with mock alert data; assert all required `IncidentPayload` fields are populated with correct types
- If imports require credentials: mark both with explicit `pytest.skip` and explain in comment
- `test_dedup_load.py`, `test_activity_log.py`, `test_state_sync.py`: replace `pass` with:
  ```python
  pytest.skip("requires Fabric deployment — enable when enable_fabric_data_plane=true")
  ```

**Success criteria:**
- No test file has a bare `pass` body with a TODO comment
- `test_pipeline_flow.py` and `test_round_trip.py` either pass without credentials or have an explicit, conditional `pytest.skip` with a real reason
- 3 remaining files have explicit `pytest.skip` with infra condition
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
| 4.6 Single ConversationReference (no multi-channel) | Architectural change — requires persistent ConversationReference store; deferred to Teams bot refactor milestone |
| 4.7 Detection plane disabled | Enablement requires operator Fabric config |
| 7.1 `sys.path` manipulation | Low risk, deferred to refactor milestone |
| 7.2 `console.log` logging | Deferred to Teams bot refactor milestone |
| 9.x Documentation gaps | Separate documentation milestone |
