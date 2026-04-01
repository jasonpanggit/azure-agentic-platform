# Concerns & Technical Debt

> Last updated: 2026-04-01. Full refresh — covers phases 1–13, debug logs, BACKLOG.md, source inspection, and MANUAL-SETUP.md.
> Sources: `.planning/debug/`, `.planning/BACKLOG.md`, `.planning/STATE.md`, `TODO.md`, `docs/MANUAL-SETUP.md`, grep scans across `services/`, `agents/`, `terraform/`.

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| **CRITICAL** | Immediate risk of security breach, data loss, or platform-wide outage |
| **HIGH** | Broken in production, exploitable, or blocking a core platform capability |
| **MEDIUM** | Functional gap or debt that causes problems at scale or during incidents |
| **LOW** | Code quality issue, minor deviation from best practice, or future risk |

---

## Known Issues (bugs, broken features)

### BUG-001 — `NameError: outputs` in `chat.py` — silent tool submission failure [HIGH]

- **File:** `services/api-gateway/chat.py:412`
- **Code:** `client.runs.submit_tool_outputs(..., tool_outputs=outputs)` — variable name `outputs` is undefined; the correct local name built 10 lines earlier is `tool_outputs`.
- **Impact:** When the orchestrator's own run hits `requires_action / submit_tool_outputs`, the submission raises a `NameError` that is silently caught by the surrounding `except Exception: logger.warning(...)`. The run stalls at `requires_action` until it times out (expired). This is the code path that executes function tools on the orchestrator — currently only triggered by the `azure_tools` blocked path, but any future function tool added to the orchestrator would be silently broken.
- **Status:** Not fixed.

### BUG-002 — `GET /api/v1/runbooks/search` returns 500 in prod [HIGH]

- **Source:** Backlog F-02 (open)
- **Detail:** `PGVECTOR_CONNECTION_STRING` env var is not confirmed set on `ca-api-gateway-prod`, and prod runbooks have never been seeded. Any operator chat query or incident triage that triggers runbook lookup fails with an unhandled exception.
- **Status:** Operator action required: verify env var + run `scripts/seed-runbooks/seed.py` against prod PostgreSQL.

### BUG-003 — Missing 404 on `GET /api/v1/approvals/{id}/approve` [MEDIUM]

- **File:** `services/api-gateway/approvals.py`
- **Source:** Backlog F-07 (open)
- **Detail:** Non-existent `approval_id` raises an unhandled exception → HTTP 500. Correct response is 404. E2E test `sc5.spec.ts` expects 400/404/410 but receives 500, causing CI failure.

### BUG-004 — CORS wildcard `*` active on prod API gateway [HIGH]

- **Source:** Backlog F-03 (open)
- **Detail:** `CORS_ALLOWED_ORIGINS=*` on `ca-api-gateway-prod`. The web UI sends credential-bearing Entra tokens. Wildcard CORS allows any origin to make credentialed cross-origin requests with those tokens.
- **Fix:** `az containerapp update --name ca-api-gateway-prod ... --set-env-vars "CORS_ALLOWED_ORIGINS=https://ca-web-ui-prod..."`

### BUG-005 — Arc MCP E2E tests always fail — URL env var mismatch [HIGH]

- **Files:** `e2e/arc-mcp-server.spec.ts:27`, Backlog F-06
- **Detail:** The spec reads `process.env.ARC_MCP_SERVER_URL` but the backlog fix specifies `E2E_ARC_MCP_URL`. The env var is never set from either name in CI. All Arc MCP E2E tests fail in every environment and provide no coverage signal.

### BUG-006 — SSE reconnect E2E test fails [MEDIUM]

- **Source:** Backlog F-08 (open)
- **Detail:** Test "SSE stream delivers events with sequence IDs" fails — `response.ok` evaluates false. Real SSE events require the Foundry RBAC fix (F-01, now resolved), but the test itself may have a secondary issue with dev-mode auth not generating real stream events.

### BUG-007 — Auth test stubs permanently skipped [LOW]

