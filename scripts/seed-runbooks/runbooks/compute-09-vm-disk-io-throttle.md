---
title: "VM Disk I/O Throttling"
domain: compute
version: "1.0"
tags: ["disk", "iops", "throttling", "performance", "managed-disk", "vm"]
---

## Symptoms

An Azure Virtual Machine exhibits slow disk read/write operations with latency exceeding 50ms on data disk operations. Azure Monitor disk metrics show IOPS or throughput at the maximum for the assigned SKU (hitting the provisioned IOPS cap). Application databases report slow query times. The `iostat` tool inside the VM shows await time spiking. Azure Monitor raises a disk throttling alert.

## Root Causes

1. Managed disk SKU under-provisioned — Standard HDD or Standard SSD with insufficient IOPS for the workload.
2. VM SKU uncached disk IOPS limit reached — even with a Premium SSD disk, the VM SKU itself has a per-VM disk IOPS cap.
3. Single disk hosting both OS and data workloads — database and OS writes competing for the same disk IOPS budget.
4. Write-heavy batch job hitting disk limits — scheduled ETL or backup job overwhelming the disk during business hours.

## Diagnostic Steps

1. Check disk IOPS consumption vs limits in Azure Monitor:
   ```bash
   az monitor metrics list \
     --resource {disk_resource_id} \
     --metric "Disk Read Operations/Sec" "Disk Write Operations/Sec" \
     --interval PT1M --start-time $(date -u -d '-2 hours' +%FT%TZ) \
     --output table
   ```
2. Query Log Analytics for disk throttle events:
   ```kql
   InsightsMetrics
   | where Namespace == "LogicalDisk" and Name == "Reads/sec"
   | where Computer == "{vm_name}" and TimeGenerated > ago(2h)
   | summarize max(Val) by bin(TimeGenerated, 5m), Disk=tostring(Tags.disk)
   ```
3. Compare disk SKU IOPS limit against current usage:
   ```bash
   az disk show --resource-group {rg} --name {disk_name} \
     --query "{sku:sku.name,sizeGB:diskSizeGB,iopsRW:diskIOPSReadWrite,mbpsRW:diskMBpsReadWrite}"
   ```
4. Check VM-level uncached disk IOPS limit for the VM SKU:
   ```bash
   az vm show --resource-group {rg} --name {vm_name} \
     --query "hardwareProfile.vmSize" --output tsv | \
   xargs -I{} az vm list-skus --location {region} --size {} \
     --query "[0].capabilities[?name=='UncachedDiskIOPS'].value"
   ```
5. Check if disk caching is enabled on the data disk:
   ```bash
   az vm show --resource-group {rg} --name {vm_name} \
     --query "storageProfile.dataDisks[].{lun:lun,name:name,caching:caching}"
   ```

## Remediation Commands

```bash
# Upgrade disk to Premium SSD v2 with higher IOPS
az disk update --resource-group {rg} --name {disk_name} \
  --sku PremiumV2_LRS --disk-iops-read-write 10000 --disk-mbps-read-write 400

# Enable ReadOnly caching on data disk to reduce read IOPS to physical disk
az vm disk attach --resource-group {rg} --vm-name {vm_name} \
  --disk {disk_name} --caching ReadOnly

# Resize VM to a SKU with higher uncached disk IOPS limit
az vm deallocate --resource-group {rg} --name {vm_name}
az vm resize --resource-group {rg} --name {vm_name} --size Standard_D16s_v5
az vm start --resource-group {rg} --name {vm_name}
```

## Rollback Procedure

Disk SKU upgrades are not immediately reversible — downgrading from Premium SSD v2 to Standard SSD requires detaching the disk and creating a new disk from a snapshot. Before upgrading, create a snapshot: `az snapshot create --resource-group {rg} --source {disk_name} --name snap-prediskupgrade`. If the VM resize worsened the situation (e.g., cost increase not justified), resize back and investigate disk caching options as a free alternative.
