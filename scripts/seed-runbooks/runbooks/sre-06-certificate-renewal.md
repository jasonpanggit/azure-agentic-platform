---
title: "TLS Certificate Renewal"
domain: sre
version: "1.0"
tags: ["sre", "tls", "certificate", "ssl", "renewal", "key-vault", "app-gateway"]
---

## Symptoms

Azure Monitor alerts that a TLS certificate is within 30 days of expiry. Applications start receiving SSL handshake errors. Browser warnings about expiring certificates appear in user-facing services. Application Gateway, Azure Front Door, or Container Apps Custom Domain health checks fail due to an expired certificate. The operations team must renew and deploy the certificate before it expires.

## Root Causes

1. Certificate auto-rotation not configured — manual renewal process was missed or forgotten.
2. Key Vault certificate renewal contact email not configured — the built-in renewal notification system was not set up.
3. Certificate Authority (CA) changed its validation process, breaking the auto-renewal flow.
4. Certificate bound to a static file rather than Key Vault, preventing automated rotation.

## Diagnostic Steps

1. Check certificate expiry dates in Key Vault:
   ```bash
   az keyvault certificate list --vault-name {kv_name} \
     --query "[].{name:name,expires:attributes.expires}" --output table
   ```
2. Get detailed certificate information:
   ```bash
   az keyvault certificate show --vault-name {kv_name} --name {cert_name} \
     --query "{subject:policy.x509CertificateProperties.subject,sans:policy.x509CertificateProperties.subjectAlternativeNames,expires:attributes.expires,issuer:policy.issuerParameters.name,autoRenew:policy.lifetimeActions}"
   ```
3. Check Application Gateway certificate binding:
   ```bash
   az network application-gateway ssl-cert list \
     --resource-group {rg} --gateway-name {appgw_name} \
     --query "[].{name:name,keyVault:keyVaultSecretId}" --output table
   ```
4. Check Container Apps custom domain certificate:
   ```bash
   az containerapp hostname list \
     --resource-group {rg} --name {app_name} \
     --query "[].{hostname:name,bindingType:bindingType,certificateId:certificateId}" --output table
   ```
5. Verify certificate by checking the live TLS endpoint:
   ```bash
   echo | openssl s_client -connect {domain}:443 -servername {domain} 2>/dev/null \
     | openssl x509 -text -noout | grep -A2 "Validity"
   ```

## Remediation Commands

```bash
# Renew certificate in Key Vault (if issuer is DigiCert or Let's Encrypt via Key Vault integration)
az keyvault certificate create \
  --vault-name {kv_name} \
  --name {cert_name} \
  --policy @cert-policy.json

# Import a renewed certificate from a PFX file
az keyvault certificate import \
  --vault-name {kv_name} \
  --name {cert_name} \
  --file {path_to_cert.pfx} \
  --password {pfx_password}

# Update Application Gateway to use the new certificate version
az network application-gateway ssl-cert update \
  --resource-group {rg} --gateway-name {appgw_name} \
  --name {cert_name} \
  --key-vault-secret-id $(az keyvault certificate show \
    --vault-name {kv_name} --name {cert_name} \
    --query "sid" --output tsv)

# Configure auto-renewal policy (90 days before expiry)
az keyvault certificate set-attributes --vault-name {kv_name} --name {cert_name} \
  --policy '{"lifetimeActions":[{"trigger":{"daysBeforeExpiry":90},"action":{"actionType":"AutoRenew"}}]}'
```

## Rollback Procedure

If the new certificate causes unexpected SSL errors (e.g., certificate chain not trusted by some clients), revert to the previous certificate version in Key Vault: `az keyvault certificate show-versions --vault-name {kv_name} --name {cert_name}` to list versions, then update the Application Gateway to reference the previous version's secret ID. Always test certificate renewal in staging first using a short-lived test domain before applying to production.
