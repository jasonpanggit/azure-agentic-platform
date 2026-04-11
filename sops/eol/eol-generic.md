---
title: "EOL Domain — Generic Triage"
version: "1.0"
domain: eol
scenario_tags: []
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic EOL domain triage. Used when no scenario-specific EOL SOP matches.

## Pre-conditions
- Domain classified as eol

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_eol_status` for the detected software/OS.
2. **[DIAGNOSTIC]** Call `query_software_inventory` for full version details.
3. **[DIAGNOSTIC]** Call `query_resource_health`.
4. **[NOTIFY]** Notify operator of EOL finding.
   - *Channels:* teams
   - *Severity:* info

5. **[DECISION]** Route to specific EOL SOP if pattern matches, else create advisory.

## Remediation Steps

6. **[REMEDIATION:LOW]** Propose advisory notification only.
   - EOL findings never take ARM actions.
   - *Approval message:* "Acknowledge EOL finding for {resource_name}?"

## Escalation
- If security-critical: escalate to security team

## Rollback
- Advisory only — no rollback needed.

## References
- KB: https://endoflife.date/
