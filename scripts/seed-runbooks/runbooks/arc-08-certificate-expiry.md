---
title: "Arc Server Certificate Expiry"
domain: arc
version: "1.0"
tags: ["arc", "certificate", "expiry", "tls", "connected-machine", "renewal"]
---

## Symptoms

An Azure Arc-enabled server begins failing to communicate with Azure services. The Azure Connected Machine Agent logs show TLS certificate errors. The Arc agent reports a status of "Disconnected" even though network connectivity is available. Operations that require agent communication (extension management, run commands, policy evaluation) fail with certificate-related errors. Azure Monitor shows a gap in Arc machine heartbeats coinciding with the certificate expiry date.

## Root Causes

1. Internal Arc agent certificate expired — the Azure Connected Machine Agent uses auto-renewed internal certificates that occasionally fail to renew due to service interruption.
2. Custom CA-signed certificate on the machine replaced or expired, affecting the agent's trust chain.
3. System clock skew on the Arc machine — a clock that is significantly ahead or behind current time causes certificates to appear expired or not yet valid.
4. Disk full condition prevented Arc agent from writing renewed certificate files.

## Diagnostic Steps

1. Check Arc agent certificate files and their validity:
   ```bash
   # Linux
   openssl x509 -in /var/opt/azcmagent/certs/msoidsvc.crt \
     -text -noout 2>/dev/null | grep -A4 "Validity"
   ls -la /var/opt/azcmagent/certs/
   ```
2. Check the Arc machine status in Azure:
   ```bash
   az connectedmachine show --resource-group {rg} --name {machine_name} \
     --query "{status:status,version:agentVersion,lastChange:lastStatusChange,reason:statusDetails}"
   ```
3. Verify the system clock on the machine:
   ```bash
   # Compare machine time with Azure time
   date -u
   curl -s -I https://management.azure.com/ | grep Date
   # Check NTP sync status
   timedatectl show | grep -E "NTP|Time|RTC"
   ```
4. Check Arc agent logs for certificate errors:
   ```bash
   journalctl -u himagent --since '-4h' | grep -i "certificate\|tls\|ssl\|expir\|x509" | tail -30
   ```
5. Check available disk space for certificate renewal:
   ```bash
   df -h /var/opt/azcmagent/
   ```

## Remediation Commands

```bash
# Restart Arc services to trigger certificate renewal attempt
sudo systemctl stop himagent himds
sudo rm -f /var/opt/azcmagent/certs/msoidsvc.crt /var/opt/azcmagent/certs/msoidsvc.key
sudo systemctl start himds himagent

# Wait 2 minutes and check if certificate was renewed
sleep 120
openssl x509 -in /var/opt/azcmagent/certs/msoidsvc.crt -text -noout | grep "Not After"

# Fix NTP sync if clock skew is the issue
sudo systemctl enable --now chronyd
sudo chronyc makestep

# If certificate renewal fails, re-onboard the agent
sudo azcmagent disconnect --force
sudo azcmagent connect \
  --tenant-id {tenant_id} \
  --subscription-id {subscription_id} \
  --resource-group {rg} \
  --location {region} \
  --tags "environment={env}"
```

## Rollback Procedure

Arc agent re-onboarding creates a new machine resource if the original was deleted. Ensure the original Arc resource is still present in Azure before re-onboarding to avoid creating a duplicate. If a duplicate is created, delete the stale one and verify all policy assignments and extension configurations are still applied to the correct (re-onboarded) resource. Set up Azure Monitor alerts for Arc agent connectivity to get early warning 7 days before any expected certificate-related disconnection.
