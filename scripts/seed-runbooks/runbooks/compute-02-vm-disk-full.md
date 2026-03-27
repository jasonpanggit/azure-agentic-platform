---
title: "VM Disk Full Remediation"
domain: compute
version: "1.0"
tags: ["disk", "storage", "vm", "capacity", "os-disk"]
---

## Symptoms

An Azure Virtual Machine raises a Sev1 alert when OS disk or data disk utilization exceeds 95%. Application writes fail with "No space left on device" errors. Log rotation stops, databases refuse new writes, and services may crash with disk-full errors. The VM remains reachable but in a degraded state.

## Root Causes

1. Log files accumulating without rotation — misconfigured logrotate or a verbose application flooding `/var/log` or `C:\Windows\Logs`.
2. Temporary files not cleaned up — build artifacts, Docker layer cache, or temp upload directories consuming untracked space.
3. Undersized OS disk at provisioning — 30 GB default OS disk insufficient for long-running workloads.
4. Database transaction logs growing unbounded — SQL Server or PostgreSQL WAL not archived or truncated.

## Diagnostic Steps

1. Check disk utilization across all attached disks from Azure Monitor:
   ```kql
   InsightsMetrics
   | where Namespace == "LogicalDisk" and Name == "FreeSpacePercentage"
   | where Computer == "{vm_name}" and TimeGenerated > ago(30m)
   | summarize min(Val) by Disk=tostring(Tags.disk), Computer
   | order by min_Val asc
   ```
2. Identify the largest directories inside the VM via the Run Command extension:
   ```bash
   az vm run-command invoke \
     --resource-group {rg} \
     --name {vm_name} \
     --command-id RunShellScript \
     --scripts "du -sh /* 2>/dev/null | sort -rh | head -20"
   ```
3. Check the managed disk size and current allocation in the portal:
   ```bash
   az disk show --resource-group {rg} --name {disk_name} \
     --query "{sizeGB:diskSizeGB,tier:sku.name,state:diskState}"
   ```
4. Look for large log files to remove safely:
   ```bash
   az vm run-command invoke \
     --resource-group {rg} \
     --name {vm_name} \
     --command-id RunShellScript \
     --scripts "find /var/log -name '*.log' -size +100M -ls 2>/dev/null"
   ```
5. Verify disk IOPS are not also throttled during the incident:
   ```bash
   az monitor metrics list --resource {disk_resource_id} \
     --metric "Disk Read Bytes/sec" "Disk Write Bytes/sec" \
     --interval PT1M --start-time $(date -u -d '-1 hour' +%FT%TZ)
   ```

## Remediation Commands

```bash
# Option 1: Expand the managed disk online (no VM downtime for data disks)
az disk update --resource-group {rg} --name {disk_name} --size-gb 256

# Option 2: Clean up old journal logs via run-command
az vm run-command invoke \
  --resource-group {rg} --name {vm_name} \
  --command-id RunShellScript \
  --scripts "journalctl --vacuum-size=500M && apt-get clean"

# Option 3: Deallocate and resize OS disk (requires downtime)
az vm deallocate --resource-group {rg} --name {vm_name}
az disk update --resource-group {rg} --name {os_disk_name} --size-gb 128
az vm start --resource-group {rg} --name {vm_name}
```

## Rollback Procedure

Disk expansion cannot be reversed directly — shrinking an OS disk requires creating a new disk from a snapshot. Before expanding, take a snapshot: `az snapshot create --resource-group {rg} --source {disk_name} --name snap-pre-expand-$(date +%Y%m%d)`. If log cleanup removed critical files, restore from the snapshot or Recovery Services Vault backup taken before the change.
