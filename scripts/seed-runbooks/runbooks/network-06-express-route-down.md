---
title: "ExpressRoute Circuit Down"
domain: network
version: "1.0"
tags: ["expressroute", "circuit", "bgp", "connectivity", "hybrid", "on-premises"]
---

## Symptoms

Hybrid connectivity between Azure and on-premises data centers is lost. ExpressRoute circuit state shows as "Not Provisioned" or "No Circuit Provisioned". BGP session is down and no routes are being exchanged between Azure and the on-premises edge. All traffic falling back to VPN gateway (if configured as backup) may be saturating that link.

## Root Causes

1. Physical fiber cut or connectivity issue between on-premises edge and the ExpressRoute provider peering location.
2. BGP session misconfiguration — ASN or authentication key mismatch after a router config change.
3. ExpressRoute circuit billing issue causing provider-side deprovisioning.
4. Microsoft peering or private peering configuration drift after an Azure infrastructure maintenance event.

## Diagnostic Steps

1. Check ExpressRoute circuit provisioning and service provider state:
   ```bash
   az network express-route show \
     --resource-group {rg} --name {er_circuit_name} \
     --query "{state:serviceProviderProvisioningState,circuitState:circuitProvisioningState,bandwidth:serviceProviderProperties.bandwidthInMbps}"
   ```
2. Check BGP peer state for private peering:
   ```bash
   az network express-route list-route-tables \
     --resource-group {rg} --name {er_circuit_name} \
     --peering-name AzurePrivatePeering \
     --path primary --device-path primary
   ```
3. Verify gateway connection to the ExpressRoute circuit:
   ```bash
   az network vpn-connection show \
     --resource-group {rg} --name {er_connection_name} \
     --query "{state:connectionStatus,routingWeight:routingWeight,expressRoute:peer.id}"
   ```
4. Check circuit ARP tables to confirm Layer 2 connectivity:
   ```bash
   az network express-route list-arp-tables \
     --resource-group {rg} --name {er_circuit_name} \
     --peering-name AzurePrivatePeering \
     --path primary --device-path primary
   ```
5. Query Azure Monitor for circuit-level metrics:
   ```bash
   az monitor metrics list \
     --resource {er_circuit_resource_id} \
     --metric "BitsInPerSecond" "BitsOutPerSecond" \
     --interval PT5M --start-time $(date -u -d '-2 hours' +%FT%TZ)
   ```

## Remediation Commands

```bash
# Reset BGP peers on the ExpressRoute connection
az network vnet-gateway reset --resource-group {rg} --name {er_gateway_name}

# Update peering BGP authentication key if mismatch detected
az network express-route peering update \
  --resource-group {rg} --circuit-name {er_circuit_name} \
  --peering-type AzurePrivatePeering \
  --shared-key {new_bgp_key}

# Re-enable circuit after provider has confirmed their side is up
az network express-route update \
  --resource-group {rg} --name {er_circuit_name} \
  --sku-tier Premium --sku-family MeteredData

# Trigger a support request for provider-side investigation
az support tickets create \
  --ticket-name "ExpressRoute-Down-$(date +%Y%m%d)" \
  --title "ExpressRoute circuit {er_circuit_name} is down" \
  --problem-classification "/providers/Microsoft.Support/services/expressroute/problemClassifications/connectivity"
```

## Rollback Procedure

ExpressRoute circuit issues are typically resolved by coordinating with the service provider. Ensure the VPN Gateway failover path is activated and capacity is sufficient for the duration of the outage. Document the BGP peer state and ARP tables before any reset operations. Once the provider confirms the circuit is restored, verify BGP session re-establishment and route advertisement before deactivating the VPN failover path.
