# Phase 1: Foundation - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Provision all Azure infrastructure via Terraform — networking (VNet, subnets, private endpoints, NSGs), Azure AI Foundry workspace + project + gpt-4o deployment, Cosmos DB Serverless + PostgreSQL Flexible Server with pgvector, Container Apps environment + ACR, and Key Vault. Deliver environment isolation (dev/staging/prod) with per-environment state backends and a CI pipeline (plan on PR, apply on merge). No application code, no agents, no agent identities — pure infrastructure delivery.

</domain>

<decisions>
## Implementation Decisions

### Terraform Module Structure
- **D-01:** Per-domain module structure — separate, independently-applyable Terraform directories for each infrastructure domain (e.g., `terraform/networking/`, `terraform/foundry/`, `terraform/databases/`, `terraform/compute-env/`).
- **D-02:** Internal layout (flat domain dirs vs. root-with-local-modules) — **Claude's discretion.** Use whatever is most idiomatic for a platform of this size and complexity.

### Environment Strategy
- **D-03:** Directory-per-environment approach — `envs/dev/`, `envs/staging/`, `envs/prod/` each as their own Terraform root (their own `backend.tf` + tfvars), not Terraform workspaces.
- **D-04:** Each environment directory calls shared modules — `envs/dev/` calls `terraform/modules/networking`, etc. Shared module code; per-env state and variable overrides.

### State Backend Design
- **D-05:** One Azure Storage account per environment for Terraform state (e.g., `staaaptfstatedev`, `staaaptfstateprod`) — full blast-radius isolation between environments.
- **D-06:** Entra auth / OIDC authentication for the backend — `use_oidc = true` with workload identity federation in GitHub Actions. No storage access keys anywhere in the codebase or secrets.

### CI Pipeline
- **D-07:** Two separate GitHub Actions workflows: `terraform-plan.yml` (triggers on PR) and `terraform-apply.yml` (triggers on merge to main). Not a combined single workflow.
- **D-08:** `required_tags` policy lint is included in the Phase 1 CI plan workflow — untagged resources must cause the plan job to fail. All resources must carry `environment`, `managed-by: terraform`, and `project: aap` tags.

### Claude's Discretion
- Internal Terraform module layout within each domain directory (flat vs. sub-modules)
- Exact naming conventions for storage accounts, resource groups, and other resources (follow Azure naming guidance)
- Key Vault initial setup (provision in Phase 1; seeding with app secrets deferred to Phase 2)
- NSG rule specifics beyond what ROADMAP success criteria require
- Exact Cosmos DB partition key design for `incidents` and `approvals` containers

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Infrastructure Requirements
- `.planning/REQUIREMENTS.md` §INFRA — INFRA-001 through INFRA-004, INFRA-008 define exact resource list and CI behaviour required
- `.planning/ROADMAP.md` §"Phase 1: Foundation" — Success criteria (6 items) define acceptance test for every resource and the CI gate

### Technology Stack (versions and patterns)
- `CLAUDE.md` §"Technology Stack" — Authoritative version matrix: `azurerm ~>4.65`, `azapi ~>2.9`, Container Apps environment pattern, Foundry provisioning via `azurerm_cognitive_account` (kind="AIServices") + `azurerm_cognitive_account_project`, Foundry model deployment via `azurerm_cognitive_deployment`, capability host via `azapi`
- `CLAUDE.md` §"Infrastructure as Code (Terraform)" — Provider strategy, resource mapping table (which resources use azurerm vs azapi), state management backend config, CI/CD pipeline pattern
- `CLAUDE.md` §"Data Persistence" — Cosmos DB and PostgreSQL provisioning guidance, pgvector requirements

### Research Artifacts
- `.planning/research/ARCHITECTURE.md` — System architecture and build order; Phase 1 infrastructure placement decisions
- `.planning/research/STACK.md` — Technology version research and version matrix
- `.planning/research/PITFALLS.md` — Known risks for Terraform + Azure; pitfalls to avoid during IaC

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — this is a greenfield repository. Only `CLAUDE.md` and `.planning/` exist.

### Established Patterns
- None yet. Phase 1 establishes the patterns all subsequent phases follow.

### Integration Points
- Phase 1 outputs (resource IDs, connection strings, endpoints) will be consumed by Phase 2 (agent identities, RBAC) and all subsequent phases. Plan Terraform outputs carefully — downstream phases will reference them.

</code_context>

<specifics>
## Specific Ideas

- No specific references provided. Standard Terraform + Azure community idioms apply.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within Phase 1 scope.

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-03-26*
