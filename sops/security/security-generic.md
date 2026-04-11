---
title: "Security Domain — Generic Triage"
version: "1.0"
domain: security
scenario_tags: []
severity_threshold: P2
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic security domain triage. Used when no scenario-specific security SOP matches.
Security incidents always escalate to the security team.

## Pre-conditions
- Domain classified as security

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_defender_alert_details` for relevant alerts.
2. **[DIAGNOSTIC]** Call `query_secure_score` for the subscription.
3. **[DIAGNOSTIC]** Call `query_policy_compliance` for security-related policies.
4. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back).
5. **[NOTIFY]** Notify security team immediately.
   - *Channels:* teams, email
   - *Severity:* critical

6. **[DECISION]** Route to specific security SOP if pattern matches, else escalate.

## Remediation Steps

7. **[REMEDIATION:LOW]** Security remediation always requires security team approval.
   - No automated ARM calls for security incidents.
   - *Approval message:* "Approve security investigation findings?"

## Escalation
- All security incidents escalate to security team by default

## Rollback
- Determined by incident response team.

## References
- KB: https://learn.microsoft.com/en-us/azure/defender-for-cloud/
