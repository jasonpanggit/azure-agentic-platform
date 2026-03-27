---
title: "Storage Account Access Key Rotation"
domain: storage
version: "1.0"
tags: ["storage", "access-key", "rotation", "security", "key-vault", "credentials"]
---

## Symptoms

Security team or Defender for Cloud raises an alert that a storage account access key has not been rotated in over 90 days. Alternatively, a key has been accidentally exposed in logs, a Git repository, or an error message. The compliance team requires immediate key rotation with zero downtime for applications using the storage account.

## Root Causes

1. Key rotation cadence not enforced — no automated rotation or alert threshold configured.
2. Key exposed in application logs via a verbose logging configuration capturing HTTP headers including the Authorization header.
3. Shared access signature (SAS) tokens derived from the primary key are now potentially compromised.
4. Key stored in plaintext configuration file committed to a source code repository.

## Diagnostic Steps

1. Check current key rotation age and usage:
   ```bash
   az storage account show \
     --resource-group {rg} --name {storage_account} \
     --query "{keyExpiryPeriod:keyPolicy.keyExpirationPeriodInDays,sasPolicy:sasPolicy}"
   ```
2. Identify all services and connection strings using this storage account:
   ```bash
   # Check Key Vault for any stored connection strings
   az keyvault secret list --vault-name {kv_name} \
     --query "[?contains(name,'{storage_account}')].name" --output tsv
   ```
3. Check if Defender for Cloud has existing alerts for this storage account:
   ```bash
   az security alert list --resource-group {rg} \
     --query "[?contains(resourceId,'{storage_account}')].{alert:alertDisplayName,severity:severity,time:reportedTimeUtc}" \
     --output table
   ```
4. Audit recent key usage via storage analytics logs:
   ```kql
   StorageBlobLogs
   | where AccountName == "{storage_account}"
   | where AuthenticationType == "AccountKey"
   | where TimeGenerated > ago(7d)
   | summarize count() by CallerIpAddress, bin(TimeGenerated, 1d)
   ```
5. Identify application settings referencing the storage key:
   ```bash
   az functionapp config appsettings list --resource-group {rg} --name {function_app} \
     --query "[?contains(value,'{storage_account}')].{name:name}"
   ```

## Remediation Commands

```bash
# Step 1: Rotate secondary key first (roll secondary → update apps → roll primary)
az storage account keys renew --resource-group {rg} --account-name {storage_account} --key secondary

# Step 2: Update all application connection strings to use the new secondary key
NEW_KEY=$(az storage account keys list --resource-group {rg} --account-name {storage_account} \
  --query "[?keyName=='key2'].value" --output tsv)

# Step 3: Update Key Vault secret with new connection string
az keyvault secret set --vault-name {kv_name} \
  --name {secret_name} \
  --value "DefaultEndpointsProtocol=https;AccountName={storage_account};AccountKey=$NEW_KEY;EndpointSuffix=core.windows.net"

# Step 4: After confirming apps use secondary key, rotate primary
az storage account keys renew --resource-group {rg} --account-name {storage_account} --key primary

# Step 5: Enforce key expiry policy
az storage account update --resource-group {rg} --name {storage_account} \
  --key-exp-days 90
```

## Rollback Procedure

Key rotation is irreversible — once a key is regenerated, the old key value cannot be recovered. If applications fail after the secondary key rotation, the primary key (not yet rotated) can still be used as a fallback while the connection strings are updated. Maintain a rollback window of 15 minutes between rotating secondary and primary keys to ensure all running application instances have picked up the new connection string before the primary is invalidated.
