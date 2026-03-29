---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: in_progress
last_updated: "2026-03-29T00:15:00.000Z"
progress:
  total_phases: 8
  completed_phases: 7
  total_plans: 30
  completed_plans: 19
current_phase: 08-azure-validation-incident-simulation
current_plan: 08-01
---

# Azure Agentic Platform (AAP) — Project State

> Last updated: 2026-03-29 — Phase 8 started. Plan 08-01 PARTIAL — Task 08-01-01 complete (--create flag added to configure-orchestrator.py); tasks 08-01-02 through 08-01-06 require operator execution (see 08-01-USER-SETUP.md).
>
> Last activity: 2026-03-29 - Quick task 260329-qro: Validated 08-01 provisioning gaps — 2/5 complete; ORCHESTRATOR_AGENT_ID ✅ set (asst_NeBVjCA5isNrIERoGYzRpBTu), CORS ⚠️ still `*`, RBAC ❌ missing, Bot Service ❌ missing, GitHub secrets ❌ missing

---

## Current Phase

**Phase 7: Quality & Hardening — ✅ COMPLETE (6/6 plans)**

Plan 07-01 complete: OTel auto-instrumentation on api-gateway (Python, `azure-monitor-opentelemetry`) and teams-bot (TypeScript, `@azure/monitor-opentelemetry`). Observability tab added to Web UI DashboardPanel as 5th tab — polling API route queries Application Insights KQL (agent latency P50/P95, pipeline lag, active errors) and Cosmos DB (approval queue depth). 9 new components (ObservabilityTab, MetricCard, AgentLatencyCard, PipelineLagCard, ApprovalQueueCard, ActiveErrorsCard, TimeRangeSelector).

Plan 07-02 complete: Remediation audit trail (REMEDI-007) — `remediation_logger.py` fire-and-forget OneLake write hooked into `approvals.py` for approve/reject/expire paths with full 10-field schema. Audit export (AUDIT-006) — `audit_export.py` + `GET /api/v1/audit/export` endpoint + "Export Report" button in AuditLogViewer with browser download. 12 unit tests pass.

Plan 07-03 complete: 60 synthetic runbooks (10 per domain × 6 domains: compute, network, storage, security, arc, sre) in `scripts/seed-runbooks/runbooks/`. Idempotent `seed.py` (ON CONFLICT upsert, text-embedding-3-small). `validate.py` with SIMILARITY_THRESHOLD=0.75 and 12 domain queries. Seed + validate steps integrated into staging CI `apply-staging` job only; prod is manual per D-09.

Plan 07-04 complete: Terraform prod extended — `agent-apps` module supports teams-bot (port 3978) and web-ui (port 3000) with configurable `target_port`; CORS_ALLOWED_ORIGINS env var wired end-to-end from Python to Terraform. Security CI workflow `security-review.yml` with 3 jobs (bandit, npm audit, secrets scan). All 12 prod modules confirmed present; `terraform fmt` passes.

Plan 07-05 complete: E2E test infrastructure — root `e2e/playwright.config.ts` (workers:1, timeout:120s, retries:2 in CI); `global-setup.ts` (MSAL CCAF auth + Cosmos E2E container creation); `global-teardown.ts` (idempotent cleanup); `fixtures/auth.ts` (bearerToken, apiRequest, apiUrl, baseUrl). sc1–sc6 de-mocked to real endpoints. `phase7-e2e.yml` CI gate with 15-min timeout, blocks merge on PR failure.

Plan 07-06 complete: 5 new E2E spec files — `e2e-incident-flow.spec.ts` (E2E-002), `e2e-hitl-approval.spec.ts` (E2E-003), `e2e-rbac.spec.ts` (E2E-004), `e2e-sse-reconnect.spec.ts` (E2E-005), `e2e-audit-export.spec.ts` (AUDIT-006 E2E validation). 15 test functions total; all tests use real endpoints with graceful skip when infra unavailable; no `page.route()` mocks.

---

## Project

**Azure Agentic Platform (AAP) — Milestone v1.0**

---

## Core Value

> Operators can understand, investigate, and resolve any Azure infrastructure issue — across all subscriptions and Arc-connected resources — through a single intelligent platform that shows its reasoning transparently and never acts without human approval.

