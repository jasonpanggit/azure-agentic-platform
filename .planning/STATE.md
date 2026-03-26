---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-26T12:28:47.302Z"
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 9
  completed_plans: 9
---

# Azure Agentic Platform (AAP) — Project State

> Last updated: 2026-03-26 — Phase 3 complete: all 4 plans done (03-01, 03-02, 03-03, 03-04)

---

## Current Phase

**Phase 3: Arc MCP Server — Complete (4/4 plans)**

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
| 4 | Detection Plane | Not started |
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