- **File:** `services/web-ui/__tests__/auth.test.tsx`
- **Detail:** Three MSAL auth tests are `it.skip()` with `// TODO: Plan 05-01`. MsalProvider wrapping, unauthenticated template, and authenticated template have zero automated test coverage. Never implemented since Phase 5.

### BUG-008 — Detection-plane integration suppression tests are empty [LOW]

- **File:** `services/detection-plane/tests/integration/test_suppression.py`
- **Detail:** Four test bodies contain only `# TODO: Implement after Phase 4 deployment`. Alert suppression (DETECT-007) is architecturally documented but has zero test coverage.

---

## Tech Debt

### DEBT-001 — Agent Framework pinned to old beta — not on RC path [HIGH]

- **File:** `agents/requirements-base.txt:9` — `agent-framework==1.0.0b260107`
- **Detail:** The codebase deliberately avoids `agent-framework==1.0.0rc5` because rc5 introduced a breaking API overhaul (Agent/tool/WorkflowBuilder) incompatible with `agentserver-agentframework b10–b15`. The agents run on a superseded beta. When the framework reaches GA, a migration to the new API (`ChatAgent`, `@ai_function`, `WorkflowBuilder`) is required across all 8 agents simultaneously.
- **Risk:** Any upstream change from Microsoft to how the `b260107` beta is hosted or resolved breaks all agents.

### DEBT-002 — Hardcoded domain agent Foundry IDs in `chat.py` [HIGH]

- **File:** `services/api-gateway/chat.py:229–238`
- **Detail:** Eight prod Foundry agent IDs (`asst_rPDw83...`, etc.) are hardcoded in `_approve_pending_subrun_mcp_calls()`. These IDs are specific to the current production Foundry project and will break silently if agents are re-created, renamed, or migrated. Should be driven by the `*_AGENT_ID` env vars already used elsewhere.

### DEBT-003 — Raw Foundry REST calls bypass SDK — preview API version hardcoded [HIGH]

- **File:** `services/api-gateway/chat.py:201, 250, 255, 271, 299`
- **Detail:** Several functions bypass the SDK and call `api-version=2025-05-15-preview` directly because the SDK's `threads.list()` ignores `limit` (~18s latency) and doesn't expose `submit_tool_approval`. Auth logic (`DefaultAzureCredential`) is duplicated inline. Preview API versions expire without notice.

### DEBT-004 — In-memory rate limiters don't scale across multiple Container App replicas [HIGH]

- **Files:** `services/api-gateway/http_rate_limiter.py`, `services/api-gateway/rate_limiter.py`
- **Detail:** Both rate limiters use in-process Python data structures. Container Apps can scale horizontally — per-instance limits give N times the allowed rate under multi-replica deployments. Redis or Azure Cache for Redis is the correct fix.

### DEBT-005 — In-memory Teams conversation state and escalation dedup — lost on restart [HIGH]

- **Files:** `services/teams-bot/src/services/conversation-state.ts:7`, `services/teams-bot/src/services/escalation.ts:9`
- **Detail:** `conversationMap` and `lastReminderMap` are `Map` instances in memory. Acknowledged as "Acceptable for Phase 6 MVP." Any pod restart or scale-in event loses all thread mappings and reminder dedup state. After restart, all pending approvals above the reminder threshold will get duplicate reminder cards immediately.

### DEBT-006 — Azure MCP Server runs with `--dangerously-disable-http-incoming-auth` [HIGH]

- **File:** `services/azure-mcp-server/Dockerfile` (CMD line)
- **Detail:** The container starts azmcp with HTTP auth fully disabled. The MCP server has `ingress: external = true`, meaning it is accessible from the internet without authentication. Debug notes explicitly flag: "add proper Entra auth in production." No fix has been scheduled. The server has subscription-level `Reader` access to all Azure resources.

### DEBT-007 — `SELECT *` and cross-partition Cosmos queries [MEDIUM]

