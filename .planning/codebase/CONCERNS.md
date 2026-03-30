# AAP Codebase Concerns

> Generated: 2026-03-30
> Scope: Full codebase audit — technical debt, security, architectural risks, operational gaps
> Sources: Static analysis, grep scans, debug logs, validation report, planning docs

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| **CRITICAL** | Immediate risk of data loss, security breach, or platform-wide outage |
| **HIGH** | Significant risk — broken in production or exploitable within the platform |
| **MEDIUM** | Functional gap or debt that will cause problems at scale or during incidents |
| **LOW** | Code quality issue, minor deviation from best practice, or future risk |

---

## 1. Security Concerns

### [CRITICAL] Plaintext credentials in checked-out `credentials.tfvars`

**File:** `terraform/envs/prod/credentials.tfvars`
**Detail:** The file contains live production secrets in plaintext, including a service principal `client_secret`, a PostgreSQL `admin_password`, and a subscription/tenant ID. The file is gitignored and not committed — but it exists on disk in the working directory. Any process with file system access (malware, accidental sharing, git edge cases) can read these values.
**Secrets exposed:**
- `client_secret = "HDM8Q~..."` (Entra SP for Terraform)
- `postgres_admin_password = "Jas190277on!"` (PostgreSQL admin)
- `subscription_id = "4c727b88-..."` (prod subscription)
- `tenant_id = "abbdca26-..."`

**Risk:** These credentials grant Terraform `Contributor`-equivalent access to the prod subscription. The PostgreSQL password gives DB admin access.
**Mitigation needed:** Rotate both credentials immediately. Store Terraform secrets in Azure Key Vault or a CI-only secrets store; never persist them on developer machines.

---

### [HIGH] Azure MCP Server deployed with authentication disabled

**File:** `scripts/deploy-azure-mcp-server.sh` (line 95), debug log `agent-deployment-and-mcp-wiring.md`
**Detail:** The Azure MCP Server deployed to production uses `--dangerously-disable-http-incoming-auth`. The debug notes explicitly flag this: _"The MCP server currently uses `--dangerously-disable-http-incoming-auth` — add proper Entra auth in production."_ The server is externally accessible (`ingress: external`) and has subscription-level `Reader` access.
**Risk:** Any actor that discovers the MCP server URL can read all Azure resources across the subscription without authentication.
**Mitigation needed:** Enable Entra authentication on the Azure MCP Server endpoint. The Foundry Agent Service supports Entra-authenticated MCP connections.
**Reference:** `agent-deployment-and-mcp-wiring.md` — Remaining Work item #2.

---

### [HIGH] Web UI proxy routes forward unauthenticated requests to API gateway

**Files:** `services/web-ui/app/api/proxy/chat/route.ts`, `proxy/incidents/route.ts`, `proxy/approvals/*/route.ts`, `proxy/chat/result/route.ts`
**Detail:** All Next.js proxy route handlers call the API gateway without forwarding the user's MSAL bearer token. The `Content-Type: application/json` header is sent but no `Authorization` header. The API gateway accepts these calls because `API_GATEWAY_AUTH_MODE=disabled` (dev-mode fallback) is still active in production — confirmed by Phase 8 validation report finding F-01 noting auth is in dev mode.
**Risk:** Removing the dev-mode bypass (which must happen eventually) will instantly break all web UI calls. Conversely, leaving dev-mode enabled means the API gateway accepts requests from any caller without token validation.
**Mitigation needed:** Each proxy route must acquire an MSAL token silently (`api://<gateway-client-id>/.default`) and forward it as `Authorization: Bearer <token>`.

---

### [HIGH] CORS wildcard `*` still active on prod API gateway

**Source:** Phase 8 Validation Report finding F-03 (OPEN as of 2026-03-29)
**Detail:** The prod Container App has `CORS_ALLOWED_ORIGINS=*` which allows any origin to make credentialed cross-origin requests. This is documented as a security risk and is listed as a backlog item — but remains unfixed.
**Risk:** Cross-site request forgery; any malicious page can call the gateway as the authenticated user.
**Mitigation:** `az containerapp update --name ca-api-gateway-prod --resource-group rg-aap-prod --set-env-vars "CORS_ALLOWED_ORIGINS=https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"`

---

### [HIGH] Rate limiter exists but is never applied to API endpoints

**Files:** `services/api-gateway/rate_limiter.py`, `services/api-gateway/main.py`
**Detail:** A `RateLimiter` class and singleton `rate_limiter` instance are defined in `rate_limiter.py`, but a search of `main.py` and all gateway modules shows the rate limiter is never imported or invoked on any endpoint. The approval, incident, chat, and runbook endpoints are all unprotected from high-frequency abuse.
**Risk:** Foundry threads and Cosmos DB writes can be exhausted by a burst of requests. Azure AI Foundry has per-minute token limits; spamming `/api/v1/chat` could exhaust capacity.
**Mitigation:** Wire the rate limiter as a FastAPI dependency on the chat and incident endpoints at minimum.

---

### [MEDIUM] Dev-mode auth bypass can be silently active if `AZURE_CLIENT_ID` is unset

