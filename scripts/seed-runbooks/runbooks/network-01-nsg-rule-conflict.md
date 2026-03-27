---
title: "NSG Rule Conflict Resolution"
domain: network
version: "1.0"
tags: ["nsg", "firewall", "security-group", "rule-conflict", "network"]
---

## Symptoms

Traffic that should be allowed is being blocked, or traffic that should be denied is passing through. Azure Network Watcher IP Flow Verify returns unexpected results. Application connectivity tests fail intermittently based on source IP or destination port. NSG flow logs show "Deny" entries for expected traffic patterns.

## Root Causes

1. A higher-priority deny rule shadowing a lower-priority allow rule for the same port range.
2. An overly broad deny rule applied at the subnet NSG level overriding a more specific allow rule at the NIC NSG level.
3. Service tag expansion change — a Microsoft-managed service tag was updated to include new IP ranges that conflict with custom rules.
4. Recently added emergency deny rule during an incident that was not removed after the incident was resolved.

## Diagnostic Steps

1. Run IP Flow Verify to confirm which rule is causing the block:
   ```bash
   az network watcher test-ip-flow \
     --vm {vm_name} \
     --direction Inbound \
     --protocol TCP \
     --local-ip {private_ip} \
     --local-port {dest_port} \
     --remote-ip {source_ip} \
     --remote-port 12345 \
     --resource-group {rg}
   ```
2. List effective NSG rules in priority order on the NIC:
   ```bash
   az network nic list-effective-nsg \
     --resource-group {rg} --name {nic_name} \
     --query "networkSecurityGroups[*].effectiveSecurityRules[?access=='Deny' && direction=='Inbound']" \
     --output table
   ```
3. List all rules on both subnet and NIC NSGs to compare:
   ```bash
   az network nsg rule list --resource-group {rg} --nsg-name {subnet_nsg} --include-default --output table
   az network nsg rule list --resource-group {rg} --nsg-name {nic_nsg} --include-default --output table
   ```
4. Check NSG flow logs for deny events in the last hour:
   ```kql
   AzureNetworkAnalytics_CL
   | where SubType_s == "FlowLog"
   | where FlowStatus_s == "D"
   | where SrcIP_s == "{source_ip}" and DestPort_d == {port}
   | where TimeGenerated > ago(1h)
   | project TimeGenerated, SrcIP_s, DestPort_d, NSGRule_s, FlowStatus_s
   ```
5. Identify the conflicting rule pair by priority:
   ```bash
   az network nsg rule list --resource-group {rg} --nsg-name {nsg_name} \
     --query "sort_by([],&priority)[].{priority:priority,name:name,access:access,port:destinationPortRange}" \
     --output table
   ```

## Remediation Commands

```bash
# Increase priority of allow rule to be higher than the conflicting deny rule
az network nsg rule update \
  --resource-group {rg} --nsg-name {nsg_name} \
  --name {allow_rule_name} --priority 100

# Delete the conflicting deny rule (if it was a temporary emergency rule)
az network nsg rule delete \
  --resource-group {rg} --nsg-name {nsg_name} --name {deny_rule_name}

# Create a targeted allow rule with higher priority than the broad deny
az network nsg rule create \
  --resource-group {rg} --nsg-name {nsg_name} \
  --name AllowSpecificTraffic --priority 150 --direction Inbound \
  --access Allow --protocol Tcp \
  --source-address-prefixes {source_cidr} \
  --destination-port-ranges {port}
```

## Rollback Procedure

NSG rule changes are immediately effective and reversible. If the rule change created an unintended security gap, re-add the deny rule and re-test. All NSG changes are recorded in the Azure Activity Log and can be replayed or reversed. Enable NSG flow logs on the affected NSG before making changes to capture a before/after baseline for comparison.
