---
title: "Security — Defender High-Severity Alert"
version: "1.0"
domain: security
scenario_tags:
  - defender
  - alert
  - threat
  - malware
severity_threshold: P1
resource_types:
  - Microsoft.Security/alerts
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where Microsoft Defender for Cloud raises a high or critical severity alert,
indicating potential security threats such as malware, brute force attacks, or suspicious activities.

## Pre-conditions
- Defender alert with severity High or Critical
- Alert: Security threat detected on resource

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_defender_alert_details` for the alert.
   - Check `alertType`, `severity`, `compromisedEntity`, `remediationSteps`.
   - *Expected signal:* False positive (known benign activity).
   - *Abnormal signal:* True positive with active threat indicators.

2. **[DIAGNOSTIC]** Call `query_secure_score` for the affected subscription.
   - *Abnormal signal:* Score dropped — multiple security controls affected.

3. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back) for the affected resource.
   - *Abnormal signal:* Unauthorized access, unusual login patterns, or privilege escalation.

4. **[DIAGNOSTIC]** Call `query_resource_health` for the affected resource.

5. **[NOTIFY]** Notify security team immediately (critical severity):
   > "SECURITY ALERT — Incident {incident_id}: Defender alert {alert_type} on {resource_name}.
   >  Severity: {severity}. Compromised entity: {entity}. Immediate review required."
   - *Channels:* teams, email
   - *Severity:* critical

6. **[DECISION]** Threat assessment:
   - If false positive: dismiss alert with justification
   - If true positive: isolate resource and escalate
   - If lateral movement detected: P0 escalation

## Remediation Steps

7. **[REMEDIATION:CRITICAL]** Propose security response actions.
   - Security remediation always requires security team approval.
   - No automated ARM calls for security incidents.
   - *Approval message:* "Approve security response actions for {resource_name}?"

## Escalation
- All high/critical Defender alerts auto-escalate to security team
- If lateral movement: P0 escalation to CISO
- If data exfiltration suspected: invoke incident response playbook

## Rollback
- Security actions determined by incident response team

## References
- KB: https://learn.microsoft.com/en-us/azure/defender-for-cloud/alerts-overview
