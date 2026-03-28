# Debug: terraform-validate-errors

## Summary
`terraform validate` reports 3 errors in the `fabric` and `foundry` modules after `terraform init` was fixed.

## Errors (captured from `terraform validate`)

### Error 1: Invalid configuration — fabric module
```
Error: Invalid configuration
  with module.fabric.azapi_resource.fabric_workspace,
  on ../../modules/fabric/main.tf line 49

embedded schema validation failed: the argument "type" is invalid.
resource type Microsoft.Fabric/workspaces can't be found.
```

**Root cause:** The azapi provider's embedded schema doesn't include `Microsoft.Fabric/workspaces` as a known resource type. Fabric workspace resources are data-plane items not in the ARM schema. The azapi provider supports this via `schema_validation_enabled = false`.

**Fix:** Add `schema_validation_enabled = false` to all `azapi_resource` blocks using `Microsoft.Fabric/workspaces/*` types (workspace, eventhouse, KQL database, activator, lakehouse). The capacity resource (`Microsoft.Fabric/capacities`) is an ARM resource and validates fine.

### Error 2: Insufficient identity blocks — foundry module
```
Error: Insufficient identity blocks
  on ../../modules/foundry/main.tf line 18, in resource "azurerm_cognitive_account_project" "main"

At least 1 "identity" blocks are required.
```

**Root cause:** `azurerm_cognitive_account_project` requires an `identity` block in azurerm ~> 4.65.0. A previous comment (ISSUE-09) said it was removed because "the project inherits identity from the parent" — but the provider schema mandates it.

**Fix:** Add `identity { type = "SystemAssigned" }` block to the `azurerm_cognitive_account_project` resource.

### Error 3: Unsupported argument `tags` — foundry module
```
Error: Unsupported argument
  on ../../modules/foundry/main.tf line 46, in resource "azurerm_cognitive_deployment" "gpt4o"

An argument named "tags" is not expected here.
```

**Root cause:** `azurerm_cognitive_deployment` does not support the `tags` argument in azurerm ~> 4.65.0. A previous comment (ISSUE-03) added tags but the schema doesn't accept them.

**Fix:** Remove the `tags` argument from the `azurerm_cognitive_deployment` resource.

## Additional Warning (non-blocking)
```
Warning: Argument is deprecated
  with module.foundry.azurerm_monitor_diagnostic_setting.foundry

`metric` has been deprecated in favour of the `enabled_metric` property
```

**Fix:** Replace `metric` block with `enabled_metric` block in the diagnostic settings resource.

## Status: RESOLVED
All 3 errors fixed + deprecation warning addressed.
