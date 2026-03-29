# Plan 08-01: User Setup Required

**All code changes are committed. The following steps require operator execution with Azure credentials.**

---

## Task 08-01-02: Create Orchestrator Agent in Foundry

Run this from a terminal with an active `az login` session that has `Cognitive Services Contributor` or `Azure AI Developer` on the Foundry account:

```bash
AZURE_PROJECT_ENDPOINT=https://aap-foundry-prod.cognitiveservices.azure.com/ \
  python3 scripts/configure-orchestrator.py --create
```

Expected output:
```
AGENT_ID=asst_<alphanumeric>
```

Verify:
```bash
AZURE_PROJECT_ENDPOINT=https://aap-foundry-prod.cognitiveservices.azure.com/ \
ORCHESTRATOR_AGENT_ID=<asst_xxx> \
  python3 scripts/configure-orchestrator.py --show
```

Expected: `Name: AAP Orchestrator`, `Model: gpt-4o`

If the script fails with auth errors, create the agent via Azure Portal: `ai.azure.com` > AAP project > Agents > Create.

---

## Task 08-01-03: Set ORCHESTRATOR_AGENT_ID and Lock CORS on ca-api-gateway-prod

Replace `<asst_xxx>` with the agent ID from Task 08-01-02:

```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars \
    "ORCHESTRATOR_AGENT_ID=<asst_xxx>" \
    "CORS_ALLOWED_ORIGINS=https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
```

Verify:
```bash
az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --query "properties.template.containers[0].env[?name=='ORCHESTRATOR_AGENT_ID' || name=='CORS_ALLOWED_ORIGINS']" \
  -o table
```

---

## Task 08-01-04: Grant Azure AI Developer Role to Gateway Managed Identity

```bash
az role assignment create \
  --assignee "69e05934-1feb-44d4-8fd2-30373f83ccec" \
  --role "Azure AI Developer" \
  --scope "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod"
```

Verify:
```bash
az role assignment list \
  --assignee "69e05934-1feb-44d4-8fd2-30373f83ccec" \
  --query "[?roleDefinitionName=='Azure AI Developer']" \
  -o table
```

---

## Task 08-01-05: Register Azure Bot Service and Enable Teams Channel

**Requires Entra admin permissions for app registration.**

Step 1: Create or look up the Entra App Registration:
```bash
az ad app create --display-name "AAP Teams Bot" --sign-in-audience "AzureADMultipleOrgs"
# Note the appId from output
```

Step 2: Create a client secret:
```bash
az ad app credential reset --id <app-id> --append
# Note the password from output
```

Step 3: Create the Azure Bot resource:
```bash
az bot create \
  --resource-group rg-aap-prod \
  --name aap-teams-bot-prod \
  --kind registration \
  --endpoint "https://ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/messages" \
  --app-type MultiTenant \
  --appid "<app-id-from-step-1>"
```

Step 4: Enable the Teams channel:
```bash
az bot msteams create --name aap-teams-bot-prod --resource-group rg-aap-prod
```

Step 5: Set bot credentials on the Container App:
```bash
az containerapp update \
  --name ca-teams-bot-prod \
  --resource-group rg-aap-prod \
  --set-env-vars \
    "MicrosoftAppId=<app-id>" \
    "MicrosoftAppPassword=<password-from-step-2>"
```

Verify:
```bash
az bot show --name aap-teams-bot-prod --resource-group rg-aap-prod -o table
```

If admin consent is blocked, document as DEGRADED finding and continue.

---

## Task 08-01-06: Add Missing GitHub Actions Secrets

**Requires repository admin access and the actual secret values.**

Retrieve the PostgreSQL admin password from Key Vault or Terraform output, then:

```bash
# PostgreSQL admin password
gh secret set POSTGRES_ADMIN_PASSWORD --body "<password>"

# Foundry endpoint for embedding generation
gh secret set AZURE_OPENAI_ENDPOINT --body "https://aap-foundry-prod.cognitiveservices.azure.com/"

# API key from Foundry account
gh secret set AZURE_OPENAI_API_KEY --body "<key>"
```

Verify:
```bash
gh secret list | grep -E "POSTGRES_ADMIN_PASSWORD|AZURE_OPENAI_ENDPOINT|AZURE_OPENAI_API_KEY"
```

Expected: All 3 secrets listed (total should be >= 9).

---

## Completion Checklist

- [ ] Task 08-01-02: `AGENT_ID=asst_...` printed by script
- [ ] Task 08-01-03: `ORCHESTRATOR_AGENT_ID` and `CORS_ALLOWED_ORIGINS` set on `ca-api-gateway-prod`
- [ ] Task 08-01-04: `Azure AI Developer` role assigned to `69e05934-1feb-44d4-8fd2-30373f83ccec`
- [ ] Task 08-01-05: `aap-teams-bot-prod` bot resource created; Teams channel enabled
- [ ] Task 08-01-06: 3 missing GitHub secrets added (`POSTGRES_ADMIN_PASSWORD`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`)
