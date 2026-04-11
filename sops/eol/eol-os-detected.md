---
title: "EOL — Operating System End-of-Life Detected"
version: "1.0"
domain: eol
scenario_tags:
  - os
  - end-of-life
  - lifecycle
  - upgrade
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where a VM or Arc-enabled server is running an operating system
version that has reached or is approaching end-of-life, requiring upgrade planning.

## Pre-conditions
- EOL agent detects OS version within 90 days of end-of-life or already EOL
- Alert: OS lifecycle status is EOL or approaching EOL

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_eol_status` for the machine's OS.
   - Check `eol_date`, `days_remaining`, `lts_status`.
   - *Expected signal:* OS supported with >180 days remaining.
   - *Abnormal signal:* EOL date passed or <90 days remaining.

2. **[DIAGNOSTIC]** Call `query_software_inventory` to confirm exact OS version and build.
   - *Abnormal signal:* OS version not in supported list.

3. **[DIAGNOSTIC]** Call `query_resource_health` for the machine.

4. **[NOTIFY]** Notify operator and compliance team:
   > "Incident {incident_id}: {resource_name} running {os_name} {os_version}.
   >  End-of-life date: {eol_date}. Days remaining: {days_remaining}.
   >  Upgrade planning recommended."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Action required:
   - If already EOL: P2 escalation — no security updates available
   - If <90 days: schedule upgrade in maintenance window
   - If <30 days: P1 escalation

## Remediation Steps

6. **[REMEDIATION:LOW]** Propose upgrade planning notification (advisory only).
   - EOL findings are advisory — no ARM actions taken.
   - Notify teams channel with upgrade recommendation.
   - *Approval message:* "Acknowledge OS upgrade planning for {resource_name}?"

## Escalation
- If already EOL with no security updates: P1 escalation to security team
- If compliance framework requires supported OS: escalate to compliance team

## Rollback
- Advisory only — no rollback needed

## References
- KB: https://endoflife.date/
- KB: https://learn.microsoft.com/en-us/lifecycle/
