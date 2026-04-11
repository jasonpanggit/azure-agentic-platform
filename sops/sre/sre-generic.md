---
title: "SRE Domain — Generic Triage"
version: "1.0"
domain: sre
scenario_tags: []
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic SRE domain triage. Used when no scenario-specific SRE SOP matches.
SRE agent performs cross-domain correlation and reliability assessment.

## Pre-conditions
- Domain classified as sre or escalated from another domain agent

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_availability_metrics` for affected services.
2. **[DIAGNOSTIC]** Call `query_service_health` for Azure platform health.
3. **[DIAGNOSTIC]** Call `query_advisor_recommendations` for high-impact items.
4. **[DIAGNOSTIC]** Call `query_change_analysis` for recent changes across resources.
5. **[NOTIFY]** Notify operator of investigation start.
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Route to specific SRE SOP if pattern matches, or coordinate
   with domain agents for multi-domain investigation.

## Remediation Steps

7. **[REMEDIATION:LOW]** Propose remediation based on cross-domain findings.
   - *Approval message:* Required for any action.

## Escalation
- If cross-domain issue affecting multiple services: P1 escalation
- If Azure platform issue: open support case

## Rollback
- Per specific action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/azure-monitor/
