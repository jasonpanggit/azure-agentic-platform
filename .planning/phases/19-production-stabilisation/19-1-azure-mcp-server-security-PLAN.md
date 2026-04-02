---
phase: 19
plan: 1
title: "Azure MCP Server Security Hardening"
objective: "Remove external internet exposure from the Azure MCP Server by creating a Terraform module, switching to internal-only ingress, and eliminating the --dangerously-disable-http-incoming-auth flag."
wave: 1
estimated_tasks: 9
gap_closure: false
---

# Plan 19-1: Azure MCP Server Security Hardening

## Objective

Resolve **SEC-001 (CRITICAL)** and **DEBT-013**: The Azure MCP Server (`ca-azure-mcp-prod`) is currently internet-exposed with no authentication, holding `Reader` access to all Azure resources. This plan creates a Terraform module to own the Container App, switches ingress to internal-only, removes the auth-bypass flag from the Dockerfile, and wires the updated internal FQDN into the Foundry MCP connection.

## Context

**Current state (verified from research):**

- `services/azure-mcp-server/Dockerfile:32` starts `azmcp` with `--dangerously-disable-http-incoming-auth`
- `ca-azure-mcp-prod` Container App has `ingress.external_enabled = true` (internet-accessible)
- The Container App was created ad-hoc via `scripts/deploy-azure-mcp-server.sh` — NOT managed by Terraform (DEBT-013)
- The Azure MCP Server holds `Reader` role on the subscription — any unauthenticated internet user can invoke it and enumerate all Azure resource metadata

**Why this must go first (Wave 1, Plan 1):**

- SEC-001 is rated CRITICAL in the risk register
- All Plan 3 MCP tool group work depends on the correct internal FQDN being registered in Foundry — that FQDN changes when we switch to internal ingress
- Fixing external ingress _before_ registering MCP connections avoids having to re-register them

**Pattern reference:** `terraform/modules/arc-mcp-server/main.tf` is the exact pattern to mirror — it already implements internal-only ingress for a MCP server Container App.

**PROD requirement:** PROD-002 — Azure MCP Server authenticated via managed identity; internal ingress only; no unauthenticated external access.

---

## Tasks

### Task 1: Create Terraform module directory structure

Create `terraform/modules/azure-mcp-server/` with three files:

```
terraform/modules/azure-mcp-server/
  main.tf
  variables.tf
  outputs.tf
```

Mirror the structure of `terraform/modules/arc-mcp-server/` exactly.

### Task 2: Write `terraform/modules/azure-mcp-server/variables.tf`

Create the variables file. Include:

```hcl
variable "environment" { type = string }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "container_apps_environment_id" { type = string }
variable "acr_login_server" { type = string }
variable "acr_id" { type = string; default = "" }
variable "image_tag" { type = string; default = "latest" }
variable "use_placeholder_image" { type = bool; default = false }
variable "subscription_id" {
  description = "Subscription ID to grant Reader role on for Azure MCP Server"
  type        = string
}
variable "app_insights_connection_string" { type = string; sensitive = true }
variable "required_tags" { type = map(string); default = {} }
```

### Task 3: Write `terraform/modules/azure-mcp-server/main.tf`

Create the Container App resource with `external_enabled = false`. Key points:

- `name = "ca-azure-mcp-${var.environment}"`
- `ingress { external_enabled = false; target_port = 8080; transport = "http" }`
- `identity { type = "SystemAssigned" }`
- Dynamic `registry` block (same pattern as arc-mcp-server — skip when `use_placeholder_image = true`)
- Container image: `${var.acr_login_server}/services/azure-mcp-server:${var.image_tag}`
- Environment variables: `APPLICATIONINSIGHTS_CONNECTION_STRING` (from secret)
- `lifecycle { ignore_changes = [template[0].container[0].image, ingress[0].target_port] }`
- RBAC assignment: `Reader` role on `var.subscription_id` via `azurerm_role_assignment.azure_mcp_reader`
- RBAC assignment: `AcrPull` on ACR (count = `var.acr_id != "" ? 1 : 0`) via `azurerm_role_assignment.azure_mcp_acr_pull`
- Secret: `appinsights-connection-string`

