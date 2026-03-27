---
title: "Storage Lifecycle Policy Failure"
domain: storage
version: "1.0"
tags: ["storage", "lifecycle-policy", "tiering", "archive", "blob-management"]
---

## Symptoms

Azure Blob Storage lifecycle management policies are not transitioning blobs to cooler tiers (Cool, Cold, Archive) or deleting expired blobs as configured. Storage costs continue to increase despite lifecycle policies being enabled. Azure Portal shows lifecycle policies as active but no transitions have occurred within the expected timeframe. Old blobs remain in Hot tier consuming premium storage costs.

## Root Causes

1. Policy conditions not matching actual blob metadata — wrong prefix filter, missing required `modifiedBefore` condition, or case sensitivity mismatch in prefix.
2. Lifecycle policy engine delay — policies run once per day and may have an 18-24 hour lag before first execution on new accounts.
3. Blob snapshots or legal holds preventing deletion or tiering.
4. Blob index tags filter mismatch — lifecycle rules using blob index tags may not match due to tag key/value case or format issues.

## Diagnostic Steps

1. Show current lifecycle management policy:
   ```bash
   az storage account management-policy show \
     --account-name {storage_account} --resource-group {rg}
   ```
2. Check when the lifecycle policy last ran:
   ```kql
   StorageBlobLogs
   | where AccountName == "{storage_account}"
   | where OperationName == "LifecycleManagement"
   | where TimeGenerated > ago(7d)
   | summarize LastRun=max(TimeGenerated), Actions=count() by OperationName
   ```
3. Verify blobs match the policy filters:
   ```bash
   az storage blob list \
     --container-name {container} \
     --account-name {storage_account} \
     --prefix {policy_prefix} \
     --auth-mode login \
     --query "[?properties.lastModified<'{cutoff_date}'].{name:name,tier:properties.blobTier,modified:properties.lastModified}" \
     --output table
   ```
4. Check for legal holds or immutability policies blocking deletion:
   ```bash
   az storage container legal-hold show \
     --container-name {container} --account-name {storage_account}
   az storage container immutability-policy show \
     --container-name {container} --account-name {storage_account}
   ```
5. Manually test tier transition for a single blob:
   ```bash
   az storage blob set-tier \
     --container-name {container} \
     --name {test_blob_name} \
     --account-name {storage_account} \
     --tier Cool --auth-mode login
   ```

## Remediation Commands

```bash
# Update policy with corrected prefix filter
az storage account management-policy create \
  --account-name {storage_account} \
  --resource-group {rg} \
  --policy '{
    "rules": [{
      "name": "move-to-cool",
      "enabled": true,
      "type": "Lifecycle",
      "definition": {
        "filters": {"blobTypes": ["blockBlob"], "prefixMatch": ["{correct_prefix}"]},
        "actions": {"baseBlob": {"tierToCool": {"daysAfterModificationGreaterThan": 30}}}
      }
    }]
  }'

# Manually tier all blobs older than 30 days in a container (one-time cleanup)
az storage blob list --container-name {container} --account-name {storage_account} \
  --auth-mode login \
  --query "[?properties.lastModified<'{thirty_days_ago}'].name" --output tsv \
  | xargs -I{} az storage blob set-tier --container-name {container} \
    --account-name {storage_account} --name {} --tier Cool
```

## Rollback Procedure

Lifecycle policy updates are effective on the next daily execution cycle (up to 24 hours). If blobs were incorrectly transitioned to Archive tier, rehydrate them: `az storage blob set-tier --tier Hot` — note Archive rehydration takes up to 15 hours. If the policy accidentally deleted blobs, recover from soft delete within the retention period: `az storage blob undelete --container-name {container} --name {blob_name} --account-name {storage_account}`.
