# Terraform Drift Fix Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring all Azure-provisioned resources under full Terraform management so `terraform apply` from clean state produces a fully functional platform.

**Architecture:** Import all manually-provisioned Azure resources into Terraform state. Add new modules/resources for missing pieces (Cosmos data-plane RBAC, Teams Bot service, PostgreSQL Entra admin). Fix env var wiring gaps. Replace manual Foundry agent provisioning with an idempotent bootstrap script.

**Tech Stack:** Terraform (azurerm ~4.65, azapi ~2.9, azuread ~3.0), Python (azure-ai-projects SDK), Bash (gh CLI for GitHub secrets)

---

## File Structure

### Files to Modify
- `terraform/envs/prod/main.tf` — enable Entra apps, add teams-bot module call, wire new variables
- `terraform/envs/prod/variables.tf` — add `postgres_dsn` variable
- `terraform/envs/prod/terraform.tfvars` — add `cors_allowed_origins`, `all_subscription_ids`
- `terraform/envs/prod/imports.tf` — uncomment/complete Entra import blocks, add Cosmos RBAC import blocks, add role assignment import block
- `terraform/modules/databases/cosmos.tf` — add `azurerm_cosmosdb_sql_role_assignment` resources
- `terraform/modules/databases/variables.tf` — add `agent_principal_ids` variable
- `terraform/modules/databases/outputs.tf` — add `cosmos_account_id` output (already exists ✅)
- `terraform/modules/agent-apps/main.tf` — add `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` env vars; remove `secret` from `ignore_changes` on teams_bot (post teams-bot module)
- `terraform/modules/agent-apps/variables.tf` — add `client_id`, `tenant_id` variables
- `.github/workflows/terraform-apply.yml` — add Foundry agents bootstrap step before prod apply
- `docs/MANUAL-SETUP.md` — remove automated steps, forward-reference BOOTSTRAP.md

### Files to Create
- `terraform/modules/teams-bot/main.tf` — Azure Bot resource + app registration + KV secrets
- `terraform/modules/teams-bot/variables.tf` — module variables
- `terraform/modules/teams-bot/outputs.tf` — bot_id, bot_fqdn outputs
- `scripts/provision-foundry-agents.py` — idempotent agent provisioning, outputs agents.tfvars
- `scripts/bootstrap-github-secrets.sh` — sets missing GitHub Actions secrets via gh CLI
- `docs/BOOTSTRAP.md` — the two remaining genuinely manual steps

---

## Chunk 1: Import Azure AI Developer Role Assignment

**Prerequisite:** None. Do this first to eliminate the duplicate-creation risk on all subsequent `terraform apply` runs.

### Task 1: Import the manually-created Azure AI Developer role assignment

**Files:**
- No file changes — this is a state-only operation

- [ ] **Step 1.1: Verify the role assignment exists in Azure**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/terraform/envs/prod
# Load credentials (adjust path if needed)
source <(grep -E '^(subscription_id|tenant_id)' credentials.tfvars | sed 's/ *= */=/' | sed 's/^/export TF_VAR_/')

az role assignment show \
  --ids "/subscriptions/$(az account show --query id -o tsv)/providers/Microsoft.Authorization/roleAssignments/6a001d6b-bc29-4355-962f-0103c81f90c6" \
  --query "{role:roleDefinitionName, principal:principalId}" -o table
```

Expected: shows `Azure AI Developer` role for the api-gateway managed identity principal.

- [ ] **Step 1.2: Get the platform subscription ID**

```bash
PLATFORM_SUB=$(az account show --query id -o tsv)
echo "Platform subscription: $PLATFORM_SUB"
```

- [ ] **Step 1.3: Terraform init**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/terraform/envs/prod
terraform init -input=false
```

Expected: `Terraform has been successfully initialized!`

- [ ] **Step 1.4: Import the role assignment into state**

```bash
terraform import \
  -var-file="credentials.tfvars" \
  'module.rbac.azurerm_role_assignment.agent_rbac["api-gateway-aidev-foundry"]' \
  "/subscriptions/${PLATFORM_SUB}/providers/Microsoft.Authorization/roleAssignments/6a001d6b-bc29-4355-962f-0103c81f90c6"
```

Expected: `Import successful! The resources that were imported are shown above.`

- [ ] **Step 1.5: Verify zero diff for this resource**

```bash
terraform plan -var-file="credentials.tfvars" 2>&1 | grep -A3 "api-gateway-aidev-foundry"
```

Expected: No changes shown for this resource. If it shows `+ create`, the import failed — re-check the resource address and assignment ID.


> State is in the remote backend — no files changed. Proceed to Chunk 2.

---

## Chunk 2: Import Entra App Registration

**Prerequisite:** CI SP must have `Application.ReadWrite.All` permission on the Entra tenant (see BOOTSTRAP.md step 0 — one-time manual step).

### Task 2: Enable Entra apps and import the existing web-UI app registration

**Files:**
- Modify: `terraform/envs/prod/main.tf`
- Modify: `terraform/envs/prod/terraform.tfvars`
- Modify: `terraform/envs/prod/imports.tf`

- [ ] **Step 2.1: Set `enable_entra_apps = true` in terraform.tfvars**

Open `terraform/envs/prod/terraform.tfvars` and add:

```hcl
enable_entra_apps = true
web_ui_public_url = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
```

- [ ] **Step 2.2: Update imports.tf with proper import blocks**

**Append** the following to the end of `terraform/envs/prod/imports.tf` (preserve the existing comment block at the top):

```hcl
# --- Entra App Registration imports ---
# Imports the web-UI app registration created manually on 2026-03-28.
# Requires: var.enable_entra_apps = true AND CI SP has Application.ReadWrite.All (see docs/BOOTSTRAP.md)
#
# After successful import, `terraform plan` must show zero changes for these resources.

import {
  to = module.entra_apps[0].azuread_application.web_ui
  id = "/applications/8176f860-9715-46e3-8875-5939a6b76a69"
}

import {
  to = module.entra_apps[0].azuread_service_principal.web_ui
  id = "505df1d3-3bd3-4151-ae87-6e5974b72a44"
}
```

