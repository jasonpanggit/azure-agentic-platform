---
title: "Network — Connectivity Failure"
version: "1.0"
domain: network
scenario_tags:
  - connectivity
  - peering
  - routing
  - vnet
  - expressroute
severity_threshold: P2
resource_types:
  - Microsoft.Network/virtualNetworks
  - Microsoft.Network/expressRouteCircuits
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers network connectivity failures including VNet peering issues, route table
misconfigurations, ExpressRoute degradation, and load balancer health probe failures.

## Pre-conditions
- Cross-VNet or on-premises connectivity failing
- Alert: VNet peering disconnected, ExpressRoute circuit degraded, or LB unhealthy backend

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_vnet_peering_status` for affected VNets.
   - *Expected signal:* Peering state Connected.
   - *Abnormal signal:* Disconnected or InitiatedByRemote.

2. **[DIAGNOSTIC]** Call `query_effective_routes` for affected NICs.
   - *Abnormal signal:* Missing route to destination network, or blackhole route.

3. **[DIAGNOSTIC]** Call `query_expressroute_health` if ExpressRoute circuit involved.
   - *Abnormal signal:* BGP peer down, circuit provider status issue.

4. **[DIAGNOSTIC]** Call `query_lb_health_probes` for load balancers in path.
   - *Abnormal signal:* Backend pool members unhealthy.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: Network connectivity failure detected.
   >  Affected path: {source_vnet} → {destination_vnet}. Investigation in progress."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Root cause:
   - Cause A: VNet peering disconnected (address space conflict or deletion)
   - Cause B: Route table misconfiguration (missing or blackhole routes)
   - Cause C: ExpressRoute circuit degraded (provider issue)
   - Cause D: Load balancer backend unhealthy (application issue)

## Remediation Steps

7. **[REMEDIATION:HIGH]** Network changes require specialized approval.
   - All remediation proposed via notification — no automated ARM calls.
   - *Approval message:* "Approve network investigation findings and proposed fix?"

## Escalation
- If ExpressRoute provider issue: escalate to provider support
- If cross-region connectivity loss: P1 escalation to SRE
- All network changes require network team approval

## Rollback
- Network changes: revert to previous configuration

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-network/virtual-network-troubleshoot-peering-issues
- KB: https://learn.microsoft.com/en-us/azure/expressroute/expressroute-troubleshooting-network-performance
