---
title: "VM Network Connectivity Loss"
domain: compute
version: "1.0"
tags: ["vm", "network", "connectivity", "nsg", "nic", "routing"]
---

## Symptoms

An Azure Virtual Machine loses network connectivity suddenly. SSH and RDP connections time out. Application health probes fail. The VM platform metrics still show it running, but all TCP connections from external clients and VNet peers are dropped. Azure Network Watcher connectivity tests fail from other VMs.

## Root Causes

1. NSG rule added incorrectly denying inbound traffic on the management port (22 or 3389).
2. NIC disconnected or in a failed state after a platform maintenance event.
3. VM route table change routing traffic to a black-hole next hop (UDR misconfiguration).
4. IP forwarding disabled on a VM acting as a network virtual appliance.

## Diagnostic Steps

1. Run Azure Network Watcher connectivity test to the VM:
   ```bash
   az network watcher test-connectivity \
     --source-resource {source_vm_resource_id} \
     --dest-resource {target_vm_resource_id} \
     --dest-port 22 \
     --resource-group {rg}
   ```
2. Check effective NSG rules applied to the VM's NIC:
   ```bash
   az network nic list-effective-nsg \
     --resource-group {rg} \
     --name {nic_name} \
     --query "networkSecurityGroups[].effectiveSecurityRules[?direction=='Inbound']" \
     | python3 -c "import sys,json; [print(r['name'],r['access'],r['destinationPortRange']) for r in json.load(sys.stdin)[0]]"
   ```
3. Check the effective routes on the NIC to detect routing black holes:
   ```bash
   az network nic show-effective-route-table \
     --resource-group {rg} \
     --name {nic_name} \
     --query "value[?state=='Active']" --output table
   ```
4. Verify NIC attachment and IP configuration:
   ```bash
   az network nic show --resource-group {rg} --name {nic_name} \
     --query "{vmAttached:virtualMachine.id,ipConfig:ipConfigurations[0].privateIpAddress,state:provisioningState}"
   ```
5. Check for platform health events affecting the VM's network:
   ```bash
   az resource health get-availability-status \
     --resource-group {rg} --name {vm_name} \
     --resource-type Microsoft.Compute/virtualMachines
   ```

## Remediation Commands

```bash
# Remove a blocking NSG deny rule
az network nsg rule delete \
  --resource-group {rg} --nsg-name {nsg_name} --name {blocking_rule_name}

# Re-add the correct allow rule for SSH
az network nsg rule create \
  --resource-group {rg} --nsg-name {nsg_name} \
  --name AllowSSH --priority 1000 --direction Inbound \
  --access Allow --protocol Tcp --destination-port-range 22

# Redeploy VM to a new host if NIC is in failed state
az vm redeploy --resource-group {rg} --name {vm_name}
```

## Rollback Procedure

If the NSG rule change inadvertently blocked other traffic, review the full NSG rule set and restore the previous configuration from the Activity Log using `az monitor activity-log list`. NSG rule changes are reversible — the original rules can be recreated from the activity log within minutes. Use Network Watcher packet capture to confirm traffic flows after remediation.
