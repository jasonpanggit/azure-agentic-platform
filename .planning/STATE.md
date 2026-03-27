---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-27T07:29:08.000Z"
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 25
  completed_plans: 17
---

# Azure Agentic Platform (AAP) — Project State

> Last updated: 2026-03-27 — Phase 6 IN PROGRESS (4/5 plans) — 06-04: Escalation Scheduler + Proactive Card Posting — Background escalation scheduler with 2-minute polling, in-memory dedup, notify route pre-flight guard, 16 new tests, 100 total teams-bot tests at 92.34% coverage.

---

## Current Phase

**Phase 6: Teams Integration — 🔄 IN PROGRESS (4/5 plans)**

Plan 06-01 complete: `services/teams-bot/` scaffold with all card builders, notify endpoint, 58 unit tests at 93.31% coverage, and CI workflow.

Plan 06-02 complete: Bot Framework Integration — AapTeamsBot extends TeamsActivityHandler with message handling (typing indicator, 30s interim, 120s timeout), Action.Execute invoke for approve/reject, GatewayClient HTTP client with managed identity auth, conversation state tracker for thread_id mapping, proactive messaging via ConversationReference + continueConversationAsync, CloudAdapter wired on /api/messages. 26 new tests, 84 total tests at 80.12% coverage.

Plan 06-03 complete: API Gateway changes — ChatRequest thread_id/user_id, thread continuation, GET /api/v1/approvals, body thread_id for Action.Execute, teams_notifier refactored to bot internal endpoint. 22 new tests, 71 api-gateway tests passing.

Plan 06-04 complete: Escalation Scheduler + Proactive Card Posting — Background escalation scheduler polling every 2 minutes with in-memory dedup, notify route pre-flight guard (503 if bot not installed), scheduler wired into index.ts with 30-second startup delay. 16 new tests, 100 total tests at 92.34% coverage.

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
| 6 | Teams Integration | 🔄 In progress (4/5 plans) |
| 7 | Quality & Hardening | Not started |

---

## Blockers/Concerns

None.

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

---

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260325-gqo | Research microsoftgbb/agentic-platform-engineering repo and incorporate findings into planning docs | 2026-03-25 | ccc5d96 | [260325-gqo-research-microsoftgbb-agentic-platform-e](./quick/260325-gqo-research-microsoftgbb-agentic-platform-e/) |
| 260326-x3n | Backfill VALIDATION.md for phases 1 and 3 | 2026-03-26 | b9a32d5 | [260326-x3n-backfill-validation-md-for-phases-1-and-](./quick/260326-x3n-backfill-validation-md-for-phases-1-and-/) |

---

## Links

- [PROJECT.md](.planning/PROJECT.md) — project context, requirements, key decisions
- [REQUIREMENTS.md](.planning/REQUIREMENTS.md) — full requirement list with REQ-IDs
- [ROADMAP.md](.planning/ROADMAP.md) — phases, success criteria, traceability
- [research/ARCHITECTURE.md](.planning/research/ARCHITECTURE.md) — system architecture and build order
- [research/FEATURES.md](.planning/research/FEATURES.md) — feature categories and table stakes
- [research/SUMMARY.md](.planning/research/SUMMARY.md) — recommended stack and critical pitfalls
