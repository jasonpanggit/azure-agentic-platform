# Debug: chat-send-failure-prod

**Date**: 2026-03-28
**Status**: ROOT CAUSE FOUND + CODE FIX APPLIED; MANUAL STEPS REQUIRED

## Symptom

Chat in production web UI at `ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` always returns "Failed to send message. Please try again." immediately after sending any message. Has never worked in production.

## Error Chain

```
User sends message in ChatPanel.tsx
  -> POST /api/proxy/chat (web-ui Next.js route handler)
    -> POST https://ca-api-gateway-prod.../api/v1/chat (API gateway)
      -> start_chat() -> create_chat_thread() -> _get_foundry_client()
        -> ValueError("AZURE_PROJECT_ENDPOINT environment variable is required.")
      -> HTTPException(503, "Foundry dispatch unavailable: ...")
    -> Web UI proxy returns 503 with error detail
  -> ChatPanel shows error from response body
```

## Confirmed Evidence

1. **API gateway logs**: `POST /api/v1/chat HTTP/1.1 503 Service Unavailable` (multiple occurrences at 07:45, 07:47, 07:49, 14:40 UTC on 2026-03-28)
2. **Other endpoints work**: `GET /api/v1/incidents` returns 200 OK consistently (incidents endpoint doesn't need Foundry client)
3. **Health check passes**: `GET /health` returns 200 OK

## Root Causes (3 issues, all required for chat to work)

### 1. AZURE_PROJECT_ENDPOINT env var missing (PRIMARY)

**Code expects**: `os.environ.get("AZURE_PROJECT_ENDPOINT")` in `services/api-gateway/foundry.py:27`
**Terraform sets**: `FOUNDRY_ACCOUNT_ENDPOINT` (line 44 of `terraform/modules/agent-apps/main.tf`)
**Live env vars on ca-api-gateway-prod**: Has `FOUNDRY_ACCOUNT_ENDPOINT=https://aap-foundry-prod.cognitiveservices.azure.com/` but NOT `AZURE_PROJECT_ENDPOINT`

The env var name mismatch causes `_get_foundry_client()` to raise `ValueError`, which `start_chat()` catches and converts to HTTP 503.

### 2. ORCHESTRATOR_AGENT_ID env var missing (SECONDARY)

Even if the Foundry client were created, `chat.py:62-63` checks for `ORCHESTRATOR_AGENT_ID` and raises `ValueError("ORCHESTRATOR_AGENT_ID environment variable is required.")`.

This env var is not set in Terraform (`agent-apps/main.tf`) and not set manually on the container app. The Orchestrator Agent must be created in Azure AI Foundry portal first, then the agent ID set as an env var.

### 3. Missing RBAC: Azure AI Developer role (TERTIARY)

The API gateway's managed identity (`69e05934-1feb-44d4-8fd2-30373f83ccec`) has no `Azure AI Developer` role assignment on the Foundry account. Without this, even with correct env vars, the `DefaultAzureCredential` call would fail with a 403 when trying to create threads.

## Fix Applied (Code + Terraform)

### Code changes (defensive fallback):

1. **`services/api-gateway/foundry.py`**: `_get_foundry_client()` now reads `AZURE_PROJECT_ENDPOINT` first, falling back to `FOUNDRY_ACCOUNT_ENDPOINT`. This makes the code work with the env var name Terraform already sets.

2. **`agents/shared/auth.py`**: Same fallback pattern applied to the shared agent auth module.

### Terraform changes (persistent fix):

3. **`terraform/modules/agent-apps/main.tf`**: Added `AZURE_PROJECT_ENDPOINT` env var (mapped from `foundry_account_endpoint`) to both the main agent loop and the teams-bot container. Also added dynamic `ORCHESTRATOR_AGENT_ID` env var block.

4. **`terraform/modules/agent-apps/variables.tf`**: Added `orchestrator_agent_id` variable (default `""`).

5. **`terraform/envs/prod/variables.tf`**: Added `orchestrator_agent_id` variable.

6. **`terraform/envs/prod/main.tf`**: Wired `orchestrator_agent_id` to the `agent_apps` module.

### Tests:

7. **`services/api-gateway/tests/test_chat_endpoint.py`**: Added `TestFoundryClientEndpointResolution` test class with 3 tests verifying priority, fallback, and error behavior. All 14 tests pass.

## Manual Steps Still Required

After merging this PR, the operator must complete these steps (from MANUAL-SETUP.md):

### Step A: Create Orchestrator Agent in Azure AI Foundry

1. Go to https://ai.azure.com -> AAP project
2. Create an agent named `orchestrator` with model `gpt-4o`
3. Note the Agent ID (format: `asst_xxxxxxxxxxxxxxxxxxxxxxxx`)

### Step B: Set ORCHESTRATOR_AGENT_ID on the container app

```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars "ORCHESTRATOR_AGENT_ID=<agent-id-from-step-A>"
```

### Step C: Grant Azure AI Developer role to API gateway managed identity

```bash
az role assignment create \
  --assignee "69e05934-1feb-44d4-8fd2-30373f83ccec" \
  --role "Azure AI Developer" \
  --scope "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod"
```

### Step D: Verify

```bash
curl -X POST https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
# Expected: 202 with {"thread_id": "...", "status": "created"}
```

## Why This Wasn't Caught Earlier

- The MANUAL-SETUP.md Step 1 already documented this exact issue, but the steps were never executed
- Terraform sets `FOUNDRY_ACCOUNT_ENDPOINT` (the Terraform output name) but the Python code expected `AZURE_PROJECT_ENDPOINT` (the SDK convention name) -- a naming disconnect between IaC and application code
- The health check (`GET /health`) passes regardless, masking the Foundry connectivity issue
- Auth is in dev mode (no `AZURE_CLIENT_ID` set), so the 503 isn't an auth error -- it's purely the missing endpoint

## Prevention

- The code fallback (`AZURE_PROJECT_ENDPOINT || FOUNDRY_ACCOUNT_ENDPOINT`) prevents this class of naming mismatch from causing outages
- The Terraform changes now set BOTH env var names, ensuring alignment
- Added `ORCHESTRATOR_AGENT_ID` as a Terraform-managed variable so it can be set via `credentials.tfvars` rather than requiring manual `az containerapp update`
