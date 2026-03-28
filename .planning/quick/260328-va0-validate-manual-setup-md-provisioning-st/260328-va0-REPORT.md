# Validation Report: MANUAL-SETUP.md Provisioning State

**Date:** 2026-03-28
**Environment:** prod (`rg-aap-prod`)
**Subscription:** `4c727b88-12f4-4c91-9c2b-372aab3bbae9`
**Method:** Read-only Azure CLI queries (no mutations)

---

## Summary Table

| Step | Description | Status | Blocking? |
|------|-------------|--------|-----------|
| 1 | API Gateway env vars | **PARTIAL** | YES |
| 2 | Foundry RBAC (Azure AI Developer) | **PENDING** | YES |
| 3 | Log Analytics on Web UI | **DONE** | - |
| 4 | Cosmos DB `incidents` container + RBAC | **DONE** | - |
| 5 | Teams Bot Registration | **PARTIAL** | Pre-Teams |
| 6 | GitHub Actions Secrets & Variables | **PARTIAL** | CI/CD |
| 7 | Runbook Seeding (Production) | **CANNOT_VERIFY** | Prod readiness |
| 8 | Multi-Subscription Reader | **SKIPPED** | Optional |
| 9 | Entra Redirect URIs | **DONE** | - |
| 10 | Secret Rotation | **PARTIAL** | Prod readiness |

**Overall: 3 DONE, 3 PARTIAL, 1 PENDING, 1 SKIPPED, 1 CANNOT_VERIFY, 1 PARTIAL (security)**

---

## Detailed Findings

### Step 1 — API Gateway: Set Missing Environment Variables

**Status: PARTIAL**

**Command:**
```bash
az containerapp show --name ca-api-gateway-prod --resource-group rg-aap-prod \
  --query "properties.template.containers[0].env" -o json
```

**Evidence — Current env vars on `ca-api-gateway-prod`:**
```json
[
  {"name": "FOUNDRY_ACCOUNT_ENDPOINT", "value": "https://aap-foundry-prod.cognitiveservices.azure.com/"},
  {"name": "FOUNDRY_PROJECT_ID", "value": "/subscriptions/.../aap-foundry-prod/projects/aap-project-prod"},
  {"name": "FOUNDRY_MODEL_DEPLOYMENT", "value": "gpt-4o"},
  {"name": "APPLICATIONINSIGHTS_CONNECTION_STRING", "secretRef": "appinsights-connection-string"},
  {"name": "COSMOS_ENDPOINT", "value": "https://aap-cosmos-prod.documents.azure.com:443/"},
  {"name": "COSMOS_DATABASE_NAME", "value": "aap"},
  {"name": "AGENT_NAME", "value": "api-gateway"},
  {"name": "ENVIRONMENT", "value": "prod"},
  {"name": "CORS_ALLOWED_ORIGINS", "value": "*"},
  {"name": "DEPLOY_TIMESTAMP", "value": "20260328051538"}
]
```

**Analysis:**

| Required Env Var (per MANUAL-SETUP.md) | Present? | Notes |
|---|---|---|
| `AZURE_PROJECT_ENDPOINT` | NO | `FOUNDRY_ACCOUNT_ENDPOINT` exists with the same value — may be a naming mismatch between the guide and actual code |
| `ORCHESTRATOR_AGENT_ID` | NO | Agent may not be created in Foundry yet |
| `AZURE_CLIENT_ID` | NO | Needed for managed identity auth; gateway uses SystemAssigned identity |
| `AZURE_TENANT_ID` | NO | |
| `CORS_ALLOWED_ORIGINS` | PARTIAL | Set to `*` (wildcard) instead of specific origin `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` |

**Observations:**
- Terraform has injected its own set of env vars (`FOUNDRY_ACCOUNT_ENDPOINT`, `FOUNDRY_PROJECT_ID`, `FOUNDRY_MODEL_DEPLOYMENT`) which may serve the same purpose as `AZURE_PROJECT_ENDPOINT`. The MANUAL-SETUP.md guide may need updating to reflect the actual variable names used by the api-gateway code.
- `ORCHESTRATOR_AGENT_ID` is genuinely missing — this requires creating the orchestrator agent in Azure AI Foundry.
- `CORS_ALLOWED_ORIGINS=*` is a security concern for production. Should be locked to the web-ui domain.

