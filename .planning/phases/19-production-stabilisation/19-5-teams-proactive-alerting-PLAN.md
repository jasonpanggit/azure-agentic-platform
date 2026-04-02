---
phase: 19
plan: 5
title: "Teams Proactive Alerting"
objective: "Enable Teams proactive alert delivery by reconciling the bot Terraform state, installing the bot in a Teams channel, setting TEAMS_CHANNEL_ID on the Container App, and running an end-to-end test that confirms an Adaptive Card arrives in the channel within 2 minutes of incident creation."
wave: 3
estimated_tasks: 9
gap_closure: false
---

# Plan 19-5: Teams Proactive Alerting

## Objective

Resolve **PROD-005 / F-04 / GAP-004**: Teams proactive alerting is silently non-functional in production. The bot code is complete (100 tests at 92.34% coverage), but `TEAMS_CHANNEL_ID` is empty on `ca-teams-bot-prod`, so all proactive posts are skipped. This plan reconciles the Terraform bot state, installs the bot in a Teams channel, captures the channel ID, sets it on the Container App, and verifies end-to-end that alert Adaptive Cards arrive in the channel within the 2-minute SLA defined by PROD-005.

## Context

**Current state (verified from research):**

- `terraform/modules/teams-bot/main.tf` exists and creates the Azure Bot Service, Teams channel, Entra app, service principal, and Key Vault secrets
- `enable_teams_bot = true` in `terraform/envs/prod/terraform.tfvars`
- Bot resource likely exists as `aap-teams-bot-prod` (manually created — may need Terraform import reconciliation)
- Entra app registration exists: object `670e3ba4-...`, client `d5b074fc-...`
- `ca-teams-bot-prod` Container App is deployed and running on port 3978
- **`TEAMS_CHANNEL_ID` is empty** on `ca-teams-bot-prod` — all proactive posts skipped silently

**How proactive messaging works (from `services/teams-bot/src/services/proactive.ts`):**
1. `initializeProactive(adapter, appId)` — called at startup
2. `setConversationReference(ref)` — called when bot is installed in a team/channel (`onInstallationUpdate` event)
3. `sendProactiveCard(card)` — uses `adapter.continueConversationAsync()` with saved `ConversationReference`
4. `hasConversationReference()` — returns `false` until bot is installed; proactive notify route returns 503 pre-flight when false

**Critical insight:** The bot must be installed in a Teams channel **first** to capture the `ConversationReference`. The `TEAMS_CHANNEL_ID` alone is not enough — the bot needs the full `ConversationReference` object saved in memory (or Cosmos DB in future). The 30-second startup delay in the escalation scheduler accounts for this.

**PROD requirement:** PROD-005 — Teams proactive alerting delivers Adaptive Cards within 2 minutes of incident creation.

---

## Tasks

### Task 1: Verify Terraform import blocks for existing bot resources

The Azure Bot Service and related resources were manually created. Check if import blocks exist in `terraform/envs/prod/imports.tf`:

```bash
grep -n "BotService\|teams-bot\|botService" terraform/envs/prod/imports.tf 2>/dev/null \
  || echo "No bot import blocks found in imports.tf"
```

If import blocks are missing, add them. The bot resource IDs:

```hcl
# terraform/envs/prod/imports.tf (append)

# Azure Bot Service (manually created before Terraform ownership)
import {
  to = module.teams_bot.azurerm_bot_service_azure_bot.main
  id = "/subscriptions/4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c/resourceGroups/rg-aap-prod/providers/Microsoft.BotService/botServices/aap-teams-bot-prod"
}
```

Retrieve the exact Resource IDs for all manually-created bot resources:
```bash
# Bot Service
az bot show --name aap-teams-bot-prod --resource-group rg-aap-prod --query id -o tsv

# Teams channel
az bot msteams show --name aap-teams-bot-prod --resource-group rg-aap-prod --query id -o tsv || \
  echo "Teams channel not yet registered via CLI — check Portal"

# Entra app
az ad app show --id d5b074fc-0000-0000-0000-000000000000 --query id -o tsv 2>/dev/null || \
  echo "Update Entra app ID from Portal"
```

### Task 2: Run `terraform plan` to reconcile bot module state

