---
title: "Storage Account Failover Procedure"
domain: storage
version: "1.0"
tags: ["storage", "failover", "geo-redundant", "disaster-recovery", "GRS", "GZRS"]
---

## Symptoms

An Azure region hosting a storage account is experiencing a prolonged outage affecting all storage services. The primary endpoint for blobs, files, queues, and tables is unreachable. Applications depending on the storage account are failing. Azure Service Health confirms the regional outage. The storage account is configured with GRS or GZRS, enabling customer-initiated failover to the secondary region.

## Root Causes

1. Azure region-wide service disruption affecting the Azure Storage infrastructure.
2. Primary region data center failure (power, cooling, or network) requiring failover to the paired region.
3. Planned maintenance requiring temporary failover for testing purposes (not recommended for production data).
4. Prolonged zonal failure exceeding the platform SLA in a GZRS account.

## Diagnostic Steps

1. Confirm the storage account endpoint is unreachable:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" \
     "https://{storage_account}.blob.core.windows.net/?comp=list" || echo "UNREACHABLE"
   ```
2. Check Azure Service Health for the region:
   ```bash
   az monitor activity-log list \
     --resource-provider Microsoft.ResourceHealth \
     --start-time $(date -u -d '-4 hours' +%FT%TZ) \
     --query "[?properties.currentHealthStatus=='Degraded'].{time:eventTimestamp,title:properties.title,region:location}"
   ```
3. Check the current replication state and last sync time before failover:
   ```bash
   az storage account show \
     --resource-group {rg} --name {storage_account} \
     --query "{sku:sku.name,location:location,secondaryLocation:secondaryLocation,geoReplication:geoReplicationStats}"
   ```
4. Estimate RPO by comparing last sync time:
   ```bash
   LAST_SYNC=$(az storage account show --resource-group {rg} --name {storage_account} \
     --query "geoReplicationStats.lastSyncTime" --output tsv)
   echo "Last successful sync: $LAST_SYNC"
   echo "Data after this time will be lost on failover"
   ```
5. Verify the secondary endpoint is reachable:
   ```bash
   # RA-GRS/RA-GZRS accounts have readable secondary
   curl -s -o /dev/null -w "%{http_code}" \
     "https://{storage_account}-secondary.blob.core.windows.net/?comp=list"
   ```

## Remediation Commands

```bash
# CAUTION: Failover is permanent — GRS becomes LRS after failover
# Only proceed if primary region is confirmed unavailable

# Step 1: Validate failover prerequisites
az storage account show --resource-group {rg} --name {storage_account} \
  --query "{failoverStatus:failoverInProgress,canFailover:geoReplicationStats.canFailover}"

# Step 2: Initiate failover (non-reversible — promotes secondary to primary)
az storage account failover \
  --resource-group {rg} \
  --name {storage_account} \
  --no-wait

# Step 3: Monitor failover progress
az storage account show --resource-group {rg} --name {storage_account} \
  --query "{failoverInProgress:failoverInProgress,location:location}"

# Step 4: Re-enable geo-redundancy after failover completes
az storage account update \
  --resource-group {rg} --name {storage_account} \
  --sku Standard_GZRS
```

## Rollback Procedure

Storage account failover cannot be reversed automatically. Once complete, the account is an LRS account in the secondary region. To restore geo-redundancy, upgrade the SKU back to GRS or GZRS, which begins asynchronously replicating data to the new secondary region. The former primary region becomes the new secondary. Update all application connection strings to use the new primary endpoint URL immediately after failover completes. Document the RPO achieved (data gap between last sync and outage) in the incident post-mortem.
