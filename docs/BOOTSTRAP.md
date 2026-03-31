# Bootstrap Guide — Azure Agentic Platform (AAP)

This guide covers the one-time manual steps that must be completed before `terraform apply`
and CI/CD can fully function. All other platform setup is automated.

> **Scope:** Steps here have no automation path — they require a Global Administrator,
> a portal click that has no stable Terraform resource, or a secret that lives outside Azure.
> Everything else is covered by Terraform and the CI pipeline.

---

## Step 1: Grant CI SP `Application.ReadWrite.All` (Entra) — DEFERRED

> **Status: Deferred.** The web-UI app registration (`aap-web-ui-prod`) already exists and
> works in production. `enable_entra_apps` is intentionally set to `false` in
> `terraform/envs/prod/terraform.tfvars` until this grant is done. The platform runs fully
> without it. This step is only required when Terraform needs to own the app registration
> lifecycle (e.g. rebuilding from scratch in a new tenant, or rotating the client secret via TF).
>
> **Future work:** When ready to enable, follow the steps below. Tracked in `TODO.md`.

**Why:** The `azuread` Terraform provider requires the Terraform service principal to have
Microsoft Graph `Application.ReadWrite.All` admin-consented on the Entra tenant to manage
app registrations (web-UI MSAL app, teams-bot app registration).

**Who:** Must be performed by a **Global Administrator** of the Entra tenant.

**SP Client ID:** `65cf695c-1def-48ba-96af-d968218c90ba`

```bash
# 1. Get the service principal object ID for the CI SP
SP_OBJECT_ID=$(az ad sp show \
  --id "65cf695c-1def-48ba-96af-d968218c90ba" \
  --query "id" -o tsv)

# 2. Get the Microsoft Graph service principal object ID
GRAPH_SP_ID=$(az ad sp show \
  --id "00000003-0000-0000-c000-000000000000" \
  --query "id" -o tsv)

# 3. Get the Application.ReadWrite.All role ID from Graph
ROLE_ID=$(az ad sp show \
  --id "00000003-0000-0000-c000-000000000000" \
  --query "appRoles[?value=='Application.ReadWrite.All'].id" \
  -o tsv)

# 4. Add the app role assignment (requires Global Admin or Privileged Role Admin)
az rest \
  --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/${SP_OBJECT_ID}/appRoleAssignments" \
  --body "{
    \"principalId\": \"${SP_OBJECT_ID}\",
    \"resourceId\": \"${GRAPH_SP_ID}\",
    \"appRoleId\": \"${ROLE_ID}\"
  }"
```

**After completion:**

1. Set `enable_entra_apps = true` in `terraform/envs/prod/terraform.tfvars`
2. Uncomment the two commented-out `import` blocks for `entra_apps` in `terraform/envs/prod/imports.tf`
3. Run:
   ```bash
   cd terraform/envs/prod
   terraform apply -var-file="credentials.tfvars"
   ```
4. Verify:
   ```bash
   terraform state list | grep azuread_application
   ```

---

## Step 2: Enable Teams Channel in Azure Bot Portal

**Why:** There is no stable Terraform resource for enabling the Microsoft Teams channel on an
Azure Bot. The `azurerm_bot_channel_ms_teams` resource exists but requires the bot to be fully
provisioned first, and enabling the channel requires accepting Microsoft's Terms of Service in
the portal — a step that cannot be scripted.

**Prerequisites:** `enable_teams_bot = true` must be set in `terraform.tfvars` and
`terraform apply` must have completed successfully, creating the `aap-teams-bot-prod` Azure Bot resource.

**Steps:**

1. Go to **Azure Portal** → **Resource Groups** → `rg-aap-prod` → `aap-teams-bot-prod` (Azure Bot)
2. Left menu → **Channels**
3. Click **Microsoft Teams**
4. Review and accept the Terms of Service
5. Click **Apply**
6. Verify the Teams channel shows status **Running**

---

## Step 3: Set GitHub Actions Secrets

**Why:** These secrets live in GitHub — Terraform cannot provision them into GitHub
Actions environments. They must be set once before CI/CD can run.

The `FOUNDRY_PROJECT_ENDPOINT` secret is a new addition: it is required by the
`provision-foundry-agents.py` pre-apply step that runs in CI to provision Foundry agents
before `terraform apply`.

### Using the bootstrap script (recommended)

```bash
# Set all four secrets at once — values come from env vars, never hardcoded
export POSTGRES_ADMIN_PASSWORD="..."
export AZURE_OPENAI_ENDPOINT="https://<account>.openai.azure.com/"
export AZURE_OPENAI_API_KEY="..."
export FOUNDRY_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project-id>"

./scripts/bootstrap-github-secrets.sh
```

The script is idempotent — safe to re-run to update values.

### How to obtain each value

| Secret | How to obtain |
|---|---|
| `POSTGRES_ADMIN_PASSWORD` | From `credentials.tfvars` (`postgres_admin_password`) |
| `AZURE_OPENAI_ENDPOINT` | Azure Portal → Foundry account → **Keys and Endpoint** |
| `AZURE_OPENAI_API_KEY` | Azure Portal → Foundry account → **Keys and Endpoint** |
| `FOUNDRY_PROJECT_ENDPOINT` | See command below |

**How to get `FOUNDRY_PROJECT_ENDPOINT`:**

```bash
# Get the Foundry account endpoint
FOUNDRY_ACCOUNT=$(az cognitiveservices account list \
  --resource-group rg-aap-prod \
  --query "[?kind=='AIServices'].name" -o tsv)

FOUNDRY_ENDPOINT=$(az cognitiveservices account show \
  --name "$FOUNDRY_ACCOUNT" \
  --resource-group rg-aap-prod \
  --query "properties.endpoint" -o tsv)

# Get the Foundry project ID from Terraform state
cd terraform/envs/prod
PROJECT_ID=$(terraform output -raw foundry_project_id 2>/dev/null || echo "<get from az portal>")

# Construct the full endpoint
echo "${FOUNDRY_ENDPOINT}api/projects/${PROJECT_ID}"
```

The value looks like:
`https://<account-name>.services.ai.azure.com/api/projects/<project-guid>`

---

## What Is NOT in This Guide

Everything else is automated. You do **not** need to manually:

- Provision Azure resources — Terraform handles all of them
- Create Foundry agents — `provision-foundry-agents.py` runs as a CI pre-apply step
- Assign Cosmos DB data-plane RBAC — managed by `module.databases` via `azurerm_cosmosdb_sql_role_assignment`
- Assign `Azure AI Developer` role to the API gateway — managed by `module.rbac`
- Set `AZURE_PROJECT_ENDPOINT` or `ORCHESTRATOR_AGENT_ID` on the Container App — wired by Terraform via `module.container_apps`
- Seed the PostgreSQL schema — applied by Terraform or the CI migration step

For the full list of all setup steps (including now-automated ones), see `docs/MANUAL-SETUP.md`.
