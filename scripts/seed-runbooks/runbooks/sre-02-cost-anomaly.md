---
title: "Cost Anomaly Investigation"
domain: sre
version: "1.0"
tags: ["sre", "cost", "billing", "anomaly", "budget", "optimization"]
---

## Symptoms

Azure Cost Management detects an unexpected cost spike and sends a budget alert. Monthly spend is tracking significantly above forecast. Azure Advisor identifies cost optimization opportunities that were previously not triggered. Finance team receives an unexpected invoice and requests an investigation. The cost anomaly email notification shows a specific resource group, service, or subscription driving the spike.

## Root Causes

1. Runaway resource scaling — an autoscale configuration with no maximum limit scaled out uncontrollably.
2. Forgotten test or development resources left running — dev VMs, load testing infrastructure, or staging environments not shut down.
3. Accidental deployment of large SKU VMs — a misconfigured IaC template deployed expensive GPU or HPC SKUs.
4. Data egress explosion — unexpected outbound data transfer due to a logging misconfiguration or a data exfiltration event.

## Diagnostic Steps

1. View cost breakdown by service and resource:
   ```bash
   az costmanagement query \
     --scope /subscriptions/{subscription_id} \
     --type Usage \
     --dataset '{
       "granularity": "Daily",
       "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
       "grouping": [{"type": "Dimension", "name": "ResourceId"}, {"type": "Dimension", "name": "ServiceName"}]
     }' \
     --time-period "from={start_date}T00:00:00Z" "to={end_date}T23:59:59Z"
   ```
2. Identify the top 10 most expensive resources:
   ```bash
   az consumption usage list --start-date {start_date} --end-date {end_date} \
     --query "sort_by([],&pretaxCost)[-10:].{resource:instanceName,service:consumedService,cost:pretaxCost}" \
     --output table
   ```
3. Check for resources without required cost tags:
   ```bash
   az resource list --subscription {subscription_id} \
     --query "[?tags.environment==null || tags.costcenter==null].{name:name,type:type,rg:resourceGroup}" \
     --output table | head -30
   ```
4. Check VMSS scaling history for autoscale runaway:
   ```bash
   az monitor autoscale history list \
     --autoscale-name {autoscale_name} --resource-group {rg} \
     --query "[?contains(message,'ScaleOut')].{time:timestamp,count:newValue}" --output table
   ```
5. Review data egress metrics for unexpected traffic:
   ```bash
   az monitor metrics list \
     --resource /subscriptions/{sub}/resourceGroups/{rg} \
     --metric "EgressBandwidth" \
     --interval PT1H --start-time {spike_start_time} --output table
   ```

## Remediation Commands

```bash
# Immediately shut down unneeded dev/test resources
az vm deallocate --resource-group {rg} --name {vm_name}
az vmss scale --resource-group {rg} --name {vmss_name} --new-capacity 0

# Set autoscale maximum to prevent runaway
az monitor autoscale update \
  --autoscale-name {autoscale_name} --resource-group {rg} \
  --max-count 10

# Set a budget alert for the subscription
az consumption budget create \
  --account-name "" --budget-name monthly-budget-$(date +%Y%m) \
  --amount 5000 --time-grain Monthly \
  --start-date $(date +%Y-%m-01) --end-date $(date -d '+1 year' +%Y-%m-01) \
  --category Cost \
  --notification "threshold=80,operator=GreaterThan,contactEmails={admin_email}"

# Delete orphaned resources identified in the audit
az resource delete --ids {orphaned_resource_id}
```

## Rollback Procedure

Deallocated VMs can be restarted: `az vm start`. Scaled-down VMSS can be scaled back up. Budget alerts are non-destructive monitoring tools. After addressing the immediate cost driver, conduct a monthly cost optimization review using Azure Advisor recommendations and implement resource tagging enforcement via Azure Policy to prevent untagged resources from being deployed in future.
