---
title: "MFA Bypass Attempt Alert"
domain: security
version: "1.0"
tags: ["mfa", "multi-factor-authentication", "bypass", "entra-id", "conditional-access", "security"]
---

## Symptoms

Microsoft Sentinel or Defender for Identity raises an alert for an MFA bypass attempt or suspicious authentication pattern. Entra ID risk detection shows a "Suspicious inbox manipulation rules" or "Token theft" detection. Sign-in logs show successful authentications from unusual locations or devices that did not complete the expected MFA challenge. Conditional Access policies should have enforced MFA but authentication succeeded without it.

## Root Causes

1. Adversary-in-the-middle (AiTM) phishing attack — attacker proxied the authentication flow and captured the session cookie after MFA was completed.
2. Legacy authentication protocol in use (Basic Auth, IMAP, POP3) that cannot support MFA challenges.
3. Conditional Access policy gap — a device compliance exclusion or trusted location exception was exploited.
4. Service account using password authentication exempted from MFA via a Conditional Access exclusion that was too broad.

## Diagnostic Steps

1. Review the suspicious sign-in details in Entra ID:
   ```kql
   SigninLogs
   | where UserPrincipalName == "{target_upn}"
   | where TimeGenerated > ago(4h)
   | project TimeGenerated, IPAddress, Location, DeviceDetail, AuthenticationDetails, MfaDetail, ConditionalAccessStatus, RiskLevelDuringSignIn
   | order by TimeGenerated desc
   ```
2. Check if legacy authentication was used:
   ```kql
   SigninLogs
   | where UserPrincipalName == "{target_upn}"
   | where ClientAppUsed in ("Exchange ActiveSync", "IMAP", "POP3", "SMTP", "Other clients")
   | where TimeGenerated > ago(24h)
   | project TimeGenerated, ClientAppUsed, IPAddress, Location, ResultType
   ```
3. Audit active sessions for token theft indicators:
   ```kql
   AADNonInteractiveUserSignInLogs
   | where UserPrincipalName == "{target_upn}"
   | where IPAddress != "{known_corp_ip}"
   | where TimeGenerated > ago(4h)
   | project TimeGenerated, IPAddress, AppDisplayName, ResourceDisplayName, TokenIssuedAt
   ```
4. Check for inbox rule creation (common post-compromise action):
   ```kql
   OfficeActivity
   | where UserId == "{target_upn}"
   | where Operation == "New-InboxRule" or Operation == "Set-InboxRule"
   | where TimeGenerated > ago(24h)
   | project TimeGenerated, ClientIPAddress, Parameters
   ```
5. Review Conditional Access policy coverage for the user:
   ```bash
   az rest --method GET \
     --uri "https://graph.microsoft.com/v1.0/identity/conditionalAccess/policies" \
     --query "value[?conditions.users.includeUsers[?@=='{user_id}'] || conditions.users.includeGroups].{name:displayName,state:state}"
   ```

## Remediation Commands

```bash
# Immediately revoke all active sessions
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/users/{user_id}/revokeSignInSessions"

# Reset user password to invalidate token-derived sessions
az ad user update --id {user_upn} \
  --password {temp_secure_password} \
  --force-change-password-next-sign-in true

# Block legacy authentication protocols via Conditional Access
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/identity/conditionalAccess/policies" \
  --body '{
    "displayName": "Block Legacy Authentication",
    "state": "enabled",
    "conditions": {"clientAppTypes": ["exchangeActiveSync","other"]},
    "grantControls": {"operator":"OR","builtInControls":["block"]}
  }'
```

## Rollback Procedure

Session revocation forces the user to re-authenticate with full MFA on the next login — this is intentional and not reversible per session. If the Conditional Access policy blocking legacy auth breaks a critical integration (e.g., a printer using SMTP), add a narrowly scoped service account exclusion. File a security incident report with the Microsoft DART team if token theft is confirmed.
