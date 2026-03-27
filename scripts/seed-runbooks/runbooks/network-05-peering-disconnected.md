---
title: "VNet Peering Disconnected"
domain: network
version: "1.0"
tags: ["vnet", "peering", "connectivity", "hub-spoke", "network"]
---

## Symptoms

Traffic between two peered Azure Virtual Networks stops flowing. VMs in peer VNets cannot ping each other or reach services across the peering. Azure Network Watcher connectivity tests between the two VNets fail. The peering state changes from "Connected" to "Disconnected" or "Initiated". Hub-and-spoke topologies where spokes communicate via the hub are fully disrupted.

## Root Causes

1. VNet peering deleted on one side — Azure requires peering to be created in both VNets, and deletion of one side disconnects both.
2. Address space conflict — one of the VNets had its address space modified to overlap with the peer.
3. Gateway transit configuration changed — `allowGatewayTransit` or `useRemoteGateways` flag modified without coordination.
4. Subscription moved or VNet deleted and recreated — peering links are not automatically re-established after resource recreation.

## Diagnostic Steps

1. Check peering state on both sides:
   ```bash
   az network vnet peering list --resource-group {rg_a} --vnet-name {vnet_a} \
     --query "[].{name:name,state:peeringState,remoteVnet:remoteVirtualNetwork.id}" --output table

   az network vnet peering list --resource-group {rg_b} --vnet-name {vnet_b} \
     --query "[].{name:name,state:peeringState,remoteVnet:remoteVirtualNetwork.id}" --output table
   ```
2. Verify address spaces do not overlap:
   ```bash
   az network vnet show --resource-group {rg_a} --name {vnet_a} --query "addressSpace.addressPrefixes"
   az network vnet show --resource-group {rg_b} --name {vnet_b} --query "addressSpace.addressPrefixes"
   ```
3. Check the effective routes on VMs in both VNets to see if peering routes are present:
   ```bash
   az network nic show-effective-route-table \
     --resource-group {rg_a} --name {nic_in_vnet_a} \
     --query "value[?nextHopType=='VNetPeering']" --output table
   ```
4. Test connectivity with Network Watcher:
   ```bash
   az network watcher test-connectivity \
     --source-resource {vm_in_vnet_a_id} \
     --dest-address {ip_in_vnet_b} --dest-port 22 \
     --resource-group {nw_rg}
   ```
5. Check Activity Log for any peering modification events:
   ```bash
   az monitor activity-log list \
     --resource-type Microsoft.Network/virtualNetworks/virtualNetworkPeerings \
     --start-time $(date -u -d '-24 hours' +%FT%TZ) \
     --query "[].{time:eventTimestamp,op:operationName.value,status:status.value,caller:caller}"
   ```

## Remediation Commands

```bash
# Delete and recreate the peering on both sides (atomic fix)
# Side A
az network vnet peering delete --resource-group {rg_a} --vnet-name {vnet_a} --name {peering_a_to_b}
az network vnet peering create \
  --resource-group {rg_a} --vnet-name {vnet_a} \
  --name {peering_a_to_b} \
  --remote-vnet {vnet_b_resource_id} \
  --allow-vnet-access --allow-forwarded-traffic

# Side B
az network vnet peering delete --resource-group {rg_b} --vnet-name {vnet_b} --name {peering_b_to_a}
az network vnet peering create \
  --resource-group {rg_b} --vnet-name {vnet_b} \
  --name {peering_b_to_a} \
  --remote-vnet {vnet_a_resource_id} \
  --allow-vnet-access --allow-forwarded-traffic
```

## Rollback Procedure

VNet peering creation is low risk and immediately effective. If address space overlap is the root cause, the overlapping address space must be resolved before the peering can be re-established — this requires reassigning IP ranges in the affected VNet which may involve VM re-IP or reconfiguration. Use Azure Network Manager for large-scale peering management to prevent ad-hoc configuration drift.
