---
title: "EOL — Runtime/Framework End-of-Life Detected"
version: "1.0"
domain: eol
scenario_tags:
  - runtime
  - framework
  - end-of-life
  - dotnet
  - java
  - python
  - nodejs
severity_threshold: P3
resource_types:
  - Microsoft.Compute/virtualMachines
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers scenarios where a VM or Arc-enabled server is running a runtime or framework
(e.g., .NET, Java, Python, Node.js) that has reached or is approaching end-of-life.

## Pre-conditions
- EOL agent detects runtime version approaching or past end-of-life
- Alert: Runtime lifecycle status is EOL or approaching

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_eol_status` for the detected runtime/framework.
   - Check `product`, `version`, `eol_date`, `days_remaining`.
   - *Abnormal signal:* Runtime past EOL or <90 days remaining.

2. **[DIAGNOSTIC]** Call `query_software_inventory` to confirm installed versions.
   - *Abnormal signal:* Multiple EOL runtimes on same machine.

3. **[DIAGNOSTIC]** Call `query_activity_log` (30-day look-back) for recent software changes.

4. **[NOTIFY]** Notify operator and application team:
   > "Incident {incident_id}: {resource_name} running {runtime_name} {runtime_version}.
   >  End-of-life date: {eol_date}. Upgrade recommended."
   - *Channels:* teams, email
   - *Severity:* info

5. **[DECISION]** Action required:
   - If critical application dependency: coordinate with application team for upgrade
   - If non-critical: schedule upgrade in next maintenance window
   - If already EOL: assess security risk

## Remediation Steps

6. **[REMEDIATION:LOW]** Propose upgrade notification (advisory only).
   - EOL findings are advisory — no ARM actions taken.
   - *Approval message:* "Acknowledge runtime upgrade planning for {resource_name}?"

## Escalation
- If runtime EOL blocks security patching: escalate to security team
- If application team unresponsive: escalate to SRE

## Rollback
- Advisory only — no rollback needed

## References
- KB: https://endoflife.date/