```bash
cd terraform/envs/prod

# Initialize to ensure providers are up to date
terraform init -upgrade

# Plan with import blocks in place
terraform plan -out=plan-19-5-bot.tfplan

# Review carefully:
# - Bot resources should show as "import" (not destroy+create)
# - Container App env vars (BOT_ID, BOT_PASSWORD, API_GATEWAY_INTERNAL_URL, WEB_UI_PUBLIC_URL) should be confirmed
# - TEAMS_CHANNEL_ID should show as empty string (we'll set it after bot installation)
```

If the plan shows resource replacements (not imports) for existing resources, **stop and investigate** before applying. Destroying the bot service would deregister the bot from Teams and require re-installation.

Apply only after confirming import semantics:
```bash
terraform apply plan-19-5-bot.tfplan
```

### Task 3: Verify all required env vars on `ca-teams-bot-prod`

After Terraform apply, confirm required env vars are set:

```bash
az containerapp show \
  --name ca-teams-bot-prod \
  --resource-group rg-aap-prod \
  --query "properties.template.containers[0].env[?name=='BOT_ID' || name=='API_GATEWAY_INTERNAL_URL' || name=='WEB_UI_PUBLIC_URL' || name=='TEAMS_CHANNEL_ID'].{name: name, value: value}" \
  -o table
```

Expected values:
| Variable | Expected value |
|---|---|
| `BOT_ID` | `d5b074fc-...` (Entra app client ID) |
| `API_GATEWAY_INTERNAL_URL` | Internal URL of `ca-api-gateway-prod` |
| `WEB_UI_PUBLIC_URL` | `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` |
| `TEAMS_CHANNEL_ID` | _(empty — to be set in Task 6)_ |

If `API_GATEWAY_INTERNAL_URL` is not set, set it:
```bash
# Get the internal FQDN of the API gateway
API_GW_FQDN=$(az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --query "properties.configuration.ingress.fqdn" -o tsv)

az containerapp update \
  --name ca-teams-bot-prod \
  --resource-group rg-aap-prod \
  --set-env-vars "API_GATEWAY_INTERNAL_URL=http://${API_GW_FQDN}"
```

### Task 4: Verify the messaging endpoint URL in the Bot Service

The Azure Bot Service must point to the Container App's messaging endpoint. Verify:

```bash
az bot show \
  --name aap-teams-bot-prod \
  --resource-group rg-aap-prod \
  --query "properties.endpoint" -o tsv
```

Expected: `https://ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/messages`

If it points elsewhere (e.g., localhost or an old URL), update via Portal:
- Azure Portal → Bot Services → `aap-teams-bot-prod` → Configuration → Messaging endpoint → Update URL

### Task 5: Upload Teams app manifest and install the bot in a channel

The Teams app manifest is at `services/teams-bot/manifest/`. Create a `.zip` package and upload to Teams:

```bash
cd services/teams-bot/manifest/

# Update manifest.json with actual bot App ID if placeholders remain
grep -n "BOT_APP_ID\|{{" manifest.json && echo "Placeholders found — update before packaging"

# Replace placeholders if needed
sed -i '' "s/{{BOT_APP_ID}}/d5b074fc-0000-0000-0000-000000000000/g" manifest.json
sed -i '' "s/{{TEAMS_APP_ID}}/$(uuidgen | tr '[:upper:]' '[:lower:]')/g" manifest.json

# Create the zip package
zip -j aap-teams-bot.zip manifest.json outline-icon.png color-icon.png

echo "Manifest package created: services/teams-bot/manifest/aap-teams-bot.zip"
```

**Install in Teams (manual step — requires Teams admin or app upload permission):**

1. Open Microsoft Teams
2. Navigate to Apps → Manage your apps → Upload an app → Upload a custom app
3. Select `services/teams-bot/manifest/aap-teams-bot.zip`
4. Add to the target team/channel (e.g., `#azure-ops-alerts`)
5. Confirm the bot posts a greeting message in the channel

**After installation:** The bot fires an `onInstallationUpdate` event, which calls `setConversationReference(ref)`. The `ConversationReference` is stored in memory. The `hasConversationReference()` function will now return `true`.

