---
title: "Azure Backup Job Failure"
domain: sre
version: "1.0"
tags: ["sre", "backup", "recovery-services", "azure-backup", "vault", "restore"]
---

## Symptoms

Azure Backup jobs for VMs, databases, or file shares fail with error codes. The Recovery Services Vault dashboard shows backup jobs in "Failed" state. Azure Monitor backup failure alerts fire. The backup SLA is at risk if the failure persists and leaves recovery point gaps. The team must investigate and resolve the backup failure to restore data protection coverage.

## Root Causes

1. VM agent not installed or not responding — the Azure Backup extension depends on the VM agent being healthy.
2. Network connectivity issue — the backup extension cannot reach the Recovery Services Vault endpoint.
3. Insufficient storage in the Recovery Services Vault — vault storage quota exceeded.
4. Backup extension conflict — another backup solution or extension is conflicting with the Azure Backup extension.

## Diagnostic Steps

1. Check recent backup job failures:
   ```bash
   az backup job list \
     --resource-group {rg} --vault-name {vault_name} \
     --status Failed \
     --query "[].{name:name,workload:properties.workloadType,error:properties.errorDetails[0].errorCode,time:properties.startTime}" \
     --output table
   ```
2. Get detailed error information for a specific failed job:
   ```bash
   az backup job show \
     --resource-group {rg} --vault-name {vault_name} \
     --name {job_id} \
     --query "{status:properties.status,errorCode:properties.errorDetails[0].errorCode,errorMessage:properties.errorDetails[0].errorMessage,recommendations:properties.errorDetails[0].recommendations}"
   ```
3. Check backup protection status for a VM:
   ```bash
   az backup protection check-vm \
     --resource-group {rg} --vm {vm_name} \
     --vault-name {vault_name}
   az backup item list \
     --resource-group {rg} --vault-name {vault_name} \
     --backup-management-type AzureIaasVM \
     --query "[?contains(properties.virtualMachineId,'{vm_name}')].{item:name,status:properties.protectionStatus,lastBackup:properties.lastBackupTime}" \
     --output table
   ```
4. Check VM agent status:
   ```bash
   az vm get-instance-view --resource-group {rg} --name {vm_name} \
     --query "instanceView.vmAgent.{status:statuses[0].displayStatus,version:vmAgentVersion}"
   ```
5. Check vault storage consumption:
   ```bash
   az monitor metrics list \
     --resource {vault_resource_id} \
     --metric "BackupStorageUsed" \
     --interval PT1H --start-time $(date -u -d '-7 days' +%FT%TZ)
   ```

## Remediation Commands

```bash
# Retry the failed backup job
az backup protection backup-now \
  --resource-group {rg} --vault-name {vault_name} \
  --container-name {container_name} \
  --item-name {vm_name} \
  --retain-until $(date -u -d '+30 days' +%Y-%m-%dT%H:%M:%SZ) \
  --backup-management-type AzureIaasVM

# Re-register the VM with the vault
az backup container unregister \
  --resource-group {rg} --vault-name {vault_name} \
  --container-name {container_name} --backup-management-type AzureIaasVM

az backup container register \
  --resource-group {rg} --vault-name {vault_name} \
  --vm {vm_resource_id} --workload-type VM

# Enable backup on a VM that is not protected
az backup protection enable-for-vm \
  --resource-group {rg} --vault-name {vault_name} \
  --vm {vm_name} --policy-name {backup_policy_name}

# Check and update the backup policy retention to fix quota issues
az backup policy set --resource-group {rg} --vault-name {vault_name} \
  --name {policy_name} --policy @updated-backup-policy.json
```

## Rollback Procedure

Backup job retries are non-destructive. If re-registration of the VM container with the vault created duplicate items, delete the stale item: `az backup item delete --resource-group {rg} --vault-name {vault_name} --container-name {old_container}`. After resolving the backup failure, verify a successful backup completes and a new recovery point is created. Confirm the recovery point is listed in: `az backup recoverypoint list --resource-group {rg} --vault-name {vault_name} --container-name {container} --item-name {vm_name}`.
