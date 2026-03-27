---
title: "Load Balancer Health Probe Failure"
domain: network
version: "1.0"
tags: ["load-balancer", "health-probe", "backend-pool", "azure-lb", "availability"]
---

## Symptoms

Requests to an Azure Load Balancer return 502 or connection timeout errors. Traffic is not distributed to backend VMs. The Load Balancer backend pool health status shows one or more instances as "Unhealthy" or all instances removed from rotation. Azure Monitor load balancer metrics show health probe success rate below 100%.

## Root Causes

1. Backend VM application process crashed or stopped listening on the probe port.
2. NSG rule on the backend subnet blocking the health probe source IP range (`168.63.129.16`).
3. Health probe timeout too short — the application takes longer than the configured probe interval to respond during startup.
4. Backend VM OS firewall (iptables or Windows Firewall) blocking the probe on the local port.

## Diagnostic Steps

1. Check current health probe status for all backend instances:
   ```bash
   az network lb show --resource-group {rg} --name {lb_name} \
     --query "backendAddressPools[0].loadBalancingRules"
   az network lb probe list --resource-group {rg} --lb-name {lb_name} \
     --output table
   ```
2. Query Azure Monitor for probe failures per backend instance:
   ```bash
   az monitor metrics list \
     --resource {lb_resource_id} \
     --metric "DipAvailability" \
     --dimension "BackendIPAddress" "BackendPort" \
     --interval PT1M --start-time $(date -u -d '-1 hour' +%FT%TZ)
   ```
3. Check if NSG is blocking probe traffic from `168.63.129.16`:
   ```bash
   az network nic list-effective-nsg \
     --resource-group {rg} --name {backend_nic_name} \
     --query "networkSecurityGroups[*].effectiveSecurityRules[?contains(sourceAddressPrefix,'168.63.129.16')]"
   ```
4. Test the probe endpoint directly from the backend VM:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {backend_vm} \
     --command-id RunShellScript \
     --scripts "curl -sI http://127.0.0.1:{probe_port}{probe_path} | head -5"
   ```
5. Review load balancer health event logs:
   ```kql
   AzureDiagnostics
   | where ResourceProvider == "MICROSOFT.NETWORK" and Category == "LoadBalancerHealthEvent"
   | where ResourceId contains "{lb_name}"
   | where TimeGenerated > ago(1h)
   | project TimeGenerated, backendIPAddress_s, healthProbeResult_s, message_s
   ```

## Remediation Commands

```bash
# Allow probe traffic from Azure platform IP 168.63.129.16
az network nsg rule create \
  --resource-group {rg} --nsg-name {backend_nsg} \
  --name AllowAzureLoadBalancerProbe --priority 100 --direction Inbound \
  --access Allow --protocol Tcp \
  --source-address-prefixes AzureLoadBalancer \
  --destination-port-ranges {probe_port}

# Increase probe timeout and interval for slow-starting applications
az network lb probe update \
  --resource-group {rg} --lb-name {lb_name} \
  --name {probe_name} \
  --interval 15 --threshold 3

# Restart the application on unhealthy backend VMs
az vm run-command invoke --resource-group {rg} --name {backend_vm} \
  --command-id RunShellScript \
  --scripts "systemctl restart {app_service_name} && sleep 10 && systemctl status {app_service_name}"
```

## Rollback Procedure

If the probe configuration change caused unexpected behavior (e.g., removing healthy instances too slowly), revert the probe interval and threshold to previous values. If adding the NSG rule opened an unintended port, scope the rule to `AzureLoadBalancer` service tag only (which maps to `168.63.129.16`). All load balancer configuration changes take effect within 1-2 seconds.
