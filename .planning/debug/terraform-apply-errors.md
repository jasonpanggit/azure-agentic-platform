# Debug: Terraform Apply Errors

**Date:** 2026-03-31
**Branch:** fix/terraform-apply-errors
**Status:** FIXED

## Error 1: Container App "Operation expired"

### Symptom
```
Error: creating Container App "ca-arc-mcp-server-prod" in rg-aap-prod
ContainerAppOperationError: Failed to provision revision for container app
'ca-arc-mcp-server-prod'. Error details: Operation expired.
Resource: module.arc_mcp_server[0].azurerm_container_app.arc_mcp_server
```

### Root Cause: Chicken-and-egg ACR pull failure

The Arc MCP Server Container App uses `identity = "system"` for ACR auth, but:

1. Terraform creates the Container App first (which triggers image pull)
2. The `AcrPull` role assignment (`azurerm_role_assignment.arc_mcp_acr_pull`) has
   `depends_on = [azurerm_container_app.arc_mcp_server]` — so it runs AFTER the app
3. Without AcrPull, the system-assigned managed identity cannot pull the image
4. Azure times out waiting for the revision to become healthy -> "Operation expired"

Verified via CLI:
- Container Apps environment: `cae-aap-prod` is `Succeeded` (healthy)
- ACR image: `services/arc-mcp-server:latest` exists in `aapcrprodjgmjti`
- Role assignments: The MI `b70f5a69-...` has **zero** role assignments on the ACR scope
- Container App state: `provisioningState: Failed`

This is the same chicken-and-egg problem the `agent-apps` module solves with
`use_placeholder_image`. The arc-mcp-server module lacked this escape hatch.

### Fix

Added `use_placeholder_image` variable to the arc-mcp-server module:
- When `true`: uses `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest`
  (public image, no ACR auth needed) and skips the `registry` block
- When `false`: uses the real ACR image with managed identity auth
- The `lifecycle { ignore_changes = [template[0].container[0].image] }` block
  was already in place, so CI/CD deploys the real image after initial provisioning
- Set `use_placeholder_image = true` in prod main.tf to unblock first apply

### Deployment Sequence
1. `terraform apply` creates the Container App with placeholder image (succeeds)
2. AcrPull role assignment is created (depends_on the app)
3. CI/CD pushes the real image and updates the container app revision

---

## Error 2: Action Group 400 Bad Request

### Symptom
```
Error: creating/updating Action Group "ag-aap-alert-forward-prod" in rg-aap-prod
400 Bad Request: EventhubReceiverNameSpaceIsInvalidFormat
Resource: module.eventhub.azurerm_monitor_action_group.main
```

### Root Cause: Wrong attribute for event_hub_namespace

In `terraform/modules/eventhub/main.tf` line 93:
```hcl
event_hub_namespace = azurerm_eventhub_namespace.main.id  # WRONG
```

The `event_hub_receiver` block's `event_hub_namespace` field expects the
**namespace name** (e.g., `"evhns-aap-prod"`), NOT the full resource ID.

Passing the full resource ID like:
```
/subscriptions/.../resourceGroups/.../providers/Microsoft.EventHub/namespaces/evhns-aap-prod
```
fails Azure's namespace name format validation with `EventhubReceiverNameSpaceIsInvalidFormat`.

### Fix

Changed line 93 from:
```hcl
event_hub_namespace = azurerm_eventhub_namespace.main.id
```
to:
```hcl
event_hub_namespace = azurerm_eventhub_namespace.main.name
```

This passes just `"evhns-aap-prod"` which is the expected format.

---

## Validation

Both fixes validated with `terraform validate` in `terraform/envs/prod/`.
