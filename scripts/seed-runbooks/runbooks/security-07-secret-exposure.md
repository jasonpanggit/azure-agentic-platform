---
title: "Secret Exposure in Code Repository"
domain: security
version: "1.0"
tags: ["secret", "git", "exposure", "credentials", "key-rotation", "security"]
---

## Symptoms

An automated secret scanning tool (GitHub Advanced Security, GitGuardian, or a custom pre-commit hook) detects a hardcoded secret in a code repository commit. Alternatively, an operator notices a connection string, API key, or password committed to a public or internal Git repository. The exposed secret may be a storage account key, Azure service principal client secret, database connection string, or API token.

## Root Causes

1. Developer accidentally committed a `.env` file or configuration file containing secrets.
2. Hardcoded credentials in test code that was promoted to the main branch without review.
3. Secret printed to application logs and captured in a log file that was committed.
4. CI/CD pipeline configuration file containing inline secrets instead of referencing environment variables or vault references.

## Diagnostic Steps

1. Identify the exact secret value and when it was committed:
   ```bash
   git log --all --full-history -p -- {path_to_file} | grep -A5 -B5 {partial_secret}
   git log --all --oneline | head -20
   ```
2. Check if the secret has been used by an external actor since exposure:
   ```kql
   StorageBlobLogs
   | where AccountName == "{storage_account}"
   | where AuthenticationType == "AccountKey"
   | where CallerIpAddress !in ({known_ip_list})
   | where TimeGenerated > ago(24h)
   | project TimeGenerated, CallerIpAddress, OperationName, ObjectKey
   ```
3. Check Azure Activity Log for any API calls using the exposed service principal:
   ```kql
   AzureActivity
   | where Caller == "{sp_app_id}"
   | where TimeGenerated > ago(24h)
   | project TimeGenerated, CallerIpAddress, OperationNameValue, ResourceId, ActivityStatusValue
   | order by TimeGenerated desc
   ```
4. Check if the GitHub secret scanner found it (if using GitHub Advanced Security):
   ```bash
   gh api repos/{org}/{repo}/secret-scanning/alerts \
     --jq '.[] | {number:.number,state:.state,secret_type:.secret_type,created:.created_at}'
   ```
5. Verify the scope of exposure — is the repo public or private:
   ```bash
   gh api repos/{org}/{repo} --jq '{private:.private,default_branch:.default_branch,forks:.forks_count}'
   ```

## Remediation Commands

```bash
# Step 1: Rotate the exposed secret IMMEDIATELY (before anything else)
# For storage account key:
az storage account keys renew --resource-group {rg} --account-name {storage_account} --key primary

# For service principal secret:
az ad app credential reset --id {app_id} --append false

# Step 2: Remove the secret from Git history using git-filter-repo
pip install git-filter-repo
git filter-repo --path {file_with_secret} --invert-paths --force
git push origin --force --all

# Step 3: Store secret in Key Vault
az keyvault secret set --vault-name {kv_name} --name {secret_name} --value {new_secret_value}

# Step 4: Notify GitHub to invalidate any cached token
gh api repos/{org}/{repo}/git/refs -X DELETE -F ref=refs/heads/{branch}
```

## Rollback Procedure

Secret rotation cannot be rolled back — the old secret must be treated as permanently compromised and never used again. Ensure all applications consuming the secret are updated to reference the new Key Vault secret before removing the old credentials. If the forced git push rewrote history on shared branches, communicate to all team members to re-clone or reset their local branches. File a security incident report documenting the exposure window and affected resources.