**Files:** `services/api-gateway/auth.py`, `services/teams-bot/src/services/auth.ts`
**Detail:** Both the Python gateway and the Teams bot fall back to a permissive "dev mode" when `AZURE_CLIENT_ID` is absent. The gateway returns a dummy `{"sub": "dev-user"}` claims dict. The bot returns a literal `"dev-token"` string. This is intentional for local development, but the risk is that a mis-configured production container could silently bypass all authentication.
**Current state:** Phase 8 validation confirms auth is running in dev mode in production — the `AZURE_CLIENT_ID` env var is not set on the api-gateway Container App. All 202 responses from the gateway in production have no real Entra validation.
**Mitigation:** Set `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` on prod Container Apps. Add startup validation that fails fast in non-dev environments.

---

### [MEDIUM] `@azure/mcp` version pinned to beta (v2.0.0-beta.34)

**Files:** `services/azure-mcp-server/Dockerfile`, `scripts/deploy-azure-mcp-server.sh`, `services/api-gateway/azure_tools.py`
**Detail:** The Azure MCP Server is pinned to `@azure/mcp@2.0.0-beta.34` — a pre-release version with no stability guarantee. All agent tool calls for Azure resources flow through this binary.
**Risk:** Beta version may have undocumented breaking changes; tool names or schemas could change without notice.

---

### [MEDIUM] Fabric SP client secret in Terraform state / Key Vault as plaintext

**File:** `terraform/envs/prod/main.tf` (`azurerm_key_vault_secret.fabric_sp_client_secret`)
**Detail:** The Fabric service principal secret is written to Terraform state as plaintext (before Key Vault storage). Anyone with read access to the Terraform state file in Azure Storage can retrieve this secret.
**Risk:** The secret grants the ability to POST incidents to the gateway under a legitimate service identity.
**Mitigation:** Use Key Vault references in the Fabric User Data Function directly; rotate the SP secret. The Terraform state backend should have access logging enabled.

---

### [MEDIUM] `azuread_application_password` has a fixed expiry (`end_date = "2027-03-26T00:00:00Z"`) with no rotation automation

**File:** `terraform/envs/prod/main.tf` (line 316)
**Detail:** The Fabric SP client secret expires 2027-03-26. There is no automated rotation job or alert configured.
**Risk:** Silent credential expiry will break the entire detection-plane → gateway pipeline with no warning.
**Mitigation:** Create an Azure Monitor alert for SP credential expiry 60 days before the date.

---

## 2. Technical Debt — Hardcoded Values

### [HIGH] Prod API gateway URL hardcoded in 5 web-UI proxy routes

**Files:**
- `services/web-ui/app/api/proxy/chat/route.ts:8`
- `services/web-ui/app/api/proxy/chat/result/route.ts:8`
- `services/web-ui/app/api/proxy/incidents/route.ts:8`
- `services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts:8`
- `services/web-ui/app/api/proxy/approvals/[approvalId]/reject/route.ts:8`

**Detail:** All five routes have the fallback:
```typescript
const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL ||
  'https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io';
```
The `.env.example` shows this should be `http://localhost:8000` for local dev. The fallback is the opposite — it silently targets prod if the env var is unset during development.
**Risk:** A developer running the web-UI locally without setting `API_GATEWAY_URL` will unknowingly send requests to the production gateway.
**Mitigation:** Remove the hardcoded prod URL fallback. Fail loudly if `API_GATEWAY_URL` is not set in non-dev contexts.

---

### [HIGH] SSE stream route hardcodes `http://localhost:3000` for internal polling

**File:** `services/web-ui/app/api/stream/route.ts:120`
**Detail:**
```typescript
const res = await fetch(
  `http://localhost:3000/api/proxy/chat/result?thread_id=...`,
  ...
);
```
The SSE route polls the chat result proxy via a hardcoded `localhost:3000`. This only works when the Next.js server is running on port 3000. In a Container Apps deployment with port 3000, this is technically correct — but it creates brittleness: port changes, staging environments, or any proxy in the chain will silently break the SSE event stream.
**Mitigation:** Use a relative URL (`/api/proxy/chat/result?...`) or an environment variable for the internal base URL.

---

### [HIGH] `arc-mcp-server.spec.ts` hardcodes `localhost:8080`

**Source:** Phase 8 Validation Report finding F-06 (OPEN)
**File:** `e2e/arc-mcp-server.spec.ts:28`
```typescript
const API_GATEWAY_URL = process.env.API_GATEWAY_URL || 'http://localhost:8000';
const ARC_MCP_URL = 'http://localhost:8080'; // Hardcoded, no env var
```
**Detail:** 5 of 8 Arc MCP E2E tests fail in every environment because the Arc MCP server URL is hardcoded to `localhost:8080`. No `E2E_ARC_MCP_URL` env var is read.
**Risk:** These tests provide no signal in CI — they always fail and are therefore effectively dead code.

---

### [MEDIUM] Duplicate `map_detection_result_to_payload()` logic in Fabric function

**Files:**
- `services/detection-plane/payload_mapper.py` (canonical)
- `fabric/user-data-function/main.py:63` (copy)

**Detail:** The comment in `main.py` acknowledges this: _"This is a self-contained copy of the mapping logic to avoid import dependencies on the detection-plane package within Fabric runtime."_ Both implementations must be kept in sync manually.
**Risk:** Divergence between implementations will produce malformed `IncidentPayload` objects that the gateway silently rejects with 422 errors.

---

### [MEDIUM] Azure MCP Server not managed by Terraform

**Source:** `agent-deployment-and-mcp-wiring.md` — Remaining Work item #3
**Detail:** The `ca-azure-mcp-prod` Container App was deployed ad-hoc via `scripts/deploy-azure-mcp-server.sh`. It is not defined in any Terraform module. This means:
- It will not be reproduced in `dev` or `staging` environments
- `terraform plan` will not detect drift on this resource
- Infrastructure documentation is incomplete

---

## 3. Missing Implementations / Stubs

### [HIGH] All 5 integration test suites for the detection plane are empty stubs

**Files:**
- `services/detection-plane/tests/integration/test_pipeline_flow.py` — 4 TODO stubs
- `services/detection-plane/tests/integration/test_dedup_load.py` — 3 TODO stubs
- `services/detection-plane/tests/integration/test_activity_log.py` — 2 TODO stubs
- `services/detection-plane/tests/integration/test_state_sync.py` — 3 TODO stubs
- `services/detection-plane/tests/integration/test_round_trip.py` — 2 TODO stubs

**Detail:** Every integration test body is a `pass` statement with a `# TODO: Implement after Phase 4 deployment` comment. The entire detection pipeline (Fabric Eventstreams → Eventhouse → Activator → API gateway) has zero automated integration test coverage.
**Risk:** The detection plane can regress silently. Currently this is masked because `enable_fabric_data_plane = false` in all environments.