---

### Step 2 — Foundry: Grant Managed Identity Access to the Project

**Status: PENDING**

**Commands:**
```bash
# Gateway principal ID
az containerapp show --name ca-api-gateway-prod --resource-group rg-aap-prod \
  --query "identity.principalId" -o tsv
# Result: 69e05934-1feb-44d4-8fd2-30373f83ccec

# Check for Azure AI Developer role
az role assignment list --assignee "69e05934-1feb-44d4-8fd2-30373f83ccec" \
  --query "[?roleDefinitionName=='Azure AI Developer']" -o json
# Result: []
```

**Evidence — All roles on gateway principal:**
```json
[
  {"role": "Cosmos DB Operator", "scope": "/subscriptions/4c727b88-..."},
  {"role": "Cognitive Services User", "scope": "/subscriptions/4c727b88-..."},
  {"role": "AcrPull", "scope": ".../Microsoft.ContainerRegistry/registries/aapcrprodjgmjti"}
]
```

**Analysis:**
- Gateway has `Cognitive Services User` (allows inference calls) but **NOT** `Azure AI Developer` (required for Foundry agent management).
- `Cognitive Services User` may be sufficient for calling an existing agent, but `Azure AI Developer` is the recommended role per the MANUAL-SETUP.md guide for full Foundry project access.
- **Action required:** Assign `Azure AI Developer` to principal `69e05934-1feb-44d4-8fd2-30373f83ccec` on the Foundry account scope.

---

### Step 3 — Log Analytics: Wire Workspace ID to Web UI

**Status: DONE**

**Command:**
```bash
az containerapp show --name ca-web-ui-prod --resource-group rg-aap-prod \
  --query "properties.template.containers[0].env" -o json
```

**Evidence:**
```json
{"name": "LOG_ANALYTICS_WORKSPACE_ID", "value": "52c2da23-a227-47ee-bec7-a0bc14135c45"}
```

**Analysis:**
- `LOG_ANALYTICS_WORKSPACE_ID` is set with a valid GUID (Customer ID format).
- Web UI also has `API_GATEWAY_URL` properly configured.
- No action needed.

---

### Step 4 — Cosmos DB: Verify the `incidents` Container + RBAC

**Status: DONE**

**Commands:**
```bash
# Cosmos account
az cosmosdb list --resource-group rg-aap-prod --query "[0].name" -o tsv
# Result: aap-cosmos-prod

# Container check
az cosmosdb sql container show --account-name aap-cosmos-prod --database-name aap \
  --name incidents --resource-group rg-aap-prod
# Result: EXISTS

# All containers
az cosmosdb sql container list --account-name aap-cosmos-prod --database-name aap \
  --resource-group rg-aap-prod --query "[].name"
# Result: ["incidents", "sessions", "approvals"]

# SQL role assignments
az cosmosdb sql role assignment list --account-name aap-cosmos-prod \
  --resource-group rg-aap-prod
# Result: 10 role assignments
```

**Evidence:**

| Check | Result |
|---|---|
| `incidents` container exists | YES |
| Partition key | `/resource_id` (note: MANUAL-SETUP.md says `/incident_id` — discrepancy, but Terraform created it correctly per the actual code) |
| Indexing policy | Composite index on `resource_id`, `detection_rule`, `created_at`, `status` |
| Gateway principal in Cosmos RBAC | YES — `69e05934-1feb-44d4-8fd2-30373f83ccec` has `Data Contributor` (role def `...00000002`) |
| Orchestrator principal in Cosmos RBAC | YES — `f4d7eea6-a1c9-4681-b2a2-08e32f9fe0da` has `Data Contributor` |
| Total Cosmos SQL role assignments | 10 (covers all container app identities) |