- **Files:** `services/api-gateway/approvals.py:64,80`, `services/api-gateway/incidents_list.py:79`, `services/api-gateway/audit_export.py:156`
- **Detail:** Multiple Cosmos DB queries use `SELECT *` with `enable_cross_partition_query=True`. No field projections, no partition-key targeting. As alert and approval data grows, these will become expensive scans.

### DEBT-008 — `main.py` at 649 lines — exceeds file size target [MEDIUM]

- **File:** `services/api-gateway/main.py`
- **Detail:** Contains startup logic, route registration, middleware, CORS config, rate limiting, SSE streaming, and background task wiring. No single-responsibility principle applied. Should be decomposed into focused modules.

### DEBT-009 — 14 broad `except Exception` clauses in `chat.py` mask logic errors [MEDIUM]

- **File:** `services/api-gateway/chat.py`
- **Detail:** Nearly every Foundry and REST call is wrapped in `except Exception as exc: logger.warning(...)`. This is intentional for non-blocking paths but also masks real bugs (e.g., BUG-001 above is silently swallowed by one of these). Makes debugging chat failures extremely difficult.

### DEBT-010 — Entra Agent ID provisioned under a Preview API [MEDIUM]

- **File:** `terraform/` (azapi resources)
- **Detail:** CLAUDE.md flags: "Important for agent identity governance but the API may change before GA." The `2025-10-01-preview` API version for `Microsoft.Foundry/agents` data-plane resources may introduce breaking changes before GA.

### DEBT-011 — Terraform ownership of Entra app registrations deferred [MEDIUM]

- **File:** `TODO.md` (DEFERRED entry), `terraform/envs/prod/terraform.tfvars`
- **Detail:** `enable_entra_apps = false` and `enable_teams_bot = false` in prod. Terraform doesn't own the web UI MSAL app registration or the Teams bot app registration. Secret rotation and redirect URI management are manual. Blocked on Global Admin consent for `Application.ReadWrite.All`.

### DEBT-012 — Duplicate payload mapper logic in Fabric function [MEDIUM]

- **Files:** `services/detection-plane/payload_mapper.py` (canonical), `fabric/user-data-function/main.py:63` (copy)
- **Detail:** The comment acknowledges this is intentional to avoid import dependencies. Both implementations must be kept in sync manually. Divergence produces malformed `IncidentPayload` objects rejected by the gateway with silent 422 errors.

### DEBT-013 — Azure MCP Server not managed by Terraform [MEDIUM]

- **Source:** `agent-deployment-and-mcp-wiring.md` — Remaining Work item #3
- **Detail:** `ca-azure-mcp-prod` was deployed ad-hoc via `scripts/deploy-azure-mcp-server.sh`. Not in any Terraform module: will not be reproduced in dev/staging, `terraform plan` detects no drift, infrastructure documentation is incomplete.

### DEBT-014 — `sys.path` manipulation for detection-plane import in gateway [MEDIUM]

- **File:** `services/api-gateway/dedup_integration.py:16–21`
- **Detail:** Runtime `sys.path.insert(0, ...)` to import the detection-plane dedup module. Fragile, environment-dependent, and opaque. Should be a proper Python package with declared dependencies.

### DEBT-015 — `console.log/warn/error` instead of structured logging in teams-bot [MEDIUM]

- **Files:** `services/teams-bot/src/services/proactive.ts`, `escalation.ts`, `routes/notify.ts`, `index.ts`, `instrumentation.ts` — ~15 production `console.*` calls
- **Detail:** Unstructured log output cannot be filtered, sampled, or correlated in Log Analytics. Structured JSON logs (e.g., `pino`) are searchable; `console.log` is not.

### DEBT-016 — Approval scope check uses unsafe substring matching [MEDIUM]

- **File:** `services/api-gateway/approvals.py:128–135`
- **Detail:** `if prod_sub and prod_sub in resource_id` — using `in` for subscription ID matching on a resource ID string. A subscription ID that is a prefix of another produces false positives. Should use exact segment matching on the `/subscriptions/<id>/` path component.

---

## Security Concerns

### SEC-001 — Azure MCP Server externally exposed with no auth [CRITICAL]

