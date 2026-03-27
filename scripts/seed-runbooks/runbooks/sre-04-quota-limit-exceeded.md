---
title: "Azure Quota Limit Exceeded"
domain: sre
version: "1.0"
tags: ["sre", "quota", "limit", "capacity", "subscription", "scaling"]
---

## Symptoms

Deployment or scaling operations fail with "QuotaExceeded" or "OperationNotAllowed" errors citing insufficient quota for a specific resource type. Azure Monitor shows deployment failures. New VM, AKS node, or Container App deployments are blocked. The error message specifies which quota limit has been reached (vCPUs, public IP addresses, storage accounts, etc.).

## Root Causes

1. Regional vCPU quota for a specific VM family exhausted by organic workload growth.
2. Public IP address quota hit in a region due to large-scale deployment.
3. Storage account per-subscription quota reached by automated test or dev environment creation.
4. AKS node pool scale-out hitting the subscription's vCore limit for the specified SKU family.

## Diagnostic Steps

1. Check current quota usage for a specific resource type:
   ```bash
   az vm list-usage --location {region} \
     --query "[?currentValue>=limit || currentValue>(limit * 0.8)].{name:name.localizedValue,current:currentValue,limit:limit,pct:to_string(currentValue * 100 / limit)}" \
     --output table
   ```
2. Check compute quota specifically for vCPU families:
   ```bash
   az vm list-usage --location {region} \
     --query "[?contains(name.value,'Family') && currentValue>(limit * 0.7)].{family:name.value,used:currentValue,limit:limit}" \
     --output table
   ```
3. Check network quota (public IPs, VNets):
   ```bash
   az network list-usages --location {region} \
     --query "[?currentValue>=limit].{name:name.localizedValue,used:currentValue,limit:limit}" \
     --output table
   ```
4. Check storage quota:
   ```bash
   az storage account list --subscription {subscription_id} --query "length([])" --output tsv
   # Default limit is 250 accounts per subscription per region
   az storage account list --subscription {subscription_id} \
     --query "[?location=='{region}'].name" --output tsv | wc -l
   ```
5. Identify which resource groups are consuming the most of the quota:
   ```bash
   az vm list --subscription {subscription_id} \
     --query "[?location=='{region}'].{rg:resourceGroup,size:hardwareProfile.vmSize}" \
     --output tsv | cut -f1 | sort | uniq -c | sort -rn | head -10
   ```

## Remediation Commands

```bash
# Request quota increase via Azure CLI (opens support ticket)
az support tickets create \
  --ticket-name "Quota-Increase-$(date +%Y%m%d)" \
  --title "Request increase for Standard_DSv3Family vCPUs in {region}" \
  --problem-classification "/providers/Microsoft.Support/services/quota/problemClassifications/compute" \
  --severity minimal \
  --description "Current limit: {current_limit}. Requesting increase to {requested_limit}."

# Short-term: deallocate unused VMs in the region to free quota
az vm list --resource-group {rg} --query "[?powerState=='VM deallocated'].name" --output tsv

# Alternative: use a different SKU family with available quota
az vm list-skus --location {region} \
  --query "[?restrictions[0].reasonCode!='NotAvailableForSubscription' && capabilities[?name=='vCPUs'].value=='4'].name" \
  --output tsv | head -10

# Scale out to a different region if quota is unavailable in the primary
az containerapp update --resource-group {rg_alt} --name {app_name} \
  --min-replicas {required_count}
```

## Rollback Procedure

Quota increase requests are non-destructive — approval typically takes 1-3 business days via the standard process or minutes via the Azure Portal "New Support Request" for common SKUs. While waiting for approval, consider temporarily reducing non-critical workloads in the quota-constrained region to free headroom for the critical deployment. Document quota limits in the capacity planning spreadsheet and set up Azure Monitor alerts at 80% quota utilization to prevent surprise quota exhaustion.
