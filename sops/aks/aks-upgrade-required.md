---
title: "AKS — Kubernetes Version Upgrade Required"
version: "1.0"
domain: compute
scenario_tags:
  - aks
  - upgrade
  - version
  - deprecation
severity_threshold: P3
resource_types:
  - Microsoft.ContainerService/managedClusters
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers AKS scenarios where the cluster Kubernetes version is approaching end-of-support
or deprecated APIs are detected, requiring upgrade planning.

## Pre-conditions
- AKS cluster running a Kubernetes version within 60 days of end-of-support
- Alert: Kubernetes version deprecation warning

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_aks_upgrade_profile` to list available upgrade versions
   and detect deprecated API usage.
   - *Expected signal:* Current version supported, upgrade path available.
   - *Abnormal signal:* No upgrade path → end of support imminent.

2. **[DIAGNOSTIC]** Call `query_activity_log` (7-day look-back) for recent upgrade attempts.
   - *Abnormal signal:* Previous upgrade failed → check error details.

3. **[DIAGNOSTIC]** Call `query_resource_health` for the AKS cluster.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: AKS cluster {resource_name} running Kubernetes {current_version}.
   >  End-of-support in {days_remaining} days. Upgrade recommended."
   - *Channels:* teams, email
   - *Severity:* info

5. **[DECISION]** Action required:
   - If upgrade path exists and no deprecated APIs: schedule upgrade
   - If deprecated APIs detected: escalate for API migration first
   - If end-of-support imminent (<14 days): P2 escalation

## Remediation Steps

6. **[REMEDIATION:LOW]** Propose upgrade planning notification.
   - No automated upgrade — this requires operator-led planning with maintenance windows.
   - *Approval message:* "Acknowledge upgrade planning for {resource_name} to {target_version}?"

## Escalation
- If deprecated APIs in use: escalate to application teams for API migration
- If <14 days to end-of-support: P2 escalation to SRE

## Rollback
- Kubernetes upgrades are irreversible — thorough testing required before approval

## References
- KB: https://learn.microsoft.com/en-us/azure/aks/supported-kubernetes-versions
