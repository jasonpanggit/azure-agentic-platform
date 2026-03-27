---
title: "Resource Tag Compliance Remediation"
domain: sre
version: "1.0"
tags: ["sre", "tags", "compliance", "policy", "governance", "cost-management"]
---

## Symptoms

Azure Policy compliance dashboard shows a large percentage of resources non-compliant with tagging requirements. Cost allocation reports cannot attribute spending to business units due to missing `costcenter`, `environment`, or `owner` tags. Azure Advisor governance recommendations flag missing tags. Automated chargeback processes fail because tag-based filtering returns insufficient results.

## Root Causes

1. Resources deployed without tags via the Azure portal, bypassing IaC pipelines that enforce tagging.
2. Azure Policy "Append" or "Modify" tag policies not assigned to all subscriptions or resource groups.
3. Resources created before the tagging policy was implemented and never retroactively tagged.
4. Automated deployments using CLI or SDK calls that do not pass tag parameters.

## Diagnostic Steps

1. Check tagging compliance percentage by subscription:
   ```bash
   az policy state list \
     --query "[?policyDefinitionCategory=='Tagging' && complianceState=='NonCompliant'].{resource:resourceId,policy:policyDefinitionName}" \
     --output table | wc -l
   ```
2. Find all resources missing required tags:
   ```bash
   REQUIRED_TAGS=("environment" "costcenter" "owner")
   for tag in "${REQUIRED_TAGS[@]}"; do
     echo "=== Missing tag: $tag ==="
     az resource list --subscription {subscription_id} \
       --query "[?tags.$tag==null].{name:name,type:type,rg:resourceGroup}" \
       --output table | head -20
   done
   ```
3. Check which resource types most commonly lack tags:
   ```bash
   az resource list --subscription {subscription_id} \
     --query "[?tags.environment==null].type" --output tsv | sort | uniq -c | sort -rn | head -20
   ```
4. View existing Azure Policy tag enforcement assignments:
   ```bash
   az policy assignment list \
     --query "[?contains(displayName,'tag') || contains(displayName,'Tag')].{name:displayName,scope:scope,effect:parameters.effect.value}" \
     --output table
   ```
5. Get the count of non-compliant resources by resource group:
   ```bash
   az policy state list \
     --query "[?policyDefinitionCategory=='Tagging' && complianceState=='NonCompliant'].resourceGroup" \
     --output tsv | sort | uniq -c | sort -rn | head -20
   ```

## Remediation Commands

```bash
# Bulk-tag all resources in a resource group
az resource list --resource-group {rg} --query "[].id" --output tsv | \
  xargs -I{} az resource tag --ids {} \
    --tags environment={env} costcenter={cc} owner={team} managed-by=terraform

# Apply tag with Azure Policy "Modify" effect for all new resources
az policy assignment create \
  --name tag-policy-{env} \
  --scope /subscriptions/{subscription_id} \
  --policy {tag_policy_definition_id} \
  --params '{"tagName":{"value":"environment"},"tagValue":{"value":"{env}"}}'

# Run remediation task for existing non-compliant resources
az policy remediation create \
  --name tag-remediation-$(date +%Y%m%d) \
  --policy-assignment {tag_policy_assignment_id} \
  --resource-discovery-mode ExistingNonCompliant

# Tag resources missing environment tag in a subscription
az tag create --resource-id /subscriptions/{subscription_id} \
  --tags environment={env}
```

## Rollback Procedure

Tag additions are non-destructive — existing tags are not affected by adding new tags. If an incorrect tag value was applied in bulk, update it with the correct value: `az resource tag --ids {resource_id} --tags {key}={correct_value}`. After the bulk remediation, re-run the compliance scan to confirm the compliance percentage has improved. Review and tighten the Azure Policy assignment to use "Deny" effect for future resources without required tags to prevent recurrence.