---

## Phase Summary

| # | Phase | Status |
|---|---|---|
| 1 | Foundation | Complete (5/5 plans) |
| 2 | Agent Core | Complete (2026-03-26) |
| 3 | Arc MCP Server | Complete (2026-03-26) |
| 4 | Detection Plane | ✅ Complete (2026-03-26) — all 4 plans, 92 unit tests, 8 requirements |
| 5 | Triage & Remediation + Web UI | ✅ Complete (2026-03-27) — all 7 plans, 40 unit tests, 4 E2E specs, CI workflow |
| 6 | Teams Integration | ✅ Complete (2026-03-27) — all 5 plans, 100 tests at 92.34% coverage, 6 TEAMS requirements |
| 7 | Quality & Hardening | ✅ Complete (2026-03-27) — all 6 plans, E2E-001–005, REMEDI-007, AUDIT-006, 60 runbooks, security CI, Terraform prod |
| 8 | Azure Validation & Incident Simulation | 🔄 In Progress (1/5 plans) — Plan 08-01: --create flag added; operator steps pending |

---

## Blockers/Concerns

**Phase 8 blocking items (operator must complete before chat validation):**
- `ORCHESTRATOR_AGENT_ID` must be created in Foundry and set on `ca-api-gateway-prod` (task 08-01-02 + 08-01-03)
- `Azure AI Developer` RBAC must be assigned to gateway MI `69e05934-1feb-44d4-8fd2-30373f83ccec` (task 08-01-04)
- See `.planning/phases/08-azure-validation-incident-simulation/08-01-USER-SETUP.md` for exact commands

---

## Key Decisions

