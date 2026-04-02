---
plan: 19-1
title: "Azure MCP Server Security Hardening"
status: complete
completed: "2026-04-02"
commits:
  - e52e93d
  - e84105b
  - 00a4483
  - 8c46a1f
  - 4a0d368
---

# Plan 19-1: Azure MCP Server Security Hardening — COMPLETE

## Objective

Resolved **SEC-001 (CRITICAL)** and **DEBT-013**: Removed internet exposure from the Azure MCP Server, created a Terraform module to own the Container App, switched to internal-only ingress, and eliminated the `--dangerously-disable-http-incoming-auth` flag.

## Tasks Completed

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Create `terraform/modules/azure-mcp-server/` directory structure | ✅ | e52e93d |
| 2 | Write `variables.tf` (10 variables matching plan spec) | ✅ | e52e93d |
| 3 | Write `main.tf` (Container App with `external_enabled = false`, RBAC) | ✅ | e52e93d |
| 4 | Write `outputs.tf` (container_app_id, internal_fqdn, principal_id) | ✅ | e52e93d |
| 5 | Add `module "azure_mcp_server"` to `terraform/envs/prod/main.tf`; add `azure_mcp_image_tag` variable + tfvars entry | ✅ | e84105b |
| 6 | Add import block for `ca-azure-mcp-prod` in `terraform/envs/prod/imports.tf` | ✅ | 00a4483 |
| 7 | Remove `--dangerously-disable-http-incoming-auth` from `services/azure-mcp-server/Dockerfile` | ✅ | 8c46a1f |
| 8 | Wire `azure_mcp_server_url = "http://${module.azure_mcp_server.internal_fqdn}"` into `agent_apps` module | ✅ | e84105b |
| 9 | Write operator runbook `scripts/ops/19-1-azure-mcp-security.sh` | ✅ | 4a0d368 |

## Files Created

- `terraform/modules/azure-mcp-server/main.tf`
- `terraform/modules/azure-mcp-server/variables.tf`
- `terraform/modules/azure-mcp-server/outputs.tf`
- `scripts/ops/19-1-azure-mcp-security.sh`

## Files Modified

- `services/azure-mcp-server/Dockerfile` — removed `--dangerously-disable-http-incoming-auth` from CMD; added security comment
- `terraform/envs/prod/main.tf` — added `module "azure_mcp_server"` block; wired `azure_mcp_server_url` into `agent_apps` module
- `terraform/envs/prod/variables.tf` — added `variable "azure_mcp_image_tag"`
- `terraform/envs/prod/terraform.tfvars` — added `azure_mcp_image_tag = "latest"`
- `terraform/envs/prod/imports.tf` — added import block for `ca-azure-mcp-prod`

## Success Criteria Verified

1. ✅ `external_enabled = false` set in `terraform/modules/azure-mcp-server/main.tf`
2. ✅ Import block present for `ca-azure-mcp-prod` in `imports.tf` — Terraform takes ownership without destroy-and-recreate
3. ✅ `azure_mcp_server_url` in `agent_apps` module wired to `http://${module.azure_mcp_server.internal_fqdn}`
4. ✅ `services/azure-mcp-server/Dockerfile` CMD contains no `--dangerously-disable-http-incoming-auth` (only in a comment explaining removal)
5. ✅ Module directory `terraform/modules/azure-mcp-server/` has all three files: `main.tf`, `variables.tf`, `outputs.tf`
6. ✅ RBAC: `Reader` on subscription + `AcrPull` on ACR via `azurerm_role_assignment` resources

## Operator Actions Still Required

To fully activate SEC-001 fix in production, the operator must:

1. **Build + push new image**: `az acr login --name aapcrprodjgmjti && docker build/push services/azure-mcp-server/`
2. **Run terraform apply**: `cd terraform/envs/prod && terraform plan -out=plan-19-1.tfplan && terraform apply plan-19-1.tfplan`
3. **Verify**: `az containerapp show --name ca-azure-mcp-prod --resource-group rg-aap-prod --query "properties.configuration.ingress.external" -o tsv` should return `false`

See `scripts/ops/19-1-azure-mcp-security.sh` for the full interactive runbook.

## Pattern Notes

- Mirrors `terraform/modules/arc-mcp-server/main.tf` exactly (internal ingress, dynamic registry block, lifecycle ignore_changes)
- Unlike arc-mcp-server which uses a list of subscription IDs (`arc_subscription_ids`), azure-mcp-server uses a single `subscription_id` (platform subscription)
- Defense-in-depth: network boundary (`external_enabled = false`) + process boundary (no auth bypass flag)