Verify the bot installed successfully by checking Container App logs:
```bash
az containerapp logs show \
  --name ca-teams-bot-prod \
  --resource-group rg-aap-prod \
  --tail 50 | grep -i "installation\|conversation\|channel"
```

### Task 6: Capture the Teams channel ID and set it on the Container App

The channel ID can be found in two ways:

**Method A: From Teams admin center**
1. Teams admin center → Teams → select your team → Channels → right-click channel → Get link
2. Extract the `groupId` and `channelId` parameters from the URL

**Method B: From bot installation event logs**
```bash
az containerapp logs show \
  --name ca-teams-bot-prod \
  --resource-group rg-aap-prod \
  --tail 100 | grep -i "channelId\|channel_id\|conversationReference"
```

**Method C: From Graph API**
```bash
# Get your Teams team ID first
az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/me/joinedTeams" \
  --query "value[?displayName=='<your-team-name>'].id" -o tsv

# Then get channels
az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/teams/<team-id>/channels" \
  --query "value[?displayName=='azure-ops-alerts'].id" -o tsv
```

Once you have the channel ID, set it:
```bash
TEAMS_CHANNEL_ID="<channel-id>"

az containerapp update \
  --name ca-teams-bot-prod \
  --resource-group rg-aap-prod \
  --set-env-vars "TEAMS_CHANNEL_ID=${TEAMS_CHANNEL_ID}"

# Restart to apply env var change
az containerapp revision restart \
  --name ca-teams-bot-prod \
  --resource-group rg-aap-prod \
  --revision $(az containerapp revision list \
    --name ca-teams-bot-prod \
    --resource-group rg-aap-prod \
    --query "[0].name" -o tsv)
```

> **Important:** After restart, the bot will need to be re-triggered to re-capture the `ConversationReference`. Send a message to the bot in Teams to trigger `onMessage`, which re-stores the reference. The proactive route checks `hasConversationReference()` before sending.

### Task 7: Create end-to-end test script for Teams alert delivery

Create `scripts/ops/19-5-test-teams-alerting.sh`:

```bash
#!/usr/bin/env bash
# Phase 19 Plan 5: Teams Proactive Alerting E2E Test
#
# Prerequisites:
#   - Bot installed in Teams channel (Task 5 complete)
#   - TEAMS_CHANNEL_ID set on ca-teams-bot-prod (Task 6 complete)
#   - Auth token available (requires E2E_CLIENT_ID/SECRET from Plan 2)

set -euo pipefail

API_URL="https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
INCIDENT_ID="test-teams-alert-$(date +%s)"

# Get auth token
TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/abbdca26-d233-4a1e-9d8c-c4eebbc16e50/oauth2/v2.0/token" \
  -d "grant_type=client_credentials&client_id=${E2E_CLIENT_ID}&client_secret=${E2E_CLIENT_SECRET}&scope=api://505df1d3-3bd3-4151-ae87-6e5974b72a44/.default" \
  | jq -r '.access_token')

echo "=== Phase 19 Teams Alerting E2E Test ==="
echo "Incident ID: $INCIDENT_ID"
echo "Posting synthetic incident to trigger Teams alert..."

# Inject synthetic incident
RESPONSE=$(curl -s -X POST "${API_URL}/api/v1/incidents" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"incident_id\": \"${INCIDENT_ID}\",
    \"severity\": \"Sev1\",
    \"domain\": \"compute\",
    \"affected_resources\": [\"/subscriptions/4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-prod-01\"],
    \"detection_rule\": \"CPU_CRITICAL_TEAMS_TEST\",
    \"kql_evidence\": \"avg_cpu_percent = 99 for 20 minutes (TEAMS TEST)\"
  }")

echo "Response: $RESPONSE"
echo ""
echo "Incident posted. Check Teams channel within 2 minutes for Adaptive Card."
echo ""
echo "Expected card fields:"
echo "  - Resource: vm-prod-01"
echo "  - Severity: Sev1"
echo "  - Subscription: 4c727b88-..."
echo "  - 'Investigate' button linking to web UI"
echo ""

# Check bot notify endpoint status
echo "Checking bot proactive notify readiness..."
BOT_NOTIFY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "https://ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/notify/test" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"type":"ping"}' 2>/dev/null || echo "000")

if [[ "$BOT_NOTIFY_STATUS" == "503" ]]; then
  echo "WARNING: Bot notify returns 503 — ConversationReference not yet captured."
  echo "Send a message to the bot in Teams to re-capture the reference, then re-run this test."
elif [[ "$BOT_NOTIFY_STATUS" == "200" || "$BOT_NOTIFY_STATUS" == "202" ]]; then
  echo "Bot notify endpoint ready (HTTP $BOT_NOTIFY_STATUS)"
else
  echo "Bot notify endpoint returned HTTP $BOT_NOTIFY_STATUS"
fi

echo ""
echo "Check Container App logs for proactive send confirmation:"
echo "  az containerapp logs show --name ca-teams-bot-prod --resource-group rg-aap-prod --tail 30"
```

