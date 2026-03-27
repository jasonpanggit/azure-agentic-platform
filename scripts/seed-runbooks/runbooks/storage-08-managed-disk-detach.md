---
title: "Managed Disk Detach Failure"
domain: storage
version: "1.0"
tags: ["managed-disk", "detach", "vm", "storage", "disk-state"]
---

## Symptoms

An attempt to detach a managed data disk from an Azure VM fails with an error such as "ConflictingOperation" or "DiskBeingUsedByAnotherOperation". The Azure portal shows the disk as "Attached" but the VM does not have the disk listed in its storage profile. Operations to update the VM configuration block on the stuck disk state. The disk remains in an inconsistent state preventing reuse or deletion.

## Root Causes

1. Active I/O on the disk — the OS is still writing to the disk at the time of the detach API call, causing a conflict.
2. Azure Cache flush in progress — when disk caching is enabled, Azure is flushing the write cache before allowing detachment.
3. Orphaned disk attachment — the VM was force-deallocated with a disk attached, leaving the disk's owner reference stale.
4. Azure platform update in progress — the host node is undergoing maintenance that prevents VM configuration changes.

## Diagnostic Steps

1. Check the disk's current state and attachment status:
   ```bash
   az disk show --resource-group {rg} --name {disk_name} \
     --query "{state:diskState,managedBy:managedBy,osType:osType,sizeGB:diskSizeGB}"
   ```
2. Check if the VM references the disk in its configuration:
   ```bash
   az vm show --resource-group {rg} --name {vm_name} \
     --query "storageProfile.dataDisks[?name=='{disk_name}'].{lun:lun,name:name,caching:caching}"
   ```
3. Check VM power state and provisioning state:
   ```bash
   az vm get-instance-view --resource-group {rg} --name {vm_name} \
     --query "{powerState:instanceView.statuses[1].displayStatus,provState:instanceView.statuses[0].displayStatus}"
   ```
4. Check for long-running operations on the VM:
   ```bash
   az monitor activity-log list \
     --resource-id {vm_resource_id} \
     --start-time $(date -u -d '-1 hour' +%FT%TZ) \
     --query "[?status.value=='Started'].{op:operationName.value,time:eventTimestamp}" \
     --output table
   ```
5. Check the disk's resource lock:
   ```bash
   az lock list --resource-group {rg} \
     --query "[?resourceName=='{disk_name}']"
   ```

## Remediation Commands

```bash
# Unmount disk inside the VM before detaching (Linux)
az vm run-command invoke --resource-group {rg} --name {vm_name} \
  --command-id RunShellScript \
  --scripts "umount /dev/sdc && sync"

# Detach disk from VM
az vm disk detach --resource-group {rg} --vm-name {vm_name} --name {disk_name}

# Force detach if normal detach fails (use --force-detach for stuck disks)
az disk update --resource-group {rg} --name {disk_name} \
  --disk-state Unattached

# If disk still shows attached to deallocated VM, update VM storage profile directly
az vm update --resource-group {rg} --name {vm_name} \
  --set storageProfile.dataDisks=[]
```

## Rollback Procedure

If the forced detach causes data inconsistency, restore the disk from the most recent snapshot before re-attaching to another VM. Ensure the file system is checked and repaired: after attaching to a repair VM, run `fsck /dev/sdc` (Linux) before mounting to verify integrity. Document the disk's LUN, mounting configuration, and filesystem type in the CMDB before detaching to facilitate clean re-attachment.
