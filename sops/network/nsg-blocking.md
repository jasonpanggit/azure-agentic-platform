---
title: "Network — NSG Blocking Traffic"
version: "1.0"
domain: network
scenario_tags:
  - nsg
  - firewall
  - blocking
  - deny
severity_threshold: P2
resource_types:
  - Microsoft.Network/networkSecurityGroups
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where an NSG rule is blocking legitimate traffic, causing connectivity
failures for VMs, load balancers, or application gateways.

## Pre-conditions
- Connectivity probe failing for a resource behind an NSG
- Alert: NSG flow log shows denied traffic matching expected application flows

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_nsg_effective_rules` for the affected NIC/subnet.
   - Enumerate all effective rules (including inherited from subnet and NIC).
   - *Expected signal:* Allow rules for application ports present.
   - *Abnormal signal:* Deny rule with higher priority blocking traffic.

2. **[DIAGNOSTIC]** Call `query_nsg_flow_logs` for denied flows (last 1h).
   - *Abnormal signal:* High volume of denied flows on expected ports.

3. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back).
   - *Abnormal signal:* Recent NSG rule change correlating with connectivity loss.

4. **[DIAGNOSTIC]** Call `query_resource_health` for affected resources.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: NSG {resource_name} blocking traffic on port {port}.
   >  Rule: {rule_name} (priority {priority}). {denied_flow_count} denied flows in last hour."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Root cause:
   - Cause A: Intentional security rule — verify with security team
   - Cause B: Accidental rule change — revert needed
   - Cause C: Default deny catching new application port

## Remediation Steps

7. **[REMEDIATION:HIGH]** If Cause B: propose NSG rule revert.
   - NSG changes require security team approval.
   - *Approval message:* "Approve reverting NSG rule {rule_name} on {resource_name}?"
   - Note: Do NOT make ARM calls — propose change for human execution.

## Escalation
- All NSG changes require security team approval
- If critical application affected: P1 escalation

## Rollback
- NSG rule revert: reversible (re-apply original rule)

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-network/diagnose-network-traffic-filter-problem
- Related SOPs: vm-network-unreachable.md
