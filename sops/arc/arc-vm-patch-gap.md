---
title: "Arc VM — Patch Compliance Gap"
version: "1.0"
domain: arc
scenario_tags:
  - patch
  - compliance
  - missing
  - critical
severity_threshold: P2
resource_types:
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Arc-enabled server scenarios where patch compliance drops below threshold,
indicating critical or security patches are missing.

## Pre-conditions
- Patch compliance below configured threshold (default: critical patches missing)

## Triage Steps

1. **[DIAGNOSTIC]** Route to Patch agent: `route_to_domain` with domain="patch".
   - Patch agent will run `query_patch_assessment` to enumerate missing patches.

2. **[DIAGNOSTIC]** Call `query_arc_connectivity` to verify agent is connected.
   - *Abnormal signal:* Disconnected → assessment data may be stale.

3. **[DIAGNOSTIC]** Call `query_arc_guest_config` to check compliance assignment status.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: Arc VM {resource_name} has critical patches missing."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: Machine disconnected — patch data stale
   - Cause B: Update Manager excluded this machine
   - Cause C: Patches available but not scheduled

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause C: propose patch assessment to refresh compliance data.
   - Call `propose_arc_assessment` with reason="Refresh patch compliance for critical patches"
   - *Approval message:* "Approve triggering patch assessment on {resource_name} to refresh data?"

## Escalation
- If machine has critical CVEs with active exploits: P1 escalation to security team

## Rollback
- Assessment: no rollback

## References
- KB: https://learn.microsoft.com/en-us/azure/update-manager/manage-arc-enabled-servers
