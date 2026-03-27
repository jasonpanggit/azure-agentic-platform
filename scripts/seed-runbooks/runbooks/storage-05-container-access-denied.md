---
title: "Blob Container Access Denied"
domain: storage
version: "1.0"
tags: ["storage", "blob", "access-denied", "rbac", "sas", "authorization"]
---

## Symptoms

Users or services receive HTTP 403 (AuthorizationFailure) or 401 (Unauthenticated) errors when accessing Azure Blob Storage containers. Operations that previously worked suddenly fail after a permission change. Specific users or service principals cannot list, read, or write blobs. Azure Monitor shows increased authorization error rates on the storage account.

## Root Causes

1. RBAC role assignment removed or expired — a managed identity or service principal lost its Storage Blob Data Contributor role.
2. SAS token expired — a Shared Access Signature token used by an application has passed its expiry time.
3. Container-level public access changed — container access policy downgraded from public to private without updating client code.
4. Storage account public access disabled — `AllowBlobPublicAccess=false` set at the account level without migrating to private access patterns.

## Diagnostic Steps

1. Check current RBAC assignments on the storage account:
   ```bash
   az role assignment list \
     --scope /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{storage_account} \
     --query "[].{principal:principalName,role:roleDefinitionName,type:principalType}" \
     --output table
   ```
2. Check container-level access policy:
   ```bash
   az storage container show \
     --name {container_name} \
     --account-name {storage_account} \
     --auth-mode login \
     --query "properties.publicAccess"
   ```
3. Check storage account public access setting:
   ```bash
   az storage account show \
     --resource-group {rg} --name {storage_account} \
     --query "{allowBlobPublicAccess:allowBlobPublicAccess,networkRules:networkRuleSet.defaultAction}"
   ```
4. Check storage analytics for 403 error pattern:
   ```kql
   StorageBlobLogs
   | where AccountName == "{storage_account}"
   | where StatusCode == 403
   | where TimeGenerated > ago(1h)
   | summarize count() by CallerIpAddress, AuthenticationType, Uri
   | order by count_ desc
   ```
5. Verify the service principal's token has the required scopes:
   ```bash
   az ad sp show --id {sp_id} \
     --query "{displayName:displayName,appId:appId}"
   az role assignment list --assignee {sp_id} \
     --query "[?contains(scope,'storageAccounts')].{scope:scope,role:roleDefinitionName}"
   ```

## Remediation Commands

```bash
# Assign Storage Blob Data Contributor to the service principal
az role assignment create \
  --assignee {sp_or_managed_identity_id} \
  --role "Storage Blob Data Contributor" \
  --scope /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{storage_account}/blobServices/default/containers/{container}

# Generate a new SAS token with appropriate expiry
az storage container generate-sas \
  --name {container_name} \
  --account-name {storage_account} \
  --permissions rwdl \
  --expiry $(date -u -d '+7 days' +%Y-%m-%dT%H:%MZ) \
  --auth-mode login \
  --as-user

# Re-enable container public access (only if intended)
az storage container set-permission \
  --name {container_name} \
  --account-name {storage_account} \
  --public-access blob
```

## Rollback Procedure

RBAC role assignments take effect within 2-5 minutes. If an over-permissive role was assigned during emergency remediation, downscope it to the minimum required permission after service is restored. If a SAS token with broad permissions was issued as a quick fix, rotate the storage account key that signed it after implementing a proper RBAC-based access pattern. Document all permission changes in the change management system.
