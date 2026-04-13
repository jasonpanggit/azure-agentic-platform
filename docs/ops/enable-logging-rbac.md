# Enable Logging — RBAC Requirements

The `api-gateway` managed identity needs two roles to support the
`POST /api/v1/vms/{id}/diagnostic-settings` (and equivalent VMSS/AKS) endpoints
that install Azure Monitor Agent and create Data Collection Rules.

## Required Roles

| Role | Scope | Purpose |
|------|-------|---------|
| `Monitoring Contributor` | Subscription | Create/update Data Collection Rules and DCR associations |
| `Virtual Machine Contributor` | Subscription | Install VM extensions (Azure Monitor Agent) |

## Assignment Commands

Replace `<SUBSCRIPTION_ID>` and `<API_GATEWAY_PRINCIPAL_ID>` with the actual values.

The `api-gateway` managed identity principal ID can be found with:

```bash
az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --query identity.principalId \
  -o tsv
```

### Monitoring Contributor

```bash
az role assignment create \
  --assignee "<API_GATEWAY_PRINCIPAL_ID>" \
  --role "Monitoring Contributor" \
  --scope "/subscriptions/<SUBSCRIPTION_ID>"
```

### Virtual Machine Contributor

```bash
az role assignment create \
  --assignee "<API_GATEWAY_PRINCIPAL_ID>" \
  --role "Virtual Machine Contributor" \
  --scope "/subscriptions/<SUBSCRIPTION_ID>"
```

## Multi-Subscription Environments

If VMs span multiple subscriptions, repeat both assignments for each subscription:

```bash
for SUB_ID in <SUB_1> <SUB_2> <SUB_3>; do
  az role assignment create \
    --assignee "<API_GATEWAY_PRINCIPAL_ID>" \
    --role "Monitoring Contributor" \
    --scope "/subscriptions/${SUB_ID}"

  az role assignment create \
    --assignee "<API_GATEWAY_PRINCIPAL_ID>" \
    --role "Virtual Machine Contributor" \
    --scope "/subscriptions/${SUB_ID}"
done
```

## Notes

- These roles are **not** managed by the Terraform `rbac` module today. Add them there
  if you want them tracked as code (`azurerm_role_assignment` resources in
  `terraform/modules/rbac/main.tf`).
- Role assignments propagate within ~2 minutes in Azure AD. If the endpoint returns
  `403 Forbidden` immediately after assignment, wait and retry.
- Arc VM DCR associations also require `Monitoring Contributor` on the Arc-enabled
  server's subscription. The `Virtual Machine Contributor` role is **not** needed for
  Arc (extensions are managed through `Microsoft.HybridCompute/machines/extensions`
  which is covered by Arc-specific RBAC separately).