---

### [HIGH] Teams integration tests are all skipped stubs

**File:** `services/teams-bot/src/__tests__/integration/teams-e2e-stubs.test.ts`
**Detail:** All 6 Teams success criteria (TEAMS-001 through TEAMS-006) tests are inside `describe.skip(...)`. None of the Teams integration scenarios have automated test coverage.
**Risk:** Teams bot behavior changes go undetected in CI.

---

### [HIGH] SSE heartbeat tests are skipped stubs

**File:** `services/api-gateway/tests/test_sse_heartbeat.py`
**Detail:**
```python
@pytest.mark.skip(reason="stub - implement in Plan 05-02")
def test_heartbeat_sent_every_20_seconds(self): pass

@pytest.mark.skip(reason="stub - implement in Plan 05-02")
def test_heartbeat_prevents_container_app_timeout(self): pass
```
These were meant to be implemented in Plan 05-02 but remain as skipped stubs. The heartbeat is critical to prevent the Azure Container Apps 240-second idle timeout from killing SSE connections.

---

### [HIGH] Web UI unit tests are placeholder stubs

**Files:** `services/web-ui/__tests__/layout.test.tsx`, `services/web-ui/__tests__/auth.test.tsx`
**Detail:** All 7 tests in `layout.test.tsx` and all tests in `auth.test.tsx` have empty bodies with `// TODO: Plan 05-01` comments. The web UI has no meaningful unit test coverage of its components.

---

### [HIGH] Arc Agent deployed with stub identity until Arc MCP Server is wired

**File:** `agents/arc/__init__.py`
**Detail:** The package `__init__.py` declares: _"Arc-specific capabilities require the custom Arc MCP Server built in Phase 3. This agent is deployed but returns a structured stub response for all incidents until Phase 3 completes."_ Phase 3 is marked complete in the planning docs, but the Arc MCP Server is not wired to the Foundry orchestrator (validated as degraded finding F-11 in Phase 8 report).

---

### [MEDIUM] `AGENT_ENTRA_ID` environment variable never set in Terraform

**File:** `agents/shared/auth.py:73-79`, `terraform/modules/agent-apps/main.tf`
**Detail:** `get_agent_identity()` reads `AGENT_ENTRA_ID` and raises `ValueError` if missing. This env var is documented as "set by the agent-apps Terraform module from the Container App's system-assigned identity principal_id." However, there is no `AGENT_ENTRA_ID` env block in `terraform/modules/agent-apps/main.tf`.
**Risk:** Any agent code path that calls `get_agent_identity()` will crash at runtime. This is referenced for AUDIT-005 attribution.

---

### [MEDIUM] Trace SSE stream type is a stub — leaves connection open with no events

**File:** `services/web-ui/app/api/stream/route.ts:101-104`
**Detail:**
```typescript
// Only the token stream polls Foundry — trace stream stays open for future use
if (streamType !== 'token') {
  return;
}
```
A client connecting with `?type=trace` gets an open SSE connection that emits heartbeats but no events. This is an unimplemented feature that blocks the SSE connection for up to 2 minutes before the server-side timeout triggers.

---

### [LOW] `OTel spans never appear in App Insights` — operator step pending since Phase 8

**Source:** Phase 8 Validation Report — OTel section
**Detail:** All 6 span types (`foundry.*`, `mcp.*`, `agent.orchestrator`) cannot be verified in App Insights because the `08-04-06` Container App rebuild has not been completed. The `instrumentation.py` code is committed but the prod container was not rebuilt with it.
**Risk:** Observability is completely blind — no spans, no traces, no duration data.

---

## 4. Architectural Risks

