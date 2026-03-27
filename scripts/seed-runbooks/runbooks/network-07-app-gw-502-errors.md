---
title: "Application Gateway 502 Errors"
domain: network
version: "1.0"
tags: ["application-gateway", "502", "backend", "waf", "http", "load-balancing"]
---

## Symptoms

Clients receive HTTP 502 Bad Gateway errors from an Azure Application Gateway. The gateway is running and accessible, but requests are not completing successfully. Azure Monitor shows failed requests spiking. The Application Gateway access log shows `StatusSent: 502` entries. Backend pool health shows instances as unhealthy.

## Root Causes

1. Backend application is not responding within the Application Gateway timeout (default 20 seconds).
2. Backend response header or body size exceeds Application Gateway limits.
3. SSL certificate mismatch between Application Gateway backend HTTP settings and the backend server certificate.
4. WAF blocking requests that are being misidentified as malicious (false positive from CRS rule set).

## Diagnostic Steps

1. Check backend health for all backend pools:
   ```bash
   az network application-gateway show-backend-health \
     --resource-group {rg} --name {appgw_name} \
     --query "backendAddressPools[*].backendHttpSettingsCollection[*].servers[*].{ip:address,health:health,reason:healthProbeLog}" \
     --output table
   ```
2. Query Application Gateway access logs for 502 patterns:
   ```kql
   AzureDiagnostics
   | where ResourceProvider == "MICROSOFT.NETWORK" and Category == "ApplicationGatewayAccessLog"
   | where httpStatus_d == 502
   | where TimeGenerated > ago(1h)
   | summarize count() by serverStatus_s, userAgent_s, requestUri_s
   | order by count_ desc
   ```
3. Check WAF firewall log for blocked requests:
   ```kql
   AzureDiagnostics
   | where ResourceProvider == "MICROSOFT.NETWORK" and Category == "ApplicationGatewayFirewallLog"
   | where action_s == "Blocked"
   | where TimeGenerated > ago(1h)
   | project TimeGenerated, ruleSetType_s, ruleId_s, message_s, clientIP_s, requestUri_s
   ```
4. Check Application Gateway backend HTTP settings timeout configuration:
   ```bash
   az network application-gateway http-settings list \
     --resource-group {rg} --gateway-name {appgw_name} \
     --query "[].{name:name,port:port,timeout:requestTimeout,protocol:protocol}" --output table
   ```
5. Test backend connectivity from Application Gateway:
   ```bash
   az network application-gateway show-backend-health \
     --resource-group {rg} --name {appgw_name} \
     --servers {backend_ip} --address-pool {pool_name}
   ```

## Remediation Commands

```bash
# Increase request timeout on backend HTTP settings
az network application-gateway http-settings update \
  --resource-group {rg} --gateway-name {appgw_name} \
  --name {http_settings_name} --timeout 60

# Switch WAF from Prevention to Detection mode to stop blocking
az network application-gateway waf-policy policy-setting update \
  --resource-group {rg} --policy-name {waf_policy_name} \
  --mode Detection

# Add WAF custom rule exclusion for a false-positive rule
az network application-gateway waf-policy exclusion add \
  --resource-group {rg} --policy-name {waf_policy_name} \
  --match-variable RequestHeaderNames \
  --selector-match-operator Contains \
  --selector "User-Agent"

# Drain backend instance gracefully
az network application-gateway address-pool update \
  --resource-group {rg} --gateway-name {appgw_name} \
  --name {pool_name} --servers {remaining_healthy_ips}
```

## Rollback Procedure

If switching WAF to Detection mode allows malicious traffic, re-enable Prevention mode and create specific exclusions for the false-positive rules instead. If the timeout increase masked a genuine performance problem, revert the timeout and investigate backend application latency. All Application Gateway configuration changes take effect within 1-2 minutes and are fully reversible.
