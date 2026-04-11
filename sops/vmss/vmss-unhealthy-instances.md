---
title: "VMSS — Unhealthy Instances Detected"
version: "1.0"
domain: compute
scenario_tags:
  - unhealthy
  - health-probe
  - vmss
  - instances
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachineScaleSets
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers VMSS scenarios where one or more instances report unhealthy status via
health probes or extension health checks, indicating application or OS issues.

## Pre-conditions
- VMSS health probe reports unhealthy instances
- Alert: Instance health state is Unhealthy

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_vmss_instances` to list instances with health state.
   - *Expected signal:* All instances Healthy.
   - *Abnormal signal:* One or more instances Unhealthy with error details.

2. **[DIAGNOSTIC]** Call `query_vmss_rolling_upgrade` to check for failed upgrades.
   - *Abnormal signal:* Rolling upgrade in progress with failures → upgrade issue.

3. **[DIAGNOSTIC]** Call `query_resource_health` for the VMSS.
   - *Abnormal signal:* Degraded → platform issue affecting multiple instances.

4. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
   - *Abnormal signal:* Recent model update or extension change before unhealthy state.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: VMSS {resource_name} has {unhealthy_count} unhealthy instances."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Root cause:
   - Cause A: Application crash on specific instances
   - Cause B: Failed rolling upgrade left instances in mixed state
   - Cause C: Platform issue affecting availability zone

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause A: propose VMSS reimage of unhealthy instances.
   - Automatic repair policy may handle this if enabled.
   - Call `propose_vmss_scale` with reason="Reimage unhealthy instances"
   - *Reversibility:* reversible (instances are stateless)
   - *Approval message:* "Approve reimaging {unhealthy_count} unhealthy instances in {resource_name}?"

## Escalation
- If >50% instances unhealthy: P1 escalation
- If rolling upgrade stuck: escalate to SRE for rollback assessment

## Rollback
- Reimage: instances return to base image (stateless)

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machine-scale-sets/virtual-machine-scale-sets-health-extension
