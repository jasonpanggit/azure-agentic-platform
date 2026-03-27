---
title: "Subnet IP Address Exhaustion"
domain: network
version: "1.0"
tags: ["subnet", "ip-address", "cidr", "exhaustion", "capacity", "networking"]
---

## Symptoms

New VM deployments, AKS nodes, or Container App workloads fail with "AllocationFailed" or "Subnet has insufficient private IP addresses" errors. The subnet address space is fully allocated. Azure Monitor alerts on low available IPs in the subnet. Autoscale operations fail because new instances cannot obtain IP addresses.

## Root Causes

1. Subnet CIDR block sized too small at creation time relative to peak workload growth.
2. IP addresses reserved by failed or orphaned resources (deleted NICs, load balancer frontend configs) not released.
3. AKS node pool scaled out consuming all remaining IPs faster than anticipated.
4. Azure service reservations consuming IPs (first 4 and last 1 IP in each subnet are reserved by Azure).

## Diagnostic Steps

1. Count available IPs remaining in the subnet:
   ```bash
   az network vnet subnet show \
     --resource-group {rg} --vnet-name {vnet_name} --name {subnet_name} \
     --query "{prefix:addressPrefix,available:ipConfigurationReferences}"
   # Use Network Watcher for accurate count
   az network watcher show-topology --resource-group {rg} --location {region} \
     | python3 -c "import sys,json; d=json.load(sys.stdin); [print(r) for r in d.get('resources',[]) if '{subnet_name}' in str(r)]"
   ```
2. List all IP configurations using IPs in the subnet:
   ```bash
   az network nic list --resource-group {rg} \
     --query "[?ipConfigurations[0].subnet.id contains '{subnet_name}'].{name:name,ip:ipConfigurations[0].privateIpAddress,vm:virtualMachine.id}" \
     --output table
   ```
3. Find orphaned NICs not attached to any VM:
   ```bash
   az network nic list --resource-group {rg} \
     --query "[?virtualMachine==null && ipConfigurations[0].subnet.id contains '{subnet_name}'].{name:name,ip:ipConfigurations[0].privateIpAddress}" \
     --output table
   ```
4. Check current subnet utilization percentage:
   ```bash
   TOTAL=$(python3 -c "import ipaddress; n=ipaddress.ip_network('{subnet_cidr}'); print(n.num_addresses - 5)")
   USED=$(az network nic list --resource-group {rg} --query "length([?ipConfigurations[0].subnet.id contains '{subnet_name}'])" --output tsv)
   echo "Used: $USED / $TOTAL"
   ```
5. Check AKS node count if AKS is in the subnet:
   ```bash
   az aks nodepool list --resource-group {rg} --cluster-name {aks_name} \
     --query "[].{pool:name,count:count,vmSize:vmSize}" --output table
   ```

## Remediation Commands

```bash
# Delete orphaned NICs to free IPs
az network nic delete --resource-group {rg} --name {orphaned_nic_name}

# Add a new subnet to the VNet for overflow capacity
az network vnet subnet create \
  --resource-group {rg} --vnet-name {vnet_name} \
  --name {new_subnet_name} --address-prefixes 10.1.2.0/24

# Expand the existing subnet (only possible if address space allows and no other subnets conflict)
az network vnet subnet update \
  --resource-group {rg} --vnet-name {vnet_name} \
  --name {subnet_name} --address-prefixes 10.1.1.0/23

# Move AKS node pool to new subnet
az aks nodepool add --resource-group {rg} --cluster-name {aks_name} \
  --name newpool --node-count 3 --vnet-subnet-id {new_subnet_resource_id}
```

## Rollback Procedure

Subnet expansion is one-way — shrinking an already expanded subnet is not possible if IPs in the new range are allocated. Plan expansions carefully. Adding a new subnet for overflow is the safest remediation as it does not affect existing resources. Document the new CIDR allocations in the IP address management (IPAM) system and update the VNet address space diagram.
