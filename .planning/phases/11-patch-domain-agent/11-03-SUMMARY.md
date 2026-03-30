# Plan 11-03 Summary: Terraform + CI/CD for Patch Agent

**Phase:** 11 — Patch Domain Agent
**Plan:** 11-03
**Status:** COMPLETE
**Date:** 2026-03-30

---

## What Was Done

### Task 11-03-01: Add patch agent to agent-apps Terraform module
- Added `patch` entry to `local.agents` map in `terraform/modules/agent-apps/main.tf` (8th agent, cpu=0.5, memory=1Gi, internal, port 8000)
- Added `PATCH_AGENT_ID` dynamic env block after `ARC_AGENT_ID` — injects into orchestrator only when `var.patch_agent_id != ""`
- Added `variable "patch_agent_id"` to `terraform/modules/agent-apps/variables.tf` with `type = string, default = ""`
- `terraform fmt -check` passes with exit 0

### Task 11-03-02: Add RBAC assignments for patch agent
- Added patch agent RBAC block to `terraform/modules/rbac/main.tf` between Arc Agent and API Gateway blocks
- Grants Reader + Monitoring Reader on all in-scope subscriptions via `for sub_id in var.all_subscription_ids` (same pattern as SRE agent)
- Uses inner `merge()` for dual-role map flattening
- `terraform fmt -check` passes with exit 0

### Task 11-03-03: Wire patch_agent_id through environment main.tf files
- **Dev**: No change needed — `module "agent_apps"` relies on module-level defaults
- **Staging**: Added `patch_agent_id = var.patch_agent_id` to `module "agent_apps"` block and `variable "patch_agent_id"` to variables.tf (staging explicitly wires all `*_agent_id` vars)
- **Prod**: Same as staging — added wiring to main.tf and variable to variables.tf
- Plan said "no changes needed" but code inspection revealed staging and prod DO explicitly enumerate agent IDs, so patch_agent_id was added for consistency
- `terraform fmt -check` passes for all three envs

### Task 11-03-04: Add build-patch job to deploy-all-images.yml
- Added `build-patch` job definition following `build-arc` pattern (needs: build-agent-base, image_name: agents/patch, dockerfile: agents/patch/Dockerfile)
- Added `build-patch` to summary job `needs` list (14 entries, was 13)
- Added `agents/patch` row to summary table

### Task 11-03-05: Validate terraform fmt and plan for all modules
- All 5 directories pass `terraform fmt -check` with exit 0:
  - terraform/modules/agent-apps/
  - terraform/modules/rbac/
  - terraform/envs/dev/
  - terraform/envs/staging/
  - terraform/envs/prod/

---

## Files Modified (7)

| File | Change | Purpose |
|---|---|---|
| `terraform/modules/agent-apps/main.tf` | Modified | Added `patch` to local.agents + PATCH_AGENT_ID dynamic env block |
| `terraform/modules/agent-apps/variables.tf` | Modified | Added `variable "patch_agent_id"` |
| `terraform/modules/rbac/main.tf` | Modified | Added Reader + Monitoring Reader RBAC for patch agent |
| `terraform/envs/staging/main.tf` | Modified | Wired `patch_agent_id` into module "agent_apps" |
| `terraform/envs/staging/variables.tf` | Modified | Added `variable "patch_agent_id"` |
| `terraform/envs/prod/main.tf` | Modified | Wired `patch_agent_id` into module "agent_apps" |
| `terraform/envs/prod/variables.tf` | Modified | Added `variable "patch_agent_id"` |
| `.github/workflows/deploy-all-images.yml` | Modified | Added build-patch job + summary integration |

## Commits

| # | Hash | Message |
|---|---|---|
| 1 | 318b5e1 | feat(terraform): add patch agent to agent-apps module |
| 2 | 51139b8 | feat(terraform): add RBAC assignments for patch agent |
| 3 | 2d4c547 | feat(terraform): wire patch_agent_id through staging and prod envs |
| 4 | 88cbada | ci: add build-patch job to deploy-all-images workflow |

## Key Decisions

| Decision | Rationale |
|---|---|
| Wire patch_agent_id in staging/prod despite plan saying "no changes needed" | Code inspection showed staging and prod explicitly enumerate all `*_agent_id` vars — omitting patch_agent_id would make it the only agent not wirable in those environments |
| No dev changes | Dev module "agent_apps" block does not explicitly set any `*_agent_id` vars, relying on module defaults |
| Same RBAC pattern as SRE agent | Patch agent needs cross-subscription ARG queries (Reader) and Log Analytics ConfigurationData (Monitoring Reader) — identical scope requirements |

## Verification Checklist

- [x] `terraform/modules/agent-apps/main.tf` has `patch` in `local.agents` (8 entries total)
- [x] `terraform/modules/agent-apps/main.tf` injects `PATCH_AGENT_ID` into orchestrator when set
- [x] `terraform/modules/agent-apps/variables.tf` has `variable "patch_agent_id"` with `default = ""`
- [x] `terraform/modules/rbac/main.tf` grants Reader + Monitoring Reader to patch agent across all subscriptions
- [x] `.github/workflows/deploy-all-images.yml` has `build-patch` job and includes it in summary
- [x] All Terraform files pass `fmt -check`
- [x] Staging and prod environments wire `patch_agent_id` (dev relies on defaults)
