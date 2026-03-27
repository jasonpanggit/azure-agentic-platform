---
title: "Arc Agent Upgrade Failure"
domain: arc
version: "1.0"
tags: ["arc", "agent", "upgrade", "connected-machine", "version", "update"]
---

## Symptoms

An Arc-enabled server fails to upgrade to a new version of the Azure Connected Machine Agent. The upgrade operation shows as "Failed" in the Azure portal. Azure Policy requiring a minimum agent version flags the server as non-compliant. The agent version reported in the portal remains at the old version after the upgrade attempt. Upgrade jobs triggered via the Azure Update Manager or manual scripts fail silently.

## Root Causes

1. Insufficient disk space on the machine — the agent installer requires temporary disk space for extraction.
2. Package manager conflict — another package installation is running concurrently on the machine.
3. Old agent service is running and cannot be stopped by the installer.
4. Custom proxy configuration blocking the agent package download endpoint.

## Diagnostic Steps

1. Check current Arc agent version and upgrade availability:
   ```bash
   az connectedmachine show --resource-group {rg} --name {machine_name} \
     --query "{status:status,version:agentVersion,osName:osName,lastStatusChange:lastStatusChange}"
   ```
2. Check the upgrade job status:
   ```bash
   az connectedmachine upgrade-extension show \
     --resource-group {rg} --machine-name {machine_name} \
     --query "{state:provisioningState,extensions:extensionInstallationErrors}"
   ```
3. Check agent logs on the machine:
   ```bash
   # Linux
   sudo journalctl -u himagent --since '-2h' | grep -i "upgrade\|update\|error\|fail" | tail -40
   cat /var/log/azcmagent/himagent.log | grep -i "upgrade" | tail -20
   ```
4. Verify disk space available for upgrade:
   ```bash
   # Linux
   df -h / /var/opt/azcmagent 2>/dev/null
   # Windows PowerShell
   Get-PSDrive -Name C | Select-Object Used,Free
   ```
5. Check for concurrent package manager operations:
   ```bash
   # Debian/Ubuntu
   lsof /var/lib/dpkg/lock 2>/dev/null || echo "Lock is free"
   ps aux | grep -E "apt|dpkg|yum|rpm" | grep -v grep
   ```

## Remediation Commands

```bash
# Manual upgrade on Linux
# Download latest agent
wget https://aka.ms/azcmagent -O /tmp/install_linux_azcmagent.sh
chmod +x /tmp/install_linux_azcmagent.sh
sudo bash /tmp/install_linux_azcmagent.sh

# Stop existing service and force upgrade
sudo systemctl stop himagent himds
sudo dpkg --configure -a
sudo apt-get install -y azcmagent

# Restart after upgrade
sudo systemctl start himds himagent
sudo azcmagent version

# Windows PowerShell upgrade
$installer = "$env:TEMP\AzureConnectedMachineAgent.msi"
Invoke-WebRequest -Uri "https://aka.ms/AzureConnectedMachineAgent" -OutFile $installer
Start-Process msiexec.exe -ArgumentList "/i $installer /quiet /l*v $env:TEMP\azcmagent-upgrade.log" -Wait
```

## Rollback Procedure

Agent upgrades are generally forward-only — downgrading the Arc agent is not officially supported. If the upgraded agent introduces a regression (e.g., a known bug in the new version), open a Microsoft support ticket and use `azcmagent disconnect` to temporarily remove the Azure registration while waiting for a hotfix. Extension functionality will be unavailable during this time. Monitor the [Arc release notes](https://docs.microsoft.com/en-us/azure/azure-arc/servers/agent-release-notes) for known issues before upgrading in production.
