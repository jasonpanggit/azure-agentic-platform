---
title: "Service Principal Credential Expiry"
domain: security
version: "1.0"
tags: ["service-principal", "credentials", "expiry", "certificate", "rotation", "entra-id"]
---

## Symptoms

An application or automated pipeline fails to authenticate to Azure services. Error messages include "ClientSecretCredentialAuthenticationFailure" or "AADSTS7000222: The provided client secret keys for app '{appId}' are expired." Azure Monitor shows authentication failure spikes. Terraform, CI/CD pipelines, or microservices start receiving 401 Unauthorized responses from Azure APIs.

## Root Causes

1. Service principal client secret expired — the secret was created with a 1-year or 2-year expiry and the expiry was not tracked.
2. Service principal certificate expired — a certificate-based credential used for authentication exceeded its validity period.
3. Service principal deleted and recreated — the new SP has different credentials and all applications using the old credentials fail.
4. Credential rotation policy enforced by Entra ID — organization-wide policy set a maximum secret lifetime that triggered expiry on previously long-lived secrets.

## Diagnostic Steps

1. List all credentials and their expiry dates for the service principal:
   ```bash
   az ad sp credential list --id {sp_id} \
     --query "[].{customKeyId:customKeyIdentifier,startDate:startDate,endDate:endDate,type:type}" \
     --output table
   ```
2. Find all expired or soon-to-expire SPs across the tenant:
   ```bash
   THRESHOLD=$(date -u -d '+30 days' +%Y-%m-%dT%H:%M:%SZ)
   az ad app list --all \
     --query "[?passwordCredentials[?endDateTime<'$THRESHOLD']].{appId:appId,displayName:displayName,expiry:passwordCredentials[0].endDateTime}" \
     --output table
   ```
3. Check which applications are using this SP:
   ```bash
   az ad app show --id {app_id} \
     --query "{displayName:displayName,signInAudience:signInAudience,identifierUris:identifierUris}"
   ```
4. Check Azure Monitor for the authentication failure timeline:
   ```kql
   SigninLogs
   | where AppId == "{app_id}"
   | where ResultType != 0
   | where TimeGenerated > ago(48h)
   | project TimeGenerated, ResultType, ResultDescription, ResourceDisplayName
   | order by TimeGenerated desc
   ```
5. Verify the service principal has the required RBAC roles:
   ```bash
   az role assignment list --assignee {sp_id} \
     --query "[].{scope:scope,role:roleDefinitionName}" --output table
   ```

## Remediation Commands

```bash
# Add a new client secret (previous ones remain valid until removed)
NEW_SECRET=$(az ad app credential reset --id {app_id} --append \
  --years 1 --display-name "rotated-$(date +%Y%m)" \
  --query "password" --output tsv)

# Store new secret in Key Vault
az keyvault secret set \
  --vault-name {kv_name} \
  --name "{sp_name}-client-secret" \
  --value "$NEW_SECRET"

# Update application config to reference the new Key Vault secret
az functionapp config appsettings set --resource-group {rg} --name {function_app} \
  --settings "AZURE_CLIENT_SECRET=@Microsoft.KeyVault(SecretUri=https://{kv_name}.vault.azure.net/secrets/{sp_name}-client-secret/)"

# Remove expired credential after applications are updated
az ad app credential delete --id {app_id} --key-id {expired_key_id}
```

## Rollback Procedure

Adding a new credential does not remove the old one — both are valid until the old one is explicitly deleted. This provides a safe rollback window to revert to the old credential if the new one is incorrectly distributed. Set up Azure Monitor alerts for SP credential expiry: `az monitor scheduled-query-rule create` querying AAD credentials within 30 days of expiry to prevent future outages.
