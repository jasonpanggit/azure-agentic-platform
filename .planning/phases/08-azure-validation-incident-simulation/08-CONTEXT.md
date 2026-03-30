# Phase 8: Azure Validation & Incident Simulation - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate the full platform is correctly provisioned and functional in Azure against the architecture spec, then simulate incidents end-to-end. This phase has four sub-goals:

1. **Fix provisioning gaps** — Close the gaps identified in the 260328-va0 quick task: create Foundry Orchestrator Agent, complete Foundry RBAC, register Teams bot. These gaps block meaningful end-to-end validation.
2. **Critical-path validation** — Verify the full operator experience: chat → detection → triage → HITL approval → Teams alert. Plus smoke tests on all other platform services (web UI loads, Arc MCP responds, runbooks return results).
3. **Incident simulation** — 7 synthetic scenarios (one per domain + one cross-domain) injected via `POST /api/v1/incidents`, exercising the full agent pipeline with auto-cleanup afterward.
4. **Deferred Phase 7 work** — Full Teams bot round-trip E2E via Bot Connector API, and manual OTel spans for Foundry API calls, MCP tool calls, and agent invocations.

**No new platform features** — This phase proves what was built, fixes what wasn't provisioned, and adds observability depth.

</domain>

<decisions>
## Implementation Decisions

### Validation Scope & Fix Strategy

- **D-01:** Phase 8 **fixes provisioning gaps AND validates** — not just documents. Fix tasks are part of the phase plans. The 260328-va0 report showed the platform is partially provisioned; validation is meaningless until gaps are closed. Fix-then-validate within the same phase.
- **D-02:** Validation depth: **critical path + smoke tests**. Critical path = chat → detection → triage → HITL approval → Teams alert (the core platform value proposition). Smoke tests = basic health checks on all other services (web UI, Arc MCP, runbook search, audit export, observability tab).
- **D-03:** Phase 7 E2E tests (sc1–sc6, e2e-incident-flow, e2e-hitl-approval, e2e-rbac, e2e-sse-reconnect, e2e-audit-export) are **run against prod** as part of validation. The `test.skip()` graceful-skip behavior from Phase 7 should be removed/overridden for Phase 8 — these tests must pass against real endpoints.

### Incident Simulation Design

- **D-04:** Simulation injection method: **direct API injection via `POST /api/v1/incidents`** — no real Azure Monitor alerts fired, no real resource modification. Synthetic payload with realistic `incident_id`, `severity`, `domain`, `affected_resources`, `detection_rule`, and `kql_evidence` fields.
- **D-05:** Scenario scope: **7 scenarios total** — one per domain + one cross-domain:
  - compute: VM high CPU on vm-prod-01
  - network: NSG rule blocking port 443 to app tier
  - storage: storage account quota approaching limit
  - security: Defender alert on suspicious login pattern
  - arc: Arc server connectivity loss (disconnected > threshold)
  - sre: multi-signal SLA breach across services
  - cross-domain: disk-full event triggering both compute + storage agents
- **D-06:** Cleanup: **auto-cleanup after each scenario** — delete Cosmos DB incident and approval records created by the simulation after asserting outcomes. Cleanup is a postcondition of each simulation test function.
- **D-07:** Simulation scenarios are implemented as **Python scripts** in `scripts/simulate-incidents/` (not Playwright tests — no UI needed for API-level simulation). Each scenario is a self-contained script with setup, inject, assert, cleanup steps. A `run-all.sh` orchestrator runs all 7 in sequence.

### Issue Logging & Fix Task Structure