- [ ] **Step 2.3: Run terraform plan to preview**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/terraform/envs/prod
terraform plan -var-file="credentials.tfvars" 2>&1 | grep -E "(entra_apps|web_ui|import|Plan:)"
```

Expected: Plan shows the two Entra resources will be imported (not created). If you see `+ create` instead of `# will be imported`, the import block IDs are wrong.

- [ ] **Step 2.4: Apply the import**

```bash
terraform apply -var-file="credentials.tfvars" -auto-approve
```

Expected: `Apply complete! Resources: 2 imported, 0 added, 0 changed, 0 destroyed.`

- [ ] **Step 2.5: Verify zero diff after import**

```bash
terraform plan -var-file="credentials.tfvars" 2>&1 | grep -E "(entra_apps|web_ui|Plan:)"
```

Expected: `Plan: 0 to add, 0 to change, 0 to destroy.` for the Entra resources.

- [ ] **Step 2.6: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add terraform/envs/prod/terraform.tfvars terraform/envs/prod/imports.tf
git commit -m "feat: import entra app registration into terraform state"
```

---

## Chunk 3: Cosmos DB Data-Plane RBAC

### Task 3: Add Cosmos data-plane role assignments to Terraform

**Files:**
- Modify: `terraform/modules/databases/cosmos.tf`
- Modify: `terraform/modules/databases/variables.tf`
- Modify: `terraform/envs/prod/main.tf`
- Modify: `terraform/envs/prod/imports.tf`

- [ ] **Step 3.1: Add `agent_principal_ids` variable to databases module**

Append to `terraform/modules/databases/variables.tf`:

```hcl
variable "agent_principal_ids" {
  description = "Map of agent name to managed identity principal ID for Cosmos data-plane RBAC"
  type        = map(string)
  default     = {}
}
```

- [ ] **Step 3.2: Add Cosmos data-plane role assignments to cosmos.tf**

Append to the end of `terraform/modules/databases/cosmos.tf`:

```hcl
# Cosmos DB data-plane RBAC — Built-in Data Contributor for all agent MIs
# local_authentication_disabled = true means all data access requires data-plane RBAC.
# ARM role "Cosmos DB Operator" (assigned by rbac module) is control-plane only.
# This resource manages the data-plane role assignments that allow document read/write.
#
# Built-in role ID 00000000-0000-0000-0000-000000000002 = Cosmos DB Built-in Data Contributor
# Scope = Cosmos account (not database or container level, matching what was done manually)
resource "azurerm_cosmosdb_sql_role_assignment" "data_contributor" {
  for_each = var.agent_principal_ids

  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = each.value
  scope               = azurerm_cosmosdb_account.main.id
}
```

- [ ] **Step 3.3: Break the circular dependency — use data sources in prod/main.tf**

`module.agent_apps` depends on `module.databases` (via `cosmos_endpoint`). Passing `module.agent_apps.agent_principal_ids` back into `module.databases` would create a cycle. Instead, look up the Container App managed identity principal IDs via `data "azurerm_container_app"` data sources at the root level. These data sources read the existing live resources and have no dependency on `module.databases`.

Add the following to `terraform/envs/prod/main.tf`, **before** the `module "databases"` block:

```hcl
# --- Agent Managed Identity Principal IDs ---
# Used to wire Cosmos data-plane RBAC without creating a circular dependency
# (module.agent_apps depends on module.databases; we cannot pass agent_apps output back in).
# Instead, look up the live Container App MIs directly via data sources.
# These Container Apps must already exist (created by a prior apply) before this runs.

locals {
  cosmos_agent_apps = toset([
    "orchestrator", "compute", "network", "storage",
    "security", "arc", "sre", "patch", "eol", "api-gateway"
  ])
}

data "azurerm_container_app" "agent_mis" {
  for_each            = local.cosmos_agent_apps
  name                = "ca-${each.key}-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
}
```

Then add to the `module "databases"` block:

```hcl
  agent_principal_ids = {
    for name in local.cosmos_agent_apps :
    name => data.azurerm_container_app.agent_mis[name].identity[0].principal_id
  }
```

**Important:** This data source approach requires that the Container Apps exist before this plan runs. On a brand-new environment, run two applies: the first creates the Container Apps (without Cosmos RBAC), and the second adds the RBAC. In CI, this is handled by the existing sequential apply pattern.

- [ ] **Step 3.4: Get the existing Cosmos data-plane assignment GUIDs from Azure**

```bash
COSMOS_ACCOUNT=$(az cosmosdb list \
  --resource-group rg-aap-prod \
  --query "[0].name" -o tsv)

az cosmosdb sql role assignment list \
  --account-name "$COSMOS_ACCOUNT" \
  --resource-group rg-aap-prod \
  --query "[].{principal:principalId, id:name}" -o table
```

Copy the output — you need the assignment GUIDs (the `id` column, which is a GUID) and their corresponding principal IDs to write import blocks.

- [ ] **Step 3.5: Get all agent principal IDs**

```bash
for APP in ca-orchestrator-prod ca-compute-prod ca-network-prod ca-storage-prod \
           ca-security-prod ca-arc-prod ca-sre-prod ca-patch-prod ca-eol-prod \
           ca-api-gateway-prod; do
  PRINCIPAL=$(az containerapp show \
    --name "$APP" \
    --resource-group rg-aap-prod \
    --query "identity.principalId" -o tsv)
  echo "$APP: $PRINCIPAL"
