---
title: "Autoscale Misconfiguration"
domain: sre
version: "1.0"
tags: ["sre", "autoscale", "vmss", "container-apps", "scaling", "misconfiguration"]
---

## Symptoms

Azure resources are not scaling as expected. An autoscale configuration shows rules that should trigger scale-out or scale-in but no scaling events occur. Alternatively, resources are scaling too aggressively, causing cost spikes or service instability due to too-frequent scale-in events. Azure Monitor autoscale logs show "flapping" (rapid alternating scale-out/in) or no scaling events despite metrics exceeding thresholds.

## Root Causes

1. Cooldown period too short — scale-in fires immediately after scale-out because the cooldown window does not allow metrics to stabilize.
2. Metric threshold misconfigured — scale-out condition set to CPU > 90% when average is only 50%, or scale-in too aggressive at < 20%.
3. Min/max replica bounds too narrow — minimum equals maximum, preventing any scaling from occurring.
4. Multiple conflicting autoscale profiles — a recurrence-based profile conflicts with the default profile.

## Diagnostic Steps

1. Check autoscale configuration:
   ```bash
   az monitor autoscale show \
     --resource-group {rg} --name {autoscale_name} \
     --query "{min:profiles[0].capacity.minimum,max:profiles[0].capacity.maximum,default:profiles[0].capacity.default,rules:profiles[0].rules}"
   ```
2. Review autoscale history for recent events:
   ```bash
   az monitor autoscale history list \
     --autoscale-name {autoscale_name} --resource-group {rg} \
     --query "[?timestamp>'$(date -u -d '-24 hours' +%FT%TZ)'].{time:timestamp,op:message,new:newValue}" \
     --output table
   ```
3. Check current metric value vs threshold:
   ```bash
   az monitor metrics list \
     --resource {vmss_resource_id} \
     --metric "Percentage CPU" \
     --interval PT5M --start-time $(date -u -d '-1 hour' +%FT%TZ) \
     --output table
   ```
4. Check for autoscale flapping (rapid scale changes):
   ```kql
   AzureActivity
   | where ResourceProvider == "Microsoft.Insights"
   | where OperationNameValue == "microsoft.insights/autoscalesettings/scaleaction/action"
   | where ResourceGroup == "{rg}"
   | where TimeGenerated > ago(24h)
   | summarize ScaleCount=count() by bin(TimeGenerated, 1h)
   | order by TimeGenerated desc
   ```
5. Verify metric source and aggregation type:
   ```bash
   az monitor autoscale show --resource-group {rg} --name {autoscale_name} \
     --query "profiles[0].rules[].{metric:metricName,threshold:threshold,op:operator,cooldown:cooldown,scaleAction:scaleAction}"
   ```

## Remediation Commands

```bash
# Fix flapping: increase cooldown periods
az monitor autoscale rule update \
  --autoscale-name {autoscale_name} --resource-group {rg} \
  --scale-direction increase --cooldown 10 --scale-out-cooldown PT10M

az monitor autoscale rule update \
  --autoscale-name {autoscale_name} --resource-group {rg} \
  --scale-direction decrease --cooldown 30 --scale-in-cooldown PT30M

# Fix too-narrow range
az monitor autoscale update \
  --autoscale-name {autoscale_name} --resource-group {rg} \
  --min-count 2 --max-count 20 --count 3

# Fix Container Apps scaling (scale-to-zero concerns)
az containerapp update \
  --resource-group {rg} --name {app_name} \
  --min-replicas 1 --max-replicas 30 \
  --scale-rule-name http-scaling \
  --scale-rule-http-concurrency 100

# Temporarily disable autoscale for manual investigation
az monitor autoscale update \
  --autoscale-name {autoscale_name} --resource-group {rg} \
  --enabled false
```

## Rollback Procedure

Re-enable autoscale with corrected settings: `az monitor autoscale update --enabled true`. If manual investigation shows the workload requires fixed capacity for now, set min and max to the same value to effectively pin the replica count while the autoscale rules are analyzed. Use Azure Monitor metrics explorer to simulate what scaling decisions would have been made with different threshold values before applying changes to production.
