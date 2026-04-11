---
title: "Arc VM — Agent Disconnected"
version: "1.0"
domain: arc
scenario_tags:
  - disconnected
  - connectivity
  - agent
severity_threshold: P2
resource_types:
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Arc-enabled server scenarios where the Azure Connected Machine Agent (ACMA)
stops reporting, indicating connectivity loss or agent crash.

## Pre-conditions
- Arc machine connectivity status: Disconnected
- Last heartbeat >15 minutes ago

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_arc_connectivity` for the machine.
   - Check `lastStatusChange`, `agentVersion`, `disconnectReason`.

2. **[DIAGNOSTIC]** Call `query_activity_log` for the Arc machine (2h look-back).
   - *Abnormal signal:* Recent network policy change blocking outbound connectivity.

3. **[DIAGNOSTIC]** Call `query_resource_health` for the Arc machine.
   - *Abnormal signal:* Unavailable → prolonged disconnection.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: Arc VM {resource_name} disconnected since {lastStatusChange}."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: Network outage (firewall blocked *.his.arc.azure.com)
   - Cause B: Agent crash or service stopped
   - Cause C: Machine powered off

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause B: propose Arc patch assessment trigger to verify
   agent responsiveness after network access confirmed.
   - Call `propose_arc_assessment` with reason="Verify agent reconnection"
   - *Approval message:* "Approve triggering patch assessment on {resource_name} to test connectivity?"

## Escalation
- If Cause A: escalate to network team to verify firewall rules for Arc endpoints
- If machine powered off: no automated action

## Rollback
- Assessment trigger: no rollback needed

## References
- KB: https://learn.microsoft.com/en-us/azure/azure-arc/servers/troubleshoot-agent-onboard
