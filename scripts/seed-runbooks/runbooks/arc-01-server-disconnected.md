---
title: "Arc Server Disconnected Investigation"
domain: arc
version: "1.0"
tags: ["arc", "hybrid", "disconnected", "agent", "connected-machine", "on-premises"]
---

## Symptoms

An Azure Arc-enabled server shows as "Disconnected" in the Azure portal. The machine's heartbeat in Azure Monitor stops. Policies targeting Arc machines stop being evaluated, extensions become unresponsive, and the machine no longer appears in Azure Resource Graph queries. Azure Monitor alerts fire for `Microsoft.HybridCompute/machines` connectivity health. The on-premises or multi-cloud server itself is still running normally.

## Root Causes

1. Azure Connected Machine Agent service stopped on the host — the service was stopped manually, crashed, or was disabled by a policy change.
2. Network connectivity issue — outbound HTTPS to the Arc endpoints (`*.his.arc.azure.com`, `*.guestconfiguration.azure.com`) is blocked by a firewall or proxy change.
3. Arc agent certificate expired — the internal TLS certificate used by the agent for Azure communication expired.
4. Azure subscription or resource group access revoked for the system-assigned managed identity of the Arc server.

## Diagnostic Steps

1. Check the Arc server status in Azure Resource Graph:
   ```bash
   az connectedmachine show --resource-group {rg} --name {machine_name} \
     --query "{status:status,lastStatusChange:lastStatusChange,agentVersion:agentVersion,osName:osName}"
   ```
2. Check the Arc machine heartbeat in Log Analytics:
   ```kql
   Heartbeat
   | where Computer == "{machine_fqdn}"
   | where TimeGenerated > ago(2h)
   | summarize LastHeartbeat=max(TimeGenerated) by Computer
   ```
3. Verify the Azure Connected Machine Agent service is running on the host:
   ```bash
   # Run on the on-premises server (Linux)
   systemctl status himagent
   journalctl -u himagent --since '-2h' | tail -50

   # Windows PowerShell
   Get-Service -Name himds | Select-Object Status, StartType
   Get-EventLog -LogName Application -Source "Azure Connected Machine Agent" -Newest 20
   ```
4. Test outbound connectivity to Arc endpoints:
   ```bash
   # From the on-premises server
   curl -v https://gbl.his.arc.azure.com/azcmagent/health
   curl -v https://eastus.his.arc.azure.com/azcmagent/health
   ```
5. Check Arc agent certificate validity:
   ```bash
   # Linux
   openssl x509 -in /var/opt/azcmagent/certs/msoidsvc.crt -text -noout | grep -A2 "Validity"
   # Windows
   Get-ChildItem Cert:\LocalMachine\My | Where-Object {$_.Subject -like "*azcmagent*"}
   ```

## Remediation Commands

```bash
# Restart the Azure Connected Machine Agent service (on the on-premises server)
# Linux
sudo systemctl restart himagent
sudo systemctl restart himds

# Windows PowerShell
Restart-Service -Name himds -Force

# Re-onboard the agent if it's in an irrecoverable state
azcmagent disconnect --force
azcmagent connect \
  --tenant-id {tenant_id} \
  --subscription-id {subscription_id} \
  --resource-group {rg} \
  --location {region}

# Check and update agent to latest version
azcmagent version
# Download and install latest from: https://aka.ms/AzureConnectedMachineAgent
```

## Rollback Procedure

Agent reconnection is non-destructive — the Arc server resource in Azure retains all its extensions, policy assignments, and tags. If the reconnection creates a duplicate resource (e.g., the machine FQDN changed), delete the stale disconnected resource: `az connectedmachine delete --resource-group {rg} --name {stale_machine_name}`. Monitor the heartbeat metric for 15 minutes after reconnection to confirm stable connectivity.
