---
title: "VPN Gateway Connectivity Loss"
domain: network
version: "1.0"
tags: ["vpn", "gateway", "connectivity", "ipsec", "site-to-site", "tunnel"]
---

## Symptoms

A Site-to-Site VPN connection between Azure VPN Gateway and an on-premises network drops. Hybrid workloads lose connectivity to on-premises resources. Azure Monitor VPN metrics show tunnel state as "Disconnected" and packet loss across the tunnel. BGP session may be down if using BGP-enabled VPN Gateway.

## Root Causes

1. IKE/IPsec policy mismatch after a firmware update on the on-premises VPN device.
2. Pre-shared key rotation on one side without updating the other.
3. Azure VPN Gateway maintenance event causing a brief tunnel reset that the on-premises device did not recover from.
4. Dead Peer Detection (DPD) timeout — the tunnel was idle long enough that the peer declared it dead without initiating renegotiation.

## Diagnostic Steps

1. Check VPN connection status and last error:
   ```bash
   az network vpn-connection show \
     --resource-group {rg} --name {vpn_connection_name} \
     --query "{state:connectionStatus,ingressBytes:ingressBytesTransferred,egressBytes:egressBytesTransferred,lastError:sharedKey}"
   ```
2. Get BGP peer status (if BGP enabled):
   ```bash
   az network vnet-gateway list-bgp-peer-status \
     --resource-group {rg} --name {vgw_name} \
     --peer {on_prem_bgp_ip} --output table
   ```
3. Check learned routes from VPN:
   ```bash
   az network vnet-gateway list-learned-routes \
     --resource-group {rg} --name {vgw_name} \
     --output table | grep {on_prem_network}
   ```
4. Query VPN gateway diagnostics logs:
   ```kql
   AzureDiagnostics
   | where ResourceProvider == "MICROSOFT.NETWORK" and Category == "GatewayDiagnosticLog"
   | where ResourceId contains "{vgw_name}"
   | where Message contains "IKE" or Message contains "IPsec" or Message contains "error"
   | where TimeGenerated > ago(2h)
   | project TimeGenerated, Message
   | order by TimeGenerated desc
   ```
5. Run VPN troubleshooting to capture detailed diagnostic packet:
   ```bash
   az network vnet-gateway vnet-gateway-vpn-client-package generate \
     --resource-group {rg} --name {vgw_name}
   # Then initiate diagnostics capture
   az network vnet-gateway start-packet-capture --resource-group {rg} --name {vgw_name}
   ```

## Remediation Commands

```bash
# Reset the VPN connection to force IKE renegotiation
az network vpn-connection reset --resource-group {rg} --name {vpn_connection_name}

# Reset the VPN gateway (use only as last resort — causes brief downtime for all connections)
az network vnet-gateway reset --resource-group {rg} --name {vgw_name}

# Update shared key if it was changed on on-premises device
az network vpn-connection shared-key update \
  --connection-name {vpn_connection_name} \
  --resource-group {rg} --value {new_psk}

# Verify IKE policy matches on-premises settings
az network vpn-connection ipsec-policy add \
  --resource-group {rg} --connection-name {vpn_connection_name} \
  --ike-encryption AES256 --ike-integrity SHA256 \
  --dh-group DHGroup14 --ipsec-encryption AES256 \
  --ipsec-integrity SHA256 --pfs-group PFS2048 \
  --sa-lifetime 27000 --sa-data-size 102400000
```

## Rollback Procedure

VPN connection resets are non-destructive — the tunnel will attempt renegotiation automatically. If the IPsec policy change caused connectivity loss (policy mismatch), remove the custom policy with `az network vpn-connection ipsec-policy clear` to return to the default policy. Coordinate with the on-premises network team before making IKE policy changes to ensure both sides are updated simultaneously.
