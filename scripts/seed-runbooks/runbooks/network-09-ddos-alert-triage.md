---
title: "DDoS Alert Triage"
domain: network
version: "1.0"
tags: ["ddos", "network-protection", "ddos-standard", "alert", "traffic", "mitigation"]
---

## Symptoms

Azure DDoS Protection Standard fires a "DDoS attack ongoing" alert for a public IP address. Traffic volume to the affected resource spikes significantly above the baseline. Application latency increases and some requests time out. Azure Monitor DDoS metrics show elevated packet or byte rates with active mitigation flags. Some legitimate users may be rate-limited as a side effect of DDoS mitigation.

## Root Causes

1. Volumetric DDoS attack — UDP flood, ICMP flood, or TCP SYN flood saturating inbound bandwidth.
2. Protocol attack — exploiting network protocol vulnerabilities (TCP state exhaustion, fragmented packet attacks).
3. Application layer attack (L7) — HTTP/S request flood targeting application logic rather than bandwidth.
4. False positive — legitimate traffic surge (e.g., viral event, marketing campaign) triggering DDoS thresholds.

## Diagnostic Steps

1. Check DDoS protection status for the public IP:
   ```bash
   az network ddos-protection show \
     --resource-group {rg} --name {ddos_plan_name} \
     --query "{virtualNetworks:virtualNetworks,id:id}"
   az network public-ip show --resource-group {rg} --name {pip_name} \
     --query "ddosSettings"
   ```
2. Query DDoS mitigation metrics:
   ```bash
   az monitor metrics list \
     --resource {public_ip_resource_id} \
     --metric "IfUnderDDoSAttack" "DDoSTriggerTCPPackets" "DDoSTriggerUDPPackets" \
     --interval PT1M --start-time $(date -u -d '-2 hours' +%FT%TZ)
   ```
3. Analyze traffic patterns to identify attack vector:
   ```kql
   AzureDiagnostics
   | where ResourceProvider == "MICROSOFT.NETWORK" and Category == "DDoSMitigationFlowLogs"
   | where publicIpAddress_s == "{public_ip}"
   | where TimeGenerated > ago(1h)
   | summarize TotalPackets=sum(bytesForwardedDDoS_d) by bin(TimeGenerated, 5m), protocol_s
   | order by TimeGenerated desc
   ```
4. Check upstream NSG flow logs to identify top attacker IPs:
   ```kql
   AzureNetworkAnalytics_CL
   | where PublicIPs_s contains "{public_ip}"
   | where FlowStatus_s == "A" and TimeGenerated > ago(1h)
   | summarize PacketCount=sum(PacketsSrcToDest_d) by SrcIP_s
   | order by PacketCount desc | take 20
   ```
5. Verify the DDoS Protection Plan is associated with the VNet:
   ```bash
   az network vnet show --resource-group {rg} --name {vnet_name} \
     --query "ddosProtectionPlan"
   ```

## Remediation Commands

```bash
# Confirm DDoS Standard is enabled on the VNet (if not already)
az network vnet update --resource-group {rg} --name {vnet_name} \
  --ddos-protection true --ddos-protection-plan {ddos_plan_id}

# Create an NSG block rule for confirmed attacker IPs (supplement auto-mitigation)
az network nsg rule create \
  --resource-group {rg} --nsg-name {frontend_nsg} \
  --name BlockAttackerIPs --priority 90 --direction Inbound \
  --access Deny --protocol "*" \
  --source-address-prefixes {attacker_ip_1} {attacker_ip_2}

# Generate DDoS diagnostic report for the incident
az network public-ip ddos-protection-status show \
  --resource-group {rg} --name {pip_name}
```

## Rollback Procedure

DDoS mitigation is automatic and self-reverting — Azure DDoS Standard removes mitigation policies once attack traffic falls below threshold. Manual NSG deny rules added for attacker IPs should be reviewed and removed once the attack subsides to avoid accumulating stale rules. File an Azure support ticket after the incident to receive the DDoS Rapid Response team report documenting the attack vectors and mitigation effectiveness.
