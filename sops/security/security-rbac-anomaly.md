---
title: "Security — RBAC Change Anomaly Detected"
version: "1.0"
domain: security
scenario_tags:
  - rbac
  - role-assignment
  - privilege
  - iam
severity_threshold: P2
resource_types:
  - Microsoft.Authorization/roleAssignments
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where an unexpected RBAC role assignment change is detected,
indicating potential privilege escalation or unauthorized access modification.

## Pre-conditions
- RBAC role assignment created, modified, or deleted
- Alert: IAM change detected outside of change management window

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back) for role assignment operations.
   - Check `operationName`, `caller`, `principalId`, `roleDefinitionId`.
   - *Expected signal:* Change made by authorized service principal during change window.
   - *Abnormal signal:* Change by unknown principal, outside change window, or elevated role.

2. **[DIAGNOSTIC]** Call `query_policy_compliance` for IAM-related policies.
   - *Abnormal signal:* Policy violation on the role assignment.

3. **[DIAGNOSTIC]** Call `query_secure_score` for the affected subscription.

4. **[NOTIFY]** Notify security team:
   > "Incident {incident_id}: RBAC change detected — {operation} by {caller}.
   >  Role: {role_name}. Principal: {principal_id}. Scope: {scope}."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Threat assessment:
   - If authorized change: document and close
   - If unauthorized: revert role assignment
   - If privilege escalation pattern: escalate immediately

## Remediation Steps

6. **[REMEDIATION:HIGH]** If unauthorized: propose role assignment revert.
   - RBAC changes require security team approval.
   - *Approval message:* "Approve reverting RBAC change: {role_name} for {principal_id}?"

## Escalation
- If privilege escalation to Owner/Contributor: P1 escalation
- If service principal compromise suspected: invoke incident response

## Rollback
- Role assignment revert: delete the unauthorized assignment

## References
- KB: https://learn.microsoft.com/en-us/azure/role-based-access-control/troubleshooting
