---
title: "VM Boot Failure Diagnostics"
domain: compute
version: "1.0"
tags: ["vm", "boot", "diagnostics", "os-disk", "grub", "startup"]
---

## Symptoms

An Azure Virtual Machine fails to boot after a restart, OS update, or disk resize. The VM power state shows "running" but no SSH or RDP connections are accepted. Boot diagnostics screenshot shows a GRUB prompt, kernel panic screen, Windows recovery environment, or a blank black screen with cursor. The VM agent remains in "Not Ready" state.

## Root Causes

1. GRUB misconfiguration after a kernel update that changed the default boot entry.
2. `/etc/fstab` entry referencing a disk UUID that no longer matches after disk detach/reattach.
3. Windows failed update leaving the system in a boot loop with automatic repair.
4. OS disk corruption after an ungraceful shutdown during a write-heavy operation.

## Diagnostic Steps

1. Retrieve and review the boot diagnostics screenshot URI:
   ```bash
   az vm boot-diagnostics get-boot-log-uris \
     --resource-group {rg} --name {vm_name} \
     --query "serialConsoleLogBlobUri" --output tsv
   ```
2. Read the last 500 lines of the serial log to identify the last error before halt:
   ```bash
   az vm boot-diagnostics get-boot-log \
     --resource-group {rg} --name {vm_name} | tail -100
   ```
3. Check if the OS disk has any known health alerts:
   ```bash
   az disk show --resource-group {rg} --name {os_disk_name} \
     --query "{state:diskState,health:managedDiskId}"
   az resource health get-availability-status \
     --resource-group {rg} --name {os_disk_name} --resource-type Microsoft.Compute/disks
   ```
4. Use Azure VM Repair extension to create a repair VM and examine the disk offline:
   ```bash
   az vm repair create --resource-group {rg} --name {vm_name} \
     --repair-username repairadmin --repair-password {temp_password} \
     --verbose
   ```
5. Inside the repair VM, check `/etc/fstab` and disk UUIDs:
   ```bash
   blkid
   cat /mnt/troubleshootingdisk/etc/fstab
   ```

## Remediation Commands

```bash
# Fix fstab UUID mismatch on repair VM
# Replace old UUID with correct value identified from blkid
sed -i 's/UUID=OLD_UUID/UUID=NEW_UUID/' /mnt/troubleshootingdisk/etc/fstab

# Restore GRUB on repair VM
chroot /mnt/troubleshootingdisk
grub2-install /dev/sda
grub2-mkconfig -o /boot/grub2/grub.cfg
exit

# Restore the repaired OS disk to the original VM
az vm repair restore --resource-group {rg} --name {vm_name} --verbose

# Start the VM after restore
az vm start --resource-group {rg} --name {vm_name}
```

## Rollback Procedure

If the repair worsens the situation, swap back the original OS disk from the snapshot taken before the failed update: `az snapshot create --resource-group {rg} --source {os_disk_name} --name snap-prerepair`. Create a new managed disk from the pre-repair snapshot and swap it into the VM. Document the root cause in the change management system and flag the offending OS update for rollback in all affected VMs.
