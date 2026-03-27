---
title: "Arc Guest Configuration Assessment Failure"
domain: arc
version: "1.0"
tags: ["arc", "guest-configuration", "assessment", "compliance", "policy", "dsc"]
---

## Symptoms

Azure Arc Guest Configuration assessments fail to complete on one or more Arc-enabled servers. The Guest Configuration agent reports "Failed" status for configuration assignments. Azure Policy compliance reports show machines as "Non-compliant" with error codes rather than actual compliance state. The Guest Configuration report in the Azure portal shows "Error" status instead of Pass/Fail results for individual configuration items.

## Root Causes

1. Guest Configuration extension not installed or in a failed state.
2. Guest Configuration agent binary is corrupted or lacks execute permissions.
3. Required PowerShell DSC modules are missing from the machine (for DSC-based configurations).
4. The configuration package URL is inaccessible — the custom configuration package blob cannot be downloaded from the storage account.

## Diagnostic Steps

1. Check Guest Configuration assignment status:
   ```bash
   az connectedmachine show --resource-group {rg} --name {machine_name} \
     --query "properties.extensions[?name=='AzurePolicyforLinux'].{name:name,state:provisioningState}"
   az rest --method GET \
     --uri "https://management.azure.com{arc_machine_id}/providers/Microsoft.GuestConfiguration/guestConfigurationAssignments?api-version=2022-01-25" \
     --query "value[].{name:name,status:properties.complianceStatus,lastReport:properties.lastComplianceStatusChecked,error:properties.latestAssignmentReport.assignment.configurationVersion}"
   ```
2. Check Guest Configuration agent logs:
   ```bash
   # Linux
   sudo cat /var/log/GuestConfig/gc_agent.log | grep -E "error|fail|exception" | tail -40
   # Windows
   Get-Content "C:\ProgramData\GuestConfig\Logs\gc_agent.log" -Tail 50 | Where-Object { $_ -match "Error|Fail" }
   ```
3. Verify the Guest Configuration package can be downloaded:
   ```bash
   # Get the configuration package URL from the assignment
   PACKAGE_URL=$(az rest --method GET \
     --uri "https://management.azure.com{arc_machine_id}/providers/Microsoft.GuestConfiguration/guestConfigurationAssignments/{assignment_name}?api-version=2022-01-25" \
     --query "properties.guestConfiguration.contentUri" --output tsv)
   curl -s -o /dev/null -w "%{http_code}" "$PACKAGE_URL"
   ```
4. Check if required PowerShell version is installed (Windows):
   ```bash
   az vm run-command invoke --resource-group {rg} --name {machine_name} \
     --command-id RunPowerShellScript \
     --scripts "Get-Module -ListAvailable | Where-Object Name -like 'GuestConfiguration*'"
   ```
5. Check for Guest Configuration service errors:
   ```bash
   # Linux
   sudo systemctl status gcad
   journalctl -u gcad --since '-2h' | tail -30
   ```

## Remediation Commands

```bash
# Reinstall the Guest Configuration extension on the Arc machine
az connectedmachine extension delete \
  --resource-group {rg} --machine-name {machine_name} \
  --name AzurePolicyforLinux --force

sleep 30

az connectedmachine extension create \
  --resource-group {rg} --machine-name {machine_name} \
  --name AzurePolicyforLinux \
  --publisher Microsoft.GuestConfiguration \
  --type ConfigurationforLinux \
  --type-handler-version 1.0 \
  --location {region}

# Restart Guest Configuration agent
sudo systemctl restart gcad

# Force a compliance re-evaluation
az policy state trigger-scan --resource-group {rg}
```

## Rollback Procedure

Guest Configuration extension reinstallation is safe — existing configuration assignments are re-applied after the extension reinstalls. If the extension reinstallation causes a brief compliance gap in the audit reports, document the maintenance window with timestamps. After the extension is healthy, manually trigger a compliance scan to repopulate the compliance state: `az policy state trigger-scan --resource-group {rg}`. Results appear in the compliance dashboard within 10-15 minutes after the scan completes.
