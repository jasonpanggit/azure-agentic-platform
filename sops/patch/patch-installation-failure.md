---
title: "Patch — Installation Failure"
version: "1.0"
domain: patch
scenario_tags:
  - installation
  - failure
  - error
  - update
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where patch installation fails on a VM or Arc-enabled server,
leaving the machine in a non-compliant state with pending restarts or broken updates.

## Pre-conditions
- Patch installation attempt completed with errors
- Alert: Update Manager installation run failed

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_patch_installation_history` (7-day look-back).
   - Identify specific patches that failed and their error codes.
   - *Abnormal signal:* Repeated failures on same KB → systemic issue.

2. **[DIAGNOSTIC]** Call `query_patch_assessment` to verify current compliance state.
   - *Abnormal signal:* Patches still missing after installation attempt.

3. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back).
   - *Abnormal signal:* Maintenance window conflict or concurrent operations.

4. **[DIAGNOSTIC]** Call `query_resource_health`.
   - *Abnormal signal:* Machine requires reboot to complete previous updates.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: Patch installation failed on {resource_name}.
   >  {failed_count} patches failed. Error: {error_summary}."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Root cause:
   - Cause A: Disk space insufficient for update download
   - Cause B: Conflicting updates or pending reboot blocking new installations
   - Cause C: Network issue preventing download from update source

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause B: propose machine restart to clear pending state.
   - Call `propose_vm_restart` with reason="Clear pending reboot to unblock patch installation"
   - *Reversibility:* reversible
   - *Approval message:* "Approve restarting {resource_name} to unblock patch installation?"

## Escalation
- If repeated failures across multiple machines: escalate to SRE for systemic investigation
- If security patches cannot be installed: P1 escalation to security team

## Rollback
- Restart: no rollback
- Failed patches: no rollback needed (patches were not applied)

## References
- KB: https://learn.microsoft.com/en-us/azure/update-manager/troubleshoot
