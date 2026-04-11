---
title: "Patch — Compliance Violation Detected"
version: "1.0"
domain: patch
scenario_tags:
  - compliance
  - violation
  - missing-patches
  - audit
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where a VM or Arc-enabled server fails patch compliance checks,
indicating critical or security patches are missing beyond the configured SLA window.

## Pre-conditions
- Patch compliance assessment completed
- One or more critical/security patches missing beyond SLA window

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_patch_assessment` for the resource.
   - Enumerate all missing patches by classification (Critical, Security, Other).
   - *Expected signal:* No critical or security patches missing.
   - *Abnormal signal:* Critical patches missing for >7 days.

2. **[DIAGNOSTIC]** Call `query_patch_installation_history` (30-day look-back).
   - *Abnormal signal:* Recent installation attempts failed → check error codes.

3. **[DIAGNOSTIC]** Call `query_resource_health` for the machine.
   - *Abnormal signal:* Degraded → machine may need recovery before patching.

4. **[DIAGNOSTIC]** Call `query_activity_log` (7-day look-back).
   - *Abnormal signal:* Machine excluded from Update Manager schedule.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: {resource_name} has {missing_count} critical patches missing.
   >  Compliance violation — patches overdue by {days_overdue} days."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Root cause:
   - Cause A: Machine not enrolled in Update Manager schedule
   - Cause B: Previous patch installation failed
   - Cause C: Machine disconnected (Arc) — assessment data stale

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause A or B: propose patch assessment refresh.
   - Call `propose_patch_assessment` with reason="Refresh compliance and trigger remediation"
   - *Reversibility:* reversible (assessment only)
   - *Approval message:* "Approve triggering patch assessment on {resource_name}?"

## Escalation
- If critical CVE with known exploits: P1 escalation to security team
- If machine disconnected: escalate to Arc domain agent

## Rollback
- Assessment: no rollback needed

## References
- KB: https://learn.microsoft.com/en-us/azure/update-manager/overview
