---
title: "Compute Domain — Generic Triage"
version: "1.0"
domain: compute
scenario_tags: []
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic compute domain triage procedure. Used when no scenario-specific SOP matches
the incident. Covers basic VM/VMSS/AKS health checks and escalation path.

## Pre-conditions
- Domain classified as compute

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_activity_log` for all affected resources (2h look-back).

2. **[DIAGNOSTIC]** Call `query_resource_health` for all affected resources.

3. **[DIAGNOSTIC]** Call `query_monitor_metrics` for CPU, memory, disk, network (last 1h).

4. **[DIAGNOSTIC]** Call `query_log_analytics` for errors and warnings in the incident window.

5. **[NOTIFY]** Notify operator of investigation start:
   > "Incident {incident_id}: Compute triage in progress for {resource_name}."
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Based on findings, route to the most specific SOP if one matches,
   or escalate to SRE for cross-domain correlation.

## Remediation Steps

7. **[REMEDIATION:LOW]** Only propose remediation if a clear, reversible action is identified.
   - Use specific propose_* tools as appropriate.
   - *Approval message:* Required for any action.

## Escalation
- If root cause unclear: escalate to SRE agent
- If cross-domain symptoms: request orchestrator re-route

## Rollback
- Per specific action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/