### [CRITICAL] Foundry Hosted Agents cannot use private networking — data plane in Microsoft cloud

**Source:** `CLAUDE.md` project constraints
**Detail:** _"Foundry Hosted Agents: Still Preview; no private networking yet — Container Apps fill this gap."_ All agent LLM inference happens on Microsoft's infrastructure, not inside the customer VNet. This means:
- Agent conversations traverse a public endpoint
- Incident data, resource identifiers, and triage details are transmitted to Microsoft's cloud
- Private endpoints on Cosmos DB and PostgreSQL do not protect data that passes through Foundry

**Risk:** Compliance implications for regulated industries. All incident data sent to agents is visible to Foundry's LLM inference infrastructure. This is an architectural constraint of the platform, not a bug — but teams using this in regulated environments must understand this.

---

### [HIGH] `agent-framework==1.0.0rc5` is pre-release RC — high breaking-change velocity

**File:** `agents/requirements-base.txt`
**Detail:** The entire multi-agent orchestration layer (`HandoffOrchestrator`, `ChatAgent`, `@ai_function`, `AgentTarget`) depends on a Release Candidate package. The CLAUDE.md notes: _"Pre-release RC — high-velocity, breaking changes likely before GA."_
**Risk:** A patch from Microsoft could break all 7 agents simultaneously with no notice. There is no fallback framework.
**Mitigation:** Pin exactly (`==1.0.0rc5`) — which is done — and establish a process to validate upgrades in dev before applying to prod.

---

### [HIGH] Teams bot uses legacy `botbuilder` SDK — explicitly marked "avoid for new work"

**Files:** `services/teams-bot/src/bot.ts`, `services/teams-bot/src/index.ts`, `services/teams-bot/src/services/proactive.ts`
**Detail:** The teams-bot package uses `botbuilder@^4.23.0` and `@microsoft/teams-ai@^1.5.0`. The CLAUDE.md explicitly lists `botbuilder` under "What NOT to Use": _"Avoid for new work. Legacy Bot Framework SDK... not designed for AI-native bots."_ The new Teams SDK is `@microsoft/teams.js`.
**Risk:** The legacy SDK will not receive new Teams features. Teams platform updates may break the bot in non-backward-compatible ways.

---

### [HIGH] `CosmosClient` and `DefaultAzureCredential` created per-request — no connection pooling

**Files:** `services/api-gateway/approvals.py:34-37`, `services/api-gateway/incidents_list.py:24`, `services/api-gateway/dedup_integration.py:66-69`, `services/api-gateway/audit.py:125`, `services/api-gateway/foundry.py:43-46`
**Detail:** Each request creates new `DefaultAzureCredential()` and `CosmosClient()` instances. `DefaultAzureCredential` probes a chain of credential providers on first use, which includes HTTP calls to IMDS. Under load, this creates:
- Latency spikes (IMDS calls per request)
- Connection pool exhaustion (Cosmos SDK maintains TCP connections per client instance)
- High token refresh frequency (no token caching across requests)

**Mitigation:** Cache `DefaultAzureCredential` via `@lru_cache` (done in `agents/shared/auth.py` but not in the gateway). Cache `CosmosClient` as a module-level singleton using lifespan startup.

---

### [HIGH] In-memory conversation state in Teams bot is lost on restart

**File:** `services/teams-bot/src/services/conversation-state.ts`
**Detail:**
```typescript
// This is in-memory only — lost on restart. Acceptable for Phase 6 MVP.
const conversationMap = new Map<string, ConversationThread>();
```
The comment acknowledges this. Any Container App restart, scale-in event, or deployment causes all Teams conversation→thread mappings to be lost. Subsequent messages from Teams users after a restart create new Foundry threads, losing all incident context.
**Mitigation:** Persist conversation state to Cosmos DB.

---

### [HIGH] Single `ConversationReference` for proactive messaging — no multi-channel support

**File:** `services/teams-bot/src/services/proactive.ts:8`
**Detail:**
```typescript
let savedConversationReference: Partial<ConversationReference> | null = null;
```
Only one `ConversationReference` is stored. If the bot is installed in multiple teams channels, only the last installation target receives proactive alerts.
**Risk:** All production alert cards, approval requests, and escalation reminders only go to one channel — whichever last installed the bot.

---

### [MEDIUM] Detection plane entirely disabled in all environments (`enable_fabric_data_plane = false`)

**File:** `terraform/envs/prod/main.tf:258`
**Detail:** `enable_fabric_data_plane = false` across prod, staging, and dev. The Fabric workspace, Eventhouse, KQL database, Activator, and OneLake lakehouse are not provisioned. The entire automated detection pipeline does not exist in any environment. Alerts can only be injected manually via the simulation scripts.
**Risk:** The platform's core value proposition (continuous automated monitoring) is entirely unimplemented in production.

---

### [MEDIUM] Arc MCP Server disabled in prod (`enable_arc_mcp_server = false`)

**File:** `terraform/envs/prod/main.tf:9`
**Detail:** `enable_arc_mcp_server = false`. The Arc Agent cannot perform Arc-specific triage. As noted in the Phase 8 simulation, Arc incidents fall back to compute tool surface (F-11).

---

### [MEDIUM] Network, Security, and SRE Azure MCP tool groups not configured in Foundry

