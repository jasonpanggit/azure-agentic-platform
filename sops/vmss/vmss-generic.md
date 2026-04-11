---
title: "VMSS Domain — Generic Triage"
version: "1.0"
domain: compute
scenario_tags:
  - vmss
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic VMSS triage procedure. Used when no scenario-specific VMSS SOP matches.

## Pre-conditions
- Resource type is Microsoft.Compute/virtualMachineScaleSets

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_vmss_instances` to list all instances with health and provisioning state.
2. **[DIAGNOSTIC]** Call `query_vmss_autoscale` for autoscale configuration and recent events.
3. **[DIAGNOSTIC]** Call `query_resource_health` for the VMSS.
4. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
5. **[NOTIFY]** Notify operator of investigation start.
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Route to specific VMSS SOP if pattern matches, else escalate.

## Remediation Steps

7. **[REMEDIATION:LOW]** Only propose remediation if a clear, reversible action is identified.
   - *Approval message:* Required for any action.

## Escalation
- If root cause unclear: escalate to SRE agent

## Rollback
- Per specific action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machine-scale-sets/
