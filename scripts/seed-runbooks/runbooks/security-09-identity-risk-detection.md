---
title: "Entra ID Risk Detection Response"
domain: security
version: "1.0"
tags: ["entra-id", "identity-protection", "risk", "user-risk", "sign-in-risk", "conditional-access"]
---

## Symptoms

Microsoft Entra ID Identity Protection raises a user risk or sign-in risk detection. Risk events include leaked credentials, anonymous IP address sign-in, impossible travel, unfamiliar sign-in properties, or malware-linked IP addresses. The affected user may be locked out by Conditional Access policies requiring MFA or password change. The security team receives an Identity Protection alert requiring investigation and remediation.

## Root Causes

1. Credential leak — the user's password was found in a known data breach database and the account is flagged as high risk.
2. Sign-in from anonymous proxy or Tor exit node — user or attacker used an anonymizing network.
3. Impossible travel detection — authentication from two geographically distant locations within a time window that cannot be explained by legitimate travel.
4. Attacker using valid credentials from a reconnaissance phase to probe Azure resources.

## Diagnostic Steps

1. View the risk detections for the user in Entra ID:
   ```bash
   az rest --method GET \
     --uri "https://graph.microsoft.com/v1.0/identityProtection/riskDetections?\$filter=userPrincipalName eq '{upn}' and riskState eq 'atRisk'" \
     --query "value[].{id:id,type:riskEventType,level:riskLevel,state:riskState,detail:riskDetail,time:detectedDateTime,ip:ipAddress}"
   ```
2. Review the full risk history for the user:
   ```kql
   AADUserRiskEvents
   | where UserPrincipalName == "{upn}"
   | where TimeGenerated > ago(7d)
   | project TimeGenerated, RiskEventType, RiskLevel, RiskState, IpAddress, Location, DetectionTimingType
   | order by TimeGenerated desc
   ```
3. Check if the user account shows signs of compromise:
   ```kql
   SigninLogs
   | where UserPrincipalName == "{upn}"
   | where TimeGenerated > ago(24h)
   | project TimeGenerated, IPAddress, Location, AppDisplayName, ConditionalAccessStatus, AuthenticationRequirement, RiskLevelDuringSignIn
   | order by TimeGenerated desc
   ```
4. Check for post-compromise activity (suspicious operations after the risk event):
   ```kql
   AzureActivity
   | where Caller == "{upn}"
   | where TimeGenerated > todatetime("{risk_event_time}")
   | project TimeGenerated, OperationNameValue, ResourceId, ActivityStatusValue, CallerIpAddress
   | order by TimeGenerated desc
   ```
5. Verify Conditional Access policy is enforcing remediation for risky users:
   ```bash
   az rest --method GET \
     --uri "https://graph.microsoft.com/v1.0/identity/conditionalAccess/policies" \
     --query "value[?conditions.userRiskLevels[?@ in ['high','medium']]].{name:displayName,state:state,controls:grantControls.builtInControls}"
   ```

## Remediation Commands

```bash
# Confirm user identity and force password reset
az ad user update --id {upn} \
  --force-change-password-next-sign-in true

# Revoke all existing sessions
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/users/{user_id}/revokeSignInSessions"

# Dismiss a false positive risk detection
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/identityProtection/riskDetections/{detection_id}/dismiss"

# Confirm user compromise and mark account as high risk (for SOC workflow)
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/identityProtection/riskyUsers/confirmCompromised" \
  --body '{"userIds": ["{user_id}"]}'
```

## Rollback Procedure

If a password reset was triggered for a false positive, the user will need to set a new password on next sign-in — this is the standard flow and cannot be reversed without another admin intervention. To dismiss a false positive risk event after investigation, use the Entra ID portal or the dismiss API endpoint. Document the investigation outcome for the user's security file and update Identity Protection named locations if the risk was triggered by a legitimate IP (e.g., new office or VPN range).
