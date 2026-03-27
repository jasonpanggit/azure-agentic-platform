---
title: "Defender for Cloud Alert Triage"
domain: security
version: "1.0"
tags: ["defender", "security-center", "alert", "triage", "cloud-security", "soc"]
---

## Symptoms

Microsoft Defender for Cloud generates one or more security alerts requiring operator investigation. Alerts appear in the Defender portal and are forwarded to Azure Monitor and optionally to Microsoft Sentinel. Alert severity ranges from Informational to High. The security operations team must triage each alert to determine: true positive requiring remediation, false positive to be dismissed, or a risk accepted with a suppression rule.

## Root Causes

1. Actual security threat detected — malware, unauthorized access, suspicious process, or network exfiltration.
2. Misconfiguration triggering a security detection (e.g., a script that pattern-matches a PowerShell obfuscation signature but is legitimate).
3. New workload or deployment pattern not recognized by the Defender baseline model.
4. Defender plan enabled on a subscription for the first time, generating a burst of existing configuration findings.

## Diagnostic Steps

1. List all active high/critical Defender alerts:
   ```bash
   az security alert list \
     --query "[?severity=='High' || severity=='Medium'].{id:name,title:alertDisplayName,severity:severity,time:generatedDateTime,state:status,resource:resourceIdentifiers[0].azureResourceId}" \
     --output table
   ```
2. Get full details of a specific alert:
   ```bash
   az security alert show --name {alert_id} --location {region} \
     --query "{title:alertDisplayName,description:description,severity:severity,tactics:tactics,techniques:techniques,remediation:remediationSteps,entities:entities}"
   ```
3. Query the raw alert data in Log Analytics:
   ```kql
   SecurityAlert
   | where AlertName contains "{alert_type}"
   | where TimeGenerated > ago(24h)
   | project TimeGenerated, AlertName, AlertSeverity, Entities, ExtendedProperties, RemediationSteps
   | order by TimeGenerated desc
   ```
4. Correlate the alert with related activity:
   ```kql
   let alertTime = datetime({alert_timestamp});
   AzureActivity
   | where TimeGenerated between ((alertTime - 30m) .. (alertTime + 30m))
   | where ResourceGroup == "{rg}"
   | project TimeGenerated, Caller, OperationNameValue, ResourceId, ActivityStatusValue
   ```
5. Check if the entity has prior security findings:
   ```bash
   az security assessment list --resource-group {rg} \
     --query "[?statusCode!='Healthy'].{name:displayName,status:statusCode,severity:metadata.severity,resource:resourceDetails.id}" \
     --output table
   ```

## Remediation Commands

```bash
# Dismiss a false positive alert
az security alert update \
  --name {alert_id} \
  --location {region} \
  --status Dismissed

# Create an alert suppression rule for a recurring false positive
az security alerts-suppression-rule create \
  --resource-group {rg} \
  --alert-type {alert_type} \
  --name "suppress-{alert_type}-{rg}" \
  --reason "FalsePositive" \
  --comment "Legitimate workload pattern, confirmed {date}"

# Escalate to Defender for Endpoint for VM-level investigation
az security auto-provisioning-setting update \
  --name mma --auto-provision On

# Enable enhanced detection for the affected workload
az security pricing create --name VirtualMachines --tier Standard
```

## Rollback Procedure

Alert dismissals can be undone by re-opening alerts in the Defender portal. Suppression rules can be disabled or deleted if they are incorrectly scoping out true positives: `az security alerts-suppression-rule delete --name {rule_name}`. After triaging, update the security incident ticket with the disposition (true positive, false positive, risk accepted) and the investigation timeline for compliance documentation.
