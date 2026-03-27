---
title: "RBAC Over-Permission Investigation"
domain: security
version: "1.0"
tags: ["rbac", "permissions", "least-privilege", "owner", "contributor", "security"]
---

## Symptoms

A security audit or Defender for Cloud recommendation flags that service principals, users, or groups have excessive Azure RBAC permissions — Owner or Contributor at the subscription level when only resource-group-scoped or resource-scoped reader permissions are required. Azure Policy compliance report shows "Not compliant" for permission scope policies. The least-privilege principle is being violated, increasing the blast radius of any potential compromise.

## Root Causes

1. Developer convenience — Contributor role granted at subscription scope to avoid repeated permission debugging during development, never tightened.
2. Terraform service principal with Owner role used for IaC deployments when Contributor + specific role assignment grants would suffice.
3. Inherited permissions — user added to a management group with broad role, inheriting subscription-level permissions.
4. Break-glass account with Owner role that was created for emergency access but left assigned permanently.

## Diagnostic Steps

1. List all Owner and Contributor assignments at the subscription level:
   ```bash
   az role assignment list --subscription {subscription_id} \
     --query "[?roleDefinitionName=='Owner' || roleDefinitionName=='Contributor'].{principal:principalName,type:principalType,scope:scope}" \
     --output table
   ```
2. Find assignments broader than resource group scope:
   ```bash
   az role assignment list --subscription {subscription_id} \
     --query "[?scope=='/subscriptions/{subscription_id}'].{principal:principalName,role:roleDefinitionName,type:principalType}" \
     --output table
   ```
3. Check Azure Policy for RBAC compliance recommendations:
   ```bash
   az policy state list --subscription {subscription_id} \
     --query "[?complianceState=='NonCompliant' && policyDefinitionCategory=='Authorization'].{resource:resourceId,policy:policyDefinitionName}" \
     --output table
   ```
4. Identify unused permissions (service principals with assignments but no recent activity):
   ```kql
   AzureActivity
   | where TimeGenerated > ago(90d)
   | where OperationNameValue contains "write" or OperationNameValue contains "delete"
   | summarize LastActivity=max(TimeGenerated) by Caller
   | where LastActivity < ago(90d)
   | project Caller, LastActivity
   ```
5. Check Defender for Cloud RBAC recommendations:
   ```bash
   az security assessment list \
     --query "[?contains(displayName,'RBAC') || contains(displayName,'permissions')].{name:displayName,status:statusCode,severity:metadata.severity}" \
     --output table
   ```

## Remediation Commands

```bash
# Remove subscription-level Owner assignment
az role assignment delete \
  --assignee {principal_id} \
  --role Owner \
  --subscription {subscription_id}

# Replace with minimum required role at resource group scope
az role assignment create \
  --assignee {principal_id} \
  --role Contributor \
  --resource-group {rg}

# Create a custom role with only the specific permissions needed
az role definition create --role-definition '{
  "Name": "Custom-App-Role-{app_name}",
  "IsCustom": true,
  "Description": "Minimum required permissions for {app_name}",
  "Actions": ["Microsoft.Compute/virtualMachines/read","Microsoft.Compute/virtualMachines/restart/action"],
  "AssignableScopes": ["/subscriptions/{subscription_id}/resourceGroups/{rg}"]
}'
```

## Rollback Procedure

RBAC role assignment removal is immediate. If the removal causes an access failure (e.g., a critical pipeline stops working), re-add the role temporarily: `az role assignment create --assignee {id} --role Contributor --resource-group {rg}`. Conduct a proper permission analysis to identify the minimum required roles before removing the broad assignment permanently. Use Azure Managed Identity instead of service principals with secrets wherever possible to reduce credential exposure.
