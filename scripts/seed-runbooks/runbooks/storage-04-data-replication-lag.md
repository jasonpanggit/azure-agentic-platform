---
title: "Storage Replication Lag Investigation"
domain: storage
version: "1.0"
tags: ["storage", "replication", "geo-redundant", "GRS", "GZRS", "lag"]
---

## Symptoms

An Azure Storage account configured with Geo-Redundant Storage (GRS) or GZRS shows elevated replication lag. During a failover test or actual regional failure, data in the secondary region is behind the primary by more than the expected recovery point objective. Applications reading from the secondary endpoint receive stale data. Azure Monitor shows the `GeoReplicationStatus` metric as "Unavailable" or "Bootstrap".

## Root Causes

1. High write throughput on primary exceeding the geo-replication bandwidth capacity.
2. Azure platform replication issue affecting the specific storage pair region.
3. Object-level conflicts causing replication retries (unlikely but possible with certain object types).
4. Storage account recently upgraded from LRS to GRS — initial replication of all existing data is in progress ("Bootstrap" state).

## Diagnostic Steps

1. Check geo-replication status and lag:
   ```bash
   az storage account show \
     --resource-group {rg} --name {storage_account} \
     --query "{sku:sku.name,geoReplication:geoReplicationStats}" --output json
   ```
2. Query the last sync time for the secondary region:
   ```bash
   az storage account show \
     --resource-group {rg} --name {storage_account} \
     --query "geoReplicationStats.lastSyncTime"
   ```
3. Check blob service replication metrics:
   ```bash
   az monitor metrics list \
     --resource {storage_account_resource_id} \
     --metric "GeoReplication" \
     --interval PT5M --start-time $(date -u -d '-2 hours' +%FT%TZ)
   ```
4. Check Azure Service Health for geo-replication issues in the region pair:
   ```bash
   az monitor activity-log list \
     --resource-provider Microsoft.Storage \
     --start-time $(date -u -d '-24 hours' +%FT%TZ) \
     --query "[?properties.eventCategory=='ServiceHealth'].{time:eventTimestamp,title:properties.title,status:properties.currentHealthStatus}"
   ```
5. Calculate the actual data loss window from last sync time:
   ```bash
   LAST_SYNC=$(az storage account show --resource-group {rg} --name {storage_account} \
     --query "geoReplicationStats.lastSyncTime" --output tsv)
   NOW=$(date -u +%FT%TZ)
   echo "Last sync: $LAST_SYNC | Current time: $NOW"
   ```

## Remediation Commands

```bash
# Initiate account failover to secondary region (DESTRUCTIVE — use only in disaster)
# This promotes the secondary to primary and GRS becomes LRS
az storage account failover --resource-group {rg} --name {storage_account} --no-wait

# Change to GZRS for better replication consistency if on GRS
az storage account update \
  --resource-group {rg} --name {storage_account} --sku Standard_GZRS

# Reduce write throughput by implementing client-side rate limiting
# Increase replication priority for critical containers (use RA-GZRS for readable secondary)
az storage account update \
  --resource-group {rg} --name {storage_account} --sku Standard_RAGZRS

# Monitor replication lag after change
az monitor metrics list \
  --resource {storage_account_resource_id} \
  --metric "GeoReplication" --interval PT1M \
  --start-time $(date -u -d '-30 minutes' +%FT%TZ)
```

## Rollback Procedure

Account failover is permanent — once initiated, the account becomes LRS in the secondary region and cannot be automatically failed back. Before initiating failover, confirm the primary region is truly unavailable by checking Azure Service Health. After failover, re-enable geo-redundancy by upgrading back to GRS or GZRS, which will begin replicating data to the new secondary region. Document RPO/RTO achieved in the incident report for compliance purposes.