**Source:** Phase 8 Validation Findings F-09, F-10, F-11 (all OPEN)
**Detail:** Only the `compute` tool group appears accessible via the Foundry MCP connection. Network, Security, and SRE agents reply "tool group was not found" for their domain-specific queries.
**Risk:** 4 of 6 domain agents provide degraded responses.

---

### [MEDIUM] Fabric Activator and OneLake mirror require manual configuration — not automatable

**File:** `terraform/modules/fabric/main.tf:174-193`
**Detail:** Two `null_resource` provisioners emit reminders that Activator trigger wiring and OneLake Activity Log mirroring cannot be done via Terraform. They must be configured in the Fabric portal. There is no programmatic way to verify these are correctly configured.
**Risk:** These steps are easy to miss after a fresh deployment. The detection pipeline will appear to work (no errors) but produce no alerts.

---

### [MEDIUM] `pgvector` extension creation blocked in VNet — requires manual workflow step

**File:** `terraform/modules/databases/postgres.tf:39-51`
**Detail:** PostgreSQL is VNet-injected (`public_network_access_enabled = false`). GitHub-hosted runners cannot reach it to run `CREATE EXTENSION IF NOT EXISTS vector`. The Terraform plan notes this is handled by a multi-step CI workflow (add firewall rule → run psql → remove rule). If CI skips or fails the pgvector step, the runbook RAG feature fails silently at startup. Phase 8 confirmed this was the cause of the runbook search 500 error (F-02).

---

### [LOW] MCP protocol workaround via stdio subprocess — AssertionError bypass

**File:** `services/api-gateway/azure_tools.py`
**Detail:** The module docstring explains the workaround: _"bypassing Foundry's broken HTTP MCP client which has an AssertionError protocol incompatibility with @azure/mcp."_ The entire `AzureMCPClient` class exists to work around a framework bug. If Foundry's HTTP MCP client is fixed, this entire code path becomes redundant technical debt.

---

## 5. Operational Concerns

### [HIGH] Health endpoint does not validate critical dependencies

**Source:** `tasks/lessons.md` lesson 2026-03-28
**Detail:** `GET /health` returns `{"status": "ok"}` regardless of whether Foundry, Cosmos DB, PostgreSQL, or environment variables are correctly configured. The Phase 8 chat failure was masked for weeks because the health check always returned 200.
**Mitigation:** Implement a `/health/ready` endpoint that validates: `ORCHESTRATOR_AGENT_ID` is set, Foundry client can be created, Cosmos DB is reachable.

---

### [HIGH] No alerting on agent Container App crashes or OOM kills

**Detail:** The domain agents can silently crash (e.g., missing env vars on startup, `ValueError: ARC_MCP_SERVER_URL not set`) and the platform continues accepting incidents with no response. There are no Azure Monitor alerts on Container App restart counts or failure events.

---

### [HIGH] Cosmos DB cleanup blocked by firewall from non-Azure runners

**Source:** Phase 8 simulation results
**Detail:** The simulation scripts call `cleanup_incident()` after each test. From a local developer machine, this returns 403 because the prod Cosmos DB is on private networking. Test cleanup silently fails — records accumulate until TTL expiry. In CI, this works via managed identity, but it means local E2E testing leaves production data artifacts.

---

### [MEDIUM] Prod runbooks not seeded — runbook RAG returns empty results

**Source:** Phase 8 Validation Report finding F-02 detail
**Detail:** Even after fixing the pgvector connection, `GET /api/v1/runbooks/search` returns an empty array because no runbooks have been seeded to production PostgreSQL. The `scripts/seed-runbooks/seed.py` script exists but has never been run against prod.
**Impact:** The TRIAGE-005 runbook recommendation feature is non-functional in production.

---

### [MEDIUM] OTel spans not appearing in App Insights — rebuild pending

**Source:** Phase 8 Validation Report OTel section
**Detail:** The `instrumentation.py` module was added but the prod Container Apps were not rebuilt after the change. Zero spans appear in App Insights. Without spans, there is no observability into: Foundry thread creation latency, MCP tool call timing, or agent handoff chains.

---

### [MEDIUM] GitHub Actions E2E secrets not configured — E2E CI runs in dev-mode auth

**Source:** Phase 8 Validation Report finding F-05 (OPEN)
**Detail:** `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_API_AUDIENCE` are not set in the `staging` GitHub Actions environment. All CI E2E runs use `Bearer dev-token` and cannot validate any auth-protected endpoint behavior.

---

### [MEDIUM] Non-existent approval returns 500 instead of 404

**Source:** Phase 8 Validation Report finding F-07 (OPEN), test E-26
**File:** `services/api-gateway/approvals.py`
**Detail:** `GET /api/v1/approvals/{id}/approve` raises an unhandled exception when `approval_id` does not exist, returning HTTP 500. The correct behavior is 404. Test `sc5.spec.ts` expects 400/404/410 but receives 500, causing a CI failure.

---

### [LOW] Teams Bot registration incomplete — proactive alerts not functional

**Source:** Phase 8 Validation Report finding F-04 (OPEN)
**Detail:** Azure Bot Service has a registration (`aap-teams-bot-prod`) but is not fully configured. The Teams integration cannot receive messages or send proactive alerts. `teams_bot_password` is set to `"placeholder-not-configured"` in Terraform if not explicitly passed.

