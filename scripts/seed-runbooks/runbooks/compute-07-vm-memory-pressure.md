---
title: "VM Memory Pressure Investigation"
domain: compute
version: "1.0"
tags: ["memory", "ram", "oom", "vm", "performance", "swap"]
---

## Symptoms

An Azure Virtual Machine experiences high memory utilization consistently above 90% of available RAM. Azure Monitor memory alerts fire, applications report out-of-memory exceptions, and the OOM killer terminates processes. Performance degrades as the OS begins heavy swap usage. In severe cases, the VM may become unresponsive or reboot due to a kernel OOM condition.

## Root Causes

1. Memory leak in an application — a long-running process allocates memory without releasing it, growing without bound.
2. Insufficient VM SKU for current workload — the memory requirements of the deployed application have grown beyond the original sizing.
3. Excessive cache consumption — a caching layer (Redis, memcached, or OS page cache) consuming all available RAM.
4. Too many concurrent processes — a thread pool or connection pool configured too large for available memory.

## Diagnostic Steps

1. Query memory utilization over time to identify trend:
   ```kql
   Perf
   | where ObjectName == "Memory" and CounterName == "Available MBytes"
   | where Computer == "{vm_name}" and TimeGenerated > ago(4h)
   | summarize AvgAvailMB=avg(CounterValue) by bin(TimeGenerated, 5m)
   | order by TimeGenerated desc
   ```
2. Identify top memory-consuming processes via run-command:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {vm_name} \
     --command-id RunShellScript \
     --scripts "ps aux --sort=-%mem | head -20"
   ```
3. Check for OOM kill events in the VM kernel log:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {vm_name} \
     --command-id RunShellScript \
     --scripts "grep -i 'oom\|out of memory\|killed process' /var/log/syslog 2>/dev/null | tail -30"
   ```
4. Check swap utilization:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {vm_name} \
     --command-id RunShellScript \
     --scripts "free -m && swapon --show"
   ```
5. Review Azure Monitor memory counter for committed bytes:
   ```kql
   InsightsMetrics
   | where Namespace == "Memory" and Name == "commitedBytesInUse"
   | where Computer == "{vm_name}" and TimeGenerated > ago(2h)
   | summarize max(Val) by bin(TimeGenerated, 5m)
   ```

## Remediation Commands

```bash
# Clear system page cache (safe — OS will reclaim as needed)
az vm run-command invoke --resource-group {rg} --name {vm_name} \
  --command-id RunShellScript \
  --scripts "sync && echo 3 > /proc/sys/vm/drop_caches"

# Restart the memory-leaking service
az vm run-command invoke --resource-group {rg} --name {vm_name} \
  --command-id RunShellScript \
  --scripts "systemctl restart {leaking_service_name}"

# Resize VM to a memory-optimized SKU
az vm deallocate --resource-group {rg} --name {vm_name}
az vm resize --resource-group {rg} --name {vm_name} --size Standard_E8s_v5
az vm start --resource-group {rg} --name {vm_name}
```

## Rollback Procedure

If the service restart caused a brief availability gap, verify service health probes recover within the SLA window. If the VM resize introduced instability (e.g., NUMA topology change affecting application behavior), resize back to the original SKU and investigate the application-level memory leak with a heap dump. Set memory-based alerting at 80% to provide earlier warning for future incidents.
