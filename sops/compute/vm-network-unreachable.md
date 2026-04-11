---
title: "Azure VM — Network Unreachable"
version: "1.0"
domain: compute
scenario_tags:
  - network
  - connectivity
  - nsg
  - unreachable
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where the VM is running but cannot be reached over the network,
indicating NSG rule issues, routing problems, or NIC misconfiguration.

## Pre-conditions
- VM power state: Running
- Network connectivity probe failing

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_resource_health` for the VM.
   - *Expected signal:* Available.
   - *Abnormal signal:* Degraded → possible platform network issue.

2. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
   - *Abnormal signal:* Recent NSG rule change or NIC modification.

3. **[DIAGNOSTIC]** Route to Network agent via `route_to_domain` with domain="network".
   - Network agent will check NSG rules, effective routes, and flow logs.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: {resource_name} network unreachable. NSG/routing investigation in progress."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: NSG rule blocking traffic → Network agent identifies rule
   - Cause B: Route table misconfiguration
   - Cause C: VM NIC in failed state

## Remediation Steps

6. **[REMEDIATION:HIGH]** If Cause C: propose VM restart to reset NIC.
   - Call `propose_vm_restart` with reason="NIC reset for connectivity recovery"
   - *Approval message:* "Approve restarting {resource_name} to reset NIC state?"

## Escalation
- If Cause A or B: escalate to Network agent for NSG/routing remediation
- Network changes require Network domain agent and separate approval

## Rollback
- VM restart: no rollback

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/troubleshoot-rdp-nsg-problem
- Related SOPs: network-nsg-blocking.md