**Observations:**
- MANUAL-SETUP.md Step 4b specifies `--partition-key-path "/incident_id"` but the actual container uses `/resource_id`. The guide should be corrected to match the actual Terraform/code implementation.
- Additional containers `sessions` and `approvals` also exist — provisioned by Terraform.
- No action needed; fully provisioned.

---

### Step 5 — Teams Bot Registration

**Status: PARTIAL**

**Commands:**
```bash
# Azure Bot resource
az bot show --name aap-teams-bot-prod --resource-group rg-aap-prod
# Result: ERROR ResourceNotFound

# Teams Bot Container App
az containerapp show --name ca-teams-bot-prod --resource-group rg-aap-prod --query "name" -o tsv
# Result: ca-teams-bot-prod
```

**Evidence:**

| Check | Result |
|---|---|
| Azure Bot resource (`aap-teams-bot-prod`) | NOT FOUND |
| Container App (`ca-teams-bot-prod`) | EXISTS |

**Analysis:**
- The teams-bot Container App has been deployed via Terraform, but the **Azure Bot Service registration** (Steps 5a-5c) has not been completed.
- Without the Azure Bot resource, the Teams channel integration cannot function.
- Steps 5d (channel ID), 5e (credentials.tfvars), and 5f (messaging endpoint) are also pending.
- This is expected if Teams integration is not yet needed.

---

### Step 6 — GitHub Actions: Secrets and Variables

**Status: PARTIAL**

**Command:**
```bash
gh secret list && gh variable list
```

**Evidence — Secrets:**
| Required Secret | Present? | Set Date |
|---|---|---|
| `AZURE_CLIENT_ID` | YES | 2026-03-27 |
| `AZURE_CLIENT_SECRET` | YES | 2026-03-27 |
| `AZURE_TENANT_ID` | YES | 2026-03-27 |
| `AZURE_SUBSCRIPTION_ID` | YES | 2026-03-27 |
| `ACR_LOGIN_SERVER` | YES | 2026-03-27 |
| `ACR_NAME` | YES (bonus) | 2026-03-27 |
| `POSTGRES_ADMIN_PASSWORD` | **NO** | - |
| `AZURE_OPENAI_ENDPOINT` | **NO** | - |
| `AZURE_OPENAI_API_KEY` | **NO** | - |

**Evidence — Variables:**
| Required Variable | Present? | Value |
|---|---|---|
| `NEXT_PUBLIC_AZURE_CLIENT_ID` | YES | `505df1d3-3bd3-4151-ae87-6e5974b72a44` |
| `NEXT_PUBLIC_TENANT_ID` | YES | `abbdca26-d233-4a1e-9d8c-c4eebbc16e50` |
| `NEXT_PUBLIC_REDIRECT_URI` | YES | `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/callback` |
| `ACR_LOGIN_SERVER` | YES | `aapcrprodjgmjti.azurecr.io` |

**Analysis:**
- Core Azure auth secrets (4/4) are present.
- ACR secrets are present (including bonus `ACR_NAME`).
- **Missing:** `POSTGRES_ADMIN_PASSWORD`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` — these are needed for the staging CI seed/validate job and any workflow that needs PG or OpenAI access.
- All 4 required variables are present and correctly configured.
- ACR login server in variable matches actual ACR: `aapcrprodjgmjti.azurecr.io` (verified via `az acr list`).

---

### Step 7 — Runbook Seeding (Production)

**Status: CANNOT_VERIFY**

**Evidence:**
```bash
# Seed script exists locally
ls scripts/seed-runbooks/seed.py  # EXISTS

# PostgreSQL server exists
az postgres flexible-server list --resource-group rg-aap-prod \
  --query "[0].fullyQualifiedDomainName" -o tsv
