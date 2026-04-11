---
title: "SRE — SLO Breach Detected"
version: "1.0"
domain: sre
scenario_tags:
  - slo
  - breach
  - availability
  - error-budget
severity_threshold: P1
resource_types:
  - Microsoft.Compute/virtualMachines
  - Microsoft.ContainerService/managedClusters
  - Microsoft.Web/sites
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where a service's availability drops below its defined SLO threshold,
indicating a significant reliability incident requiring cross-domain investigation.

## Pre-conditions
- SLO availability threshold breached (e.g., <99.9% availability over rolling window)
- Alert: Error budget burn rate exceeds threshold

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_availability_metrics` for the affected service (1h window).
   - Check uptime percentage, error rate, and latency percentiles.
   - *Expected signal:* Availability above SLO target.
   - *Abnormal signal:* Availability below SLO target — SLO breach confirmed.

2. **[DIAGNOSTIC]** Call `query_error_budget_status` for the service.
   - *Abnormal signal:* Error budget exhausted or burn rate >10x normal.

3. **[DIAGNOSTIC]** Call `query_service_health` for Azure Service Health incidents.
   - *Abnormal signal:* Active Azure service incident affecting the region/service.

4. **[DIAGNOSTIC]** Call `query_change_analysis` for recent changes across affected resources.
   - *Abnormal signal:* Deployment or config change correlating with SLO breach onset.

5. **[NOTIFY]** Notify on-call and management:
   > "SLO BREACH — Incident {incident_id}: {service_name} availability at {current_availability}%.
   >  SLO target: {slo_target}%. Error budget remaining: {budget_remaining}%.
   >  Cross-domain investigation initiated."
   - *Channels:* teams, email
   - *Severity:* critical

6. **[DECISION]** Root cause domain:
   - Compute issue: route to compute agent
   - Network issue: route to network agent
   - Platform issue: Azure Service Health
   - Multiple domains: initiate multi-agent investigation

## Remediation Steps

7. **[REMEDIATION:HIGH]** Propose domain-specific remediation based on root cause.
   - SRE agent coordinates — domain agents propose specific actions.
   - *Approval message:* "Approve SRE-coordinated remediation for SLO breach on {service_name}?"

## Escalation
- If error budget exhausted: freeze non-critical deployments
- If Azure platform issue: open support case with priority
- If multi-domain: invoke group chat with all relevant domain agents

## Rollback
- Coordinated by SRE agent based on domain-specific rollback procedures

## References
- KB: https://learn.microsoft.com/en-us/azure/azure-monitor/app/availability-overview
- Related SOPs: sre-availability-degraded.md
