# Debug: Terraform Plan Errors

**Created:** 2026-03-31
**Status:** IN PROGRESS

## Summary

`terraform plan -var-file="credentials.tfvars"` in `terraform/envs/prod` fails with 3 errors + 2 deprecation warnings.

## Error 1 - Entra AD 403 Forbidden

**Location:** `azuread` provider reading app registration `8176f860-9715-46e3-8875-5939a6b76a69`
**Root Cause:** The service principal in `credentials.tfvars` lacks Microsoft Graph `Application.Read.All` permission. The `azuread_application.web_ui` and `azuread_application.fabric_sp` resources (and their service principals) require the SP to have Graph API read access to manage app registrations.

**Fix:** Two-pronged approach:
1. **Code fix:** Guard `entra_apps` module and `fabric_sp` resources behind a feature flag (`enable_entra_apps`) so plan succeeds even without Graph permissions. This lets infra teams who lack Entra admin run `terraform plan` on the rest of the stack.
2. **Manual action required:** Grant `Application.ReadWrite.All` (or at minimum `Application.Read.All` + `Application.ReadWrite.OwnedBy`) to the Terraform SP in Entra ID. This requires a Privileged Role Admin or Global Admin.

**Decision:** Implement Option 2a — replace the `azuread_application` data source lookup with a variable-based approach so the plan doesn't need Graph API permissions at plan time. Since the resources use `count`, gating them behind `var.enable_entra_apps = false` by default lets the rest of the infrastructure plan cleanly.

## Error 2 - Dependency Cycle in Container Apps

**Location:** `module.agent_apps.azurerm_container_app.agents` (for_each loop)
**Root Cause:** Line 107 in `modules/agent-apps/main.tf`:
```hcl
value = azurerm_container_app.agents[each.key].identity[0].principal_id
```
Each container app in the `for_each` references `azurerm_container_app.agents[each.key]` — i.e., **itself**. But because Terraform tracks the entire `for_each` resource as one dependency node, this creates a cycle: every instance depends on every other instance of the same resource.

**Fix:** Remove the self-referencing `AGENT_ENTRA_ID` env var from the container app definition. Instead, the principal_id is only known after the container app is created. Options:
- **Chosen approach:** Remove the `AGENT_ENTRA_ID` env block from the inline container definition. The agents can read their own managed identity principal_id at runtime via the Azure Instance Metadata Service (IMDS) or via `DefaultAzureCredential().get_token()` and extracting the `oid` claim from the JWT. No Terraform circular dependency needed.
- Alternative: Use a `null_resource` + `local-exec` to inject the env var post-creation, but this is fragile.

## Error 3 - Self-referential Block (teams_bot)

**Location:** `modules/agent-apps/main.tf` line 340
```hcl
value = azurerm_container_app.teams_bot.identity[0].principal_id
```
**Root Cause:** Same pattern as Error 2 but on a single resource (not for_each). The `teams_bot` container app references its own `identity[0].principal_id` in an env var, which Terraform cannot resolve because the resource doesn't exist yet at plan time.

**Fix:** Same approach as Error 2 — remove the self-referencing `AGENT_ENTRA_ID` env var. The teams-bot can retrieve its own identity at runtime.

## Deprecation Warnings - EventHub namespace_name

**Location:** `modules/eventhub/main.tf` lines 44, 55
**Root Cause:** `namespace_name` + `resource_group_name` is deprecated on `azurerm_eventhub` and `azurerm_eventhub_consumer_group`. Will be removed in azurerm v5.0.

**Fix:** Replace `namespace_name` with `namespace_id = azurerm_eventhub_namespace.main.id` and remove `resource_group_name` from those resources.

## Fix Order

1. [x] Error 3 (self-referential teams_bot) — remove AGENT_ENTRA_ID self-reference
2. [x] Error 2 (cycle in for_each agents) — remove AGENT_ENTRA_ID self-reference
3. [x] Error 1 (Entra AD 403) — add enable_entra_apps flag
4. [x] Warnings (eventhub deprecation) — switch to namespace_id
5. [ ] Validate with `terraform validate`