- See DEBT-006. The MCP server has `ingress: external = true` and `--dangerously-disable-http-incoming-auth`. Any internet client can invoke it without credentials and read all Azure resources across the monitored subscriptions.

### SEC-002 — CORS wildcard on prod API gateway with Entra Bearer tokens [HIGH]

- See BUG-004. A malicious page can make credentialed cross-origin requests to the API gateway using a victim's Entra token if the victim visits that page while authenticated.

### SEC-003 — Dev-mode auth bypass silently active in production [HIGH]

- **Files:** `services/api-gateway/auth.py`, `services/teams-bot/src/services/auth.ts`
- **Detail:** Both the gateway (Python) and the Teams bot (TypeScript) fall back to unauthenticated dev mode when `AZURE_CLIENT_ID` is absent. The gateway returns a dummy `{"sub": "dev-user"}` claims dict. Phase 8 validation confirmed auth is in dev mode in production: `AZURE_CLIENT_ID` is not set on the api-gateway Container App. All requests reach the gateway without Entra token validation.

### SEC-004 — Web UI proxy routes forward requests without auth token [HIGH]

- **Files:** All `services/web-ui/app/api/proxy/*/route.ts` handlers
- **Detail:** No `Authorization` header is forwarded from the browser's MSAL token to the API gateway. The gateway currently accepts this because auth is in dev mode (SEC-003). When auth is properly enabled, all web UI functionality will break simultaneously.

### SEC-005 — E2E CI runs without Entra auth — auth vulnerabilities not caught [MEDIUM]

- **Source:** Backlog F-05 (open)
- **Detail:** `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_API_AUDIENCE` not set in GitHub Actions `staging` environment. All CI E2E runs use `Bearer dev-token`. Auth vulnerabilities would not be detected by the E2E suite.

### SEC-006 — Teams bot falls back to `"dev-token"` if `AZURE_CLIENT_ID` absent [MEDIUM]

- **File:** `services/teams-bot/src/services/auth.ts:32`
- **Detail:** If `AZURE_CLIENT_ID` is somehow absent from a prod container, the bot silently sends `Authorization: Bearer dev-token` to the API gateway. The failure mode is completely silent — no error, no log escalation.

### SEC-007 — OTel / App Insights disabled if `APPLICATIONINSIGHTS_CONNECTION_STRING` not set [MEDIUM]

- **File:** `services/api-gateway/main.py:171`
- **Detail:** If the env var is absent, OTel is silently disabled with a warning log. Auth failures, remediation approvals, and security events would not appear in App Insights — breaking the audit trail required for compliance.

### SEC-008 — `azuread_application_password` expires 2027-03-26 with no rotation alert [MEDIUM]

- **File:** `terraform/envs/prod/main.tf`
- **Detail:** The Fabric SP client secret has a fixed expiry. No Azure Monitor alert is configured for credential expiry. Silent expiry breaks the entire detection-plane → gateway pipeline.

---

## Performance Risks

### PERF-001 — Foundry SDK `threads.list()` ignores `limit` — ~18s latency [HIGH]

- **File:** `services/api-gateway/chat.py:220–227` (comment documents this)
- **Detail:** The SDK's `threads.list()` returns ALL threads (~18s). The sub-run MCP approval function works around this by calling the REST API with `limit=5` (~1.5s). Any future code path that accidentally uses SDK `threads.list()` without the workaround will introduce 18s of latency per SSE poll cycle.

### PERF-002 — Polling-based SSE stream creates sustained Foundry API load [MEDIUM]

- **File:** `services/web-ui/app/api/stream/route.ts`
- **Detail:** Each active SSE connection generates continuous polling against `GET /api/v1/chat/{thread}/result`, which calls Foundry `runs.get()`. Under concurrent users this multiplies Foundry API calls significantly, potentially triggering TPM rate limits on the Foundry model deployment.

### PERF-003 — `CosmosClient` and `DefaultAzureCredential` created per-request [MEDIUM]