### Task 4: Write `terraform/modules/azure-mcp-server/outputs.tf`

Expose:

```hcl
output "container_app_id" { value = azurerm_container_app.azure_mcp_server.id }
output "internal_fqdn" {
  description = "Internal FQDN for Foundry MCP connection (internal ingress only)"
  value       = azurerm_container_app.azure_mcp_server.ingress[0].fqdn
}
output "principal_id" { value = azurerm_container_app.azure_mcp_server.identity[0].principal_id }
```

### Task 5: Add `azure-mcp-server` module call to `terraform/envs/prod/main.tf`

Add a module block that references the new module. Wire in existing module outputs:

```hcl
module "azure_mcp_server" {
  source = "../../modules/azure-mcp-server"

  environment                    = var.environment
  resource_group_name            = azurerm_resource_group.main.name
  location                       = var.location
  container_apps_environment_id  = module.compute_env.container_apps_environment_id
  acr_login_server               = module.compute_env.acr_login_server
  acr_id                         = module.compute_env.acr_id
  use_placeholder_image          = false
  image_tag                      = var.azure_mcp_image_tag
  subscription_id                = var.subscription_id
  app_insights_connection_string = module.monitoring.app_insights_connection_string
  required_tags                  = local.required_tags
}
```

Add `azure_mcp_image_tag = "latest"` to `terraform/envs/prod/terraform.tfvars` (and add the corresponding `variable "azure_mcp_image_tag"` to `terraform/envs/prod/variables.tf`).

### Task 6: Add Terraform import block for existing Container App

The `ca-azure-mcp-prod` Container App already exists (created ad-hoc). Add an import block to `terraform/envs/prod/imports.tf` so Terraform can take ownership without destroy-and-recreate:

```hcl
import {
  to = module.azure_mcp_server.azurerm_container_app.azure_mcp_server
  id = "/subscriptions/4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c/resourceGroups/rg-aap-prod/providers/Microsoft.App/containerApps/ca-azure-mcp-prod"
}
```

> If `imports.tf` does not exist yet, create it.

### Task 7: Update Dockerfile to remove `--dangerously-disable-http-incoming-auth`

Edit `services/azure-mcp-server/Dockerfile` line 32. Change:

```dockerfile
CMD ["sh", "-c", "node /app/proxy.js & azmcp server start --transport http --dangerously-disable-http-incoming-auth 2>&1; echo 'azmcp exited'; wait"]
```

To:

```dockerfile
CMD ["sh", "-c", "node /app/proxy.js & azmcp server start --transport http 2>&1; echo 'azmcp exited'; wait"]
```

This removes the auth-bypass flag. The Container App is internal-only after the Terraform change, so `azmcp` receives only traffic from within the Container Apps environment where Foundry agents run. This is defense-in-depth: network boundary (internal ingress) + process boundary (no bypass flag).

### Task 8: Update `AZURE_MCP_SERVER_URL` env var wiring in Terraform

The `agents/orchestrator/agent.py` and domain agents read `AZURE_MCP_SERVER_URL`. This is set in the `agent-apps` Terraform module. After switching to internal ingress, the URL must use the internal FQDN.

In `terraform/envs/prod/main.tf`, find the `module "agent_apps"` block and update the `azure_mcp_server_url` parameter to reference the new module output:

```hcl
azure_mcp_server_url = "http://${module.azure_mcp_server.internal_fqdn}"
```

Verify this parameter exists in `terraform/modules/agent-apps/variables.tf` and is wired into the agent container env vars.

### Task 9: Write operator runbook — `scripts/ops/19-1-azure-mcp-security.sh`

Create a runbook script with the exact operator commands needed to execute this plan:

