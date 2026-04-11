---
title: "SRE — Service Availability Degraded"
version: "1.0"
domain: sre
scenario_tags:
  - availability
  - degraded
  - latency
  - health
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
  - Microsoft.ContainerService/managedClusters
  - Microsoft.Web/sites
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where service availability is degraded but not yet breaching SLO,
indicating early warning signals that require proactive investigation.

## Pre-conditions
- Availability metrics trending downward but still above SLO threshold
- Alert: Error rate increase or latency spike detected

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_availability_metrics` for the affected service (1h window).
   - *Expected signal:* Stable availability above SLO.
   - *Abnormal signal:* Declining trend — may breach SLO within hours.

2. **[DIAGNOSTIC]** Call `query_advisor_recommendations` for performance and reliability.
   - *Abnormal signal:* High-impact recommendations not implemented.

3. **[DIAGNOSTIC]** Call `query_change_analysis` for recent changes.
   - *Abnormal signal:* Change correlating with degradation onset.

4. **[DIAGNOSTIC]** Call `query_service_health` for Azure Service Health advisories.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: {service_name} availability degrading.
   >  Current: {current_availability}%. Trend: declining. SLO: {slo_target}%.
   >  Proactive investigation initiated."
   - *Channels:* teams
   - *Severity:* warning

6. **[DECISION]** Root cause assessment:
   - If change-correlated: propose rollback of change
   - If Advisor recommendation: propose implementation
   - If Azure Service Health: monitor and track

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** Propose proactive measures based on findings.
   - Coordinate with relevant domain agents for specific actions.
   - *Approval message:* "Approve proactive remediation for {service_name} degradation?"

## Escalation
- If degradation accelerating: upgrade to SLO breach SOP
- If Advisor critical recommendation ignored: escalate to management

## Rollback
- Per specific action taken

## References
- KB: https://learn.microsoft.com/en-us/azure/advisor/
- Related SOPs: sre-slo-breach.md
