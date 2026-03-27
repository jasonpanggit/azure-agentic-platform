---
title: "Arc Policy Compliance Drift"
domain: arc
version: "1.0"
tags: ["arc", "policy", "compliance", "guest-configuration", "drift", "remediation"]
---

## Symptoms

Azure Policy compliance dashboard shows Arc-enabled servers drifting from their required compliance baseline. Policy assignments targeting `Microsoft.HybridCompute/machines` report `NonCompliant` states for previously compliant machines. Guest Configuration assignments show drift alerts. The compliance percentage for the management group or subscription drops below the required SLA. Audit findings reference specific Guest Configuration policy violations.

## Root Causes

1. Manual changes to the OS configuration on the Arc machine that deviate from the Guest Configuration baseline.
2. Guest Configuration extension crashed or was removed, stopping compliance evaluation.
3. Policy assignment updated with stricter requirements that existing machines now fail.
4. Drift in security baseline (e.g., a required service was stopped, a user was added to a privileged group, or a security setting was changed by a software update).

## Diagnostic Steps

1. Check compliance state for Arc machines:
   ```bash
   az policy state list \
     --query "[?resourceType=='microsoft.hybridcompute/machines' && complianceState=='NonCompliant'].{machine:resourceId,policy:policyDefinitionName,time:timestamp}" \
     --output table
   ```
2. Get detailed non-compliance reasons:
   ```bash
   az policy state list \
     --resource {arc_machine_resource_id} \
     --query "[?complianceState=='NonCompliant'].{policy:policyDefinitionName,reason:complianceReasonCode,detail:complianceDetails}" \
     --output table
   ```
3. Check Guest Configuration assignment status:
   ```bash
   az rest --method GET \
     --uri "https://management.azure.com{arc_machine_resource_id}/providers/Microsoft.GuestConfiguration/guestConfigurationAssignments?api-version=2022-01-25" \
     --query "value[].{name:name,compliance:properties.complianceStatus,details:properties.latestAssignmentReport.assignment}"
   ```
4. Check Guest Configuration agent status on the machine:
   ```bash
   # Linux
   /usr/bin/gc_linux_service status
   cat /var/log/GuestConfig/gc_agent.log | tail -50

   # Windows PowerShell
   Get-Service GCService | Select-Object Status
   Get-Content "C:\ProgramData\GuestConfig\Logs\gc_agent.log" -Tail 50
   ```
5. Query compliance history:
   ```kql
   PolicyStates
   | where ResourceId == "{arc_machine_resource_id}"
   | where TimeGenerated > ago(7d)
   | summarize ComplianceCount=countif(ComplianceState == "Compliant"),
               NonComplianceCount=countif(ComplianceState == "NonCompliant")
     by bin(TimeGenerated, 1d), PolicyDefinitionName
   ```

## Remediation Commands

```bash
# Trigger a Guest Configuration compliance scan
az policy remediation create \
  --resource-group {rg} \
  --policy-assignment {policy_assignment_name} \
  --name remediation-$(date +%Y%m%d) \
  --resource-discovery-mode ExistingNonCompliant

# Restart Guest Configuration agent (Linux)
sudo systemctl restart gcad

# Reinstall Guest Configuration extension
az connectedmachine extension delete \
  --resource-group {rg} --machine-name {machine_name} \
  --name AzurePolicyforLinux

az connectedmachine extension create \
  --resource-group {rg} --machine-name {machine_name} \
  --name AzurePolicyforLinux \
  --publisher Microsoft.GuestConfiguration \
  --type ConfigurationforLinux \
  --type-handler-version 1.0 \
  --location {region}
```

## Rollback Procedure

Policy remediation tasks create new Guest Configuration assignments — they do not undo OS changes made by prior configurations. If a remediation task applied a configuration that broke a workload (e.g., disabled a required service), revert the OS change manually and add a policy exemption for that specific machine: `az policy exemption create --name {exemption_name} --policy-assignment {assignment_id} --resource {machine_id} --exemption-category Waiver`. Document the exemption with a business justification and review date.
