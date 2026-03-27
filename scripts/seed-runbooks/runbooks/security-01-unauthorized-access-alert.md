---
title: "Unauthorized Access Alert Triage"
domain: security
version: "1.0"
tags: ["security", "unauthorized-access", "alert", "defender", "audit-log", "soc"]
---

## Symptoms

Microsoft Defender for Cloud or Microsoft Sentinel raises a high-severity alert for unauthorized access activity. Azure Monitor alert fires for unusual sign-in attempts or resource access from unexpected IP addresses or locations. The security operations team receives a notification requiring immediate triage to determine if this is a true positive attack or a false positive from a legitimate but unusual access pattern.

## Root Causes

1. Compromised user credentials used from an unfamiliar location or device.
2. Service principal secret or API key leaked and used by an external actor.
3. Brute force attack against Azure AD or a VM's SSH/RDP port.
4. Legitimate access from a new IP range (e.g., VPN change, employee travel) triggering location-based anomaly detection.

## Diagnostic Steps

1. Review the Defender for Cloud alert details:
   ```bash
   az security alert show --resource-group {rg} --location {region} \
     --name {alert_name} \
     --query "{title:alertDisplayName,severity:severity,time:generatedDateTime,entities:entities,description:description}"
   ```
2. Look up the suspicious IP address in Entra ID sign-in logs:
   ```bash
   az monitor activity-log list \
     --start-time $(date -u -d '-4 hours' +%FT%TZ) \
     --query "[?claims.ipaddr=='{suspicious_ip}'].{time:eventTimestamp,caller:caller,op:operationName.value,status:status.value}"
   ```
3. Check Entra ID sign-in risk detections:
   ```kql
   SigninLogs
   | where IPAddress == "{suspicious_ip}"
   | where TimeGenerated > ago(24h)
   | project TimeGenerated, UserPrincipalName, Location, RiskLevelDuringSignIn, ConditionalAccessStatus, ResultType
   | order by TimeGenerated desc
   ```
4. Identify all resources accessed by the suspicious identity:
   ```kql
   AzureActivity
   | where Caller == "{suspicious_upn_or_sp}"
   | where TimeGenerated > ago(24h)
   | summarize Operations=make_set(OperationNameValue) by ResourceId
   | order by array_length(Operations) desc
   ```
5. Check if MFA was used or bypassed:
   ```kql
   SigninLogs
   | where UserPrincipalName == "{upn}"
   | where TimeGenerated > ago(4h)
   | project TimeGenerated, AuthenticationDetails, MfaDetail, ConditionalAccessStatus
   ```

## Remediation Commands

```bash
# Disable the compromised user account immediately
az ad user update --id {user_upn} --account-enabled false

# Revoke all active sessions for the user
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/users/{user_id}/revokeSignInSessions"

# Block suspicious IP in the Azure tenant via Conditional Access
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/identity/conditionalAccess/namedLocations" \
  --body '{"displayName":"BlockedIP-{suspicious_ip}","isTrusted":false,"ipRanges":[{"cidrAddress":"{suspicious_ip}/32"}]}'

# Rotate service principal credentials if SP was compromised
az ad sp credential reset --id {sp_id} --append false
```

## Rollback Procedure

If the account disable was a false positive (legitimate admin from a new location), re-enable the account: `az ad user update --id {user_upn} --account-enabled true`. Unblock the IP in Conditional Access if it belongs to a legitimate VPN range. Document the investigation findings in the security incident ticket and update Named Locations in Conditional Access to include the newly approved IP range to prevent future false positives.
