---
title: "Human-readable SOP title"
version: "1.0"
domain: compute
scenario_tags:
  - tag1
  - tag2
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
<!-- One paragraph explaining when this SOP applies and what it covers. -->

## Pre-conditions
- Resource type is X
- Alert rule is Y

## Triage Steps

1. **[DIAGNOSTIC]** Description of what to check and what tool to use.
   - *Expected signal:* What a healthy result looks like.
   - *Abnormal signal:* What triggers escalation or next step.

2. **[NOTIFY]** If <condition>: send notification via Teams + email with message template:
   > "Incident {incident_id}: {resource_name} — {alert_title}. Current state: {state}."
   - *Channels:* teams, email
   - *Severity:* warning

3. **[DECISION]** Based on triage findings, determine root cause from:
   - Cause A: <description>
   - Cause B: <description>
   - Unknown: escalate

## Remediation Steps

4. **[REMEDIATION:MEDIUM]** If Cause A: description of proposed action.
   - *Reversibility:* reversible
   - *Estimated impact:* description
   - *Approval message:* "Approve action on {resource_name}?"

5. **[REMEDIATION:HIGH]** If Cause B: description of proposed action.
   - *Reversibility:* irreversible
   - *Estimated impact:* description
   - *Approval message:* "Approve action on {resource_name}?"

## Escalation
- If triage inconclusive: escalate to SRE agent
- If remediation rejected: create priority incident and notify on-call via Teams

## Rollback
- On DEGRADED verification: auto-rollback via existing WAL mechanism

## References
- KB: https://learn.microsoft.com/
