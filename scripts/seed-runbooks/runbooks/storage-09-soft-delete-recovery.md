---
title: "Blob Soft Delete Recovery"
domain: storage
version: "1.0"
tags: ["blob", "soft-delete", "recovery", "accidental-deletion", "storage", "restore"]
---

## Symptoms

Blobs or blob versions have been accidentally deleted from an Azure Storage container. Applications return 404 errors for blobs that previously existed. Users report missing data or files. The deletion may have been caused by a misconfigured lifecycle policy, an application bug, or a malicious deletion event. Soft delete is enabled on the storage account, providing a recovery window.

## Root Causes

1. Operator error — an `az storage blob delete` or storage explorer operation deleted the wrong blobs.
2. Lifecycle policy misconfiguration — an overly aggressive delete rule removed blobs before they should have been retired.
3. Application bug — a cleanup routine deleted active blobs due to incorrect date or name filtering.
4. Ransomware or malicious deletion — storage account compromised and blobs deleted intentionally.

## Diagnostic Steps

1. Confirm soft delete is enabled and check the retention period:
   ```bash
   az storage blob service-properties delete-policy show \
     --account-name {storage_account} \
     --auth-mode login \
     --query "{enabled:enabled,daysRetained:daysRetained}"
   ```
2. List all soft-deleted blobs in the container:
   ```bash
   az storage blob list \
     --container-name {container_name} \
     --account-name {storage_account} \
     --include d \
     --auth-mode login \
     --query "[?deleted].{name:name,deletedTime:properties.deletedTime,remainingRetentionDays:properties.remainingRetentionDays}" \
     --output table
   ```
3. Check blob versions if versioning is enabled:
   ```bash
   az storage blob list \
     --container-name {container_name} \
     --account-name {storage_account} \
     --include v \
     --auth-mode login \
     --query "[?versionId!=null].{name:name,versionId:versionId,isCurrent:isCurrentVersion}" \
     --output table
   ```
4. Investigate who deleted the blobs via audit logs:
   ```kql
   StorageBlobLogs
   | where AccountName == "{storage_account}"
   | where OperationName == "DeleteBlob" or OperationName == "DeleteContainer"
   | where TimeGenerated > ago(24h)
   | project TimeGenerated, CallerIpAddress, AuthenticationType, ObjectKey, StatusCode
   | order by TimeGenerated desc
   ```
5. Check if a lifecycle policy triggered the deletion:
   ```kql
   StorageBlobLogs
   | where AccountName == "{storage_account}"
   | where OperationName == "DeleteBlob" and UserAgentHeader contains "LifecycleManagement"
   | where TimeGenerated > ago(24h)
   | summarize count() by ObjectKey
   ```

## Remediation Commands

```bash
# Undelete a specific soft-deleted blob
az storage blob undelete \
  --container-name {container_name} \
  --name {blob_name} \
  --account-name {storage_account} \
  --auth-mode login

# Bulk undelete all soft-deleted blobs in a container
az storage blob list \
  --container-name {container_name} --account-name {storage_account} \
  --include d --auth-mode login \
  --query "[?deleted].name" --output tsv \
  | xargs -I{} az storage blob undelete \
    --container-name {container_name} --name {} \
    --account-name {storage_account} --auth-mode login

# Restore from a specific blob version
az storage blob copy start \
  --source-account-name {storage_account} \
  --source-container {container_name} \
  --source-blob {blob_name} \
  --source-version-id {version_id} \
  --destination-container {container_name} \
  --destination-blob {blob_name} \
  --auth-mode login
```

## Rollback Procedure

Blob undelete is non-destructive — restoring soft-deleted blobs does not overwrite active blobs with the same name if versioning is enabled. After recovery, audit the deletion event and fix the root cause (lifecycle policy misconfiguration, application bug, or credential revocation for the compromised identity). Enable container soft delete in addition to blob soft delete for defense-in-depth against container-level deletions.
