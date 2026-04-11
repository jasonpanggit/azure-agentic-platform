---
title: "Arc VM — Extension Provisioning Failure"
version: "1.0"
domain: arc
scenario_tags:
  - extension
  - provisioning
  - failed
severity_threshold: P2
resource_types:
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Arc-enabled server scenarios where a VM extension fails to provision,
potentially blocking monitoring agents, patch management, or guest configuration.

## Pre-conditions
- Arc machine extension in Failed or Unknown provisioning state

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_arc_extension_health` to list all extensions and their
   provisioning states and error messages.
   - *Abnormal signal:* Extension in Failed state with error code.

2. **[DIAGNOSTIC]** Call `query_arc_connectivity` to verify agent is connected.
   - *Abnormal signal:* Disconnected → fix connectivity first (see arc-vm-disconnected.md).

3. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back) for extension install attempts.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: Arc VM {resource_name} extension {extension_name} in Failed state."
   - *Channels:* teams
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: Agent disconnected → connectivity must be restored first
   - Cause B: Extension configuration error (wrong settings)
   - Cause C: Extension version conflict

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause B or C: propose assessment to re-trigger extension.
   - Call `propose_arc_assessment` with reason="Re-trigger failed extension provisioning"
   - *Approval message:* "Approve re-triggering extension provisioning on {resource_name}?"

## Escalation
- If extension is security-critical (AMA, MDE): P1 escalation
- If repeated failures: open support case

## Rollback
- Extension re-trigger: no rollback

## References
- KB: https://learn.microsoft.com/en-us/azure/azure-arc/servers/manage-vm-extensions
