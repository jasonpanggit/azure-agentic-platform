---
title: "Private Endpoint Unreachable"
domain: network
version: "1.0"
tags: ["private-endpoint", "private-link", "dns", "connectivity", "paaS"]
---

## Symptoms

Services connecting to an Azure PaaS resource (Azure SQL, Cosmos DB, Key Vault, Storage) via Private Endpoint fail with connection timeouts or "Name resolution failure" errors. The PaaS resource is healthy and accessible from the public internet but unreachable from inside the VNet via the private endpoint. Network Watcher connectivity tests from VNet VMs to the private endpoint IP fail.

## Root Causes

1. Private DNS zone not linked to the VNet — the private endpoint DNS A record exists but the zone resolving it is not associated with the querying VNet.
2. Private endpoint NIC is in a failed or stuck provisioning state.
3. NSG applied to the private endpoint subnet blocking traffic (private endpoints ignore NSG rules by default in some regions — but NSG policies on endpoints can be enabled).
4. DNS conditional forwarder on custom DNS server not forwarding the PaaS FQDN to Azure DNS (`168.63.129.16`).

## Diagnostic Steps

1. Verify private endpoint provisioning state:
   ```bash
   az network private-endpoint show \
     --resource-group {rg} --name {pe_name} \
     --query "{state:provisioningState,connectionState:privateLinkServiceConnections[0].privateLinkServiceConnectionState.status,ip:customDnsConfigs[0].ipAddresses[0]}"
   ```
2. Test connectivity from a VM to the private endpoint IP:
   ```bash
   az network watcher test-connectivity \
     --source-resource {test_vm_resource_id} \
     --dest-address {private_endpoint_ip} \
     --dest-port {resource_port} \
     --resource-group {nw_rg}
   ```
3. Verify DNS resolution returns the private IP:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {test_vm} \
     --command-id RunShellScript \
     --scripts "nslookup {paaS_fqdn} && dig +short {paaS_fqdn}"
   ```
4. Check that the private DNS zone has the correct A record:
   ```bash
   az network private-dns record-set a list \
     --resource-group {rg} --zone-name {private_dns_zone_name} \
     --query "[].{name:name,fqdn:fqdn,ip:aRecords[0].ipv4Address}"
   ```
5. Confirm the DNS zone is linked to the VNet:
   ```bash
   az network private-dns link vnet list \
     --resource-group {rg} --zone-name {private_dns_zone_name} \
     --query "[?virtualNetwork.id contains '{vnet_name}'].{name:name,state:provisioningState}"
   ```

## Remediation Commands

```bash
# Link the private DNS zone to the VNet
az network private-dns link vnet create \
  --resource-group {rg} \
  --zone-name {private_dns_zone_name} \
  --name {vnet_name}-link \
  --virtual-network {vnet_resource_id} \
  --registration-enabled false

# Recreate the private endpoint DNS zone group (auto-creates DNS record)
az network private-endpoint dns-zone-group create \
  --resource-group {rg} \
  --endpoint-name {pe_name} \
  --name default \
  --private-dns-zone {private_dns_zone_id} \
  --zone-name {private_dns_zone_name}

# Add private endpoint network policy (required to apply NSG to PE subnet)
az network vnet subnet update \
  --resource-group {rg} --vnet-name {vnet_name} --name {pe_subnet_name} \
  --disable-private-endpoint-network-policies false
```

## Rollback Procedure

DNS zone link creation is non-destructive. If an incorrect DNS record was added and caused resolution to return the wrong IP, delete the incorrect record with `az network private-dns record-set a remove-record` and recreate the DNS zone group to auto-populate the correct private endpoint IP. Monitor connectivity tests for 2-3 minutes after the fix to confirm DNS TTL has expired and new records are being returned.