---

## 6. Dependency Risks

### [HIGH] `agent-framework==1.0.0rc5` — pre-release, single point of failure for all agents

See Section 4 above. All 7 agents depend entirely on this RC package.

---

### [HIGH] `@azure/mcp@2.0.0-beta.34` — beta, deployed to production

**Files:** `services/azure-mcp-server/Dockerfile`, `services/api-gateway/azure_tools.py:85`
**Detail:** The beta Azure MCP Server is the sole tool surface for all Azure resource queries. It is pinned at `2.0.0-beta.34` in the Dockerfile but installed dynamically in the deploy script, which could pick up a newer beta on redeploy.

---

### [MEDIUM] `azure-ai-agentserver-agentframework` — no version pin

**File:** `agents/requirements-base.txt:14`
```
azure-ai-agentserver-agentframework
```
No version specifier. Every Docker build installs the latest available version of this adapter package. If Microsoft releases a breaking version, all agent containers will be broken on next build.

---

### [MEDIUM] Entra Agent ID (agent identity governance) is Preview API

**Source:** `CLAUDE.md` constraints
**Detail:** Entra Agent ID is provisioned with `azapi` at `2025-10-01-preview` API version. Microsoft explicitly notes this may change before GA. Any Terraform plan after an API version change will fail or produce unexpected mutations.

---

### [MEDIUM] Fabric `azapi_resource` types use `schema_validation_enabled = false`

**File:** `terraform/modules/fabric/main.tf` (all resources)
**Detail:** Every Fabric resource disables schema validation because the types are not in the AzAPI embedded schema catalog. This means Terraform will accept any typo in the resource body without error.

---

### [LOW] Teams bot uses `@microsoft/teams-ai@^1.5.0` — legacy path

**File:** `services/teams-bot/package.json`
**Detail:** `@microsoft/teams-ai` v1.5.0 is the "old Teams AI Library built on Bot Framework" (CLAUDE.md). Microsoft recommends `@microsoft/teams.js` (new SDK). This package is on a maintenance track and will not receive new Teams features.

---

## 7. Code Quality / Technical Debt

### [MEDIUM] `sys.path` manipulation for detection-plane import in gateway

**File:** `services/api-gateway/dedup_integration.py:16-21`
**Detail:**
```python
_DETECTION_PLANE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "detection-plane"
)
sys.path.insert(0, os.path.abspath(_DETECTION_PLANE_PATH))
```
Runtime `sys.path` manipulation is fragile, environment-dependent, and makes the import graph opaque. The `dedup` module should be a proper Python package or the detection-plane logic should be accessible via a well-defined interface.

---

### [MEDIUM] `console.log/warn/error` used instead of a proper logging library in teams-bot

**Files:** `services/teams-bot/src/services/proactive.ts`, `services/teams-bot/src/services/escalation.ts`, `services/teams-bot/src/routes/notify.ts`, `services/teams-bot/src/index.ts`, `services/teams-bot/src/instrumentation.ts`
**Detail:** ~15 production `console.log/warn/error` calls. These produce unstructured log output and cannot be filtered, sampled, or correlated. In Azure Container Apps, structured JSON logs (e.g., `pino`) are searchable in Log Analytics; `console.log` is not.

---

### [MEDIUM] In-memory dedup map in escalation scheduler is reset on restart

**File:** `services/teams-bot/src/services/escalation.ts:9`
**Detail:**
```typescript
const lastReminderMap = new Map<string, number>();
```
The dedup map tracking when reminders were last sent is in-memory. After any restart, the scheduler will immediately re-post reminder cards for all pending approvals that exceed the threshold, regardless of when the last reminder was sent.

---

### [MEDIUM] Approval `scope_confirmed` check relies on substring matching of subscription IDs

**File:** `services/api-gateway/approvals.py:128-135`
**Detail:**
```python
for prod_sub in prod_subscriptions:
    if prod_sub and prod_sub in resource_id:
```
Using `in` for substring matching on resource IDs is fragile. A subscription ID that is a prefix of another will produce false positives. Use exact segment matching on the resource ID path components.

---

### [LOW] `test_sse_heartbeat.py` and `test_layout.tsx` / `test_auth.tsx` test files contain no actual tests

**Files:** Multiple
**Detail:** Skipped or placeholder tests inflate the apparent test count without contributing to coverage. These should be removed or implemented.

---

### [LOW] `conftest.py` installs a hand-rolled `agent_framework` stub

**File:** `conftest.py:24-76`
**Detail:** The test suite installs a fake `agent_framework` module because the real RC package is not installed in the CI test environment. This means unit tests never exercise real `ChatAgent`, `HandoffOrchestrator`, or `@ai_function` behavior. Test fidelity is limited.

---

## 8. Deployment Gaps

### [HIGH] Domain agent IDs (`COMPUTE_AGENT_ID`, etc.) are empty strings in production

