---
title: "Resource Lock Management"
domain: sre
version: "1.0"
tags: ["sre", "resource-lock", "delete-lock", "read-only", "governance", "protection"]
---

## Symptoms

An operator is unable to delete, modify, or update an Azure resource because a resource lock is preventing the operation. An error message states "ScopeLocked" or "The resource '{name}' is locked." A planned maintenance activity, decommissioning, or configuration change is blocked by an unexpected lock. Alternatively, an important resource was accidentally deleted because it lacked a required delete lock.

## Root Causes

1. CanNotDelete lock applied by a governance team to protect production resources from accidental deletion.
2. ReadOnly lock applied during a change freeze or maintenance window and not removed afterward.
3. Lock inherited from the resource group level, affecting all resources within the group unexpectedly.
4. Terraform-managed lock left in place after a resource was decommissioned from IaC but lock remains.

## Diagnostic Steps

1. List all locks on a specific resource:
   ```bash
   az lock list --resource-group {rg} \
     --query "[].{name:name,level:level,resourceName:resourceName,notes:notes}" \
     --output table
   ```
2. Check for inherited locks from the resource group or subscription:
   ```bash
   # Resource group locks
   az lock list --resource-group {rg} \
     --query "[?resourceName==null].{name:name,level:level,scope:id}"

   # Subscription-level locks
   az lock list \
     --query "[?contains(id,'/subscriptions/{sub}/providers/Microsoft.Authorization/locks')].{name:name,level:level}"
   ```
3. Find who created the lock and when:
   ```bash
   az monitor activity-log list \
     --resource-type Microsoft.Authorization/locks \
     --start-time $(date -u -d '-90 days' +%FT%TZ) \
     --query "[?contains(resourceId,'{lock_name}')].{time:eventTimestamp,caller:caller,op:operationName.value}"
   ```
4. Check if the lock is managed by Terraform:
   ```bash
   # Search Terraform state for lock resources
   terraform state list | grep azurerm_management_lock
   terraform state show {lock_resource_address}
   ```
5. Check if the blocked operation is expected to succeed post-lock-removal:
   ```bash
   az lock show --resource-group {rg} --name {lock_name} \
     --query "{level:level,notes:notes,createdAt:createdTime}"
   ```

## Remediation Commands

```bash
# Remove a specific resource-level lock
az lock delete --resource-group {rg} --name {lock_name} \
  --resource-name {resource_name} \
  --resource-type {resource_type} \
  --namespace {resource_provider_namespace}

# Remove a resource group-level lock
az lock delete --resource-group {rg} --name {rg_lock_name}

# Add a CanNotDelete lock to protect a critical resource
az lock create \
  --resource-group {rg} \
  --name protect-{resource_name} \
  --lock-type CanNotDelete \
  --resource-name {resource_name} \
  --resource-type {resource_type} \
  --namespace {resource_provider_namespace} \
  --notes "Production resource — requires CAB approval to delete"

# Add a resource group-level lock for all resources
az lock create --resource-group {rg} \
  --name protect-rg-{rg} --lock-type CanNotDelete \
  --notes "Production resource group — CAB approval required"
```

## Rollback Procedure

Lock deletion is irreversible in the sense that the lock is gone — but re-adding a lock is trivial: `az lock create`. After performing the maintenance operation that required lock removal, immediately re-add the lock with the same or stricter configuration. All lock operations are recorded in the Azure Activity Log. Maintain a CMDB entry for all production locks with their justification, owner, and review date to prevent orphaned locks blocking future operations.
