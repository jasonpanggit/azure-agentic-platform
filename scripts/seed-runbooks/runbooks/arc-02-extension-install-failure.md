---
title: "Arc Extension Install Failure"
domain: arc
version: "1.0"
tags: ["arc", "extension", "install", "hybrid", "connected-machine", "agent"]
---

## Symptoms

An Azure Arc extension (such as Azure Monitor Agent, Custom Script Extension, Dependency Agent, or Guest Configuration) fails to install on an Arc-enabled server. The extension provisioning state shows "Failed" in the Azure portal. Azure Policy "Deploy if not exists" remediation tasks fail for the affected machines. Extension error messages appear in the Activity Log and the extension logs on the machine.

## Root Causes

1. Arc agent not healthy — the Connected Machine Agent is in a bad state preventing extension operations.
2. Extension prerequisite missing — a required package (Python, .NET runtime) is absent or the wrong version.
3. Proxy or firewall blocking extension download — the extension installer cannot reach `*.blob.core.windows.net` or extension-specific endpoints.
4. Extension version conflict — an older version of the extension is installed and the upgrade path fails.

## Diagnostic Steps

1. Check extension status and error message:
   ```bash
   az connectedmachine extension show \
     --resource-group {rg} --machine-name {machine_name} --name {ext_name} \
     --query "{state:provisioningState,version:typeHandlerVersion,error:instanceView.status}"
   ```
2. Check all extensions on the machine:
   ```bash
   az connectedmachine extension list \
     --resource-group {rg} --machine-name {machine_name} \
     --query "[].{name:name,type:type,state:provisioningState,version:typeHandlerVersion}" \
     --output table
   ```
3. Check Arc agent logs for extension operation errors (Linux):
   ```bash
   # Run on the target machine
   cat /var/log/azcmagent/himagent.log | grep -i "extension\|error\|fail" | tail -50
   ls /var/lib/GuestConfig/extension_logs/
   cat /var/lib/GuestConfig/extension_logs/{ext_name}/*.log | tail -100
   ```
4. Test endpoint connectivity for extension packages:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" \
     "https://aka.ms/InstallAzureCliDeb" || echo "UNREACHABLE"
   ```
5. Check Arc agent health:
   ```bash
   azcmagent check
   azcmagent show
   ```

## Remediation Commands

```bash
# Delete and reinstall the failed extension
az connectedmachine extension delete \
  --resource-group {rg} --machine-name {machine_name} --name {ext_name} --force

# Wait for deletion to complete, then reinstall
sleep 30
az connectedmachine extension create \
  --resource-group {rg} --machine-name {machine_name} \
  --name AzureMonitorLinuxAgent \
  --type AzureMonitorLinuxAgent \
  --publisher Microsoft.Azure.Monitor \
  --type-handler-version 1.0 \
  --auto-upgrade-minor-version true \
  --location {region}

# Upgrade the Arc agent to the latest version (on the machine)
# Linux
sudo apt-get update && sudo apt-get install --only-upgrade azcmagent

# Restart the Arc agent service
sudo systemctl restart himagent himds
```

## Rollback Procedure

Extension deletion and reinstallation is the primary remediation — it is safe and does not affect the Arc server resource itself. If the extension is required by an Azure Policy "deploy if not exists" rule, the policy remediation task will automatically attempt reinstallation after the extension is deleted. Check the extension logs after reinstallation to confirm "ProvisioningState/succeeded" before marking the incident resolved.
