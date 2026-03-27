---
title: "VM High CPU Investigation"
domain: compute
version: "1.0"
tags: ["cpu", "performance", "vm", "monitoring", "azure-monitor"]
---

## Symptoms

Sustained CPU utilization above 90% on an Azure Virtual Machine triggers a Sev1 Azure Monitor alert. Users report application slowness or timeouts, and automated health probes may start failing. The VM remains reachable via SSH or RDP but response times are severely degraded.

## Root Causes

1. Runaway process consuming excessive CPU cycles — a hung or looping application thread that fails to yield.
2. Under-provisioned VM SKU for the current workload — the VM was correctly sized for peak load at deployment but workload has grown.
3. Cryptomining malware or unauthorized compute workload introduced via a compromised package or container image.
4. Inefficient query or batch job hitting the VM's CPU hard during a scheduled window.

## Diagnostic Steps

1. Query Azure Monitor metrics for the VM CPU percentage over the last 2 hours to confirm the spike pattern:
   ```kql
   Perf
   | where ObjectName == "Processor" and CounterName == "% Processor Time"
   | where Computer == "{vm_name}"
   | where TimeGenerated > ago(2h)
   | summarize avg(CounterValue) by bin(TimeGenerated, 5m), Computer
   | order by TimeGenerated desc
   ```
2. Check the top CPU-consuming processes inside the VM using Azure Monitor agent performance data:
   ```kql
   InsightsMetrics
   | where Name == "utilization" and Namespace == "Processor"
   | where Computer == "{vm_name}" and TimeGenerated > ago(30m)
   | top 10 by Val desc
   ```
3. Review the VM activity log for any recent deployments, extensions, or scale events:
   ```bash
   az monitor activity-log list --resource-id {vm_resource_id} --start-time $(date -u -d '-2 hours' +%FT%TZ) --query "[].{time:eventTimestamp,op:operationName.value,status:status.value}"
   ```
4. Check if Defender for Cloud has flagged any anomalous CPU activity or process alerts:
   ```bash
   az security alert list --resource-group {rg} --query "[?contains(alertDisplayName,'CPU')]"
   ```
5. Verify the VM SKU limits via the Azure portal or CLI and compare against current utilization:
   ```bash
   az vm show --resource-group {rg} --name {vm_name} --query "hardwareProfile.vmSize"
   az vm list-vm-resize-options --resource-group {rg} --name {vm_name} --output table
   ```

## Remediation Commands

```bash
# Option 1: Restart the VM to clear runaway process (short-term)
az vm restart --resource-group {rg} --name {vm_name}

# Option 2: Resize to a larger SKU if workload has grown
az vm deallocate --resource-group {rg} --name {vm_name}
az vm resize --resource-group {rg} --name {vm_name} --size Standard_D4s_v5
az vm start --resource-group {rg} --name {vm_name}

# Option 3: Set a CPU-based autoscale rule on the VMSS (if part of scale set)
az monitor autoscale rule create \
  --autoscale-name {autoscale_name} \
  --resource-group {rg} \
  --scale out 1 \
  --condition "Percentage CPU > 85 avg 5m"
```

## Rollback Procedure

If resizing the VM caused application instability, reverse the SKU change by deallocating and resizing back to the original SKU. If restart caused a service outage, restore from the latest Recovery Services Vault snapshot taken before the incident. Document the exact time of the restart in the incident timeline for SLA reporting.