**File:** `terraform/modules/agent-apps/main.tf:104-144`, `agents/orchestrator/agent.py:220-258`
**Detail:** The orchestrator registers domain agents with:
```python
agent_id=os.environ.get("COMPUTE_AGENT_ID", "")
```
The dynamic `env` blocks in Terraform only inject these if the variable is non-empty. As of Phase 8, none of the domain Foundry Hosted Agents exist in the Foundry portal — only the orchestrator `asst_NeBVjCA5isNrIERoGYzRpBTu`. All 6 domain agent IDs are empty strings. The `HandoffOrchestrator` will fail to route to any domain agent.

---

### [HIGH] `AZURE_MCP_VERSION=2.0.0-beta.34` hardcoded in both Dockerfile and deploy script

**Files:** `services/azure-mcp-server/Dockerfile:5`, `scripts/deploy-azure-mcp-server.sh:17`
**Detail:** Version is duplicated in two places and must be updated manually in sync. The deploy script installs at runtime (`npm install -g @azure/mcp@$AZURE_MCP_VERSION`), but the Dockerfile builds at image-build time. If these diverge, the live server version will differ from the tagged image.

---

### [MEDIUM] `postgres_admin_password` passed as a Terraform variable (plaintext in tfvars)

**File:** `terraform/modules/databases/postgres.tf:14`, `terraform/envs/prod/credentials.tfvars:14`
**Detail:** The PostgreSQL admin password is passed as a Terraform variable string (`var.postgres_admin_password`). It appears in Terraform state (encrypted by Azure Storage at rest) and in `credentials.tfvars` as plaintext. The proper pattern is to generate the password in Key Vault and reference it.

---

### [MEDIUM] Dev and staging environments use `use_placeholder_image = true` (default)

**File:** `terraform/modules/agent-apps/variables.tf:77` (default: `true`)
**Detail:** Dev and staging do not explicitly set `use_placeholder_image = false`. All Container Apps in dev and staging run `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest` — not the actual agent images. Dev/staging effectively cannot be used for functional testing without manually deploying images.

---

### [MEDIUM] `API_GATEWAY_AUTH_MODE` not managed by Terraform — defaults to Entra but never set explicitly

**File:** `services/api-gateway/auth.py:118`, `terraform/modules/agent-apps/main.tf`
**Detail:** The API gateway reads `API_GATEWAY_AUTH_MODE` to determine validation mode. This variable is never set in Terraform, so it defaults to the environment variable's presence/absence. In production, the combination of missing `AZURE_CLIENT_ID` causes the gateway to silently fall into dev mode.

---

### [LOW] `@azure/mcp` MCP connection on Foundry uses `category: "CustomKeys"` workaround

**Source:** `agent-deployment-and-mcp-wiring.md`
**Detail:** _"ARM API `category: 'MCP'` for connections is NOT available yet in GA or current preview API versions. Used `CustomKeys` category with MCP metadata as workaround."_ This connection cannot be managed in Terraform and may break when Microsoft adds proper `MCP` category support.

---

## 9. Missing Documentation

### [MEDIUM] Architecture diagram does not exist

**File:** `CLAUDE.md` — "Architecture not yet mapped."
**Detail:** The CLAUDE.md explicitly states architecture documentation is missing. There is no system diagram showing the Container Apps topology, agent routing, data flows, or network boundaries.

---

### [MEDIUM] Conventions section is empty

**File:** `CLAUDE.md` — "Conventions not yet established."
**Detail:** No documented naming conventions, environment variable naming rules, error envelope format standards, or API versioning policy.

---

### [MEDIUM] MANUAL-SETUP.md steps not tracked for completion

**File:** `docs/MANUAL-SETUP.md`
**Detail:** The manual setup guide contains many steps (Foundry agent creation, RBAC assignments, Bot registration, pgvector seeding) that have no automated verification. There is no checklist tracking which steps have been completed in each environment.

---

### [LOW] No runbook for common failure modes

**Detail:** There are no operational runbooks for the platform's own infrastructure — only for customer Azure resources (compute, network, etc.). Common failure modes like "agent container crashes on startup," "Foundry dispatch returns 503," "SSE stream silently empty" have no documented remediation steps.

---

## Summary Table

