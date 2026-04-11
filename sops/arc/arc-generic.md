---
title: "Arc Domain — Generic Triage"
version: "1.0"
domain: arc
scenario_tags: []
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic Arc domain triage. Used when no scenario-specific SOP matches.

## Pre-conditions
- Domain classified as arc

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_arc_connectivity` for the machine.
2. **[DIAGNOSTIC]** Call `query_arc_extension_health` to list extension states.
3. **[DIAGNOSTIC]** Call `query_resource_health`.
4. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
5. **[NOTIFY]** Notify operator of investigation start.
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Route to specific Arc SOP if pattern matches, else escalate.

## Remediation Steps
7. **[REMEDIATION:LOW]** Only propose reversible actions with explicit approval.

## Escalation
- Unknown issues: escalate to SRE agent

## Rollback
- Per action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/azure-arc/servers/