| Decision | Phase | Rationale |
|---|---|---|
| Centralized private-endpoints module | 1-01 | All PEs in one module eliminates duplication and avoids circular deps between networking and resource modules |
| PostgreSQL VNet injection over PE | 1-01 | Azure-recommended approach for Flexible Server; delegated subnet is simpler than PE |
| Interface-first module design | 1-01 | All variables.tf/outputs.tf fully defined before implementation enables parallel work in Plans 02-04 |
| No PEs in networking module | 1-02 | Centralized in modules/private-endpoints to avoid circular deps where networking needs resource IDs from dependent modules |
| Reserved subnet for Phase 4 Event Hub | 1-02 | Pre-allocate snet-reserved-1 at 10.0.64.0/24 to avoid VNet CIDR changes later |
| Foundry subnet gets own NSG | 1-02 | ISSUE-08: Foundry subnet needs inbound 443 from Container Apps for future PE traffic |
| No local-exec for pgvector on VNet-isolated PostgreSQL | 1-03 | ISSUE-04: GitHub runners can't reach VNet-injected PG; deferred to PLAN-05 CI workflow |
| ACR name uses random_string suffix | 1-03 | ISSUE-10: Azure Container Registry names must be globally unique |
| Foundry project inherits identity from parent account | 1-03 | ISSUE-09: azurerm_cognitive_account_project does not support identity block |
| Dev/staging Cosmos Serverless; prod Provisioned Autoscale | 1-04 | Cost optimization for non-prod; multi-region westus2 secondary for prod HA |
| Tiered PostgreSQL SKUs per environment | 1-04 | dev B1ms, staging B2ms, prod GP_Standard_D4s_v3 — General Purpose needed for prod workloads |
| Identical env structure, parameter-only differences | 1-04 | All envs share same provider/output/variable structure; only module parameters differ to minimize env drift |
| Tag lint via jq on tfplan.json | 1-05 | Catches both null tags and missing required keys; runs only when plan succeeds (ISSUE-05/06) |
| pgvector setup via temporary firewall rule in CI | 1-05 | ISSUE-04 resolution: GitHub runners can't reach VNet-injected PG directly; temporary firewall rule pattern with always-cleanup |
| Docker push as reusable workflow_call | 1-05 | Avoids duplication across agent image builds in Phase 2+; composable per-agent |
| SystemAssigned identity IS the Entra Agent ID | 2-01 | Container App SystemAssigned managed identity registers as Entra Agent ID automatically; no separate azapi_data_plane_resource block needed |
| RBAC merge() pattern for flat map | 2-01 | merge() with flat keyed map avoids Terraform index instability vs. concat() list approach; replace(sub_id, "-", "") for safe keys |
| Arc Agent as Phase 2 stub | 2-01 | Arc Agent Container App + identity provisioned but returns structured pending response; full tooling deferred to Phase 3 Arc MCP Server |
| Prod multi-subscription RBAC variables | 2-01 | compute/network/storage/all_subscription_ids vars added to prod only; dev/staging default all to platform subscription_id |
| ETag optimistic concurrency for Cosmos budget records | 2-02 | Prevents lost-update race conditions when multiple agent iterations write to the same session record |
| pythonpath=["."] in pyproject.toml | 2-02 | Required for pytest to resolve `agents.shared.*` imports from repo root without installing the package |
| Dev-mode auth fallback for gateway | 2-03 | AZURE_CLIENT_ID absent → validator is None → all requests allowed with WARNING; enables local development without Entra credentials |
| Optional[X] over X\|None in FastAPI signatures | 2-03 | FastAPI's get_type_hints() evaluates annotations at runtime; `|` union fails on Python 3.9 even with `from __future__ import annotations` |
| conftest.py hyphenated package shim | 2-03 | Python cannot import hyphenated directories; shim registers `services/api-gateway` as `sys.modules["services.api_gateway"]` + setattr on parent for mock.patch compat |
| Gateway as thin router only | 2-03 | No business logic in gateway; all incident reasoning deferred to Foundry agent threads; keeps gateway small and independently testable |
| Integration tests excluded from fast unit CI run | 3-04 | pytest.mark.integration prevents prolonged disconnection and triage workflow tests from running in the fast unit test CI job; they run in a separate integration job |
| E2E pagination tests use mock ARM server via AZURE_ARM_BASE_URL | 3-04 | Avoids real Azure credentials and expensive Arc estate provisioning in CI; mock ARM seeded with 120 Arc machines covers the >100 E2E-006 requirement |
| azapi_resource for all Fabric data-plane items | 4-01 | Fabric REST API types supported via azapi; consistent with project Fabric Terraform pattern |
| count gate on Fabric SP resources | 4-01 | gateway_app_client_id="" default allows deploy before API gateway Entra app is registered |
| Fixed end_date for azuread_application_password | 4-01 | Avoids perpetual diff from timeadd(timestamp(),...) per WARN-D4a; fixed to 2027-03-26T00:00:00Z |
| Activity Log module with for_each over subscription IDs | 4-01 | Supports multi-subscription export — single sub in dev/staging, all_subscription_ids in prod |
| Service Bus DNS zone in networking module | 4-01 | Follows existing pattern: DNS zones + VNet links in networking, PEs in private-endpoints |
| IsTransactional=false on KQL hop 1 (RawAlerts→EnrichedAlerts) | 4-02 | Prevents data loss: if EnrichAlerts() fails with IsTransactional=true, source ingestion into RawAlerts is rolled back; false ensures raw alert is always preserved (Risk 6 mitigation) |
| Python classify_domain() uses exact then prefix match | 4-02 | Exact match covers known types; prefix match handles broad categories (microsoft.security/*, microsoft.azurearcdata/*) — mirrors KQL has_any substring behavior |
| DETECT-007 satisfied by architecture | 4-02 | Suppressed alerts never reach Event Hub (Azure Monitor processing rules suppress Action Group invocation upstream); no code needed, documented in KQL comments |
| Dedup check is non-blocking in gateway | 4-03 | COSMOS_ENDPOINT absent → skip dedup silently; ImportError → skip silently; prevents dedup bugs from taking down incident ingestion |
| Fire-and-forget Azure Monitor sync | 4-03 | Platform state transition must never block on external sync; Azure Monitor failures logged but not raised (non-blocking by design) |
| Self-contained UDF mapping copy in Fabric | 4-03 | Fabric runtime cannot import services/detection-plane; mapping logic duplicated intentionally, clearly commented with canonical reference |
| det- prefix on incident_id | 4-03 | Provides traceability: any incident ID starting with det- was created via the detection plane (vs. manual/API ingestion) |
| UDF tests import at module level (not per-test reload) | 4-04 | importlib.reload() pattern caused MSAL ConfidentialClientApplication to call Entra authority discovery before @patch applied; module-level import + patch("main.func") resolves correctly |
| KQL consistency test regex requires full path (has /) | 4-04 | classify_domain.kql uses has_any() with both full paths and prefix-only values (Microsoft.Security); regex r'"(Microsoft\.[^/"]+/[^"]+)"' skips prefix-only values avoiding false "sre" failures |
| Integration stubs use @pytest.mark.skip on class + pytestmark | 4-04 | Both marks required: pytestmark for -m filtering, @pytest.mark.skip so tests don't run without infra even when -m integration is specified |
| Action.Execute for teams-bot approval/reminder cards | 6-01 | Action.Http is NOT supported for bot-sent Adaptive Cards in Teams (per 06-RESEARCH.md Section 2); must use Action.Execute with verb + data fields |
| createNotifyRouter(config) factory for Express testability | 6-01 | Module-level router binds config at import time, requiring env vars in tests; factory pattern allows injecting mock AppConfig cleanly |
| ESLint 9 requires flat config (eslint.config.js) | 6-01 | ESLint 9 dropped .eslintrc.* support; CJS eslint.config.js used to match commonjs tsconfig output |
| API_GATEWAY_PUBLIC_URL empty-string default (deprecated) | 6-01 | Post-Action.Execute migration, api-gateway public URL is not used in card action URLs; retained in config for forward-compatibility with default "" |
| body.thread_id takes precedence over query param | 6-03 | Action.Execute sends data in card body; body is more explicit than query param; backward compat maintained |
| GET /api/v1/approvals before /{approval_id} route | 6-03 | FastAPI path matching: parameterized route would match query-only requests as approval_id |
| notify_teams() generic dispatcher replaces _build_adaptive_card | 6-03 | Card rendering moved to TypeScript bot; gateway sends structured payloads via single dispatcher |
| Cross-partition query for pending approvals | 6-03 | Acceptable for small pending counts; used by scheduler, not hot-path |
| Constructor-based event registration for Bot Framework | 6-02 | Bot Framework SDK's onMessage/onInstallationUpdate are event registrators, not overridable handlers; must use this.onMessage(handler) pattern for TypeScript type safety |
| handleMessage as public method for testability | 6-02 | Direct method call in tests avoids Bot Framework event pipeline; onAdaptiveCardInvoke remains protected override |
| In-memory conversation state with 24h TTL | 6-02 | Map<teamsConversationId, {threadId, incidentId, lastUsed}> sufficient for MVP; upgrade to Cosmos DB if durability needed |
| Dev-mode auth: isDevelopmentMode() returns dev-token | 6-02 | Matches api-gateway auth.py pattern — no AZURE_CLIENT_ID = dev mode; consistent across all platform services |
| In-memory dedup Map for escalation reminders | 6-04 | Map<approvalId, lastReminderTimestamp> sufficient for single-instance MVP; upgrade to Cosmos DB if HA/multi-instance needed |
| 503 pre-flight on notify route | 6-04 | hasConversationReference() check returns 503 Service Unavailable when bot not installed — prevents silent failures from api-gateway calls |
| 30-second startup delay for escalation scheduler | 6-04 | Allows bot installation event to fire and ConversationReference to be captured before scheduler attempts proactive posting |
| Placeholder PNG icons for Teams manifest | 6-05 | Minimal single-color PNGs (32x32 outline, 192x192 color); real icons deferred to pre-production design phase |
| describe.skip for integration test stubs | 6-05 | Stubs define full test plans but require live Teams environment; Phase 7 Quality & Hardening will implement real integration tests |
| vitest.config.ts + CI --exclude double-guard | 6-05 | Both vitest config exclude and CI --exclude flag ensure integration stubs never run in unit test CI |
| OTel auto-instrumentation only in Phase 7 | 7-01 | Manual spans (per-Foundry-call, per-tool-call latency) deferred to Phase 8; auto-instrumentation via azure-monitor-opentelemetry sufficient for production observability baseline |
| No APIM in Phase 7 | 7-04 | Standard v2 ~$700/month cost not justified without production traffic; direct Container Apps ingress sufficient; revisit at first multi-tenant or API monetization requirement |
| E2E tests gracefully skip when infra unavailable | 7-06 | test.skip() on non-202/503 responses prevents CI failures in environments without full Azure infra while still verifying API contract |
| Prod seed is manual operational step | 7-03 | Never run seed script against prod automatically; seed/validate only in staging CI; prod seed documented in ops runbook per D-09 |
| CORS locked via env var, not hardcoded | 7-04 | CORS_ALLOWED_ORIGINS env var replaces hardcoded wildcard; prod Container App sets explicit origin; default `*` maintained for dev/staging convenience |
| Tasks 08-01-02 through 08-01-06 are operator-only steps | 8-01 | These steps require live Azure credentials, Entra admin permissions, or secret values not available to autonomous agent; documented in 08-01-USER-SETUP.md |
| --create guard against existing ORCHESTRATOR_AGENT_ID | 8-01 | Mutual exclusion prevents accidental double-create; check runs before client.create_agent() API call to fail fast |

---

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260325-gqo | Research microsoftgbb/agentic-platform-engineering repo and incorporate findings into planning docs | 2026-03-25 | ccc5d96 | [260325-gqo-research-microsoftgbb-agentic-platform-e](./quick/260325-gqo-research-microsoftgbb-agentic-platform-e/) |
| 260326-x3n | Backfill VALIDATION.md for phases 1 and 3 | 2026-03-26 | b9a32d5 | [260326-x3n-backfill-validation-md-for-phases-1-and-](./quick/260326-x3n-backfill-validation-md-for-phases-1-and-/) |
| 260327-x4g | Fix ObservabilityTab container-type bug, add tab icons, and modernise web-UI visual design | 2026-03-28 | 03994fb | [260327-x4g-fix-observabilitytab-container-type-bug-](./quick/260327-x4g-fix-observabilitytab-container-type-bug-/) |
| 260328-1ca | Move run-mock.sh to scripts folder and update the script accordingly | 2026-03-27 | 4b26f66 | [260328-1ca-move-run-mock-sh-to-scripts-folder-and-u](./quick/260328-1ca-move-run-mock-sh-to-scripts-folder-and-u/) |
| 260328-2ir | Deploy images to container registry — teams-bot build, deploy-all workflow, naming fix | 2026-03-28 | 94d0b8b | [260328-2ir-deploy-images-to-container-registry](./quick/260328-2ir-deploy-images-to-container-registry/) |
| 260328-va0 | Validate MANUAL-SETUP.md provisioning state — 3 DONE, 3 PARTIAL, 1 PENDING, 1 SKIPPED, 1 CANNOT_VERIFY | 2026-03-28 | fcca5fc | [260328-va0-validate-manual-setup-md-provisioning-st](./quick/260328-va0-validate-manual-setup-md-provisioning-st/) |
| 260329-315 | Review and clean up 65 uncommitted changes — gitignore coverage/build artifacts, commit real files | 2026-03-29 | 3b53ff1 | [260329-315-review-uncommitted-changes](./quick/260329-315-review-uncommitted-changes/) |
| 260329-qro | validate 08-01 provisioning gaps are done | 2026-03-29 | — | [260329-qro-validate-08-01-provisioning-gaps-are-don](./quick/260329-qro-validate-08-01-provisioning-gaps-are-don/) |

---

## Links

- [PROJECT.md](.planning/PROJECT.md) — project context, requirements, key decisions
- [REQUIREMENTS.md](.planning/REQUIREMENTS.md) — full requirement list with REQ-IDs
- [ROADMAP.md](.planning/ROADMAP.md) — phases, success criteria, traceability
- [research/ARCHITECTURE.md](.planning/research/ARCHITECTURE.md) — system architecture and build order
- [research/FEATURES.md](.planning/research/FEATURES.md) — feature categories and table stakes
- [research/SUMMARY.md](.planning/research/SUMMARY.md) — recommended stack and critical pitfalls
