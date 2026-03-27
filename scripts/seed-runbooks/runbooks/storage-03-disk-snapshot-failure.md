---
title: "Disk Snapshot Failure Recovery"
domain: storage
version: "1.0"
tags: ["disk", "snapshot", "backup", "managed-disk", "recovery", "azure-backup"]
---

## Symptoms

An Azure managed disk snapshot operation fails with an error such as "SnapshotFailed" or "ConflictingOperation". Backup jobs that rely on snapshots as recovery points fail. Azure Backup reports "VMSnapshotLinux extension operation failed" or similar errors in the job details. The VM may be in a state where ongoing operations prevent snapshot creation.

## Root Causes

1. VM in a non-snapshotable state — the VM is being resized, deallocated mid-operation, or undergoing live migration at the time of the snapshot.
2. Backup extension failure — the Azure Backup Linux or Windows VM extension failed to quiesce the OS before snapshot initiation.
3. Disk encryption conflict — the VM uses customer-managed keys and the Key Vault is soft-deleted or the key is expired.
4. Concurrent snapshot operation — another snapshot is already in progress for the same disk.

## Diagnostic Steps

1. Check snapshot status and error details:
   ```bash
   az snapshot show --resource-group {rg} --name {snapshot_name} \
     --query "{state:provisioningState,error:diskRestorePoint.completionPercent}" 2>/dev/null || \
   az backup job show --resource-group {rg} --vault-name {vault_name} --name {job_id} \
     --query "{status:properties.status,errorCode:properties.errorDetails[0].errorCode,errorMessage:properties.errorDetails[0].errorMessage}"
   ```
2. Check if any conflicting operations are running on the disk:
   ```bash
   az disk show --resource-group {rg} --name {disk_name} \
     --query "{state:diskState,operations:managedDiskId}"
   az disk list-operations --resource-group {rg} --disk-name {disk_name} 2>/dev/null
   ```
3. Check backup extension status on the VM:
   ```bash
   az vm extension list --resource-group {rg} --vm-name {vm_name} \
     --query "[?contains(name,'Backup') || contains(name,'Snapshot')].{name:name,state:provisioningState,message:instanceView.statuses[-1].message}"
   ```
4. Verify Key Vault and disk encryption set are accessible:
   ```bash
   az disk-encryption-set show --resource-group {rg} --name {des_name} \
     --query "{identity:identity.type,keyVault:activeKey.keyUrl}"
   az keyvault show --resource-group {rg} --name {kv_name} \
     --query "{state:properties.provisioningState,softDelete:properties.enableSoftDelete}"
   ```
5. Review Azure Backup job history:
   ```bash
   az backup job list --resource-group {rg} --vault-name {vault_name} \
     --workload-type VM --status Failed \
     --query "[?properties.entityFriendlyName=='{vm_name}'].{job:name,time:properties.startTime,error:properties.errorDetails[0].errorCode}" \
     --output table
   ```

## Remediation Commands

```bash
# Retry the backup job manually
az backup protection backup-now \
  --resource-group {rg} \
  --vault-name {vault_name} \
  --container-name {container_name} \
  --item-name {vm_name} \
  --retain-until $(date -u -d '+30 days' +%Y-%m-%dT%H:%M:%SZ) \
  --backup-management-type AzureIaasVM

# Remove and reinstall the backup extension
az vm extension delete --resource-group {rg} --vm-name {vm_name} \
  --name VMSnapshot
az vm extension set --resource-group {rg} --vm-name {vm_name} \
  --name VMSnapshot --publisher Microsoft.Azure.RecoveryServices \
  --version 1.0 --enable-auto-upgrade true

# Create a manual snapshot bypassing backup service (for immediate recovery point)
az snapshot create \
  --resource-group {rg} \
  --name manual-snap-$(date +%Y%m%d%H%M) \
  --source {disk_name} \
  --incremental true
```

## Rollback Procedure

Failed snapshot operations do not affect the source disk. Retry the backup after resolving the root cause. If the disk encryption set key is expired, rotate the key in Key Vault and update the disk encryption set to reference the new key version: `az disk-encryption-set update --key-url {new_key_url}`. Ensure Key Vault purge protection is enabled to prevent accidental key deletion that would make disks permanently unrecoverable.
