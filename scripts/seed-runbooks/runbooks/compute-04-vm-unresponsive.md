---
title: "VM Unresponsive Recovery"
domain: compute
version: "1.0"
tags: ["vm", "unresponsive", "recovery", "reboot", "serial-console"]
---

## Symptoms

An Azure Virtual Machine stops responding to SSH, RDP, or application-level health probes. Azure Monitor shows the VM as running (power state: running) but the guest OS is unresponsive. Network connectivity tests from other VMs in the VNet time out. The Azure Agent (WA Agent or Windows Guest Agent) heartbeat has gone silent.

## Root Causes

1. Kernel panic or Windows BSOD — guest OS crashed but the hypervisor kept the VM in a "running" state.
2. Full disk causing systemd or Windows services to hang at boot.
3. OOM killer terminated critical system processes (kernel OOM condition).
4. Network stack freeze due to a driver bug or kernel regression after a kernel update.

## Diagnostic Steps

1. Check VM power state and agent health via Azure Resource Manager:
   ```bash
   az vm get-instance-view --resource-group {rg} --name {vm_name} \
     --query "{powerState:instanceView.statuses[1].displayStatus,agentStatus:instanceView.vmAgent.statuses[0].displayStatus}"
   ```
2. Check boot diagnostics screenshot for kernel panic or BSOD:
   ```bash
   az vm boot-diagnostics get-boot-log --resource-group {rg} --name {vm_name}
   # Or retrieve screenshot URI:
   az vm boot-diagnostics get-boot-log-uris --resource-group {rg} --name {vm_name}
   ```
3. Review serial console output for last kernel messages before hang:
   Navigate to VM → Boot Diagnostics → Serial Console in the Azure Portal, or use the REST API to capture the serial log.
4. Check Azure Monitor for OOM events in guest metrics:
   ```kql
   Syslog
   | where Computer == "{vm_name}" and SeverityLevel == "err"
   | where SyslogMessage contains "OOM" or SyslogMessage contains "Out of memory"
   | where TimeGenerated > ago(4h)
   | order by TimeGenerated desc
   ```
5. Check the VM activity log for any platform-initiated reboot or maintenance events:
   ```bash
   az monitor activity-log list --resource-id {vm_resource_id} \
     --start-time $(date -u -d '-6 hours' +%FT%TZ) \
     --query "[].{time:eventTimestamp,op:operationName.localizedValue,status:status.value}"
   ```

## Remediation Commands

```bash
# Step 1: Attempt a graceful restart
az vm restart --resource-group {rg} --name {vm_name}

# Step 2: If restart fails, power off and back on
az vm stop --resource-group {rg} --name {vm_name}
az vm start --resource-group {rg} --name {vm_name}

# Step 3: If VM is stuck in a bad state, redeploy to a new host node
az vm redeploy --resource-group {rg} --name {vm_name}

# Step 4: Enable boot diagnostics if not already enabled
az vm boot-diagnostics enable --resource-group {rg} --name {vm_name} \
  --storage "https://{storage_account}.blob.core.windows.net/"
```

## Rollback Procedure

If the restart does not resolve the issue and the VM remains unresponsive, attach the OS disk to a repair VM to investigate offline: `az vm repair create --resource-group {rg} --name {vm_name} --repair-username adminuser`. After diagnostics are complete, swap the repaired OS disk back and start the VM. If the issue is kernel-related, restore from the most recent Recovery Services Vault backup to a known-good state.
