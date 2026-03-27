---
title: "Multi-Region Failover Procedure"
domain: sre
version: "1.0"
tags: ["sre", "disaster-recovery", "failover", "multi-region", "traffic-manager", "availability"]
---

## Symptoms

The primary Azure region hosting production workloads is experiencing a major outage. Azure Service Health confirms a regional service disruption. Application health probes in the primary region are failing. Traffic Manager or Azure Front Door health checks show the primary endpoint as degraded. The RTO clock is ticking and the team must execute the regional failover procedure to restore service availability from the secondary region.

## Root Causes

1. Azure regional outage — Azure infrastructure in the primary region is unavailable due to power, cooling, or network failure.
2. Application-level failure in the primary region — all primary-region deployments are unhealthy due to a cascading failure.
3. Planned maintenance requiring a controlled failover to the secondary region.
4. Data corruption in the primary region requiring a point-in-time restore from the secondary.

## Diagnostic Steps

1. Confirm the regional outage via Azure Service Health:
   ```bash
   az rest --method GET \
     --uri "https://management.azure.com/subscriptions/{sub}/providers/Microsoft.ResourceHealth/events?api-version=2022-10-01" \
     --query "value[?properties.eventType=='ServiceIssue' && properties.status=='Active'].{title:properties.title,region:properties.impactedRegions[0].id,time:properties.activatedTime}"
   ```
2. Verify primary region endpoint health via Traffic Manager:
   ```bash
   az network traffic-manager endpoint show \
     --resource-group {rg} --profile-name {tm_profile} \
     --name {primary_endpoint} \
     --query "{status:endpointStatus,monitor:endpointMonitorStatus}"
   ```
3. Check database replication lag before failover:
   ```bash
   # Cosmos DB
   az cosmosdb show --resource-group {rg} --name {cosmos_account} \
     --query "writeLocations[0].locationName"
   # PostgreSQL
   az postgres flexible-server replica list --resource-group {rg} --name {primary_server} \
     --query "[].{name:name,replicationState:replicationState,lag:replicationLag}"
   ```
4. Verify secondary region resources are healthy:
   ```bash
   az network traffic-manager endpoint show \
     --resource-group {rg} --profile-name {tm_profile} \
     --name {secondary_endpoint} --query "endpointMonitorStatus"
   az containerapp show --resource-group {rg_secondary} --name {app_name} \
     --query "properties.provisioningState"
   ```
5. Check current DNS TTL and estimate DNS propagation time:
   ```bash
   az network traffic-manager profile show \
     --resource-group {rg} --name {tm_profile} --query "dnsConfig.ttl"
   ```

## Remediation Commands

```bash
# Step 1: Disable primary endpoint to route all traffic to secondary
az network traffic-manager endpoint update \
  --resource-group {rg} --profile-name {tm_profile} \
  --name {primary_endpoint} --status Disabled

# Step 2: Scale up secondary region Container Apps
az containerapp update --resource-group {rg_secondary} --name {app_name} \
  --min-replicas 3 --max-replicas 10

# Step 3: Failover Cosmos DB write region
az cosmosdb failover-priority-change --resource-group {rg} \
  --name {cosmos_account} \
  --failover-policies {secondary_region}=0 {primary_region}=1

# Step 4: Promote PostgreSQL replica to primary
az postgres flexible-server replica stop-replication \
  --resource-group {rg_secondary} --name {replica_server}

# Step 5: Update DNS TTL to 60s for faster future failovers
az network traffic-manager profile update \
  --resource-group {rg} --name {tm_profile} --ttl 60
```

## Rollback Procedure

To fail back to the primary region after it recovers: re-enable the primary Traffic Manager endpoint, re-establish database replication with the secondary as the new replica, and gradually shift traffic back using Traffic Manager weighted routing. Plan a 24-hour stabilization window in the secondary region before attempting failback to ensure the primary region is fully stable. Document RPO and RTO achieved in the incident post-mortem for SLA reporting.