```bash
#!/usr/bin/env bash
# Phase 19 Plan 1: Azure MCP Server Security Hardening
# Run these steps in order. Each step is idempotent.

set -euo pipefail

# Step 1: Build and push updated Dockerfile (removes --dangerously-disable-http-incoming-auth)
cd "$(git rev-parse --show-toplevel)"
az acr login --name aapcrprodjgmjti
docker build -t aapcrprodjgmjti.azurecr.io/services/azure-mcp-server:latest \
  --platform linux/amd64 \
  -f services/azure-mcp-server/Dockerfile \
  services/azure-mcp-server/
docker push aapcrprodjgmjti.azurecr.io/services/azure-mcp-server:latest

# Step 2: Terraform plan (review import + ingress changes)
cd terraform/envs/prod
terraform plan -out=plan-19-1.tfplan

# Step 3: Review plan output — confirm:
#   - ca-azure-mcp-prod imported (not destroyed)
#   - ingress.external_enabled changes to false
#   - RBAC assignments present
echo "Review plan-19-1.tfplan before proceeding."
read -p "Apply? [y/N] " confirm
[[ "$confirm" == "y" ]] || exit 0

# Step 4: Apply
terraform apply plan-19-1.tfplan

# Step 5: Verify internal FQDN
INTERNAL_FQDN=$(terraform output -raw azure_mcp_server_internal_fqdn 2>/dev/null || \
  az containerapp show --name ca-azure-mcp-prod --resource-group rg-aap-prod \
    --query "properties.configuration.ingress.fqdn" -o tsv)
echo "Internal FQDN: $INTERNAL_FQDN"

# Step 6: Verify external access is blocked
echo "Testing external access is blocked (should return curl error or 404)..."
curl --max-time 5 "https://ca-azure-mcp-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/mcp" \
  && echo "FAIL: external access still works" || echo "PASS: external access blocked"

# Step 7: Update ca-api-gateway-prod with new internal URL (if not handled by Terraform)
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars "AZURE_MCP_SERVER_URL=http://${INTERNAL_FQDN}"

echo "Plan 19-1 complete. Proceed to Plan 19-3 (MCP tool group registration)."
```

---

## Success Criteria

1. `ca-azure-mcp-prod` Container App shows `externalIngressEnabled: false` in Azure Portal / CLI: `az containerapp show --name ca-azure-mcp-prod --resource-group rg-aap-prod --query "properties.configuration.ingress.external" -o tsv` returns `false`
2. External HTTPS URL returns connection refused or 404 (no public endpoint): `curl https://ca-azure-mcp-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/mcp` fails
3. Internal URL resolves and responds 200 when called from another Container App in the same environment (verified via `az containerapp exec` or from orchestrator logs)
4. `terraform plan` on `terraform/envs/prod/` shows zero diff after `terraform apply` completes (resource is fully owned by Terraform)
5. `services/azure-mcp-server/Dockerfile` contains no instance of `--dangerously-disable-http-incoming-auth`
6. `terraform/modules/azure-mcp-server/` module exists with all three files (`main.tf`, `variables.tf`, `outputs.tf`)

---

## Files Touched

### Created
- `terraform/modules/azure-mcp-server/main.tf`
- `terraform/modules/azure-mcp-server/variables.tf`
- `terraform/modules/azure-mcp-server/outputs.tf`
- `scripts/ops/19-1-azure-mcp-security.sh`

### Modified
- `services/azure-mcp-server/Dockerfile` — remove `--dangerously-disable-http-incoming-auth`
- `terraform/envs/prod/main.tf` — add `module "azure_mcp_server"` block; update `azure_mcp_server_url` in `agent_apps` module
- `terraform/envs/prod/terraform.tfvars` — add `azure_mcp_image_tag = "latest"`
- `terraform/envs/prod/variables.tf` — add `variable "azure_mcp_image_tag"`
- `terraform/envs/prod/imports.tf` — add import block for `ca-azure-mcp-prod` (create if not exists)
