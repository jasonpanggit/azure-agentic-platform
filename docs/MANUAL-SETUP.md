# Manual Setup Guide — Azure Agentic Platform (AAP)

This document lists every configuration step that **cannot be automated by Terraform** and must be performed manually in the Azure Portal, Azure CLI, or GitHub. Follow steps in order; some later steps depend on values produced by earlier ones.

---

## Prerequisites

- `az` CLI installed and logged in: `az login`
- Terraform applied successfully (`terraform apply` in `terraform/envs/prod/`)
- Access to the GitHub repository settings (Secrets & Variables)
- Owner or Contributor on subscription `4c727b88-12f4-4c91-9c2b-372aab3bbae9`

---

## Step 1 — API Gateway: Set Missing Environment Variables

The API gateway container app (`ca-api-gateway-prod`) fails to start the Foundry dispatch because two critical variables are not injected by Terraform.

### 1a. Get the Foundry project endpoint

```bash
az cognitiveservices account show \
  --name $(az cognitiveservices account list --query "[?kind=='AIServices'].name" -o tsv) \
  --resource-group rg-aap-prod \
  --query "properties.endpoint" -o tsv
```

Copy the value — it looks like:
`https://<account-name>.cognitiveservices.azure.com/`

### 1b. Get the Orchestrator agent ID

