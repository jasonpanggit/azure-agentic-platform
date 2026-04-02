---
phase: 19-production-stabilisation
plan: 3
subsystem: infra
tags: [terraform, azapi, mcp, foundry, azure-mcp-server, arc-mcp-server, tool-groups]

# Dependency graph
requires:
  - phase: 19-production-stabilisation plan 1
    provides: Azure MCP Server internal-only ingress (internal_fqdn output)
  - phase: 19-production-stabilisation plan 2
    provides: Auth enablement (Bearer token for authenticated tool tests)
provides:
  - azapi_resource blocks for azure-mcp-connection and arc-mcp-connection on Foundry project
  - internal_fqdn output on arc-mcp-server module (consistent with azure-mcp-server module)
  - scripts/ops/19-3-register-mcp-connections.sh operator verification script
affects:
  - network-agent
  - security-agent
  - arc-agent
  - sre-agent
  - foundry-tool-surfaces

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "azapi_resource for Foundry MCP connections at project level (all agents share)"
    - "count gate for conditional resources (enable_arc_mcp_server toggle)"
    - "internal_fqdn output alias pattern for consistent cross-module referencing"

key-files:
  created:
    - terraform/envs/prod/mcp-connections.tf
    - scripts/ops/19-3-register-mcp-connections.sh
  modified:
    - terraform/modules/arc-mcp-server/outputs.tf

key-decisions:
  - "Use foundry_project_id (not project_id) as the local alias — matches existing foundry module output name"
  - "Add internal_fqdn alias output to arc-mcp-server module for consistency with azure-mcp-server module pattern"
  - "azapi provider already present in providers.tf (v~>2.9.0) — no versions.tf change needed"
  - "body uses HCL object syntax (not jsonencode) — consistent with capability-host.tf pattern in foundry module"
  - "Tasks 1, 2, 8, 9 are operator-only steps (require live Azure credentials) — encapsulated in verification script"

requirements-completed: []

# Metrics
duration: 18min
completed: 2026-04-02
---

# Phase 19 Plan 3: MCP Tool Group Registration Summary

**Two azapi_resource Terraform blocks register Azure MCP Server and Arc MCP Server as Foundry project-level tool surfaces, resolving PROD-003 "tool group was not found" errors for Network, Security, Arc, and SRE agents**

## Performance

- **Duration:** 18 min
- **Started:** 2026-04-02T08:15:00Z
- **Completed:** 2026-04-02T08:33:00Z
- **Tasks:** 9 (3 code tasks + 2 no-op confirmations + 4 operator-only steps)
- **Files modified/created:** 3

## Accomplishments

- Created `terraform/envs/prod/mcp-connections.tf` with two `azapi_resource` blocks registering Azure MCP Server and Arc MCP Server as Foundry project-level MCP connections
- Added `internal_fqdn` output to `terraform/modules/arc-mcp-server/outputs.tf` to match the `azure-mcp-server` module's output naming pattern
- Created `scripts/ops/19-3-register-mcp-connections.sh` with full operator runbook: Arc image verification, internal FQDN retrieval, Foundry connection listing, and domain agent tool invocation tests

## Task Commits

Each task was committed atomically:

1. **Task 3: azapi MCP connections Terraform file** - `5d5ce18` (feat)
2. **Task 5: MCP tool group verification script** - `9d5afee` (feat)
3. **Task 7: internal_fqdn output for arc-mcp-server module** - `23fd6dd` (feat)

Tasks 1-2 (FQDN retrieval), Task 4 (azapi provider already present), Task 6 (foundry_project_id already present), Tasks 8-9 (terraform apply + verification run) are operator-only steps documented in the verification script.

## Files Created/Modified

