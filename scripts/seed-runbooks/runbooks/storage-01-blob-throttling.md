---
title: "Blob Storage Throttling Investigation"
domain: storage
version: "1.0"
tags: ["blob", "throttling", "storage", "503", "iops", "throughput"]
---

## Symptoms

Applications connecting to Azure Blob Storage receive intermittent HTTP 503 (Server Busy) or 429 (Too Many Requests) responses. Throughput drops significantly below expected rates. Upload or download operations fail with retry exhaustion. Azure Monitor storage metrics show requests exceeding the egress or IOPS limits for the storage account tier.

## Root Causes

1. Storage account throughput limit reached — Standard LRS has a default 60 Gbps egress limit; single-blob operations are bottlenecked.
2. Hot partition — all requests targeting the same partition key (blob name prefix causing a single partition to handle all load).
3. Too many concurrent connections to a single blob — large number of parallel small reads hitting the same blob.
4. Shared storage account used by too many services — multiple high-throughput workloads on the same account competing for the same IOPS budget.

## Diagnostic Steps

1. Check storage account metrics for throttling:
   ```bash
   az monitor metrics list \
     --resource {storage_account_resource_id} \
     --metric "Transactions" "SuccessServerLatency" "Availability" \
     --filter "ResponseType eq 'ServerBusyError'" \
     --interval PT1M --start-time $(date -u -d '-2 hours' +%FT%TZ)
   ```
2. Query Log Analytics for 503 responses by blob name pattern:
   ```kql
   StorageBlobLogs
   | where AccountName == "{storage_account}"
   | where StatusCode == 503 or StatusCode == 429
   | where TimeGenerated > ago(2h)
   | summarize ErrorCount=count() by ObjectKey, Uri, OperationName
   | order by ErrorCount desc | take 20
   ```
3. Check egress throughput vs limit:
   ```bash
   az monitor metrics list \
     --resource {storage_account_resource_id} \
     --metric "Egress" \
     --interval PT1M --start-time $(date -u -d '-1 hour' +%FT%TZ) \
     --output table
   ```
4. Analyze request patterns by client IP:
   ```kql
   StorageBlobLogs
   | where AccountName == "{storage_account}" and TimeGenerated > ago(1h)
   | summarize RequestCount=count() by CallerIpAddress, OperationName
   | order by RequestCount desc | take 20
   ```
5. Check if Premium Block Blob storage tier would resolve the issue:
   ```bash
   az storage account show --resource-group {rg} --name {storage_account} \
     --query "{sku:sku.name,kind:kind,accessTier:accessTier}"
   ```

## Remediation Commands

```bash
# Enable blob access tier lifecycle to move cold data to Archive tier
az storage account management-policy create \
  --account-name {storage_account} \
  --resource-group {rg} \
  --policy @lifecycle-policy.json

# Upgrade to Premium Block Blob for higher IOPS (requires new account + data migration)
az storage account create \
  --resource-group {rg} \
  --name {new_premium_account} \
  --kind BlockBlobStorage \
  --sku Premium_LRS \
  --location {region}

# Add retry policy with exponential backoff in the application (SDK approach)
# Set soft delete to protect against accidental deletion during migration
az storage blob service-properties delete-policy update \
  --account-name {storage_account} --enable true --days-retained 7

# Distribute load across multiple storage accounts using consistent hashing
# (Documented pattern — requires application code change)
```

## Rollback Procedure

If the lifecycle policy moved data to a colder tier prematurely, rehydrate blobs from Archive to Hot tier with `az storage blob set-tier --tier Hot`. Note that rehydration can take up to 15 hours for Archive to Hot. The original storage account remains unaffected by Premium account creation — data migration can be paused at any point using AzCopy with `--check-md5`. Monitor 503 error rate continuously during migration.
