---
title: "NSG Open Port Compliance Audit"
domain: security
version: "1.0"
tags: ["nsg", "compliance", "open-port", "security", "remediation", "audit"]
---

## Symptoms

An Azure Policy compliance report or Defender for Cloud recommendation flags multiple Network Security Groups with overly permissive inbound rules. Rules allowing any source (`*` or `Internet`) to management ports (22, 3389, 5985, 1433) are flagged as non-compliant. The organization's security posture score is reduced, and SOC 2/ISO 27001 audit findings cite the open ports as a control gap.

## Root Causes

1. Default allow rules for SSH/RDP left in place after initial VM deployment for convenience.
2. Temporary rules added during a troubleshooting session never removed.
3. Terraform `any source` rule used as a placeholder during development and promoted to production.
4. Third-party compliance requirements for specific ports incorrectly scoped to `Any` source.

## Diagnostic Steps

1. List all NSGs with overly permissive inbound rules:
   ```bash
   az network nsg list --subscription {subscription_id} \
     --query "[].{name:name,rg:resourceGroup,rules:securityRules[?sourceAddressPrefix=='*' && access=='Allow' && direction=='Inbound'].{name:name,port:destinationPortRange,priority:priority}}" \
     --output json | python3 -c "import sys,json; [print(n['name'],r) for n in json.load(sys.stdin) if n.get('rules') for r in n['rules']]"
   ```
2. Check Defender for Cloud NSG recommendations:
   ```bash
   az security assessment list \
     --query "[?contains(displayName,'Management ports') || contains(displayName,'SSH') || contains(displayName,'RDP')].{name:displayName,status:statusCode,count:additionalData.affectedResourcesCount}" \
     --output table
   ```
3. Find NSGs with port 22 or 3389 open to the internet:
   ```bash
   az network nsg list --subscription {subscription_id} --output json | \
     python3 -c "
   import sys, json
   nsgs = json.load(sys.stdin)
   for nsg in nsgs:
     for rule in nsg.get('securityRules', []):
       ports = rule.get('destinationPortRange', '')
       src = rule.get('sourceAddressPrefix', '')
       if rule.get('access') == 'Allow' and rule.get('direction') == 'Inbound':
         if ('22' in ports or '3389' in ports) and src in ('*', 'Internet', '0.0.0.0/0'):
           print(f\"{nsg['name']}: {rule['name']} allows {ports} from {src}\")
   "
   ```
4. Check Azure Policy compliance for the subscription:
   ```bash
   az policy state list --subscription {subscription_id} \
     --filter "policyDefinitionName eq '9daedab3-fb2d-461e-b861-71790eebb998'" \
     --query "[?complianceState=='NonCompliant'].{resource:resourceId,rule:policyDefinitionReferenceId}"
   ```
5. List all VMs attached to the non-compliant NSGs:
   ```bash
   az network nic list --resource-group {rg} \
     --query "[?networkSecurityGroup.id contains '{nsg_name}'].{nic:name,vm:virtualMachine.id}" \
     --output table
   ```

## Remediation Commands

```bash
# Change source from * to a specific IP range (replace with actual management IP)
az network nsg rule update \
  --resource-group {rg} --nsg-name {nsg_name} --name {rule_name} \
  --source-address-prefixes {corp_vpn_cidr}

# Delete the wildcard rule entirely if JIT is used instead
az network nsg rule delete \
  --resource-group {rg} --nsg-name {nsg_name} --name {open_port_rule_name}

# Enable Just-in-Time VM access for controlled port opening
az security jit-policy create \
  --resource-group {rg} --name default \
  --virtual-machines '[{"id":"{vm_resource_id}","ports":[{"number":22,"protocol":"TCP","allowedSourceAddressPrefix":"*","maxRequestAccessDuration":"PT3H"}]}]'
```

## Rollback Procedure

If restricting the source IP breaks legitimate access (e.g., a remote team member's IP was not included in the CIDR), add the additional IP to the source address prefixes: `az network nsg rule update --source-address-prefixes {ip1} {ip2}`. Enable Azure Bastion as a long-term alternative to direct port 22/3389 exposure, completely eliminating the need for public-facing management ports. Document all approved source IP ranges in the CMDB.
