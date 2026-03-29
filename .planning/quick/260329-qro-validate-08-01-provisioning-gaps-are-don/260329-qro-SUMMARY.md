---
quick_id: 260329-qro
task: validate 08-01 provisioning gaps are done
date: 2026-03-29
status: complete
---

# Validation: 08-01 Provisioning Gaps

## Results

| Task | Requirement | Status | Evidence |
|------|-------------|--------|----------|
| 08-01-02 | Foundry Orchestrator Agent created | ✅ Done | `ORCHESTRATOR_AGENT_ID=asst_NeBVjCA5isNrIERoGYzRpBTu` present on container app |
| 08-01-03 | ORCHESTRATOR_AGENT_ID + CORS set on gateway | ⚠️ Partial | `ORCHESTRATOR_AGENT_ID` is set correctly; `CORS_ALLOWED_ORIGINS` is set but still `*` (wildcard) — not locked to production URL |
| 08-01-04 | Azure AI Developer role assigned to gateway MI | ❌ Not done | No role assignments exist for principal `69e05934-1feb-44d4-8fd2-30373f83ccec`; `--assignee` query returned empty |
| 08-01-05 | Azure Bot Service + Teams channel enabled | ❌ Not done | `ResourceNotFound`: `Microsoft.BotService/botServices/aap-teams-bot-prod` does not exist in `rg-aap-prod` |
| 08-01-06 | GitHub secrets added (3 of 3) | ❌ Not done | Only 6 secrets present; `POSTGRES_ADMIN_PASSWORD`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` all absent |

## Summary

**2/5 tasks complete** (08-01-02 fully done; 08-01-03 partially done). Three tasks remain outstanding before Phase 8 validation can proceed:

- **08-01-03 (PARTIAL)**: `CORS_ALLOWED_ORIGINS` must be updated from `*` to `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` per the setup instructions
- **08-01-04 (BLOCKED)**: `Azure AI Developer` role must be granted to the gateway managed identity at Foundry account scope — without this, the gateway cannot call Foundry APIs and chat will fail
- **08-01-05 (NOT STARTED)**: Azure Bot resource `aap-teams-bot-prod` must be created and Teams channel enabled — Teams integration is non-functional until complete
- **08-01-06 (NOT STARTED)**: 3 GitHub secrets must be added; current secrets total 6, all infra/auth — missing `POSTGRES_ADMIN_PASSWORD`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`

---

## Raw Output

### 08-01-02 — ORCHESTRATOR_AGENT_ID value
```
$ az containerapp show --name ca-api-gateway-prod --resource-group rg-aap-prod \
    --query "properties.template.containers[0].env[?name=='ORCHESTRATOR_AGENT_ID'].value" -o tsv

asst_NeBVjCA5isNrIERoGYzRpBTu
```

### 08-01-03 — ORCHESTRATOR_AGENT_ID + CORS env vars
```
$ az containerapp show --name ca-api-gateway-prod --resource-group rg-aap-prod \
    --query "properties.template.containers[0].env[?name=='ORCHESTRATOR_AGENT_ID' || name=='CORS_ALLOWED_ORIGINS']" -o table

Name                   Value
---------------------  -----------------------------
CORS_ALLOWED_ORIGINS   *
ORCHESTRATOR_AGENT_ID  asst_NeBVjCA5isNrIERoGYzRpBTu
```
Note: `CORS_ALLOWED_ORIGINS=*` is the default (wildcard). Task 08-01-03 requires setting it to the prod web-ui URL.

### 08-01-04 — Role assignments for gateway MI (69e05934-...)
```
$ az role assignment list --assignee "69e05934-1feb-44d4-8fd2-30373f83ccec" \
    --query "[?roleDefinitionName=='Azure AI Developer']" -o table

(no output — empty result set)

$ az role assignment list --assignee "69e05934-1feb-44d4-8fd2-30373f83ccec" -o table

(no output — principal has zero role assignments)
```
Note: The `b534021f-...` principal that appeared in a broader check is a different service principal (unrelated).

### 08-01-05 — Azure Bot Service
```
$ az bot show --name aap-teams-bot-prod --resource-group rg-aap-prod -o table

ERROR: (ResourceNotFound) The Resource 'Microsoft.BotService/botServices/aap-teams-bot-prod'
under resource group 'rg-aap-prod' was not found.
Code: ResourceNotFound
```

### 08-01-06 — GitHub secrets
```
$ gh secret list

ACR_LOGIN_SERVER        2026-03-27T18:06:49Z
ACR_NAME                2026-03-27T18:06:48Z
AZURE_CLIENT_ID         2026-03-27T18:06:45Z
AZURE_CLIENT_SECRET     2026-03-27T18:06:55Z
AZURE_SUBSCRIPTION_ID   2026-03-27T18:06:47Z
AZURE_TENANT_ID         2026-03-27T18:06:46Z

# grep for required secrets returned no matches:
# POSTGRES_ADMIN_PASSWORD  — MISSING
# AZURE_OPENAI_ENDPOINT    — MISSING
# AZURE_OPENAI_API_KEY     — MISSING
```