| # | Concern | Severity | Area |
|---|---------|----------|------|
| 1.1 | Plaintext credentials in `credentials.tfvars` | **CRITICAL** | Security |
| 1.2 | Azure MCP Server auth disabled in production | **HIGH** | Security |
| 1.3 | Web UI proxy routes don't forward auth tokens | **HIGH** | Security |
| 1.4 | CORS wildcard active on prod gateway | **HIGH** | Security |
| 1.5 | Rate limiter never applied to endpoints | **HIGH** | Security |
| 1.6 | Dev-mode auth bypass silently active in prod | **MEDIUM** | Security |
| 1.7 | `@azure/mcp` beta version in prod | **MEDIUM** | Security |
| 1.8 | Fabric SP secret in Terraform state | **MEDIUM** | Security |
| 1.9 | SP secret expiry with no rotation alert | **MEDIUM** | Security |
| 2.1 | Prod URL hardcoded in 5 proxy routes | **HIGH** | Tech Debt |
| 2.2 | SSE route hardcodes `localhost:3000` internally | **HIGH** | Tech Debt |
| 2.3 | Arc MCP E2E tests hardcode `localhost:8080` | **HIGH** | Tech Debt |
| 2.4 | Duplicate payload mapper in Fabric function | **MEDIUM** | Tech Debt |
| 2.5 | Azure MCP Server not managed by Terraform | **MEDIUM** | Tech Debt |
| 3.1 | All 5 detection-plane integration tests empty | **HIGH** | Missing Impl |
| 3.2 | All 6 Teams integration tests skipped | **HIGH** | Missing Impl |
| 3.3 | SSE heartbeat tests are skipped stubs | **HIGH** | Missing Impl |
| 3.4 | Web UI unit tests are placeholder stubs | **HIGH** | Missing Impl |
| 3.5 | Arc Agent still returning stub responses | **HIGH** | Missing Impl |
| 3.6 | `AGENT_ENTRA_ID` never set in Terraform | **MEDIUM** | Missing Impl |
| 3.7 | Trace SSE stream type is unimplemented stub | **MEDIUM** | Missing Impl |
| 3.8 | OTel spans never appearing in App Insights | **LOW** | Missing Impl |
| 4.1 | Foundry Hosted Agents: no private networking | **CRITICAL** | Architecture |
| 4.2 | `agent-framework==1.0.0rc5` RC dependency | **HIGH** | Architecture |
| 4.3 | Teams bot uses legacy `botbuilder` SDK | **HIGH** | Architecture |
| 4.4 | CosmosClient/DefaultAzureCredential per-request | **HIGH** | Architecture |
| 4.5 | In-memory Teams conversation state lost on restart | **HIGH** | Architecture |
| 4.6 | Single ConversationReference — no multi-channel | **HIGH** | Architecture |
| 4.7 | Detection plane disabled in all environments | **MEDIUM** | Architecture |
| 4.8 | Arc MCP Server disabled in prod | **MEDIUM** | Architecture |
| 4.9 | Network/Security/SRE MCP tools not wired | **MEDIUM** | Architecture |
| 4.10 | Fabric Activator/OneLake require manual config | **MEDIUM** | Architecture |
| 4.11 | pgvector creation blocked in VNet | **MEDIUM** | Architecture |
| 4.12 | Azure MCP stdio workaround for Foundry bug | **LOW** | Architecture |
| 5.1 | Health endpoint doesn't validate dependencies | **HIGH** | Operations |
| 5.2 | No alerting on agent Container App crashes | **HIGH** | Operations |
| 5.3 | Cosmos cleanup blocked from local runners | **HIGH** | Operations |
| 5.4 | Prod runbooks not seeded | **MEDIUM** | Operations |
| 5.5 | OTel rebuild pending since Phase 8 | **MEDIUM** | Operations |
| 5.6 | E2E CI secrets not configured | **MEDIUM** | Operations |
| 5.7 | Missing approval returns 500 not 404 | **MEDIUM** | Operations |
| 5.8 | Teams Bot registration incomplete | **LOW** | Operations |
| 6.1 | `agent-framework` RC — single point of failure | **HIGH** | Dependencies |
| 6.2 | `@azure/mcp` beta in production | **HIGH** | Dependencies |
| 6.3 | `azure-ai-agentserver-agentframework` no version pin | **MEDIUM** | Dependencies |
| 6.4 | Entra Agent ID Preview API | **MEDIUM** | Dependencies |
| 6.5 | Fabric `schema_validation_enabled = false` | **MEDIUM** | Dependencies |
| 6.6 | `teams-ai@1.5.0` legacy path | **LOW** | Dependencies |
| 7.1 | `sys.path` manipulation for detection-plane | **MEDIUM** | Code Quality |
| 7.2 | `console.log` instead of structured logging | **MEDIUM** | Code Quality |
| 7.3 | Escalation dedup map reset on restart | **MEDIUM** | Code Quality |
| 7.4 | Approval scope check uses substring matching | **MEDIUM** | Code Quality |
| 7.5 | Empty/skipped test files inflate test count | **LOW** | Code Quality |
| 7.6 | `agent_framework` stub in conftest | **LOW** | Code Quality |
| 8.1 | Domain agent Foundry IDs empty in production | **HIGH** | Deployment |
| 8.2 | `@azure/mcp` version duplicated in Dockerfile + script | **HIGH** | Deployment |
| 8.3 | `postgres_admin_password` as Terraform variable | **MEDIUM** | Deployment |
| 8.4 | Dev/staging use placeholder images (default) | **MEDIUM** | Deployment |
| 8.5 | `API_GATEWAY_AUTH_MODE` not set via Terraform | **MEDIUM** | Deployment |
| 8.6 | MCP connection uses `CustomKeys` workaround | **LOW** | Deployment |
| 9.1 | Architecture diagram missing | **MEDIUM** | Documentation |
| 9.2 | Conventions section empty | **MEDIUM** | Documentation |
| 9.3 | MANUAL-SETUP.md steps untracked | **MEDIUM** | Documentation |
| 9.4 | No platform operational runbooks | **LOW** | Documentation |

---

*Generated by codebase audit — grep patterns: TODO, FIXME, HACK, stub, placeholder, workaround, hardcode, NotImplemented, dev-token, localhost; cross-referenced with .planning/BACKLOG.md, 08-VALIDATION-REPORT.md, debug/* logs, tasks/lessons.md*
