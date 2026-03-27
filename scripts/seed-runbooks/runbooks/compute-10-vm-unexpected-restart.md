---
title: "VM Unexpected Restart Analysis"
domain: compute
version: "1.0"
tags: ["vm", "restart", "crash", "root-cause", "activity-log", "watchdog"]
---

## Symptoms

An Azure Virtual Machine reboots unexpectedly during normal operation without any operator-initiated restart command. Application logs show a hard cutoff at the reboot time. Azure Monitor shows a gap in agent metrics. Post-reboot, the VM comes back healthy but the root cause is unknown. Stakeholders need a post-incident report explaining the cause.

## Root Causes

1. Azure platform-initiated maintenance requiring a reboot — scheduled maintenance event that was not acknowledged for live migration.
2. Guest OS watchdog timeout — the Linux watchdog daemon or Windows watchdog timer triggered a forced reboot due to a kernel hang.
3. Memory corruption causing a kernel panic with a forced reboot-on-panic setting.
4. Operator-initiated restart from another team or automation script not tracked in the incident system.

## Diagnostic Steps

1. Check Azure Activity Log for any platform or operator-initiated restart:
   ```bash
   az monitor activity-log list \
     --resource-id {vm_resource_id} \
     --start-time $(date -u -d '-24 hours' +%FT%TZ) \
     --query "[?operationName.value=='Microsoft.Compute/virtualMachines/restart/action' || operationName.value=='Microsoft.Compute/virtualMachines/deallocate/action'].{time:eventTimestamp,caller:caller,status:status.value,reason:description}"
   ```
2. Check for Azure-initiated maintenance events:
   ```bash
   az vm get-instance-view --resource-group {rg} --name {vm_name} \
     --query "instanceView.maintenanceRedeployStatus"
   ```
3. Check Azure Service Health for any platform incidents at the restart time:
   ```bash
   az monitor activity-log list \
     --resource-provider Microsoft.ResourceHealth \
     --start-time $(date -u -d '-24 hours' +%FT%TZ) \
     --query "[?contains(resourceId,'{subscription_id}')].{time:eventTimestamp,title:properties.title,status:properties.currentHealthStatus}"
   ```
4. Review guest OS event logs for crash dump or watchdog event:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {vm_name} \
     --command-id RunShellScript \
     --scripts "last reboot | head -10 && journalctl -k --since '-24h' | grep -i 'panic\|watchdog\|reboot' | tail -30"
   ```
5. Check boot diagnostics for crash screen at reboot time:
   ```bash
   az vm boot-diagnostics get-boot-log --resource-group {rg} --name {vm_name} | grep -A5 -B5 "panic\|BSOD\|watchdog"
   ```

## Remediation Commands

```bash
# Enable crash dump collection for future root cause analysis
az vm run-command invoke --resource-group {rg} --name {vm_name} \
  --command-id RunShellScript \
  --scripts "echo 'kernel.panic=10' >> /etc/sysctl.conf && sysctl -p"

# Enable scheduled maintenance notifications to prevent surprise reboots
az maintenance assignment create \
  --resource-group {rg} \
  --resource-name {vm_name} \
  --resource-type virtualMachines \
  --provider-name Microsoft.Compute \
  --maintenance-configuration-id {maintenance_config_id}

# Enable Azure Update Manager for controlled patching
az maintenance configuration create \
  --resource-group {rg} --name vm-maintenance-window \
  --maintenance-scope InGuestPatch \
  --recur-every "Week Saturday Sunday" --duration 02:00 --time-zone UTC
```

## Rollback Procedure

Unexpected reboots themselves are typically self-resolving once the VM comes back online. If the VM comes back with corrupted data due to the unclean shutdown, restore the relevant data volumes from the Recovery Services Vault backup taken before the incident window. File an Azure support ticket if the restart was platform-initiated to get the official root cause analysis and confirm SLA credits if applicable.