### Task 8: Run the end-to-end test and verify delivery

Execute the test script and verify:

```bash
export E2E_CLIENT_ID="<from GitHub secrets>"
export E2E_CLIENT_SECRET="<from GitHub secrets>"

bash scripts/ops/19-5-test-teams-alerting.sh
```

**Verify in Teams:** Within 120 seconds of the incident post, an Adaptive Card should appear in the `#azure-ops-alerts` channel with:
- Resource name: `vm-prod-01`
- Severity: `Sev1`
- Subscription context
- "Investigate" button

**Verify in Container App logs:**
```bash
az containerapp logs show \
  --name ca-teams-bot-prod \
  --resource-group rg-aap-prod \
  --tail 30 \
  | grep -i "proactive\|card\|alert\|channel"
```

**Check Application Insights:**
```kql
traces
| where cloud_RoleName == "ca-teams-bot-prod"
| where message contains "proactive" or message contains "card" or message contains "sent"
| where timestamp > ago(5m)
| project timestamp, message, severityLevel
| order by timestamp desc
| take 20
```

### Task 9: Wire `TEAMS_CHANNEL_ID` into Terraform

Ensure the channel ID is persisted in Terraform so it survives Container App revision changes:

In `terraform/modules/teams-bot/variables.tf`, verify or add:
```hcl
variable "teams_channel_id" {
  description = "Teams channel ID for proactive alert delivery"
  type        = string
  default     = ""
}
```

In `terraform/modules/teams-bot/main.tf`, add the env var to the Container App definition:
```hcl
env {
  name  = "TEAMS_CHANNEL_ID"
  value = var.teams_channel_id
}
```

In `terraform/envs/prod/terraform.tfvars`:
```hcl
teams_channel_id = "<channel-id-captured-in-task-6>"
```

Run `terraform apply` to persist the change:
```bash
cd terraform/envs/prod
terraform plan -target=module.teams_bot -out=plan-19-5-channel.tfplan
terraform apply plan-19-5-channel.tfplan
```

---

## Success Criteria

1. Within 120 seconds of `POST /api/v1/incidents` with a synthetic Sev1 incident, an Adaptive Card appears in the configured Teams channel — confirmed by manual visual inspection
2. The Adaptive Card contains: resource name, severity (`Sev1`), subscription context, timestamp, and a functional "Investigate" button
3. Container App logs show: `"proactive card sent successfully"` (or equivalent log message from `proactive.ts`)
4. `az containerapp show --name ca-teams-bot-prod --query "properties.template.containers[0].env[?name=='TEAMS_CHANNEL_ID'].value"` returns the non-empty channel ID
5. `hasConversationReference()` returns `true` after bot installation — confirmed by bot notify endpoint returning `200`/`202` (not `503`)
6. `terraform plan` on `terraform/envs/prod/` shows zero diff after `terraform apply` (TEAMS_CHANNEL_ID persisted in Terraform state)

---

## Files Touched

### Created
- `scripts/ops/19-5-test-teams-alerting.sh` — end-to-end Teams alert delivery test

### Modified
- `terraform/modules/teams-bot/variables.tf` — add `teams_channel_id` variable (if missing)
- `terraform/modules/teams-bot/main.tf` — add `TEAMS_CHANNEL_ID` env var to Container App (if missing)
- `terraform/envs/prod/terraform.tfvars` — add `teams_channel_id` value
- `terraform/envs/prod/imports.tf` — add bot resource import blocks (if not already present)
