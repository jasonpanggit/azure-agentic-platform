---
title: "VMSS — Scale-Out/Scale-In Failure"
version: "1.0"
domain: compute
scenario_tags:
  - scale-failure
  - autoscale
  - capacity
  - vmss
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachineScaleSets
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers VMSS scenarios where autoscale operations fail to add or remove instances,
indicating quota exhaustion, allocation failures, or misconfigured autoscale rules.

## Pre-conditions
- VMSS autoscale event failed OR instance count diverges from desired capacity
- Alert: Autoscale action failed OR instances stuck in Creating/Deleting state

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_activity_log` for the VMSS (2h look-back).
   - *Expected signal:* Successful scale events.
   - *Abnormal signal:* Failed scale events with error codes (QuotaExceeded, AllocationFailed).

2. **[DIAGNOSTIC]** Call `query_vmss_instances` to list instances with health state.
   - *Expected signal:* All instances in Succeeded provisioning state.
   - *Abnormal signal:* Instances in Failed or Creating state.

3. **[DIAGNOSTIC]** Call `query_vmss_autoscale` to check autoscale settings and recent events.
   - *Abnormal signal:* Autoscale profile misconfigured (min > max, wrong metric).

4. **[DIAGNOSTIC]** Call `query_resource_health` for the VMSS.
   - *Abnormal signal:* Degraded → platform capacity issue in the region.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: VMSS {resource_name} scale operation failed.
   >  Current instance count: {current}. Desired: {desired}."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Root cause:
   - Cause A: Regional quota exhausted (QuotaExceeded error)
   - Cause B: VM SKU allocation failure in availability zone
   - Cause C: Autoscale profile misconfiguration

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause C: propose manual scale to correct instance count.
   - Call `propose_vmss_scale` with target_count and reason="Manual scale after autoscale misconfiguration"
   - *Reversibility:* reversible (scale back)
   - *Approval message:* "Approve scaling {resource_name} to {target_count} instances?"

8. **[REMEDIATION:HIGH]** If Cause A or B: propose scale with different SKU or zone.
   - Requires operator to update VMSS model with alternative SKU.
   - Call `propose_vmss_scale` with reason="Alternative SKU/zone required due to allocation failure"
   - *Approval message:* "Approve VMSS {resource_name} model update for alternative capacity?"

## Escalation
- If quota exhausted: escalate to cloud ops team for quota increase request
- If regional capacity issue: escalate to SRE agent for cross-region failover assessment

## Rollback
- Manual scale: scale back to original count via `propose_vmss_scale`

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machine-scale-sets/troubleshoot
- Related SOPs: compute-generic.md
