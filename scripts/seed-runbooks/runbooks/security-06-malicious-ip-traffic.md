---
title: "Malicious IP Traffic Alert"
domain: security
version: "1.0"
tags: ["security", "malicious-ip", "threat-intelligence", "defender", "nsg", "firewall"]
---

## Symptoms

Microsoft Defender for Cloud or Azure Sentinel raises an alert for communication between an Azure resource and a known malicious IP address from the Microsoft threat intelligence feed. NSG flow logs show traffic to or from an IP flagged as a command-and-control server, botnet node, or known attacker. The alert severity is High or Critical and requires immediate investigation.

## Root Causes

1. Compromised VM or container communicating with a C2 server — malware installed via a supply chain attack or exposed service.
2. Cryptominer phoning home to its pool server — unauthorized mining software installed on a VM.
3. Data exfiltration to an attacker-controlled server — credentials or sensitive data being sent outbound.
4. False positive — a business-required API or CDN endpoint sharing an IP range with a flagged address in the threat intelligence feed.

## Diagnostic Steps

1. Review the Defender for Cloud alert details and the malicious IP:
   ```bash
   az security alert show --resource-group {rg} --location {region} \
     --name {alert_name} \
     --query "{title:alertDisplayName,severity:severity,time:generatedDateTime,ip:entities[?type=='ip'].address,resource:entities[?type=='host'].hostName}"
   ```
2. Check NSG flow logs for the malicious IP traffic:
   ```kql
   AzureNetworkAnalytics_CL
   | where SrcIP_s == "{malicious_ip}" or DestIP_s == "{malicious_ip}"
   | where TimeGenerated > ago(4h)
   | project TimeGenerated, SrcIP_s, DestIP_s, DestPort_d, Protocol_s, FlowStatus_s, BytesSrcToDest_d
   | order by TimeGenerated desc
   ```
3. Identify the source VM communicating with the malicious IP:
   ```kql
   AzureNetworkAnalytics_CL
   | where DestIP_s == "{malicious_ip}"
   | summarize count(), firstSeen=min(TimeGenerated) by SrcIP_s, VM1_s
   | order by count_ desc
   ```
4. Check for malware-related processes running on the VM:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {affected_vm} \
     --command-id RunShellScript \
     --scripts "netstat -anp | grep {malicious_ip} && ps aux | grep -v grep | sort -%cpu | head -20"
   ```
5. Check Defender endpoint alerts for the affected VM:
   ```bash
   az security assessment list --resource-group {rg} \
     --query "[?contains(resourceDetails.id,'{affected_vm}') && statusCode=='Unhealthy'].{name:displayName,severity:metadata.severity}"
   ```

## Remediation Commands

```bash
# Immediately block the malicious IP in the NSG
az network nsg rule create \
  --resource-group {rg} --nsg-name {nsg_name} \
  --name BlockMaliciousIP --priority 100 --direction Outbound \
  --access Deny --protocol "*" \
  --destination-address-prefixes {malicious_ip} \
  --destination-port-ranges "*"

# Isolate the infected VM by blocking all outbound traffic (quarantine)
az network nsg rule create \
  --resource-group {rg} --nsg-name {vm_nsg_name} \
  --name QuarantineVM --priority 90 --direction Outbound \
  --access Deny --protocol "*" --destination-address-prefixes Internet

# Trigger a Defender antimalware scan
az vm extension set --resource-group {rg} --vm-name {affected_vm} \
  --name IaaSAntimalware --publisher Microsoft.Azure.Security \
  --version 1.6 --settings '{"AntimalwareEnabled":true,"ScheduledScanSettings":{"isEnabled":true,"day":1,"time":"120","scanType":"Quick"}}'
```

## Rollback Procedure

The malicious IP block in the NSG is a permanent security control — do not remove it unless threat intelligence confirms the IP was incorrectly flagged. To unquarantine a VM after malware has been cleaned and Defender confirms the VM is clean, remove the `QuarantineVM` outbound deny rule. Conduct a forensic image capture of the VM's disk before any cleanup to preserve evidence: `az snapshot create --resource-group {rg} --source {os_disk_name} --name forensic-snap-$(date +%Y%m%d)`.
