# Plan 21-1: Terraform Activation — SUMMARY

**Status:** COMPLETE
**Completed:** 2026-04-03
**Branch:** gsd/phase-21-detection-plane-activation
**Commits:** 3 atomic commits

---

## What Was Done

### Task 21-1-01: Flip enable_fabric_data_plane flag to true

Changed line 344 of `terraform/envs/prod/main.tf` inside the `module "fabric"` block:

```hcl
# Before:
enable_fabric_data_plane = false

# After:
# Phase 21: Fabric data plane activated (workspace, Eventhouse, KQL DB, Activator, Lakehouse).
# Post-apply: run scripts/ops/21-2-activate-detection-plane.sh for manual wiring steps.
enable_fabric_data_plane = true
```

**Commit:** `feat: enable Fabric data plane in prod (Phase 21)`

### Task 21-1-02: Add fabric_admin_email comment to terraform.tfvars

`fabric_admin_email` was already declared in `variables.tf` (no default — required) and referenced in `main.tf`. It was not present in `terraform.tfvars`. Added a commented documentation block after the `enable_teams_bot` line directing the operator to supply the value via `TF_VAR_fabric_admin_email` or `credentials.tfvars`.

**Commit:** `chore: add fabric_admin_email comment to prod terraform.tfvars`

### Task 21-1-03: Validate Terraform format passes

`terraform fmt` was run to auto-fix alignment in `main.tf`, `mcp-connections.tf`, and `terraform.tfvars`. `terraform fmt -check` exits 0.

**Commit:** `chore: apply terraform fmt to prod env files`

---

## Verification Results

| Check | Result |
|---|---|
| `grep "enable_fabric_data_plane = true" main.tf` | ✅ 1 match on line 346 |
| `grep -c "enable_fabric_data_plane = false" main.tf` | ✅ 0 matches |
| `grep "Phase 21" main.tf` | ✅ Comment present on line 344 |
| `grep "21-2-activate-detection-plane" main.tf` | ✅ Operator runbook reference on line 345 |
| `grep "fabric_admin_email" variables.tf` | ✅ Variable declared (required) |
| `grep "fabric_admin_email" terraform.tfvars` | ✅ Comment block with operator instructions |
| `terraform fmt -check` | ✅ Exits 0 — no formatting issues |

---

## Must-Haves

- [x] `enable_fabric_data_plane` is set to `true` in `terraform/envs/prod/main.tf`
- [x] No instances of `enable_fabric_data_plane = false` remain in prod main.tf
- [x] Comment references the operator runbook script path (`scripts/ops/21-2-activate-detection-plane.sh`)
- [x] Terraform formatting passes

---

## Effect

After the next `terraform apply`, these 5 Fabric data-plane resources will be provisioned in production:
1. **Fabric Workspace** — `aap-prod`
2. **Eventhouse** — `eh-aap-prod`
3. **KQL Database** — `kqldb-aap-prod`
4. **Activator** — `act-aap-prod`
5. **OneLake Lakehouse** — `lh-aap-prod`

The post-apply operator steps (Activator trigger wiring, Eventstream connection, OneLake mirror) are documented in the Phase 21 Plan 2 operator runbook at `scripts/ops/21-2-activate-detection-plane.sh`.

---

## Decisions

- `fabric_admin_email` kept commented (not set to a value) in `terraform.tfvars` — the actual admin email is sensitive operator config that belongs in `credentials.tfvars` or as a `TF_VAR_` env var, not committed to git.
- `terraform fmt` fixes were committed separately from the logic change for clean atomic history.
