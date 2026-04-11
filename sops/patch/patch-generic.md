---
title: "Patch Domain — Generic Triage"
version: "1.0"
domain: patch
scenario_tags: []
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic patch domain triage. Used when no scenario-specific patch SOP matches.

## Pre-conditions
- Domain classified as patch

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_patch_assessment` for affected machines.
2. **[DIAGNOSTIC]** Call `query_patch_installation_history` (30-day look-back).
3. **[DIAGNOSTIC]** Call `query_resource_health` for affected machines.
4. **[DIAGNOSTIC]** Call `query_activity_log` (7-day look-back).
5. **[NOTIFY]** Notify operator of investigation start.
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Route to specific patch SOP if pattern matches, else escalate.

## Remediation Steps

7. **[REMEDIATION:LOW]** Only propose reversible actions (assessment triggers) with approval.
   - *Approval message:* Required for any action.

## Escalation
- Unknown patch issues: escalate to SRE agent

## Rollback
- Per action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/update-manager/
