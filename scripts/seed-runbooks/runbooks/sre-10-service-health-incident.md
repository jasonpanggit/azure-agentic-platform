---
title: "Azure Service Health Incident Response"
domain: sre
version: "1.0"
tags: ["sre", "service-health", "incident", "azure-status", "communication", "availability"]
---

## Symptoms

Azure Service Health reports an active service issue affecting one or more Azure services in regions where the platform operates. Users report application errors or degraded performance that correlates with the Azure-side incident. Azure Monitor alerts fire for services that depend on the affected Azure service. The operations team must assess the impact, communicate status to stakeholders, and implement workarounds while Azure resolves the underlying platform issue.

## Root Causes

1. Azure infrastructure failure in a specific availability zone or region causing service degradation.
2. Azure platform software deployment causing unexpected behavior in customer workloads.
3. Azure service capacity constraint causing throttling or unavailability for new requests.
4. Third-party network provider issue affecting Azure's connectivity to certain regions or ISPs.

## Diagnostic Steps

1. Check active Azure Service Health incidents:
   ```bash
   az rest --method GET \
     --uri "https://management.azure.com/subscriptions/{sub}/providers/Microsoft.ResourceHealth/events?api-version=2022-10-01&\$filter=EventType eq 'ServiceIssue' and Status eq 'Active'" \
     --query "value[].{id:name,title:properties.title,service:properties.impactedServices[0].serviceName,region:properties.impactedRegions[0].id,level:properties.impactMitigationTime}"
   ```
2. Check service health for specific resources:
   ```bash
   az resource health list --resource-group {rg} \
     --query "[?availabilityState!='Available'].{resource:id,state:availabilityState,summary:summary,reason:reasonType}" \
     --output table
   ```
3. Determine which workloads are directly affected:
   ```kql
   AppRequests
   | where TimeGenerated > ago(2h)
   | summarize FailureCount=countif(Success==false), TotalCount=count(), FailureRate=round(countif(Success==false)*100.0/count(),1) by AppRoleName, bin(TimeGenerated, 5m)
   | where FailureRate > 5
   | order by TimeGenerated desc
   ```
4. Set up Service Health alert for the duration of the incident:
   ```bash
   az monitor activity-log alert create \
     --resource-group {rg} \
     --name service-health-alert-$(date +%Y%m%d) \
     --scope /subscriptions/{sub} \
     --condition "category=ServiceHealth and level=Critical and service={affected_service}" \
     --action-group {action_group_id}
   ```
5. Check Azure Status page programmatically for public incident status:
   ```bash
   curl -s "https://azure.status.microsoft/en-us/status/feed/" | \
     python3 -c "import sys,xml.etree.ElementTree as ET; tree=ET.parse(sys.stdin); root=tree.getroot(); [print(item.find('title').text, item.find('pubDate').text) for item in root.findall('./channel/item')[:5]]"
   ```

## Remediation Commands

```bash
# Activate Traffic Manager failover to secondary region
az network traffic-manager endpoint update \
  --resource-group {rg} --profile-name {tm_profile} \
  --name {primary_endpoint} --endpoint-status Disabled

# Scale up secondary region to absorb traffic
az containerapp update \
  --resource-group {rg_secondary} --name {app_name} \
  --min-replicas 5 --max-replicas 30

# Enable Azure Front Door failover if configured
az afd endpoint update \
  --resource-group {rg} --profile-name {afd_profile} \
  --endpoint-name {endpoint_name} \
  --enabled-state Enabled

# Send status update to stakeholders (via Teams webhook)
curl -X POST {teams_webhook_url} \
  -H "Content-Type: application/json" \
  -d '{"text":"**Service Health Incident**: {title}. Impact: {impact}. Workaround: Traffic shifted to secondary region. Updates every 30 min."}'
```

## Rollback Procedure

Once Azure declares the incident mitigated via Service Health, gradually restore traffic to the primary region. Use Traffic Manager weighted routing to shift traffic incrementally: start at 10% primary, monitor error rates, then increase to 50%, then 100% over 30-60 minutes. After full restoration, set the secondary region back to warm-standby capacity (minimum replicas). File the incident in the post-mortem tracker and document the actual RTO/RPO achieved vs targets.
