---
title: "Network Domain — Generic Triage"
version: "1.0"
domain: network
scenario_tags: []
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic network domain triage. Used when no scenario-specific network SOP matches.

## Pre-conditions
- Domain classified as network

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_nsg_effective_rules` for affected resources.
2. **[DIAGNOSTIC]** Call `query_effective_routes` for affected NICs.
3. **[DIAGNOSTIC]** Call `query_resource_health` for network resources.
4. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back).
5. **[NOTIFY]** Notify operator of investigation start.
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Route to specific network SOP if pattern matches, else escalate.

## Remediation Steps

7. **[REMEDIATION:LOW]** Network changes always require human approval.
   - No automated ARM calls for network resources.
   - *Approval message:* Required for any action.

## Escalation
- All network issues with production impact: escalate to network team

## Rollback
- Per specific action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-network/
