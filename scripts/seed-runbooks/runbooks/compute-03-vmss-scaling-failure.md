---
title: "VMSS Scaling Failure Triage"
domain: compute
version: "1.0"
tags: ["vmss", "autoscale", "scaling", "capacity", "quota"]
---

## Symptoms

A Virtual Machine Scale Set fails to scale out when autoscale rules fire, leaving the fleet under-provisioned during a demand spike. Azure Monitor autoscale logs show "ScaleOut" events with status "Failed" or "Dropped". Application latency increases as existing instances become overloaded. Scale-in operations may also fail, leaving excess capacity and incurring unnecessary costs.

## Root Causes

1. Azure subscription quota exhaustion — the target VM SKU has hit its regional vCPU limit.
2. Spot instance eviction rate too high — Spot-based VMSS exhausted available capacity in the selected region/zone.
3. Custom image unavailable — the VMSS image reference points to a deleted or unshared Shared Image Gallery version.
4. Unhealthy extension failing on new instances — startup extension fails causing instances to never reach "Succeeded" state, blocking further scale-out.

## Diagnostic Steps

1. Check autoscale history for failure reasons:
   ```bash
   az monitor autoscale history list \
     --autoscale-name {autoscale_name} \
     --resource-group {rg} \
     --query "[?status=='Failed'].{time:timestamp,reason:message}" \
     --output table
   ```
2. Verify current quota against usage for the VM SKU:
   ```bash
   az vm list-usage --location {region} \
     --query "[?contains(name.value,'standardDSv3Family')].{name:name.localizedValue,current:currentValue,limit:limit}" \
     --output table
   ```
3. Check the VMSS instance list for instances stuck in "Creating" or "Failed" state:
   ```bash
   az vmss list-instances --resource-group {rg} --name {vmss_name} \
     --query "[?provisioningState!='Succeeded'].{id:instanceId,state:provisioningState}" \
     --output table
   ```
4. Review extension provisioning logs on a failed instance:
   ```bash
   az vmss get-instance-view --resource-group {rg} --name {vmss_name} --instance-id {instance_id} \
     --query "extensions[?statuses[0].code!='ProvisioningState/succeeded']"
   ```
5. Confirm the image reference is accessible:
   ```bash
   az vmss show --resource-group {rg} --name {vmss_name} \
     --query "virtualMachineProfile.storageProfile.imageReference"
   ```

## Remediation Commands

```bash
# Delete stuck failed instances to unblock scaling
az vmss delete-instances --resource-group {rg} --name {vmss_name} --instance-ids {instance_ids}

# Request quota increase (opens a support ticket)
az support tickets create \
  --ticket-name "VMSS-Quota-{region}" \
  --title "Request vCPU quota increase for Standard_DSv3 in {region}" \
  --problem-classification "/providers/Microsoft.Support/services/quota/problemClassifications/compute" \
  --severity minimal

# Switch to a different SKU with available capacity
az vmss update --resource-group {rg} --name {vmss_name} \
  --set virtualMachineProfile.hardwareProfile.vmSize=Standard_E4s_v5

# Manually trigger a scale-out to test
az monitor autoscale rule create \
  --autoscale-name {autoscale_name} --resource-group {rg} \
  --scale out 2 --condition "Percentage CPU > 10 avg 1m"
```

## Rollback Procedure

If the SKU change caused compatibility issues with the workload, revert the image reference and VM SKU to the previous configuration using `az vmss update`. Re-image all instances with `az vmss reimage --all` to ensure consistency. Document quota limits hit and initiate a long-term capacity planning review with the Azure subscription owner.
