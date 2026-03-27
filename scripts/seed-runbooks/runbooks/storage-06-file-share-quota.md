---
title: "Azure File Share Quota Exceeded"
domain: storage
version: "1.0"
tags: ["file-share", "azure-files", "quota", "capacity", "smb", "storage"]
---

## Symptoms

Applications or users mounting an Azure File Share receive "disk full" errors when writing new files. The SMB share reports zero available space. Azure Monitor alerts fire on file share capacity utilization. File sync operations from on-premises using Azure File Sync stop with quota exceeded errors. File share provisioned IOPS may also be fully consumed if using Premium file shares.

## Root Causes

1. File share quota set too low at creation — the initial quota has been reached by organic data growth.
2. Log files or temp files not being cleaned up on the share, consuming quota without productive use.
3. Azure File Sync cloud tiering not configured — all data stored locally and in the cloud rather than tiering cold data to the cloud only.
4. Large one-time upload or backup job filling the share unexpectedly.

## Diagnostic Steps

1. Check current file share quota and usage:
   ```bash
   az storage share show \
     --name {share_name} \
     --account-name {storage_account} \
     --query "{quota:properties.quota,usage:properties.shareUsageBytes}"
   ```
2. Check file share metrics in Azure Monitor:
   ```bash
   az monitor metrics list \
     --resource {storage_account_resource_id}/fileServices/default \
     --metric "ShareCapacityUsedInBytes" "ShareQuota" \
     --interval PT1H --start-time $(date -u -d '-7 days' +%FT%TZ) \
     --output table
   ```
3. Analyze largest directories in the file share:
   ```bash
   az storage file list \
     --share-name {share_name} --account-name {storage_account} \
     --auth-mode login --output table
   ```
4. Check Azure File Sync endpoint health if sync is configured:
   ```bash
   az storagesync server-endpoint show \
     --resource-group {rg} \
     --storage-sync-service {sync_service} \
     --sync-group-name {sync_group} \
     --name {server_endpoint_name} \
     --query "{cloudTiering:cloudTiering,tierFilesOlderThanDays:tierFilesOlderThanDays,volumeFreeSpacePercent:volumeFreeSpacePercent}"
   ```
5. Check Premium file share IOPS consumption:
   ```bash
   az monitor metrics list \
     --resource {storage_account_resource_id}/fileServices/default \
     --metric "FileShareSnapshotCount" "Transactions" \
     --interval PT5M --start-time $(date -u -d '-2 hours' +%FT%TZ)
   ```

## Remediation Commands

```bash
# Increase file share quota immediately
az storage share update \
  --name {share_name} \
  --account-name {storage_account} \
  --quota 2048

# Enable cloud tiering on Azure File Sync to reclaim space
az storagesync server-endpoint update \
  --resource-group {rg} \
  --storage-sync-service {sync_service} \
  --sync-group-name {sync_group} \
  --name {server_endpoint_name} \
  --cloud-tiering true \
  --volume-free-space-percent 20 \
  --tier-files-older-than-days 30

# Delete old snapshots to reclaim quota
az storage share snapshot list --share-name {share_name} \
  --account-name {storage_account} \
  --query "[?properties.lastModified<'{cutoff_date}'].snapshot" --output tsv \
  | xargs -I{} az storage share delete --name {share_name} \
    --account-name {storage_account} --snapshot {}
```

## Rollback Procedure

File share quota increases are non-destructive. If the quota increase temporarily masked a cleanup problem, identify and remove unnecessary files using the Azure portal Storage Explorer or `az storage file delete`. For Premium file shares, monitor IOPS and throughput metrics after the quota change to ensure performance remains within the provisioned limits. Plan regular capacity reviews to avoid quota exhaustion incidents.
