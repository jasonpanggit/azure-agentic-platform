---
title: "Azure VM — High CPU Utilization"
version: "1.0"
domain: compute
scenario_tags:
  - high-cpu
  - cpu
  - throttling
  - performance
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where CPU utilization exceeds 90% for more than 5 minutes,
indicating resource contention, runaway processes, or insufficient VM sizing.

## Pre-conditions
- Resource type is Microsoft.Compute/virtualMachines
- Alert: CPU percentage > 90% for ≥5 minutes

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_activity_log` for the VM (2h look-back). Check for recent
   deployments, configuration changes, or scaling events that may have triggered load.
   - *Expected signal:* No changes in the last 2 hours.
   - *Abnormal signal:* Recent deployment → likely application regression.

2. **[DIAGNOSTIC]** Call `query_monitor_metrics` for CPU, memory, disk I/O (last 1h, 5-min granularity).
   - *Expected signal:* CPU below 80%, no co-located resource pressure.
   - *Abnormal signal:* CPU sustained >90% with normal memory → CPU-bound workload.

3. **[DIAGNOSTIC]** Call `query_log_analytics` for `Perf` table, `% Processor Time` object,
   last 30 minutes.
   - *Expected signal:* Specific process(es) consuming CPU identifiable.
   - *Abnormal signal:* No data → Log Analytics workspace not connected.

4. **[DIAGNOSTIC]** Call `query_resource_health` for the VM.
   - *Expected signal:* Available.
   - *Abnormal signal:* Degraded or platform issue → skip to Escalation.

5. **[NOTIFY]** Alert operator of sustained CPU breach:
   > "Incident {incident_id}: {resource_name} CPU exceeded 90% for >5 min.
   >  Investigating cause. No action taken yet."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Determine root cause:
   - Cause A: Recent deployment → application regression
   - Cause B: VM undersized for current workload
   - Cause C: Platform issue (resource health degraded)
   - Unknown → escalate

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause A: propose VM restart to apply latest config/restart app.
   - Call `propose_vm_restart` with `incident_id`, `resource_id`, reason="High CPU post-deployment"
   - *Reversibility:* reversible (VM restarts automatically)
   - *Estimated impact:* ~2-5 min downtime
   - *Approval message:* "Approve restarting {resource_name} to recover from high CPU post-deployment?"

8. **[REMEDIATION:HIGH]** If Cause B: propose VM resize to next SKU tier.
   - First call `query_vm_sku_options` to list available SKUs in same family
   - Then call `propose_vm_resize` with `target_sku` and reason="CPU saturation — undersized VM"
   - *Reversibility:* reversible
   - *Estimated impact:* ~5-10 min downtime for deallocate/resize/start
   - *Approval message:* "Approve resizing {resource_name} from {current_sku} to {target_sku}?"

## Escalation
- If Cause C (platform issue): escalate to SRE agent for Azure Service Health correlation
- If root cause unknown after all diagnostic steps: escalate to SRE agent
- If remediation rejected: create priority P1 incident, notify on-call via Teams

## Rollback
- VM restart: no rollback needed (idempotent)
- VM resize: resize back to original SKU via `propose_vm_resize` with original SKU

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/troubleshoot-high-cpu
- Related SOPs: vm-memory-pressure.md, sre-slo-breach.md