1. Go to **Azure AI Foundry** → [https://ai.azure.com](https://ai.azure.com)
2. Open the AAP project
3. Navigate to **Agents** in the left sidebar
4. If the Orchestrator agent does not exist yet, create it:
   - Click **+ New agent**
   - Name: `orchestrator`
   - Model: `gpt-4o` (use the deployment already provisioned)
   - System prompt: set per your runbook / operational instructions
   - Click **Create**
5. Note the **Agent ID** from the agent detail page (format: `asst_xxxxxxxxxxxxxxxxxxxxxxxx`)

### 1c. Set the env vars on the Container App

```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars \
    "AZURE_PROJECT_ENDPOINT=<value from 1a>" \
    "ORCHESTRATOR_AGENT_ID=<value from 1b>" \
    "AZURE_CLIENT_ID=65cf695c-1def-48ba-96af-d968218c90ba" \
    "AZURE_TENANT_ID=abbdca26-d233-4a1e-9d8c-c4eebbc16e50" \
    "CORS_ALLOWED_ORIGINS=https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
```

### 1d. Verify the gateway is healthy

```bash
curl https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/health
# Expected: {"status":"ok"} or similar
```

---

## Step 2 — Foundry: Grant Managed Identity Access to the Project

The API gateway uses its **system-assigned managed identity** to call Foundry. The identity needs the `Azure AI Developer` role on the Foundry account.

```bash
# Get the gateway container app's managed identity principal ID
GATEWAY_PRINCIPAL=$(az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --query "identity.principalId" -o tsv)

# Get the Foundry account resource ID
FOUNDRY_ID=$(az cognitiveservices account show \
  --name $(az cognitiveservices account list \
    --resource-group rg-aap-prod \
    --query "[?kind=='AIServices'].name" -o tsv) \
  --resource-group rg-aap-prod \
  --query "id" -o tsv)

# Assign Azure AI Developer role
az role assignment create \
  --assignee "$GATEWAY_PRINCIPAL" \
  --role "Azure AI Developer" \
  --scope "$FOUNDRY_ID"
```

> **Note**: If you already ran `terraform apply` with the `entra-apps` module, this role assignment may already exist. Run `az role assignment list --assignee "$GATEWAY_PRINCIPAL"` to check.

---

## Step 3 — Log Analytics: Wire Workspace ID to Web UI

The observability tab reads `LOG_ANALYTICS_WORKSPACE_ID` from the web-ui container. If Terraform was applied before this variable was wired, set it manually.

### 3a. Get the Log Analytics customer ID (workspace ID)

```bash
az monitor log-analytics workspace show \
  --resource-group rg-aap-prod \
  --workspace-name $(az monitor log-analytics workspace list \
    --resource-group rg-aap-prod \
    --query "[0].name" -o tsv) \
  --query "customerId" -o tsv
```

The output is a GUID like `a1b2c3d4-...`. This is the **Customer ID**, not the resource ID.

### 3b. Set on the web-ui container app

```bash
az containerapp update \
  --name ca-web-ui-prod \
  --resource-group rg-aap-prod \
  --set-env-vars "LOG_ANALYTICS_WORKSPACE_ID=<customer ID from 3a>"
```

---

## Step 4 — Cosmos DB: Verify the `incidents` Container

The dedup layer and incident feed require a Cosmos DB container named `incidents`.

### 4a. Check if the container exists

```bash
COSMOS_ACCOUNT=$(az cosmosdb list \
  --resource-group rg-aap-prod \
  --query "[0].name" -o tsv)

az cosmosdb sql container show \
  --account-name "$COSMOS_ACCOUNT" \
  --database-name aap \
  --name incidents \
  --resource-group rg-aap-prod
```

### 4b. Create if missing

```bash
az cosmosdb sql container create \
  --account-name "$COSMOS_ACCOUNT" \
  --database-name aap \
  --name incidents \
  --resource-group rg-aap-prod \
  --partition-key-path "/incident_id" \
  --throughput 400
```

### 4c. Grant Managed Identity data plane access (Cosmos RBAC)

Each container app that reads/writes Cosmos needs a **data plane role assignment** (distinct from ARM RBAC).

```bash
# Get the Cosmos DB account ID
COSMOS_ID=$(az cosmosdb show \
  --name "$COSMOS_ACCOUNT" \
  --resource-group rg-aap-prod \
  --query "id" -o tsv)

# Repeat for each container app that accesses Cosmos
for APP_NAME in ca-api-gateway-prod ca-orchestrator-prod; do
  PRINCIPAL=$(az containerapp show \
    --name "$APP_NAME" \
    --resource-group rg-aap-prod \
    --query "identity.principalId" -o tsv)

  az cosmosdb sql role assignment create \
    --account-name "$COSMOS_ACCOUNT" \
    --resource-group rg-aap-prod \
    --role-definition-name "Cosmos DB Built-in Data Contributor" \
    --principal-id "$PRINCIPAL" \
    --scope "$COSMOS_ID"
done
```

---

## Step 5 — Teams Bot Registration

Required for the Teams integration. Skip if Teams notifications are not needed yet.

### 5a. Create an Azure Bot resource

1. Azure Portal → **Create a resource** → search "Azure Bot" → **Create**
2. Fill in:
   - **Bot handle**: `aap-teams-bot-prod`
   - **Subscription**: `ME-MngEnvMCAP719041-gutee-1`
   - **Resource group**: `rg-aap-prod`
   - **Pricing tier**: F0 (free) or S1
   - **Type of App**: `User-Assigned Managed Identity` or `Single Tenant`
3. Click **Review + Create** → **Create**

### 5b. Get the Bot application ID and create a secret

1. In the Azure Bot resource → **Configuration** → note the **Microsoft App ID** (this is `teams_bot_id`)
2. Go to **Azure Active Directory** → **App registrations** → find the app with that ID
3. **Certificates & secrets** → **New client secret**
   - Description: `teams-bot-prod`
   - Expiry: 24 months
4. Copy the **Value** immediately — this is `teams_bot_password`

### 5c. Set the Teams channel

1. In the Azure Bot resource → **Channels** → click **Microsoft Teams**
2. Accept terms → **Apply**

### 5d. Get the Teams channel ID

1. Open Microsoft Teams desktop/web app
2. Navigate to the target channel
3. Click **...** (More options) → **Get link to channel**
4. The URL contains `groupId=<guid>&tenantId=<guid>&channelId=<encoded>` — note the `groupId` and `channelId`
5. URL-decode the `channelId` value

### 5e. Update credentials.tfvars and re-apply Terraform

```hcl
# terraform/envs/prod/credentials.tfvars
teams_bot_id       = "<Microsoft App ID from 5b>"
teams_bot_password = "<client secret value from 5b>"
teams_channel_id   = "<channelId from 5d>"
```

```bash
cd terraform/envs/prod
terraform apply -var-file="credentials.tfvars"
```

### 5f. Set the bot messaging endpoint

After Terraform deploys the teams-bot Container App:

1. Back in Azure Portal → Azure Bot resource → **Configuration**
2. Set **Messaging endpoint**:
   ```
   https://ca-teams-bot-prod.<random>.azurecontainerapps.io/api/messages
   ```
3. Click **Apply**

---

## Step 6 — GitHub Actions: Secrets and Variables

Open the GitHub repository → **Settings** → **Secrets and variables** → **Actions**.

### Required Secrets

| Name | Value | How to Obtain |
|---|---|---|
| `AZURE_CLIENT_ID` | `65cf695c-1def-48ba-96af-d968218c90ba` | Already in credentials.tfvars |
| `AZURE_CLIENT_SECRET` | `HDM8Q~...` | Already in credentials.tfvars |
| `AZURE_TENANT_ID` | `abbdca26-d233-4a1e-9d8c-c4eebbc16e50` | Already in credentials.tfvars |
| `AZURE_SUBSCRIPTION_ID` | `4c727b88-12f4-4c91-9c2b-372aab3bbae9` | Already in credentials.tfvars |
| `ACR_LOGIN_SERVER` | `<acr-name>.azurecr.io` | `az acr list --resource-group rg-aap-prod --query "[0].loginServer" -o tsv` |
| `POSTGRES_ADMIN_PASSWORD` | `Jas190277on!` | Already in credentials.tfvars |
| `AZURE_OPENAI_ENDPOINT` | e.g. `https://aap-foundry-prod.openai.azure.com/` | Same as `AZURE_PROJECT_ENDPOINT` prefix |
| `AZURE_OPENAI_API_KEY` | API key | Azure Portal → Foundry account → Keys and Endpoint |

> GitHub Actions auth modes:
> - Preferred: configure a federated identity credential on the app or service principal referenced by `AZURE_CLIENT_ID` so `azure/login` can use OIDC.
> - Fallback: set `AZURE_CLIENT_SECRET` in GitHub Actions secrets. The reusable build and deploy workflows will use the client secret automatically when it is present.

### Required Variables

| Name | Value | How to Obtain |
|---|---|---|
| `NEXT_PUBLIC_AZURE_CLIENT_ID` | `505df1d3-...` | Azure Portal → App registrations → `aap-web-ui-prod` → Application (client) ID |
| `NEXT_PUBLIC_TENANT_ID` | `abbdca26-d233-4a1e-9d8c-c4eebbc16e50` | Same as tenant ID |
| `NEXT_PUBLIC_REDIRECT_URI` | `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/callback` | Web UI public URL + `/callback` |
| `ACR_LOGIN_SERVER` | `<acr-name>.azurecr.io` | Same as secret above |

> **After setting** `NEXT_PUBLIC_AZURE_CLIENT_ID`, you must rebuild the web-ui Docker image with a cache-bust to bake the new value in:
> ```bash
> gh workflow run web-ui-build.yml --ref main -f no_cache=true
> ```

---

## Step 7 — Runbook Seeding (Production)

The CI pipeline seeds runbooks automatically in staging but **not in production**. Run manually:

```bash
cd services
pip install azure-openai asyncpg pgvector

# Get the PostgreSQL connection details
PG_HOST=$(az postgres flexible-server list \
  --resource-group rg-aap-prod \
  --query "[0].fullyQualifiedDomainName" -o tsv)

export AZURE_OPENAI_ENDPOINT="<from Step 6 secrets>"
export AZURE_OPENAI_API_KEY="<from Step 6 secrets>"
export POSTGRES_HOST="$PG_HOST"
export POSTGRES_DB="aap"
export POSTGRES_USER="aap_admin"
export POSTGRES_PASSWORD="<from credentials.tfvars>"

python scripts/seed-runbooks/seed.py
```

---

## Step 8 — Multi-Subscription Reader Roles (Optional)

If you want the platform to monitor **additional Azure subscriptions** beyond the main one, grant the platform's managed identity `Reader` on each:

```bash
# Platform service principal object ID
SP_OBJECT_ID=$(az ad sp show \
  --id "65cf695c-1def-48ba-96af-d968218c90ba" \
  --query "id" -o tsv)

# Repeat for each additional subscription
for SUB_ID in "<sub-id-2>" "<sub-id-3>"; do
  az role assignment create \
    --assignee "$SP_OBJECT_ID" \
    --role "Reader" \
    --scope "/subscriptions/$SUB_ID"
done
```

Then update `credentials.tfvars`:

```hcl
all_subscription_ids = [
  "4c727b88-12f4-4c91-9c2b-372aab3bbae9",  # primary
  "<sub-id-2>",
  "<sub-id-3>",
]
```

---

## Step 9 — Entra App Registration Redirect URIs

After deploying the web-ui, verify the Entra app registration has the correct redirect URI.

### Check existing URIs

```bash
az ad app show \
  --id "505df1d3-..." \
  --query "spa.redirectUris"
```

### Add/update if needed

```bash
az ad app update \
  --id "505df1d3-..." \
  --set spa.redirectUris="[\"https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/callback\",\"http://localhost:3000/callback\"]"
```

---

## Step 10 — Security: Rotate Exposed Secrets

> ⚠️ **The following secrets are currently committed in plaintext to `credentials.tfvars`**. They should be rotated and moved to a secrets manager (Azure Key Vault or GitHub Secrets).

| Secret | Location | Action |
|---|---|---|
| `client_secret = "HDM8Q~..."` | `credentials.tfvars` | Rotate in Azure AD → App registrations → Certificates & secrets |
| `postgres_admin_password = "Jas190277on!"` | `credentials.tfvars` | Rotate via `az postgres flexible-server update --admin-password <new>` |

After rotating:
1. Update `credentials.tfvars` with new values
2. Update GitHub Actions secrets
3. Run `terraform apply` to push new values to Container Apps
4. Consider adding `credentials.tfvars` to `.gitignore` and using `terraform.tfvars.example` instead

---

## Summary Checklist

```
IMMEDIATE (platform will not work without these):
✅ Step 1 — Set AZURE_PROJECT_ENDPOINT + ORCHESTRATOR_AGENT_ID on api-gateway
           ORCHESTRATOR_AGENT_ID=asst_NeBVjCA5isNrIERoGYzRpBTu (set 2026-03-31, revision 0000030)
           Also wired in terraform/envs/prod/terraform.tfvars
✅ Step 2 — Grant Azure AI Developer role to api-gateway managed identity
           Role assignment ID: 6a001d6b-bc29-4355-962f-0103c81f90c6 (created 2026-03-31)
           Also wired in terraform/modules/rbac/main.tf (api-gateway-aidev-foundry)
□ Step 3 — Set LOG_ANALYTICS_WORKSPACE_ID on web-ui container app
□ Step 4 — Verify Cosmos DB 'incidents' container + RBAC

BEFORE TEAMS GO-LIVE:
□ Step 5 — Register Azure Bot, get BOT_ID + BOT_PASSWORD, set Teams channel
□ Step 5e — Re-run terraform apply with teams_bot_id + teams_bot_password

GITHUB ACTIONS (CI/CD will fail without these):
□ Step 6 — Add all repository secrets
□ Step 6 — Add all repository variables
□ Step 6 — Trigger no-cache web-ui rebuild

PRODUCTION READINESS:
□ Step 7 — Seed runbooks in production
□ Step 8 — Grant Reader on additional subscriptions (if multi-sub)
□ Step 9 — Verify Entra redirect URIs
□ Step 10 — Rotate client_secret and postgres_admin_password out of git
```
