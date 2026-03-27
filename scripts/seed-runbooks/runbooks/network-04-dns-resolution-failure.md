---
title: "DNS Resolution Failure"
domain: network
version: "1.0"
tags: ["dns", "azure-dns", "private-dns", "resolution", "private-endpoint"]
---

## Symptoms

VMs or services in the Azure VNet cannot resolve DNS names for Azure PaaS services (e.g., `*.postgres.database.azure.com`, `*.vault.azure.net`) or custom domain names. Connections fail with `NXDOMAIN` or `SERVFAIL` errors. Private endpoint resources are unreachable by FQDN despite the private endpoint being provisioned correctly. On-premises clients cannot resolve Azure private zone records.

## Root Causes

1. Private DNS zone not linked to the VNet — the private DNS zone exists but is not associated with the querying VNet.
2. DNS forwarding misconfiguration in a hub-and-spoke topology — spoke VNet DNS is not forwarded to the hub DNS resolver.
3. Custom DNS server set on the VNet pointing to an on-premises resolver that does not forward Azure DNS queries to `168.63.129.16`.
4. Private DNS zone A record deleted or pointing to the wrong private IP after resource recreation.

## Diagnostic Steps

1. Test DNS resolution from a VM in the affected VNet:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {test_vm} \
     --command-id RunShellScript \
     --scripts "nslookup {fqdn} && dig {fqdn} && cat /etc/resolv.conf"
   ```
2. Check if the private DNS zone is linked to the VNet:
   ```bash
   az network private-dns link vnet list \
     --resource-group {rg} --zone-name {private_dns_zone} \
     --query "[].{vnet:virtualNetwork.id,enabled:registrationEnabled,state:provisioningState}" \
     --output table
   ```
3. Verify the private DNS zone has an A record for the resource:
   ```bash
   az network private-dns record-set a list \
     --resource-group {rg} --zone-name {private_dns_zone} \
     --query "[].{name:name,ip:aRecords[0].ipv4Address}"
   ```
4. Check VNet DNS server configuration:
   ```bash
   az network vnet show --resource-group {rg} --name {vnet_name} \
     --query "dhcpOptions.dnsServers"
   ```
5. Check private endpoint DNS configuration:
   ```bash
   az network private-endpoint show \
     --resource-group {rg} --name {pe_name} \
     --query "customDnsConfigs"
   az network private-endpoint dns-zone-group list \
     --resource-group {rg} --endpoint-name {pe_name}
   ```

## Remediation Commands

```bash
# Link the private DNS zone to the missing VNet
az network private-dns link vnet create \
  --resource-group {rg} \
  --zone-name {private_dns_zone} \
  --name link-to-{vnet_name} \
  --virtual-network {vnet_name} \
  --registration-enabled false

# Add missing A record for the private endpoint IP
az network private-dns record-set a add-record \
  --resource-group {rg} \
  --zone-name {private_dns_zone} \
  --record-set-name {hostname} \
  --ipv4-address {private_endpoint_ip}

# Set VNet DNS to use Azure default (168.63.129.16)
az network vnet update --resource-group {rg} --name {vnet_name} \
  --dns-servers ""
```

## Rollback Procedure

DNS zone links and record additions are safe to revert. If the VNet DNS server change caused unintended resolution breaks for on-premises forwarding, restore the previous custom DNS server IP: `az network vnet update --dns-servers {previous_dns_ip}`. DNS changes propagate within seconds in Azure. Test resolution from multiple VMs across subnets after making changes to confirm the fix is effective across the network.
