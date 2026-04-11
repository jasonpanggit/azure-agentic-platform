---
title: "AKS Domain — Generic Triage"
version: "1.0"
domain: compute
scenario_tags:
  - aks
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic AKS triage procedure. Used when no scenario-specific AKS SOP matches.

## Pre-conditions
- Resource type is Microsoft.ContainerService/managedClusters

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_aks_node_pools` for node pool health and resource status.
2. **[DIAGNOSTIC]** Call `query_aks_diagnostics` for control plane logs and pod events.
3. **[DIAGNOSTIC]** Call `query_resource_health` for the AKS cluster.
4. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
5. **[NOTIFY]** Notify operator of investigation start.
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Route to specific AKS SOP if pattern matches, else escalate.

## Remediation Steps

7. **[REMEDIATION:LOW]** Only propose remediation if a clear, reversible action is identified.
   - *Approval message:* Required for any action.

## Escalation
- If root cause unclear: escalate to SRE agent

## Rollback
- Per specific action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/aks/
