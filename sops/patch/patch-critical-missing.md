---
title: "Patch — Critical Patches Missing"
version: "1.0"
domain: patch
scenario_tags:
  - critical
  - security
  - cve
  - urgent
severity_threshold: P1
resource_types:
  - Microsoft.Compute/virtualMachines
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers high-urgency scenarios where critical security patches (e.g., actively exploited CVEs)
are missing on production machines, requiring immediate triage and remediation.

## Pre-conditions
- Critical or zero-day CVE advisory published
- Patch assessment shows affected machines

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_patch_assessment` across all affected machines.
   - Filter for critical classification patches matching CVE advisory.
   - *Abnormal signal:* Any production machine missing the critical patch.

2. **[DIAGNOSTIC]** Call `query_resource_health` for affected machines.
   - *Abnormal signal:* Machine offline → cannot be patched.

3. **[DIAGNOSTIC]** Call `query_activity_log` (24h look-back).
   - Check if emergency patch deployment was already attempted.

4. **[NOTIFY]** Notify operator and security team immediately:
   > "URGENT — Incident {incident_id}: {affected_count} machines missing critical patch for {cve_id}.
   >  Immediate patching recommended."
   - *Channels:* teams, email
   - *Severity:* critical

5. **[DECISION]** Action required:
   - If machines are online and healthy: proceed to remediation
   - If machines are offline: escalate to infrastructure team
   - If patch not available in Update Manager: escalate to vendor

## Remediation Steps

6. **[REMEDIATION:HIGH]** Propose emergency patch assessment to confirm readiness.
   - Call `propose_patch_assessment` with reason="Emergency CVE patch verification"
   - *Reversibility:* reversible (assessment only)
   - *Approval message:* "Approve emergency patch assessment for {affected_count} machines?"

## Escalation
- All critical patch incidents are auto-escalated to security team
- If patch unavailable: open vendor support case immediately

## Rollback
- Assessment: no rollback

## References
- KB: https://learn.microsoft.com/en-us/azure/update-manager/manage-updates
