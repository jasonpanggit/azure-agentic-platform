---
title: "Azure VM — Memory Pressure"
version: "1.0"
domain: compute
scenario_tags:
  - memory
  - oom
  - swap
  - pagefile
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where available memory drops below 10% or OOM kills are detected,
indicating memory-intensive workloads or memory leaks.

## Pre-conditions
- Resource type is Microsoft.Compute/virtualMachines
- Alert: Available memory < 10% OR OOM kill event detected

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_activity_log` for the VM (2h look-back).
   - *Abnormal signal:* Recent deployment or config change.

2. **[DIAGNOSTIC]** Call `query_monitor_metrics` for available memory bytes (last 1h).
   - *Expected signal:* >500 MB available.
   - *Abnormal signal:* <100 MB → critical memory pressure.

3. **[DIAGNOSTIC]** Call `query_log_analytics` for `Perf` table, `Available MBytes` counter,
   and `Event` table for EventID 2004 (OOM kernel warning) in last 30 minutes.
   - *Abnormal signal:* OOM event found → OS-level kill in progress.

4. **[DIAGNOSTIC]** Call `query_resource_health`.
   - *Abnormal signal:* Degraded → platform-side memory issue.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: {resource_name} memory pressure detected.
   >  Available memory < 10%. OOM risk."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Determine root cause:
   - Cause A: Memory leak in application (growing RSS over time)
   - Cause B: VM undersized for workload
   - Cause C: Platform issue

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause A: propose VM restart to clear leaked memory.
   - Call `propose_vm_restart` with reason="Memory leak recovery"
   - *Reversibility:* reversible
   - *Approval message:* "Approve restarting {resource_name} to recover from memory leak?"

8. **[REMEDIATION:HIGH]** If Cause B: propose VM resize to higher-memory SKU.
   - Call `query_vm_sku_options`, then `propose_vm_resize`
   - *Approval message:* "Approve resizing {resource_name} to {target_sku} for memory capacity?"

## Escalation
- If Cause C: escalate to SRE agent
- If OOM kills are ongoing and restart rejected: escalate immediately

## Rollback
- VM restart: no rollback
- VM resize: resize back to original SKU

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/troubleshoot-performance-bottlenecks
- Related SOPs: vm-high-cpu.md