done
```

- [ ] **Step 3.6: Add import blocks to imports.tf for existing Cosmos assignments**

Using the GUIDs from Step 3.4, **append** to `terraform/envs/prod/imports.tf`.
The `to` address uses the **agent name** key (e.g. `orchestrator`, `api-gateway`) matching the keys in `local.cosmos_agent_apps`.

**Important:** Import block `id` fields must be **literal strings** — no `local.*` or interpolations are supported. Replace `<PLATFORM_SUB>` with your actual subscription ID (from Step 1.2) and replace each `<GUID>` with the corresponding assignment GUID from Step 3.4.

Template (fill in all values from Steps 1.2, 3.4, and 3.5):

```hcl
# --- Cosmos DB data-plane RBAC imports ---
# Assignment GUIDs from: az cosmosdb sql role assignment list --account-name aap-cosmos-prod --resource-group rg-aap-prod
# Replace <PLATFORM_SUB> with subscription ID and <GUID-for-xxx> with actual GUIDs.

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["orchestrator"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-orchestrator>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["compute"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-compute>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["network"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-network>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["storage"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-storage>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["security"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-security>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["arc"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-arc>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["sre"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-sre>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["patch"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-patch>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["eol"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-eol>"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["api-gateway"]
  id = "/subscriptions/<PLATFORM_SUB>/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/<GUID-for-api-gateway>"
}
```

**Note:** Any agent that does NOT have an existing assignment (GUID not found in Step 3.4) should simply be omitted — Terraform will create it fresh. Do not include import blocks for non-existent assignments.

- [ ] **Step 3.7: Run terraform plan**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/terraform/envs/prod
terraform plan -var-file="credentials.tfvars" 2>&1 | grep -E "(cosmosdb_sql_role|Plan:)"
```

Expected: Each existing assignment shows `# will be imported`, new ones show `+ create`. Zero shows `~ update` or `- destroy`.

- [ ] **Step 3.8: Apply**

```bash
terraform apply -var-file="credentials.tfvars" -auto-approve
```

Expected: `Apply complete! Resources: N imported, M added, 0 changed, 0 destroyed.`

- [ ] **Step 3.9: Verify all 10 assignments in state**

```bash
terraform state list 2>/dev/null | grep cosmosdb_sql_role_assignment | wc -l
```

Expected: `10`

- [ ] **Step 3.10: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add terraform/modules/databases/cosmos.tf \
        terraform/modules/databases/variables.tf \
        terraform/envs/prod/main.tf \
        terraform/envs/prod/imports.tf
git commit -m "feat: add cosmos data-plane rbac to terraform with imports"
```

---

## Chunk 4: Teams Bot Module

### Task 4: Create teams-bot module and wire into prod

**Files:**
- Create: `terraform/modules/teams-bot/main.tf`
- Create: `terraform/modules/teams-bot/variables.tf`
- Create: `terraform/modules/teams-bot/outputs.tf`
- Modify: `terraform/envs/prod/main.tf`
- Modify: `terraform/envs/prod/variables.tf`

- [ ] **Step 4.1: Verify bot app type in Azure Portal**

Before writing any import block, check whether the Azure Bot was manually created (and if so, what type):

```bash
az bot show \
  --name aap-teams-bot-prod \
  --resource-group rg-aap-prod 2>/dev/null || echo "Bot resource NOT YET CREATED"
```

If this returns "NOT YET CREATED", the module will create the bot fresh — **no import block needed**. If it returns a result, note the `msaAppType` field (`SingleTenant` or `MultiTenant`).

- [ ] **Step 4.2: Create `terraform/modules/teams-bot/variables.tf`**

```hcl
variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "required_tags" {
  description = "Required tags for all resources"
  type        = map(string)
}

variable "tenant_id" {
  description = "Entra tenant ID for SingleTenant bot"
  type        = string
}

variable "keyvault_id" {
  description = "Key Vault resource ID for storing bot credentials"
  type        = string
}

variable "teams_bot_fqdn" {
  description = "FQDN of the teams-bot Container App (for messaging endpoint)"
  type        = string
  default     = ""
}

variable "bot_sku" {
  description = "Azure Bot pricing tier (F0 = free, S1 = standard)"
  type        = string
  default     = "F0"
}
```

- [ ] **Step 4.3: Create `terraform/modules/teams-bot/main.tf`**

```hcl
# Teams Bot module — manages the Azure Bot service resource and its Entra app registration.
# The azurerm_container_app.teams_bot resource stays in agent-apps module.
# This module owns: Azure Bot resource, bot app registration, credentials in Key Vault.

resource "azuread_application" "teams_bot" {
  display_name     = "aap-teams-bot-${var.environment}"
  sign_in_audience = "AzureADMyOrg"
}

resource "azuread_service_principal" "teams_bot" {
  client_id                    = azuread_application.teams_bot.client_id
  app_role_assignment_required = false
}

# IMPORTANT: Use a fixed end_date. timestamp() causes perpetual drift.
# Update this date during scheduled secret rotation.
resource "azuread_application_password" "teams_bot" {
  application_id = azuread_application.teams_bot.id
  display_name   = "teams-bot-secret-${var.environment}"
  end_date       = "2028-03-31T00:00:00Z"
}

resource "azurerm_bot_service_azure_bot" "main" {
  name                = "aap-teams-bot-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = "global"
  sku                 = var.bot_sku

  microsoft_app_id        = azuread_application.teams_bot.client_id
  microsoft_app_type      = "SingleTenant"
  microsoft_app_tenant_id = var.tenant_id

  # Messaging endpoint points to the teams-bot Container App
  # Set after the Container App FQDN is known (output from agent-apps module)
  endpoint = var.teams_bot_fqdn != "" ? "https://${var.teams_bot_fqdn}/api/messages" : ""

  tags = var.required_tags
}

# Store credentials in Key Vault — agent-apps module reads these
resource "azurerm_key_vault_secret" "bot_id" {
  name         = "teams-bot-id"
  value        = azuread_application.teams_bot.client_id
  key_vault_id = var.keyvault_id
}

resource "azurerm_key_vault_secret" "bot_password" {
  name         = "teams-bot-password"
  value        = azuread_application_password.teams_bot.value
  key_vault_id = var.keyvault_id
}
```

- [ ] **Step 4.4: Create `terraform/modules/teams-bot/outputs.tf`**

```hcl
output "bot_id" {
  description = "Microsoft App ID (client_id) of the Teams bot app registration"
  value       = azuread_application.teams_bot.client_id
}

output "bot_password" {
  description = "Client secret for the Teams bot app registration"
  value       = azuread_application_password.teams_bot.value
  sensitive   = true
}

output "bot_service_id" {
  description = "Resource ID of the Azure Bot service"
  value       = azurerm_bot_service_azure_bot.main.id
}
```

- [ ] **Step 4.5: Add `enable_teams_bot` variable to `terraform/envs/prod/variables.tf`**

Append:

```hcl
variable "enable_teams_bot" {
  description = "Enable Teams Bot module (creates Azure Bot resource + Entra app registration)"
  type        = bool
  default     = false
}
```

- [ ] **Step 4.6: Add teams-bot module call to `terraform/envs/prod/main.tf`**

After the `module "entra_apps"` block, add:

```hcl
# --- Teams Bot (depends on: keyvault, entra-apps) ---
# Creates the Azure Bot service resource and bot app registration.
# The teams-bot Container App stays in module.agent_apps.
# Gate behind enable_teams_bot until Teams Bot app registration is ready.

module "teams_bot" {
  count  = var.enable_teams_bot ? 1 : 0
  source = "../../modules/teams-bot"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
  tenant_id           = var.tenant_id
  keyvault_id         = module.keyvault.keyvault_id
  teams_bot_fqdn      = module.agent_apps.teams_bot_fqdn
}
```

- [ ] **Step 4.7: Confirm `teams_bot_fqdn` output already exists in agent-apps**

```bash
grep "teams_bot_fqdn" /Users/jasonmba/workspace/azure-agentic-platform/terraform/modules/agent-apps/outputs.tf
```

Expected: output block found. This output already exists — **no changes needed**. If for any reason it's missing, add it as shown below, but this should not be necessary:

```hcl
output "teams_bot_fqdn" {
  description = "FQDN of the teams-bot Container App"
  value       = azurerm_container_app.teams_bot.ingress[0].fqdn
}
```

- [ ] **Step 4.8: Plan with `enable_teams_bot = false` (current default) — expect zero changes**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/terraform/envs/prod
terraform plan -var-file="credentials.tfvars" 2>&1 | grep -E "(teams_bot|Plan:)"
```

Expected: `Plan: 0 to add, 0 to change, 0 to destroy.` — the module is gated off.

- [ ] **Step 4.9: Apply gated-off plan**

```bash
terraform apply -var-file="credentials.tfvars" -auto-approve
```

Expected: `Apply complete! Resources: 0 added, 0 changed, 0 destroyed.`

- [ ] **Step 4.10: Enable bot and apply to create resources**

Add to `terraform/envs/prod/terraform.tfvars`:

```hcl
enable_teams_bot = true
```

Then plan and apply:

```bash
terraform plan -var-file="credentials.tfvars" 2>&1 | grep -E "(teams_bot|bot_service|Plan:)"
terraform apply -var-file="credentials.tfvars" -auto-approve
```

Expected: `Apply complete! Resources: 4 added, 0 changed, 0 destroyed.` (app reg + SP + password + bot service)

- [ ] **Step 4.11: Verify bot service in state**

```bash
terraform state list 2>/dev/null | grep bot_service
```

Expected: `module.teams_bot[0].azurerm_bot_service_azure_bot.main`

- [ ] **Step 4.12: Update agent-apps to read bot credentials from Key Vault**

In `terraform/modules/agent-apps/main.tf`, find the teams_bot secret block:

```hcl
secret {
  name  = "teams-bot-password"
  value = var.teams_bot_password != "" ? var.teams_bot_password : "placeholder-not-configured"
}
```

The `teams_bot_password` variable continues to serve as the injection point. In `prod/main.tf`, wire the teams_bot module output to the agent_apps module:

```hcl
module "agent_apps" {
  # ... existing args ...
  teams_bot_id       = var.enable_teams_bot ? module.teams_bot[0].bot_id : var.teams_bot_id
  teams_bot_password = var.enable_teams_bot ? module.teams_bot[0].bot_password : var.teams_bot_password
}
```

- [ ] **Step 4.13: Apply the wiring change**

```bash
terraform apply -var-file="credentials.tfvars" -auto-approve
```

Expected: The teams-bot Container App secret gets updated with the real bot password.

- [ ] **Step 4.14: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add terraform/modules/teams-bot/ \
        terraform/envs/prod/main.tf \
        terraform/envs/prod/variables.tf \
        terraform/envs/prod/terraform.tfvars \
        terraform/modules/agent-apps/outputs.tf 2>/dev/null || true
git commit -m "feat: add teams-bot module - azure bot resource + app registration"
```

---

## Chunk 5: Env Var Wiring & PostgreSQL Entra Admin

### Task 5: Fix env var wiring gaps and add PostgreSQL Entra auth admin

**Files:**
- Modify: `terraform/envs/prod/terraform.tfvars`
- Modify: `terraform/envs/prod/variables.tf`
- Modify: `terraform/envs/prod/main.tf`
- Modify: `terraform/modules/agent-apps/main.tf`
- Modify: `terraform/modules/agent-apps/variables.tf`
- Modify: `terraform/modules/databases/postgres.tf`
- Modify: `terraform/modules/databases/variables.tf`

- [ ] **Step 5.1: Add `client_id` and `tenant_id` to the agent-apps MODULE variables**

**Note:** `client_id` and `tenant_id` already exist in `terraform/envs/prod/variables.tf` — do NOT add them there again. Only the agent-apps **module** (`terraform/modules/agent-apps/variables.tf`) is missing them.

Verify they're absent from the module first:

```bash
grep -E "^variable \"(client_id|tenant_id)\"" /Users/jasonmba/workspace/azure-agentic-platform/terraform/modules/agent-apps/variables.tf || echo "NOT FOUND — safe to add"
```

If "NOT FOUND", append to `terraform/modules/agent-apps/variables.tf`:

```hcl
variable "client_id" {
  description = "Azure AD service principal client ID (injected as AZURE_CLIENT_ID env var)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tenant_id" {
  description = "Entra tenant ID (injected as AZURE_TENANT_ID env var)"
  type        = string
  default     = ""
}
```

- [ ] **Step 5.2: Decision gate — confirm whether to inject `AZURE_CLIENT_ID`**

All 11 container apps use **system-assigned managed identities**. `DefaultAzureCredential` in an Azure Container App with a system-assigned MI reads from IMDS automatically — it does NOT need `AZURE_CLIENT_ID` set explicitly.

**Before proceeding**, run:

```bash
az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --query "identity" -o json
```

- If output shows `"type": "SystemAssigned"` with no `userAssignedIdentities` — the `AZURE_CLIENT_ID` env var injection is **unnecessary** and should be **skipped**. Remove Steps 5.2–5.3 from your execution. Skip to Step 5.4.
- If output shows `"type": "UserAssigned"` — inject `AZURE_CLIENT_ID` using the **MI's client ID** (not the CI SP client ID). Get the MI client ID from `identity.userAssignedIdentities.<mi_resource_id>.clientId`.

**Why this matters:** Injecting the CI SP client ID (`65cf695c-...`) as `AZURE_CLIENT_ID` when apps use system-assigned MIs is harmless now (IMDS is tried after env-var credential), but if any app ever switches to user-assigned MI it would silently override it with the wrong identity.

If you confirm system-assigned MIs only, remove the `AZURE_CLIENT_ID`/`AZURE_TENANT_ID` env vars from the agent-apps injection entirely. The MANUAL-SETUP.md Step 1c was wrong to set these manually — agents authenticate via IMDS without them.

- [ ] **Step 5.3: Inject `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` in agent-apps/main.tf (only if user-assigned MI confirmed)**

*Skip this step if system-assigned MI confirmed in Step 5.2.*

In the `container` block of `azurerm_container_app.agents`, after the existing `ENVIRONMENT` env block, add:

```hcl
      dynamic "env" {
        for_each = var.client_id != "" ? [1] : []
        content {
          name  = "AZURE_CLIENT_ID"
          value = var.client_id
        }
      }
      dynamic "env" {
        for_each = var.tenant_id != "" ? [1] : []
        content {
          name  = "AZURE_TENANT_ID"
          value = var.tenant_id
        }
      }
```

Add the same two blocks to `azurerm_container_app.teams_bot` container block as well.

- [ ] **Step 5.3: Wire client_id and tenant_id into agent-apps in prod/main.tf**

In `module "agent_apps"` block in `prod/main.tf`, add:

```hcl
  client_id = var.client_id
  tenant_id = var.tenant_id
```

- [ ] **Step 5.4: Add `postgres_dsn` variable to `prod/variables.tf`**

**Note:** `postgres_dsn` already exists in `terraform/modules/agent-apps/variables.tf` (line ~189). Do NOT add it there again. Only `prod/variables.tf` is missing it.

Verify it's absent from prod:

```bash
grep "postgres_dsn" /Users/jasonmba/workspace/azure-agentic-platform/terraform/envs/prod/variables.tf || echo "NOT FOUND — safe to add"
```

Append to `terraform/envs/prod/variables.tf`:

```hcl
variable "postgres_dsn" {
  description = "PostgreSQL DSN for agents that need direct DB access (e.g., eol-agent eol_cache table)"
  type        = string
  sensitive   = true
  default     = ""
}
```

- [ ] **Step 5.5: Wire postgres_dsn into agent_apps in prod/main.tf**

In `module "agent_apps"` block in `prod/main.tf`, add:

```hcl
  postgres_dsn = var.postgres_dsn
```

- [ ] **Step 5.6: Add postgres_dsn to credentials.tfvars**

Add to `terraform/envs/prod/credentials.tfvars` (gitignored):

```hcl
postgres_dsn = "postgresql://aap_admin:<password>@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require"
```

Replace `<password>` with the PostgreSQL admin password. Get the server FQDN:

```bash
az postgres flexible-server show \
  --name aap-postgres-prod \
  --resource-group rg-aap-prod \
  --query "fullyQualifiedDomainName" -o tsv
```

- [ ] **Step 5.6: Add `cors_allowed_origins` and `all_subscription_ids` to terraform.tfvars**

Add to `terraform/envs/prod/terraform.tfvars`:

```hcl
cors_allowed_origins = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
all_subscription_ids = ["4c727b88-12f4-4c91-9c2b-372aab3bbae9"]
```

(Replace `4c727b88-12f4-4c91-9c2b-372aab3bbae9` with the actual platform subscription ID.)

- [ ] **Step 5.7: Add PostgreSQL Entra auth admin to databases/postgres.tf**

Append to the end of `terraform/modules/databases/postgres.tf`:

```hcl
# PostgreSQL Entra auth administrator
# The server already has active_directory_auth_enabled = true.
# This assigns the API gateway managed identity as an Entra administrator,
# enabling token-based auth (in addition to existing password auth).
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "api_gateway" {
  count = var.enable_postgres_entra_auth ? 1 : 0

  server_name         = azurerm_postgresql_flexible_server.main.name
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  object_id           = var.api_gateway_principal_id
  principal_name      = "ca-api-gateway-${var.environment}"
  principal_type      = "ServicePrincipal"
}
```

- [ ] **Step 5.8: Add new variables to databases/variables.tf**

Append to `terraform/modules/databases/variables.tf`:

```hcl
variable "enable_postgres_entra_auth" {
  description = "Add Entra auth administrator for PostgreSQL (server already has active_directory_auth_enabled = true)"
  type        = bool
  default     = true
}

variable "api_gateway_principal_id" {
  description = "Managed identity principal ID of the API gateway for PostgreSQL Entra auth"
  type        = string
  default     = ""
}
```

- [ ] **Step 5.9: Wire api_gateway_principal_id into databases module in prod/main.tf**

In `module "databases"` block in `prod/main.tf`, add:

```hcl
  api_gateway_principal_id = module.agent_apps.agent_principal_ids["api-gateway"]
```

- [ ] **Step 5.10: Plan and review expected changes**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/terraform/envs/prod
terraform plan -var-file="credentials.tfvars" 2>&1 | grep -E "(Plan:|AZURE_CLIENT_ID|AZURE_TENANT_ID|cors|activity_log|postgres_entra)"
```

Expected changes:
- Container apps: env vars `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` added (in-place update, no restart needed)
- `module.activity_log`: 1 new `azurerm_monitor_diagnostic_setting` created (expected — was zero due to empty `all_subscription_ids`)
- `module.databases`: 1 new `azurerm_postgresql_flexible_server_active_directory_administrator`

**Before applying:** Verify `AZURE_CLIENT_ID` env var change — ensure the CI SP client ID (`65cf695c-...`) is correct for your container apps' DefaultAzureCredential chain. If the apps use system-assigned MIs exclusively, this env var is harmless but unnecessary. If they need explicit client ID for a user-assigned MI, ensure this is the right client ID.

- [ ] **Step 5.11: Apply**

```bash
terraform apply -var-file="credentials.tfvars" -auto-approve
```

Expected: Container apps updated in-place; activity log diagnostic setting created; PostgreSQL Entra admin created.

- [ ] **Step 5.12: Verify**

```bash
terraform state list 2>/dev/null | grep -E "(activity_log|postgres_flexible_server_active)"
```

Expected: At least one `azurerm_monitor_diagnostic_setting` and one `azurerm_postgresql_flexible_server_active_directory_administrator`.

- [ ] **Step 5.13: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add terraform/envs/prod/terraform.tfvars \
        terraform/envs/prod/variables.tf \
        terraform/envs/prod/main.tf \
        terraform/modules/agent-apps/main.tf \
        terraform/modules/agent-apps/variables.tf \
        terraform/modules/databases/postgres.tf \
        terraform/modules/databases/variables.tf
git commit -m "feat: wire env vars, cors, subscription ids, postgres entra auth"
```

---

## Chunk 6: Foundry Agents Bootstrap Script & CI Workflow

### Task 6: Create idempotent Foundry agents provisioning script and wire into CI

**Files:**
- Create: `scripts/provision-foundry-agents.py`
- Modify: `.github/workflows/terraform-apply.yml`
- Modify: `terraform/envs/prod/terraform.tfvars` (once agents created)

- [ ] **Step 6.1: Create `scripts/provision-foundry-agents.py`**

```python
#!/usr/bin/env python3
"""
Idempotent Foundry agent provisioning script.

Creates all 9 platform agents if they don't already exist.
Outputs agents.tfvars with all agent IDs for use with terraform apply -var-file.

Usage:
    python scripts/provision-foundry-agents.py

Environment variables required:
    AZURE_PROJECT_ENDPOINT  — AI Foundry project endpoint URL
    AZURE_CLIENT_ID         — Service principal client ID (or use DefaultAzureCredential)
    AZURE_TENANT_ID         — Entra tenant ID
    AZURE_CLIENT_SECRET     — Service principal secret (or use DefaultAzureCredential)
"""
import os
import sys
import json
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

AGENT_DEFINITIONS = [
    {
        "name": "orchestrator",
        "var_name": "orchestrator_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the platform orchestrator. Analyze Azure incidents and delegate to the appropriate domain specialist agent.",
    },
    {
        "name": "compute",
        "var_name": "compute_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the compute specialist. Investigate and remediate Azure compute incidents (VMs, VMSS, AKS).",
    },
    {
        "name": "network",
        "var_name": "network_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the network specialist. Investigate and remediate Azure networking incidents (VNet, NSG, DNS, connectivity).",
    },
    {
        "name": "storage",
        "var_name": "storage_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the storage specialist. Investigate and remediate Azure storage incidents.",
    },
    {
        "name": "security",
        "var_name": "security_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the security specialist. Investigate and remediate Azure security incidents and Defender alerts.",
    },
    {
        "name": "sre",
        "var_name": "sre_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the SRE specialist. Investigate reliability and availability issues across Azure services.",
    },
    {
        "name": "arc",
        "var_name": "arc_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the Arc specialist. Investigate and remediate incidents on Arc-enabled servers and Kubernetes clusters.",
    },
    {
        "name": "patch",
        "var_name": "patch_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the patch compliance specialist. Investigate and remediate OS patching and update management incidents.",
    },
    {
        "name": "eol",
        "var_name": "eol_agent_id",
        "model": "gpt-4o",
        "instructions": "You are the end-of-life specialist. Detect and report on end-of-life operating systems and software across Azure.",
    },
]

def get_project_endpoint() -> str:
    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT")
    if not endpoint:
        raise EnvironmentError(
            "AZURE_PROJECT_ENDPOINT environment variable is required. "
            "Get it from: az cognitiveservices account show --name <name> --resource-group rg-aap-prod --query properties.endpoint"
        )
    return endpoint.rstrip("/")


def provision_agents() -> dict[str, str]:
    """Create agents if they don't exist. Returns map of var_name -> agent_id."""
    endpoint = get_project_endpoint()
    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=endpoint, credential=credential)

    # List existing agents indexed by name for O(1) lookup
    existing: dict[str, str] = {}
    try:
        agents_list = client.agents.list_agents()
        for agent in agents_list:
            existing[agent.name] = agent.id
        print(f"Found {len(existing)} existing agent(s): {list(existing.keys())}")
    except Exception as e:
        print(f"Warning: could not list existing agents: {e}", file=sys.stderr)

    results: dict[str, str] = {}

    for defn in AGENT_DEFINITIONS:
        name = defn["name"]
        var_name = defn["var_name"]

        if name in existing:
            agent_id = existing[name]
            print(f"  [skip] {name}: already exists ({agent_id})")
        else:
            print(f"  [create] {name} ...", end="", flush=True)
            agent = client.agents.create_agent(
                model=defn["model"],
                name=name,
                # Note: 'description' is not a parameter in azure-ai-projects 2.0.1 GA.
                # Instructions serve as the agent's identity.
                instructions=defn["instructions"],
            )
            agent_id = agent.id
            print(f" {agent_id}")

        results[var_name] = agent_id

    return results


def write_tfvars(agent_ids: dict[str, str], output_path: Path) -> None:
    """Write agents.tfvars for use with terraform apply -var-file."""
    lines = [
        "# Auto-generated by scripts/provision-foundry-agents.py",
        "# Do not edit manually — this file is regenerated on each bootstrap run.",
        "# This file is gitignored.",
        "",
    ]
    for var_name, agent_id in agent_ids.items():
        lines.append(f'{var_name} = "{agent_id}"')
    lines.append("")

    output_path.write_text("\n".join(lines))
    print(f"\nWrote {output_path}")


def main() -> None:
    print("=== Foundry Agent Provisioning ===")
    agent_ids = provision_agents()

    output_path = Path(__file__).parent.parent / "terraform" / "envs" / "prod" / "agents.tfvars"
    write_tfvars(agent_ids, output_path)

    print("\nAll agents provisioned successfully.")
    print(f"Pass to terraform: -var-file={output_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6.2: Make the script executable**

```bash
chmod +x /Users/jasonmba/workspace/azure-agentic-platform/scripts/provision-foundry-agents.py
```

- [ ] **Step 6.3: Add `agents.tfvars` to .gitignore**

```bash
grep -q "agents.tfvars" /Users/jasonmba/workspace/azure-agentic-platform/.gitignore || \
  echo "terraform/envs/prod/agents.tfvars" >> /Users/jasonmba/workspace/azure-agentic-platform/.gitignore
```

- [ ] **Step 6.4: Add Foundry agents bootstrap step to terraform-apply.yml**

In `.github/workflows/terraform-apply.yml`, in the `apply-prod` job, add a step **before** `Terraform Apply`:

```yaml
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Foundry SDK
        run: pip install "azure-ai-projects>=2.0.1" "azure-identity"

      - name: Provision Foundry Agents
        env:
          AZURE_PROJECT_ENDPOINT: ${{ secrets.AZURE_PROJECT_ENDPOINT }}
          AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
          AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
          AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
        run: python scripts/provision-foundry-agents.py
```

Also add `-var-file="agents.tfvars"` to the prod `terraform apply` command:

```yaml
      - name: Terraform Apply
        working-directory: terraform/envs/prod
        run: terraform apply -auto-approve -input=false -var-file="agents.tfvars"
```

**Note:** Also add `AZURE_PROJECT_ENDPOINT` to the GitHub Actions secrets list (same value as the Foundry project endpoint).

- [ ] **Step 6.5: Run the script manually to provision agents and generate agents.tfvars**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
export AZURE_PROJECT_ENDPOINT="<your foundry project endpoint>"
python scripts/provision-foundry-agents.py
```

Expected: Script creates missing agents, outputs `terraform/envs/prod/agents.tfvars`.

- [ ] **Step 6.6: Verify agents.tfvars content**

```bash
cat terraform/envs/prod/agents.tfvars
```

Expected: 9 lines of `xxx_agent_id = "asst_..."` with non-empty values.

- [ ] **Step 6.7: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add scripts/provision-foundry-agents.py \
        .github/workflows/terraform-apply.yml \
        .gitignore
git commit -m "feat: idempotent foundry agent bootstrap script + ci workflow integration"
```

---

## Chunk 7: GitHub Secrets Script, BOOTSTRAP.md, MANUAL-SETUP.md Cleanup

### Task 7: Add bootstrap-github-secrets.sh, write BOOTSTRAP.md, update MANUAL-SETUP.md

**Files:**
- Create: `scripts/bootstrap-github-secrets.sh`
- Create: `docs/BOOTSTRAP.md`
- Modify: `docs/MANUAL-SETUP.md`

- [ ] **Step 7.1: Create `scripts/bootstrap-github-secrets.sh`**

```bash
#!/usr/bin/env bash
# bootstrap-github-secrets.sh
#
# Sets missing GitHub Actions secrets for the AAP repository.
# Reads values from environment variables — never hardcoded.
#
# Required environment variables:
#   GH_REPO               — e.g. "myorg/azure-agentic-platform"
#   POSTGRES_ADMIN_PASSWORD
#   AZURE_OPENAI_ENDPOINT
#   AZURE_OPENAI_API_KEY
#   AZURE_PROJECT_ENDPOINT  (for Foundry agents bootstrap)
#
# Prerequisites:
#   gh CLI installed and authenticated: gh auth login
#
set -euo pipefail

REPO="${GH_REPO:?GH_REPO env var is required (e.g. myorg/azure-agentic-platform)}"

required_vars=(
  POSTGRES_ADMIN_PASSWORD
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_API_KEY
  AZURE_PROJECT_ENDPOINT
)

echo "=== Setting GitHub Actions secrets for ${REPO} ==="

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: \$${var} is not set" >&2
    exit 1
  fi
  echo "  Setting ${var}..."
  gh secret set "${var}" \
    --repo "${REPO}" \
    --body "${!var}"
done

echo ""
echo "All secrets set successfully."
echo "Verify at: https://github.com/${REPO}/settings/secrets/actions"
```

- [ ] **Step 7.2: Make script executable**

```bash
chmod +x /Users/jasonmba/workspace/azure-agentic-platform/scripts/bootstrap-github-secrets.sh
```

- [ ] **Step 7.3: Create `docs/BOOTSTRAP.md`**

```markdown
# Bootstrap Guide — Azure Agentic Platform

This document lists the **two steps that cannot be automated** and must be performed manually once when setting up a new environment. Everything else is handled by `terraform apply` and the CI/CD pipeline.

---

## Step 0 (Before First Terraform Apply): Grant CI SP Graph Permission

The Entra app registration (`aap-web-ui-prod`) is managed by Terraform. This requires the CI service principal to have `Application.ReadWrite.All` on the Entra tenant.

### Run once:

```bash
SP_CLIENT_ID="65cf695c-1def-48ba-96af-d968218c90ba"

# Grant Application.ReadWrite.All (Microsoft Graph, application permission)
az ad app permission add \
  --id "$SP_CLIENT_ID" \
  --api 00000003-0000-0000-c000-000000000000 \
  --api-permissions 1bfefb4e-e0b5-418b-a88f-73c46d2cc8e9=Role

# Grant admin consent
az ad app permission admin-consent --id "$SP_CLIENT_ID"
```

Then verify:
```bash
az ad app permission list --id "$SP_CLIENT_ID" --query "[?resourceAppId=='00000003-0000-0000-c000-000000000000'].resourceAccess[].id" -o tsv
# Expected: includes 1bfefb4e-e0b5-418b-a88f-73c46d2cc8e9
```

---

## Step 1 (After `enable_teams_bot = true` Apply): Enable Teams Channel

After `terraform apply` creates the Azure Bot resource, enable the Microsoft Teams channel:

1. Azure Portal → **Azure Bot** → `aap-teams-bot-prod`
2. Left menu → **Channels** → click **Microsoft Teams**
3. Accept terms → click **Apply**
4. Back in the Azure Bot → **Configuration** → verify **Messaging endpoint** is set to `https://ca-teams-bot-prod.<fqdn>/api/messages`

No CLI equivalent exists for Teams channel configuration.

---

## Everything Else is Automated

| Task | How |
|---|---|
| All Azure resources | `terraform apply` |
| Foundry agent IDs | `scripts/provision-foundry-agents.py` (runs before `terraform apply` in CI) |
| GitHub Actions secrets | `scripts/bootstrap-github-secrets.sh` |
| pgvector extension | `terraform-apply.yml` CI workflow (temp firewall rule + psql) |
| Runbook seeding | `terraform-apply.yml` CI workflow (staging only) |
```

- [ ] **Step 7.4: Update `docs/MANUAL-SETUP.md`**

Replace the top of the file with a deprecation notice and forward-reference. Replace the Summary Checklist with an updated version reflecting what is now automated. Keep the full step details for reference but mark automated steps clearly.

Add at the very top of `docs/MANUAL-SETUP.md`:

```markdown
> **IMPORTANT:** Most steps in this document are now automated by Terraform and the CI/CD pipeline.
> See [BOOTSTRAP.md](BOOTSTRAP.md) for the two remaining manual steps.
> Steps that are now automated are marked with `[AUTOMATED]` below.
```

Update the Summary Checklist at the bottom to:

```markdown
## Summary Checklist

```
[AUTOMATED] Step 1 — AZURE_PROJECT_ENDPOINT, ORCHESTRATOR_AGENT_ID, AZURE_CLIENT_ID, AZURE_TENANT_ID, CORS_ALLOWED_ORIGINS — now wired by Terraform + provision-foundry-agents.py
[AUTOMATED] Step 2 — Azure AI Developer role for api-gateway MI — now managed by module.rbac (api-gateway-aidev-foundry)
[AUTOMATED] Step 3 — LOG_ANALYTICS_WORKSPACE_ID on web-ui — now wired by Terraform (module.monitoring output)
[AUTOMATED] Step 4 — Cosmos DB containers + data-plane RBAC — now managed by module.databases
□ Step 5a-5c — Register Azure Bot → see BOOTSTRAP.md Step 1 (one-time after enable_teams_bot = true)
[AUTOMATED] Step 5e — teams_bot_id + teams_bot_password — now managed by module.teams_bot + KV
[AUTOMATED] Step 6 — GitHub secrets: POSTGRES_ADMIN_PASSWORD, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY — run scripts/bootstrap-github-secrets.sh
□ Step 7 — Runbook seeding in production — still manual (VNet-isolated; CI seeds staging only)
[AUTOMATED] Step 8 — Multi-subscription reader roles (when all_subscription_ids is populated)
[AUTOMATED] Step 9 — Entra redirect URIs — managed by module.entra_apps
□ Step 10 — Rotate client_secret and postgres_admin_password (periodic rotation task)
```
```

- [ ] **Step 7.5: Run the GitHub secrets script to set missing secrets**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
export GH_REPO="<your-org>/azure-agentic-platform"
export POSTGRES_ADMIN_PASSWORD="<from credentials.tfvars>"
export AZURE_OPENAI_ENDPOINT="<foundry endpoint>"
export AZURE_OPENAI_API_KEY="<key from Azure Portal>"
export AZURE_PROJECT_ENDPOINT="<foundry project endpoint>"

./scripts/bootstrap-github-secrets.sh
```

Expected: `All secrets set successfully.`

- [ ] **Step 7.6: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add scripts/bootstrap-github-secrets.sh \
        docs/BOOTSTRAP.md \
        docs/MANUAL-SETUP.md
git commit -m "docs: add bootstrap guide, github secrets script, update manual-setup"
```

---

## Chunk 8: Final Verification

### Task 8: Final terraform plan must show zero unexpected changes

- [ ] **Step 8.1: Run terraform plan with all var-files**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/terraform/envs/prod
terraform plan \
  -var-file="credentials.tfvars" \
  -var-file="agents.tfvars" \
  2>&1 | tee /tmp/final-plan.txt

tail -5 /tmp/final-plan.txt
```

Expected: `Plan: 0 to add, 0 to change, 0 to destroy.`

If there are unexpected changes, investigate each one before accepting.

- [ ] **Step 8.2: Verify success criteria in state**

```bash
# Cosmos RBAC — expect 10
terraform state list 2>/dev/null | grep cosmosdb_sql_role_assignment | wc -l

# Entra app registration
terraform state list 2>/dev/null | grep azuread_application | grep -v fabric_sp

# Azure Bot service
terraform state list 2>/dev/null | grep bot_service

# Activity log diagnostic settings
terraform state list 2>/dev/null | grep monitor_diagnostic_setting

# PostgreSQL Entra admin
terraform state list 2>/dev/null | grep postgresql_flexible_server_active_directory_administrator
```

Expected outputs:
- Cosmos: `10`
- Entra: `module.entra_apps[0].azuread_application.web_ui` (plus fabric_sp if enabled)
- Bot: `module.teams_bot[0].azurerm_bot_service_azure_bot.main`
- Activity log: at least 1 entry
- PostgreSQL Entra admin: 1 entry

- [ ] **Step 8.3: Final commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add -A
git commit -m "chore: terraform drift fix complete - all resources under terraform management"
```

---

## Summary of Changes

| Area | Before | After |
|---|---|---|
| Entra app reg | Manual, invisible to TF | `module.entra_apps[0]` — fully managed |
| Azure AI Developer role | Manual + TF duplicate risk | Imported, TF-owned |
| Cosmos data-plane RBAC | 10 manual assignments | `module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor` for_each |
| Azure Bot / Teams | CA exists, bot service absent | `module.teams_bot[0].azurerm_bot_service_azure_bot.main` |
| CORS_ALLOWED_ORIGINS | `*` (hardcoded default) | Locked to web-UI URL via tfvars |
| AZURE_CLIENT_ID / TENANT_ID env vars | Set manually, wiped on apply | Wired via Terraform variables |
| all_subscription_ids | `[]` (zero ARM roles, zero activity log) | Platform sub ID set — roles and activity log activated |
| PostgreSQL Entra admin | Missing | `azurerm_postgresql_flexible_server_active_directory_administrator` |
| Foundry agents | Manual portal creation | `provision-foundry-agents.py` — idempotent, generates agents.tfvars |
| GitHub secrets | 3 missing | `bootstrap-github-secrets.sh` — sets all missing secrets |
| Documentation | MANUAL-SETUP.md (stale) | BOOTSTRAP.md (2 manual steps) + updated MANUAL-SETUP.md |