- **Files:** `services/api-gateway/approvals.py`, `incidents_list.py`, `dedup_integration.py`, `audit.py`, `foundry.py`
- **Detail:** New `DefaultAzureCredential()` and `CosmosClient()` instances are created on each request. `DefaultAzureCredential` probes a chain of credential providers on first use (including IMDS HTTP calls). Under load: IMDS latency spikes, Cosmos SDK TCP connection pool exhaustion, high token refresh frequency. The shared agents module (`agents/shared/auth.py`) uses `@lru_cache` correctly; the gateway doesn't.

### PERF-004 — In-memory rate limiters reset on pod restart [LOW]

- See DEBT-004. Rate limits start fresh after deployments, allowing burst traffic during rollouts.

---

## Missing Features / Gaps

### GAP-001 — Network, Security, SRE, Arc MCP tool groups not wired in Foundry [HIGH]

- **Source:** Backlog F-09, F-10, F-11 (all open)
- **Detail:** Network agent returns "tool group was not found" for NSG queries. Security agent returns same for Defender alerts. Arc and SRE agents fall back to the compute tool surface. Three Azure MCP tool groups (`Microsoft.Network`, `Microsoft.Security`, Arc MCP + SRE cross-domain) need to be registered as MCP connections on the Foundry project.

### GAP-002 — OTel manual spans not active in prod [HIGH]

- **Source:** Backlog OTel item (open)
- **Detail:** Manual OTel spans (`foundry.*`, `mcp.*`, `agent.*`) added in Phase 8 have never been deployed — the Container App was not rebuilt. App Insights has no per-agent or per-tool-call latency data.

### GAP-003 — Runbooks not seeded in prod — RAG search broken [HIGH]

- See BUG-002. No runbook-assisted triage is possible until `scripts/seed-runbooks/seed.py` is run against prod PostgreSQL.

### GAP-004 — Teams bot proactive messaging broken (`TEAMS_CHANNEL_ID` not set) [HIGH]

- **File:** `services/api-gateway/teams_notifier.py:46`
- **Detail:** `TEAMS_CHANNEL_ID` env var is empty on `ca-teams-bot-prod`. Proactive detection-plane alerts to Teams channels are silently skipped. Reactive (user → bot → reply) works; unsolicited alerting does not.

### GAP-005 — Detection plane entirely disabled in all environments [HIGH]

- **File:** `terraform/envs/prod/main.tf:258` — `enable_fabric_data_plane = false`
- **Detail:** Fabric workspace, Eventhouse, KQL database, Activator, and OneLake lakehouse are not provisioned in any environment. The automated detection pipeline does not exist. Alerts can only be injected via simulation scripts. The platform's core value proposition (continuous automated monitoring) is architecturally implemented but operationally absent.

### GAP-006 — APIM layer absent — no API versioning, throttling, or developer portal [MEDIUM]

- **Source:** Phase 7 architectural decision: "No APIM — ~$700/month cost not justified without production traffic."
- **Detail:** Direct Container Apps ingress means no centralized auth policy, no API versioning, no developer-facing rate limiting, and no monetization path.

### GAP-007 — Fabric IQ / Operations Agent semantic layer not implemented [MEDIUM]

- **Detail:** The semantic enrichment layer using Fabric IQ / Operations Agent is explicitly excluded from the critical path (Preview). No data enrichment or semantic alerting layer exists today.

### GAP-008 — No multi-region / HA for Cosmos DB in dev/staging [MEDIUM]

- **Detail:** Dev and staging use Cosmos DB Serverless with no geo-redundancy. A Cosmos outage would take down deduplication, incident storage, and approval workflows in those environments with no fallback.

### GAP-009 — Arc MCP Server disabled in prod [MEDIUM]

- **File:** `terraform/envs/prod/main.tf` — `enable_arc_mcp_server = false` (implicit)
- **Detail:** The arc-mcp-server Terraform module is toggled off. Arc agent falls back to the compute tool surface (confirmed degraded finding F-11).

### GAP-010 — No monitoring alerts on agent Container App crash loops [MEDIUM]