- **D-08:** All validation findings logged in a **single `VALIDATION-REPORT.md`** in the phase directory (`.planning/phases/08-azure-validation-incident-simulation/08-VALIDATION-REPORT.md`). Each finding becomes a GSD todo item via `/gsd:add-backlog`.
- **D-09:** Severity levels: **3-tier** — BLOCKING (platform can't function), DEGRADED (platform works but a feature is broken), COSMETIC (minor UI/docs issues). Phase 8 fixes all BLOCKING issues before marking complete. DEGRADED and COSMETIC findings are logged as follow-up todos.
- **D-10:** Validation report structure per finding:
  ```
  | ID | Service | Description | Severity | Fix | Status |
  ```
  Status: OPEN → IN-PROGRESS → FIXED (updated as fixes are applied within Phase 8).

### Teams Bot Round-Trip E2E (from Phase 7 deferred)

- **D-11:** Full Teams bot E2E uses **Microsoft Teams Bot Connector API** (REST call to the bot's service URL) to simulate a user message sent to the bot in CI. The CI service principal needs `Messaging.Send` permission on the Teams channel. This is a true round-trip test — message in → agent response out.
- **D-12:** New E2E spec: `e2e/e2e-teams-roundtrip.spec.ts` — sends "investigate the CPU alert on vm-prod-01" to the bot service URL, waits for response (streamed back via the existing Teams bot infrastructure), asserts a triage response appears in the Teams channel within 60 seconds.

### Manual OTel Spans (from Phase 7 deferred)

- **D-13:** Manual OTel span scope: **three instrumentation points** in the api-gateway Python service:
  1. **Foundry API calls** — spans for `create_thread`, `post_message`, `poll_response` with attributes: `foundry.thread_id`, `foundry.model`, `foundry.duration_ms`, `foundry.tokens_used`
  2. **MCP tool calls** — spans for each Azure MCP and Arc MCP tool invocation with attributes: `mcp.tool_name`, `mcp.server`, `mcp.duration_ms`, `mcp.outcome` (success/error)
  3. **Agent invocations** — spans per domain agent activation with attributes: `agent.name`, `agent.domain`, `agent.correlation_id`, `agent.duration_ms`
- **D-14:** Manual spans use the **existing OTel setup** (`azure-monitor-opentelemetry` already configured in Phase 7). No new exporters — just add manual instrumentation on top of auto-instrumentation. Spans appear in Application Insights and the Web UI Observability tab.

### Claude's Discretion

- Exact Foundry Orchestrator Agent creation script (CLI commands vs. Terraform vs. Python SDK — whichever is most reliable for CI)
- Teams Bot Connector API authentication flow details (exact header format, token endpoint)
- Python simulation script structure and assertion depth per scenario
- VALIDATION-REPORT.md table formatting details

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Provisioning State (Critical — read first)
- `.planning/quick/260328-va0-validate-manual-setup-md-provisioning-st/260328-va0-REPORT.md` — Exact provisioning gaps found: API Gateway missing ORCHESTRATOR_AGENT_ID, Foundry RBAC incomplete, Teams bot not registered
- `MANUAL-SETUP.md` — Manual provisioning steps for prod; Phase 8 completes the PARTIAL/PENDING steps

### Platform Architecture
- `.planning/research/ARCHITECTURE.md` — Full system architecture diagram, agent graph, data layer
- `.planning/REQUIREMENTS.md` — All 72 requirements with REQ-IDs (Phase 8 validates critical-path requirements)

### Phase 7 E2E Tests (extend/run against prod)
- `e2e/e2e-incident-flow.spec.ts` — E2E-002: full incident flow
- `e2e/e2e-hitl-approval.spec.ts` — E2E-003: HITL approval via Teams/webhook
- `e2e/e2e-rbac.spec.ts` — E2E-004: cross-subscription RBAC
- `e2e/e2e-sse-reconnect.spec.ts` — E2E-005: SSE reconnect
- `e2e/e2e-audit-export.spec.ts` — AUDIT-006 E2E
- `e2e/playwright.config.ts` — E2E test config (BASE_URL, auth, timeouts)
- `e2e/global-setup.ts` — E2E auth and Cosmos container setup fixture

### Services (validation targets)
- `services/api-gateway/main.py` — All endpoint signatures; `POST /api/v1/incidents` payload schema
- `services/api-gateway/approvals.py` — Approval lifecycle (HITL simulation)
- `services/api-gateway/chat.py` — Chat endpoint (operator conversation validation)
- `services/api-gateway/runbook_rag.py` — Runbook retrieval (smoke test)
- `services/teams-bot/src/routes/notify.ts` — Internal notify endpoint (Teams simulation)
- `services/teams-bot/src/bot.ts` — Bot Framework handler (round-trip E2E entry point)
- `services/web-ui/app/` — Next.js routes (web UI smoke tests)

### OTel Instrumentation
- `services/api-gateway/main.py` — Existing auto-instrumentation setup (add manual spans on top)
- `.planning/phases/07-quality-hardening/07-CONTEXT.md` — D-05, D-06, D-07: OTel decisions from Phase 7

### Incident Simulation
- `scripts/configure-orchestrator.py` — Existing orchestrator config script (reference for Foundry agent creation)
- `scripts/run-mock.sh` — Existing mock server (reference for simulation structure)

### CI/CD
- `.github/workflows/staging-e2e-simulation.yml` — Phase 7 E2E CI job (extend for Phase 8 scenarios)
- `.github/workflows/security-review.yml` — Security CI (reference for CI job pattern)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/configure-orchestrator.py`: Existing Python script for Foundry orchestrator config — directly reusable for the Foundry agent creation fix task.
- `scripts/seed-runbooks/seed.py`: Pattern for idempotent seed scripts — simulation scripts should follow the same setup/cleanup pattern.
- `e2e/fixtures/auth.ts`: Playwright auth fixture (bearerToken, apiRequest) — reuse directly for Phase 8 E2E specs.
- `e2e/global-setup.ts` / `global-teardown.ts`: Cosmos DB container create/cleanup pattern — reuse for simulation cleanup.

### Established Patterns
- Python simulation scripts → `scripts/` directory (matches `scripts/seed-runbooks/`, `scripts/configure-orchestrator.py`)
- E2E specs → `e2e/` directory (matches existing sc1–sc6, e2e-incident-flow, etc.)
- Manual OTel spans: `from opentelemetry import trace; tracer = trace.get_tracer(__name__)` — Python OTel manual instrumentation pattern

### Integration Points
- Simulation scripts POST to `POST /api/v1/incidents` — api-gateway must be running and reachable
- VALIDATION-REPORT.md findings → GSD backlog via `/gsd:add-backlog`
- Manual OTel spans export to Application Insights via `APPLICATIONINSIGHTS_CONNECTION_STRING` (already set in Container Apps env from Phase 7)

</code_context>

<specifics>
## Specific Ideas

- **Provisioning fix order matters**: Create Foundry Orchestrator Agent first (get `asst_xxx` ID), then update `ca-api-gateway-prod` env var `ORCHESTRATOR_AGENT_ID`, then grant Foundry RBAC. The api-gateway won't connect to Foundry without this sequence.
- **Simulation scripts should mirror runbook domains**: each simulation scenario maps 1:1 to a runbook domain (compute → VM CPU runbook, arc → Arc connectivity runbook), so the RAG retrieval can be asserted as part of the simulation outcome.
- **BLOCKING threshold for Phase 8 completion**: Phase 8 is NOT complete if any BLOCKING severity finding remains open. DEGRADED findings must have associated todos logged before marking complete.

</specifics>

<deferred>
## Deferred Ideas

- **APIM Standard v2** — Still deferred. No production traffic data yet. Evaluate at first multi-tenant or API monetization requirement.
- **Custom domain + TLS via Azure Front Door** — Deferred from Phase 7. Still no branded URL needed.
- **Azure SRE Agent integration** — The Azure SRE Agent (GA March 2026) could be treated as a specialist alongside domain agents. Interesting future capability; out of scope for Phase 8 validation.
- **Multi-subscription E2E with real secondary subscriptions** — Phase 8 validates RBAC with the platform subscription only. True multi-subscription validation (compute sub, network sub, etc.) requires provisioning those subscriptions and is a future ops hardening task.

</deferred>

---

*Phase: 08-azure-validation-incident-simulation*
*Context gathered: 2026-03-29*
