---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-26T15:40:15.661Z"
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 13
  completed_plans: 13
---

# Azure Agentic Platform (AAP) — Project State

> Last updated: 2026-03-26 — Phase 4: COMPLETE (4/4 plans) — 92 unit tests passing, 18 integration stubs scaffolded, CI workflows live, DETECT-007 documented

---

## Current Phase

**Phase 4: Detection Plane — ✅ Complete (4/4 plans)**

Current position: 04-04 complete — shared conftest.py fixtures, 14 KQL pipeline unit tests, 10 UDF unit tests, 18 integration stubs (all skipped), Detection Plane CI workflow, Terraform detection workflow, SUPPRESSION.md. All 8 Phase 4 requirements covered. 92 unit tests passing.

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
| 5 | Triage & Remediation + Web UI | Not started |
| 6 | Teams Integration | Not started |
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

---

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260325-gqo | Research microsoftgbb/agentic-platform-engineering repo and incorporate findings into planning docs | 2026-03-25 | ccc5d96 | [260325-gqo-research-microsoftgbb-agentic-platform-e](./quick/260325-gqo-research-microsoftgbb-agentic-platform-e/) |

---

## Links

- [PROJECT.md](.planning/PROJECT.md) — project context, requirements, key decisions
- [REQUIREMENTS.md](.planning/REQUIREMENTS.md) — full requirement list with REQ-IDs
- [ROADMAP.md](.planning/ROADMAP.md) — phases, success criteria, traceability
- [research/ARCHITECTURE.md](.planning/research/ARCHITECTURE.md) — system architecture and build order
- [research/FEATURES.md](.planning/research/FEATURES.md) — feature categories and table stakes
- [research/SUMMARY.md](.planning/research/SUMMARY.md) — recommended stack and critical pitfalls