- **Detail:** Domain agents can silently crash on startup (missing env vars, import errors) and the platform continues accepting incidents with no routing. No Azure Monitor alerts exist on Container App restart counts or revision failure events.

---

## Prod Blockers

These require operator action to restore full production functionality:

| ID | Blocker | Impact |
|---|---|---|
| F-02 | `PGVECTOR_CONNECTION_STRING` not set or prod not seeded | Runbook RAG returns 500 for all triage queries |
| F-03 | `CORS_ALLOWED_ORIGINS=*` on api-gateway prod | Security risk — any origin can make credentialed requests |
| F-04 | Azure Bot Service not in Terraform; Teams channel unconfigured | Teams proactive alerts non-functional |
| F-05 | E2E GitHub Actions secrets not set | E2E CI runs without auth validation |
| F-09 | `Microsoft.Network` MCP tool group not in Foundry | Network agent returns "tool group not found" |
| F-10 | `Microsoft.Security` MCP tool group not in Foundry | Security agent returns "tool group not found" |
| F-11 | Arc MCP + SRE tool groups not in Foundry | Arc/SRE agents fall back to compute surface |
| OTel | Container App not rebuilt with OTel spans | App Insights has zero per-agent/tool latency data |
| TEAMS | `TEAMS_CHANNEL_ID` empty on `ca-teams-bot-prod` | Proactive channel alerting silently skipped |
| TODO | `enable_entra_apps = false` — awaiting Global Admin consent | Entra app lifecycle is manual |
| Step 7 | Prod runbooks not seeded (manual step) | Same as F-02 |
| Step 3 | `LOG_ANALYTICS_WORKSPACE_ID` not set on web-ui | Observability tab shows no data |

---

## Deprecated / Unused Code

### DEP-001 — SSE heartbeat test stubs permanently skipped [LOW]

- **File:** `services/api-gateway/tests/test_sse_heartbeat.py`
- **Detail:** File comment: "permanently skipped with an explanatory message." Two `@pytest.mark.skip` tests have never been implemented since Plan 05-02. Dead test code inflating test counts.

### DEP-002 — `API_GATEWAY_PUBLIC_URL` config retained as deprecated no-op [LOW]

- **File:** `services/teams-bot/src/config.ts`
- **Detail:** Post-Action.Execute migration, this env var is no longer used in card action URLs. Retained for "forward-compatibility" with default `""`. Has no effect and may confuse operators.

### DEP-003 — `use_placeholder_image = true` for Arc MCP Server — real image never deployed [MEDIUM]

- **File:** `terraform/modules/arc-mcp-server/` — `use_placeholder_image = true` in prod
- **Detail:** Set as a first-apply bootstrap workaround. The operator step to push the arc-mcp-server image and flip the flag to `false` is pending. The prod Container App runs the Microsoft hello-world placeholder, not the real arc-mcp-server.

### DEP-004 — `services/api-gateway/migrations/` seed path is a dead code path [LOW]

- **File:** `services/api-gateway/migrations/002_seed_runbooks.py`
- **Detail:** The startup migration runner skips seeding if the Runbook DB is not configured (which it never is in prod). The actual seeding path is the standalone `scripts/seed-runbooks/seed.py`. The migration file duplicates seed data and represents an unmaintained code path that has never successfully run in production.

### DEP-005 — `azure-ai-agentserver-agentframework` has no version pin [MEDIUM]

- **File:** `agents/requirements-base.txt:14` — no specifier after package name
- **Detail:** Every Docker build installs the latest available version of this adapter. A Microsoft breaking release would fail all agent builds simultaneously with no warning.

### DEP-006 — `conftest.py` hand-rolled `agent_framework` stub limits test fidelity [LOW]

- **File:** `conftest.py:24–76`
- **Detail:** A fake `agent_framework` module is installed because the real RC package is not in the CI test environment. Unit tests never exercise real `ChatAgent`, `HandoffOrchestrator`, or `@ai_function` behavior. Orchestrator routing and agent handoff logic are effectively untested.
