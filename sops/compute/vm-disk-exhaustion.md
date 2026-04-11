---
title: "Azure VM — Disk Space Exhaustion"
version: "1.0"
domain: compute
scenario_tags:
  - disk
  - storage
  - exhaustion
  - full
severity_threshold: P1
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where OS disk or data disk utilization exceeds 90%,
risking application failures and OS instability.

## Pre-conditions
- Alert: Disk space > 90% on OS disk or data disk

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_monitor_metrics` for disk space utilization (last 1h).
   - *Abnormal signal:* Any disk > 90%.

2. **[DIAGNOSTIC]** Call `query_disk_health` for the VM's OS disk and data disks.
   - *Expected signal:* All disks in Succeeded state, IOPS within limits.
   - *Abnormal signal:* Disk in Failed state → provisioning issue.

3. **[DIAGNOSTIC]** Call `query_log_analytics` for `Perf` table, `% Free Space` counter.
   - *Abnormal signal:* Trend shows accelerating growth (log file flood, dump file accumulation).

4. **[NOTIFY]** Alert operator:
   > "Incident {incident_id}: {resource_name} disk space critical (>90% full).
   >  Risk of application failure."
   - *Channels:* teams, email
   - *Severity:* critical

5. **[DECISION]** Root cause:
   - Cause A: Log file accumulation (accelerating growth pattern)
   - Cause B: Application data growth (steady growth)
   - Cause C: Disk too small for workload

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause A or B: propose VM restart to flush temp files (last resort).
   - Only if disk cleanup scripts are unavailable.
   - Call `propose_vm_restart` with reason="Disk space recovery — flush temp/log files"
   - *Approval message:* "Approve restarting {resource_name} to flush temp files and recover disk space?"

7. **[REMEDIATION:HIGH]** If Cause C: propose disk resize (expand data disk).
   - Note: disk resize requires VM deallocation. Coordinate with application team.
   - Call `propose_vm_redeploy` with reason="Requires maintenance window for disk expansion"
   - *Approval message:* "Approve maintenance window for {resource_name} disk expansion?"

## Escalation
- If growth is accelerating and remediation is rejected: P0 escalation to on-call via Teams

## Rollback
- VM restart: no rollback
- Disk resize: irreversible (can only expand, not shrink)

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/linux/expand-disks
