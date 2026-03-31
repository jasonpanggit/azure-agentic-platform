# Debug: Teams Bot Registration & Credential Wiring

**Date:** 2026-03-31
**Status:** RESOLVED (BOT_ID + BOT_PASSWORD fixed; TEAMS_CHANNEL_ID still pending)

## Problem

Teams Bot container app `ca-teams-bot-prod` was running but non-functional:
- `BOT_ID` env var was empty string
- `BOT_PASSWORD` secret was `placeholder-not-configured`
- `TEAMS_CHANNEL_ID` env var was empty string
- `BOT_TENANT_ID` env var was missing entirely (not in Terraform config)

The bot code (`services/teams-bot/src/config.ts`) throws on startup if `BOT_ID` is empty, so the bot was crash-looping or running the placeholder image.

## Root Cause

The Azure Bot resource `aap-teams-bot-prod` was created manually with:
- App Registration: `d5b074fc-7ca6-4354-8938-046e034d80da`
- Type: SingleTenant
- Endpoint: `https://ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/messages`
- Teams channel: configured

But the Terraform variables (`teams_bot_id`, `teams_bot_password`, `teams_channel_id`) in `credentials.tfvars` were never populated, so the container app was deployed with empty/placeholder values.

Additionally, `BOT_TENANT_ID` (required for SingleTenant auth in `botbuilder` SDK) was not wired in Terraform at all -- only mentioned in a warning comment.

## Fix Applied

### 1. Client Secret Created
```
az ad app credential reset --id d5b074fc-7ca6-4354-8938-046e034d80da \
  --append --display-name "teams-bot-prod-2026-cli" --years 2
```
- KeyId: (new, appended alongside existing `80aa7952-...`)
- Expires: ~2028-03-31

### 2. Container App Updated (immediate fix)
```
az containerapp secret set --name ca-teams-bot-prod --resource-group rg-aap-prod \
  --secrets "teams-bot-password=<real-secret>"

az containerapp update --name ca-teams-bot-prod --resource-group rg-aap-prod \
  --set-env-vars "BOT_ID=d5b074fc-7ca6-4354-8938-046e034d80da" \
                 "BOT_TENANT_ID=abbdca26-d233-4a1e-9d8c-c4eebbc16e50"

az containerapp revision restart ... (pick up secret change)
```

### 3. Terraform Updated (persistence)

**credentials.tfvars** -- added:
```hcl
teams_bot_id       = "d5b074fc-7ca6-4354-8938-046e034d80da"
teams_bot_password = "<secret>"
teams_channel_id   = ""  # Pending manual retrieval
```

**New Terraform variable added:** `teams_bot_tenant_id`
- Added to: `modules/agent-apps/variables.tf`, `envs/prod/variables.tf`, `envs/prod/main.tf`
- Added `BOT_TENANT_ID` env block to `modules/agent-apps/main.tf`
- Falls back to `var.tenant_id` if not explicitly set

### 4. Verification
- Container app revision `ca-teams-bot-prod--0000012`: **Running**, **Healthy**
- Logs confirm: `Teams bot listening on port 3978` (no BOT_ID error)
- `terraform validate`: **Success**
- Bot Service endpoint matches Container App FQDN

## Remaining: TEAMS_CHANNEL_ID

`TEAMS_CHANNEL_ID` is needed for **proactive messaging** (bot sending unsolicited messages to a channel). It is NOT required for:
- Receiving messages from users
- Responding to messages
- Bot Framework authentication

### How to Get TEAMS_CHANNEL_ID

**Option A: Teams Client (easiest)**
1. Open Microsoft Teams
2. Right-click the target channel -> "Get link to channel"
3. The URL contains the channel ID, e.g.: `19:abc123...@thread.tacv2`
4. URL-decode it if needed

**Option B: MS Graph API**
```bash
# List teams the bot/user belongs to
az rest --method GET --url "https://graph.microsoft.com/v1.0/me/joinedTeams" --query "value[].{name:displayName,id:id}"

# List channels in a team
az rest --method GET --url "https://graph.microsoft.com/v1.0/teams/{team-id}/channels" --query "value[].{name:displayName,id:id}"
```

Once obtained, update:
1. Container app: `az containerapp update --name ca-teams-bot-prod --resource-group rg-aap-prod --set-env-vars "TEAMS_CHANNEL_ID=<channel-id>"`
2. credentials.tfvars: `teams_channel_id = "<channel-id>"`

## Bot Service Configuration (verified)
| Property | Value |
|---|---|
| Bot name | `aap-teams-bot-prod` |
| App ID | `d5b074fc-7ca6-4354-8938-046e034d80da` |
| App type | SingleTenant |
| Tenant ID | `abbdca26-d233-4a1e-9d8c-c4eebbc16e50` |
| Endpoint | `https://ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/messages` |
| Teams channel | Configured |

## Files Modified
- `terraform/envs/prod/credentials.tfvars` -- added teams_bot_id, teams_bot_password, teams_channel_id
- `terraform/modules/agent-apps/main.tf` -- added BOT_TENANT_ID env block, updated comments
- `terraform/modules/agent-apps/variables.tf` -- added teams_bot_tenant_id variable
- `terraform/envs/prod/variables.tf` -- added teams_bot_tenant_id variable
- `terraform/envs/prod/main.tf` -- wired teams_bot_tenant_id to module
