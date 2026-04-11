---
title: "Azure VM — Rightsizing via Low CPU Utilization (<5%)"
version: "1.0"
domain: compute
scenario_tags:
  - cost
  - rightsizing
  - low-cpu
  - advisor
  - vm-sku
severity_threshold: P4
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where sustained CPU utilization is below 5% over a
7-day window, indicating the VM is oversized for its workload. Azure Advisor
has flagged the VM with a Cost recommendation suggesting a smaller SKU to
reduce monthly spend.

## Pre-conditions
- Resource type is Microsoft.Compute/virtualMachines
- Average CPU utilization < 5% over the past 7 days (confirmed via query_monitor_metrics)
- Azure Advisor has an active Cost recommendation with a specific target_sku
- VM is NOT tagged as 'protected'

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_advisor_rightsizing_recommendations` for the VM.
   - *Expected signal:* One or more Cost recommendations with a target_sku and estimated monthly savings.
   - *Abnormal signal:* No recommendations → VM not yet assessed by Advisor; wait 24h and retry.
   - *Key output:* `target_sku`, `estimated_monthly_savings`, `savings_currency`

2. **[DIAGNOSTIC]** Call `query_vm_cost_7day` to confirm actual spend.
   - *Expected signal:* Consistent daily cost matching the SKU's list price.
   - *Abnormal signal:* Zero cost → VM may already be deallocated; no action needed.
   - *Key output:* `total_cost_7d`, `currency`, `daily_costs`

3. **[DIAGNOSTIC]** Call `query_monitor_metrics` for CPU utilization (last 7 days, 1-hour granularity).
   - *Expected signal:* P95 CPU < 5%, confirming the VM is idle/underutilized.
   - *Abnormal signal:* CPU spikes > 20% at any point → do NOT downsize; workload is bursty.

4. **[DIAGNOSTIC]** Call `query_activity_log` (48h look-back) to confirm no recent deployments
   that might explain temporary low utilization.
   - *Expected signal:* No activity in the past 48 hours.
   - *Abnormal signal:* Recent deployment → wait for workload stabilisation before downsizing.

5. **[NOTIFY]** Alert operator of rightsizing opportunity:
   > "VM '{vm_name}' has averaged <5% CPU over 7 days. Azure Advisor recommends
   >  downsizing to {target_sku} with estimated savings of {savings}/month.
   >  Awaiting approval to proceed."
   - *Channels:* teams
   - *Severity:* informational

6. **[DECISION]** Evaluate whether to propose downsize:
   - Proceed if: Advisor recommendation exists + CPU < 5% confirmed + no recent deployments
     + estimated savings > $20/month
   - Defer if: Bursty workload pattern detected (CPU spikes) or recent deployment activity
   - Skip if: VM is tagged 'protected' or in a change-freeze window

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** Propose VM SKU downsize via `propose_vm_sku_downsize`.
   - Use `target_sku` from Advisor recommendation (Step 1)
   - Set `justification`: "CPU utilization <5% for 7 days. Advisor recommends {target_sku}
     with ${savings}/month savings."
   - *Reversibility:* reversible (resize back to original SKU via propose_vm_resize)
   - *Estimated impact:* ~5-10 min downtime (deallocate/resize/start)
   - *Approval message:* "Approve downsizing {vm_name} from {current_sku} to {target_sku}?
     Estimated savings: {savings_currency} {savings}/month."

## Escalation
- If VM is tagged 'protected': do not propose remediation; log and close as informational
- If CPU has any spikes > 20%: escalate for workload pattern review before downsizing
- If Advisor shows no recommendations after 48h: escalate to FinOps team for manual review

## Rollback
- Resize back to original SKU via `propose_vm_resize` with the original SKU
- Original SKU is preserved in the ApprovalRecord `resource_snapshot` field

## References
- Azure Advisor rightsizing recommendations: https://learn.microsoft.com/en-us/azure/advisor/advisor-cost-recommendations
- Azure VM sizes: https://learn.microsoft.com/en-us/azure/virtual-machines/sizes
- Related SOPs: vm-high-cpu.md, sre-cost-optimisation.md