# Result: aap-postgres-prod.postgres.database.azure.com
```

**Analysis:**
- The seed script exists at `scripts/seed-runbooks/seed.py`.
- PostgreSQL Flexible Server is provisioned at `aap-postgres-prod.postgres.database.azure.com`.
- **Cannot verify** whether the seed script has been run against production — would require a database query through the VNet (not possible from local/CI without a firewall rule).
- Per project decision (Key Decision: "Prod seed is manual operational step"), this must be run manually.

---

### Step 8 — Multi-Subscription Reader Roles

**Status: SKIPPED (Optional)**

**Command:**
```bash
az role assignment list --assignee "65cf695c-1def-48ba-96af-d968218c90ba" \
  --all --query "[?roleDefinitionName=='Reader']" -o json
# Result: []
```

**Analysis:**
- No `Reader` role assignments found on additional subscriptions for the platform service principal.
- This is expected — the platform currently operates within a single subscription.
- Step 8 is explicitly marked as optional in MANUAL-SETUP.md ("If you want the platform to monitor additional Azure subscriptions").

---

### Step 9 — Entra App Registration Redirect URIs

**Status: DONE**

**Command:**
```bash
az ad app show --id "505df1d3-3bd3-4151-ae87-6e5974b72a44" --query "spa.redirectUris" -o json
```

**Evidence:**
```json
[
  "http://localhost:3000/callback",
  "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/callback"
]
```

**Analysis:**
- Both required redirect URIs are configured:
  - Production: `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/callback`
  - Local dev: `http://localhost:3000/callback`
- Matches exactly what MANUAL-SETUP.md Step 9 specifies.
- No action needed.

---

### Step 10 — Security: Rotate Exposed Secrets

**Status: PARTIAL**

**Evidence:**
```bash
grep -q "credentials.tfvars" .gitignore
# Result: FOUND in .gitignore
```

**Analysis:**

| Check | Result |
|---|---|
| `credentials.tfvars` in `.gitignore` | YES |
| Client secret rotated | CANNOT_VERIFY (requires checking rotation date in Entra) |
| Postgres password rotated | CANNOT_VERIFY |

- The `.gitignore` entry is present, which prevents future commits of the credentials file.
- However, if `credentials.tfvars` was committed historically, the secrets are still in git history.
- Secret rotation status cannot be verified via read-only CLI — requires checking secret expiry dates and whether new credentials have been issued.
- **Recommendation:** Verify git history for any prior commits of `credentials.tfvars` and rotate both secrets as a precaution.

---

## MANUAL-SETUP.md Discrepancies Found

| Location | Issue | Recommendation |
|---|---|---|
| Step 1c | Guide says `AZURE_PROJECT_ENDPOINT` but Terraform injects `FOUNDRY_ACCOUNT_ENDPOINT` | Verify which var name the api-gateway code reads; update guide if it reads `FOUNDRY_ACCOUNT_ENDPOINT` |
| Step 4b | Guide says `--partition-key-path "/incident_id"` but actual container uses `/resource_id` | Update guide to match actual Terraform definition |
| Step 1c | Guide says `CORS_ALLOWED_ORIGINS=<specific URL>` | Currently `*` — should be updated to specific origin for prod security |

---

## Checklist Update Recommendations

If MANUAL-SETUP.md checkboxes were updatable, these would be ticked:

```
IMMEDIATE:
[x] Step 3 — LOG_ANALYTICS_WORKSPACE_ID is set on web-ui
[x] Step 4 — Cosmos DB 'incidents' container exists + RBAC assigned
[ ] Step 1 — PARTIAL: env vars partially set, ORCHESTRATOR_AGENT_ID missing
[ ] Step 2 — PENDING: Azure AI Developer role not assigned

BEFORE TEAMS GO-LIVE:
[ ] Step 5 — PARTIAL: Container App exists but Azure Bot not registered

GITHUB ACTIONS:
[~] Step 6 — PARTIAL: 6/9 secrets present, 4/4 variables present

PRODUCTION READINESS:
[?] Step 7 — Cannot verify prod seed status
[x] Step 8 — SKIPPED (optional, single-subscription)
[x] Step 9 — Entra redirect URIs correctly configured
[~] Step 10 — .gitignore present but secret rotation unverified
```
