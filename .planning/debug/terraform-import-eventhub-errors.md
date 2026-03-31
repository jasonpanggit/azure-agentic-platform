# Debug: terraform-import-eventhub-errors

**Date:** 2026-03-31
**Status:** RESOLVED (pending apply)

## Errors

### Error 1: Container App already exists (needs import)
- **Resource:** `module.arc_mcp_server[0].azurerm_container_app.arc_mcp_server`
- **Azure ID:** `/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.App/containerApps/ca-arc-mcp-server-prod`
- **Root cause:** Previous `terraform apply` timed out but Azure still created the resource (provisioningState: Failed). Terraform state does not know about it.
- **Fix:** `terraform import` the existing resource into state.
- **Result:** Import successful. Plan now shows "update in-place" instead of "create".

### Error 2: EventHub namespace network ruleset conflict
- **Resource:** `module.eventhub.azurerm_eventhub_namespace.main`
- **Error:** "the value of public network access of namespace should be the same as of the network rulesets"
- **Root cause:** The original inline `network_rulesets` block was missing the `public_network_access_enabled` attribute. When omitted, the provider defaults it to `true` inside the network_rulesets, which conflicts with the namespace-level `public_network_access_enabled = false`. The Azure API requires these to match.
- **Fix:** Added `public_network_access_enabled = false` and `trusted_service_access_enabled = true` inside the inline `network_rulesets` block to match the namespace-level setting.
- **Note:** Initially tried extracting to a standalone `azurerm_eventhub_namespace_network_rule_set` resource, but that resource type does not exist in azurerm 4.65.0. The inline block is the only supported approach.

## Investigation

### Container App verification
```
az containerapp show --name ca-arc-mcp-server-prod --resource-group rg-aap-prod
Result: exists, provisioningState: "Failed"
```

### EventHub namespace verification
```
az eventhubs namespace show --name evhns-aap-prod --resource-group rg-aap-prod
Result: publicNetworkAccess: "Disabled", status: "Active"

az eventhubs namespace network-rule-set show
Result: defaultAction: "Deny", publicNetworkAccess: "Disabled", trustedServiceAccessEnabled: false
Both are consistent in Azure — the conflict was in the Terraform provider's attribute defaults.
```

### Provider schema analysis
```
terraform providers schema -json | python3 (extract eventhub resources)
Result: No standalone azurerm_eventhub_namespace_network_rule_set resource exists.
The network_rulesets is a list(object) attribute on azurerm_eventhub_namespace with:
  - default_action: string
  - public_network_access_enabled: bool  <-- was missing, defaults to true
  - trusted_service_access_enabled: bool
  - ip_rule: list(object)
  - virtual_network_rule: set(object)
```

## Changes Made

### 1. terraform/modules/eventhub/main.tf
Added `public_network_access_enabled = false` and `trusted_service_access_enabled = true` inside the `network_rulesets` block:
```hcl
network_rulesets {
  default_action                = "Deny"
  public_network_access_enabled = false        # NEW - matches namespace-level setting
  trusted_service_access_enabled = true         # NEW - allows Azure Monitor to forward alerts
  virtual_network_rule {
    subnet_id = var.subnet_reserved_1_id
  }
}
```

### 2. terraform import (state operation)
```
terraform import -var-file="credentials.tfvars" \
  'module.arc_mcp_server[0].azurerm_container_app.arc_mcp_server' \
  '/subscriptions/.../Microsoft.App/containerApps/ca-arc-mcp-server-prod'
Result: Import successful!
```

## Verification

- [x] EventHub network ruleset fix applied
- [x] Container App imported into state
- [x] terraform validate passes
- [x] terraform plan succeeds (7 to add, 11 to change, 0 to destroy)
- [ ] terraform apply succeeds (user to run)

## Plan Summary (post-fix)
- **7 to add:** AcrPull roles for new agents (eol, patch), Cosmos DB Operator roles, arc_mcp_acr_pull
- **11 to change:** Arc MCP server (update in-place), EventHub namespace (trusted_service_access_enabled false->true), plus other planned changes
- **0 to destroy:** Nothing destroyed
