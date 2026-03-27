---
title: "Key Vault Access Policy Audit"
domain: security
version: "1.0"
tags: ["key-vault", "access-policy", "rbac", "secrets", "certificates", "audit"]
---

## Symptoms

A security review or compliance audit reveals that an Azure Key Vault has overly permissive access policies. Multiple service principals or users have full `get`, `list`, `set`, `delete` permissions on secrets, keys, and certificates when least-privilege should be enforced. Defender for Cloud raises a "Overpermissive Key Vault access" recommendation. An automated security scanner flags Key Vault access policies as non-compliant.

## Root Causes

1. Broad access policies granted during initial development that were never tightened for production.
2. Legacy access policy model used instead of RBAC — access policies grant per-principal blanket permissions rather than scoped role assignments.
3. Emergency access granted during an incident and never revoked.
4. Service principal with broader access than its workload requires (principle of least privilege violated).

## Diagnostic Steps

1. List all current access policies on the Key Vault:
   ```bash
   az keyvault show --resource-group {rg} --name {kv_name} \
     --query "properties.accessPolicies[].{objectId:objectId,permissions:permissions}" \
     --output json
   ```
2. Check if RBAC authorization mode is enabled (preferred over access policies):
   ```bash
   az keyvault show --resource-group {rg} --name {kv_name} \
     --query "properties.enableRbacAuthorization"
   ```
3. List RBAC role assignments on the Key Vault:
   ```bash
   az role assignment list \
     --scope /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.KeyVault/vaults/{kv_name} \
     --query "[].{principal:principalName,role:roleDefinitionName,type:principalType}" \
     --output table
   ```
4. Audit Key Vault access logs for over-privileged operations:
   ```kql
   AzureDiagnostics
   | where ResourceProvider == "MICROSOFT.KEYVAULT"
   | where ResourceId contains "{kv_name}"
   | where OperationName in ("SecretDelete", "KeyDelete", "CertificateDelete", "SecretSet")
   | where TimeGenerated > ago(30d)
   | summarize count() by CallerIPAddress, ResultType, identity_claim_oid_g
   | order by count_ desc
   ```
5. Check for Defender for Cloud Key Vault recommendations:
   ```bash
   az security assessment list --resource-group {rg} \
     --query "[?contains(resourceDetails.id,'{kv_name}') && statusCode!='Healthy'].{name:displayName,status:statusCode,severity:metadata.severity}" \
     --output table
   ```

## Remediation Commands

```bash
# Enable RBAC authorization model (migration from access policies)
az keyvault update --resource-group {rg} --name {kv_name} \
  --enable-rbac-authorization true

# Assign Key Vault Secrets User (read-only) to a service principal
az role assignment create \
  --assignee {sp_id} \
  --role "Key Vault Secrets User" \
  --scope /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.KeyVault/vaults/{kv_name}

# Assign Key Vault Administrator only to specific trusted admins
az role assignment create \
  --assignee {admin_upn} \
  --role "Key Vault Administrator" \
  --scope /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.KeyVault/vaults/{kv_name}

# Remove a legacy access policy entry
az keyvault delete-policy --resource-group {rg} --name {kv_name} \
  --object-id {legacy_sp_object_id}
```

## Rollback Procedure

RBAC authorization migration is reversible — if the RBAC transition causes access failures (e.g., a service principal with a legacy access policy loses access), temporarily disable RBAC authorization: `az keyvault update --enable-rbac-authorization false`. Then migrate each workload's access to the appropriate RBAC role before re-enabling RBAC mode. Schedule this migration during a maintenance window with all teams notified in advance.
