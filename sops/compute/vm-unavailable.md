---
title: "Azure VM — VM Unavailable / Unresponsive"
version: "1.0"
domain: compute
scenario_tags:
  - unavailable
  - unresponsive
  - stopped
  - deallocated
severity_threshold: P1
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where the VM is in a stopped, deallocated, or unresponsive state.

## Pre-conditions
- VM power state is Stopped, Deallocated, or health probe is failing

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_resource_health` for the VM.
   - *Expected signal:* Available.
   - *Abnormal signal:* Unavailable → platform issue; Degraded → partial failure.

2. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
   - *Abnormal signal:* Explicit stop/deallocate event → check who triggered it.

3. **[DIAGNOSTIC]** Call `query_monitor_metrics` for VM heartbeat signal.
   - *Abnormal signal:* No heartbeat → VM OS hung or host issue.

4. **[NOTIFY]** Notify operator immediately (P1):
   > "Incident {incident_id}: {resource_name} is unavailable. Immediate investigation in progress."
   - *Channels:* teams, email
   - *Severity:* critical

5. **[DECISION]** Root cause:
   - Cause A: Intentional stop (authorized user action) → verify intent
   - Cause B: Platform host failure → Resource Health shows Unavailable
   - Cause C: VM OS hung (heartbeat lost, resource health Available) → reboot needed

## Remediation Steps

6. **[REMEDIATION:HIGH]** If Cause C: propose VM restart.
   - Call `propose_vm_restart` with reason="VM unresponsive — OS hung"
   - *Approval message:* "Approve force-restarting {resource_name} to recover from unresponsive state?"

7. **[REMEDIATION:HIGH]** If Cause B: propose VM redeploy (move to different host).
   - Call `propose_vm_redeploy` with reason="Host-level failure"
   - *Approval message:* "Approve redeploying {resource_name} to a healthy host?"

## Escalation
- If Cause A and intentional: no action, close incident
- If platform issue persists: open Azure Support ticket, escalate to SRE

## Rollback
- Restart: no rollback
- Redeploy: irreversible (new host allocation)

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/troubleshoot-vm-not-running