- `terraform/envs/prod/mcp-connections.tf` — `azapi_resource` blocks for `azure-mcp-connection` (Azure MCP) and `arc-mcp-connection` (Arc MCP, count-gated on `local.enable_arc_mcp_server`)
- `terraform/modules/arc-mcp-server/outputs.tf` — added `internal_fqdn` output alias alongside existing `arc_mcp_server_fqdn`
- `scripts/ops/19-3-register-mcp-connections.sh` — operator verification script covering all 9 plan tasks

## Decisions Made

- **`foundry_project_id` vs `project_id`:** The plan template referenced `module.foundry.project_id` but the actual output is `module.foundry.foundry_project_id` (existing in outputs.tf). Used the correct name — no output change needed.
- **`internal_fqdn` alias added:** The `arc-mcp-server` module exposed `arc_mcp_server_fqdn` (not `internal_fqdn`). Added `internal_fqdn` as an alias to match the `azure-mcp-server` module pattern, keeping `mcp-connections.tf` consistent across both connections.
- **`azapi` provider already present:** `terraform/envs/prod/providers.tf` already declared `azapi ~> 2.9.0` — Task 4 was a no-op.
- **HCL object syntax for `body`:** Used `body = { ... }` (not `jsonencode`) — consistent with `capability-host.tf` in the foundry module.
- **Tasks 8-9 are operator-only:** `terraform apply` and verification script execution require live Azure credentials. Documented in script with a complete operator checklist and App Insights KQL query.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Output name mismatch: `module.foundry.project_id` → `module.foundry.foundry_project_id`**
- **Found during:** Task 3 (writing mcp-connections.tf)
- **Issue:** Plan template referenced `module.foundry.project_id` but the actual output in `terraform/modules/foundry/outputs.tf` is `foundry_project_id`
- **Fix:** Used correct output name `module.foundry.foundry_project_id` in the local alias in `mcp-connections.tf`
- **Files modified:** `terraform/envs/prod/mcp-connections.tf`
- **Verification:** `grep -n "foundry_project_id" terraform/modules/foundry/outputs.tf` confirms output exists
- **Committed in:** `5d5ce18` (Task 3 commit)

**2. [Rule 1 - Bug] Output name mismatch: `module.arc_mcp_server[0].internal_fqdn` missing**
- **Found during:** Task 7 (verifying arc-mcp-server outputs)
- **Issue:** Plan required `module.arc_mcp_server[0].internal_fqdn` but arc-mcp-server module only exposed `arc_mcp_server_fqdn`; `mcp-connections.tf` references `internal_fqdn`
- **Fix:** Added `internal_fqdn` output alias to `terraform/modules/arc-mcp-server/outputs.tf`
- **Files modified:** `terraform/modules/arc-mcp-server/outputs.tf`
- **Verification:** Both outputs return same `azurerm_container_app.arc_mcp_server.ingress[0].fqdn` value
- **Committed in:** `23fd6dd` (Task 7 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs — output name mismatches)
**Impact on plan:** Both fixes essential for Terraform to reference correct module outputs. No scope creep.

## Issues Encountered

None — plan executed cleanly. Operator-only tasks (1, 2, 8, 9) are by design and documented in the verification script.

## User Setup Required

**Operator must run the following after this plan's code is merged:**

1. `cd terraform/envs/prod && terraform init -upgrade` (if first time with azapi provider changes)
2. `terraform plan -out=plan-19-3.tfplan` — should show 2 `azapi_resource` creates
3. `terraform apply plan-19-3.tfplan`
4. `bash scripts/ops/19-3-register-mcp-connections.sh` — verify connections registered

See `scripts/ops/19-3-register-mcp-connections.sh` for full operator checklist and verification steps.

## Next Phase Readiness

- Plan 19-3 Terraform code complete — ready for operator `terraform apply`
- Plans 19-4 (Runbook RAG Seeding) and 19-5 (Teams Proactive Alerting) are Wave 3 and can proceed independently
- PROD-003 will be resolved once operator runs `terraform apply` and verifies via the script

---
*Phase: 19-production-stabilisation*
*Completed: 2026-04-02*
