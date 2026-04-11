---
plan_id: "34-01"
phase: "34"
title: "Activate Phase 32 VM Tools in Compute Agent + Fix AMA Status"
objective: >
  Wire all 15 unregistered Phase 32 tools into compute/agent.py so the compute
  agent can actually call them. Fix AMA status hardcoded "unknown" in the fleet
  inventory endpoint by querying ARG for the AMA extension presence.
req_ids: []
gap_closure: false
wave: 1
---

# Plan 34-01: Activate Phase 32 VM Tools in Compute Agent + Fix AMA Status

## Objective

Phase 32 delivered 15 new @ai_function tools in `agents/compute/tools.py` but
`agents/compute/agent.py` only imports and registers 5 of them. None of the new
tools (extensions, boot diagnostics, disk health, propose_*, VMSS, AKS) are
reachable by the agent. This plan fixes that.

Additionally, the fleet inventory endpoint (`services/api-gateway/vm_inventory.py`)
returns `ama_status: "unknown"` for every VM because the ARG KQL query does not
include extension data. This plan extends the ARG query to look up the AMA
(`MicrosoftMonitoringAgent` or `AzureMonitorAgent`) extension and return
`installed` / `not_installed` / `unknown` (Arc VMs, or query failure).

## Tasks

### Task 1 — Update compute/agent.py imports

In the import block at the top of `agents/compute/agent.py`, replace:
```python
from compute.tools import (
    ALLOWED_MCP_TOOLS,
    query_activity_log,
    query_log_analytics,
    query_monitor_metrics,
    query_os_version,
    query_resource_health,
)
```
With all 20 tool imports:
```python
from compute.tools import (
    ALLOWED_MCP_TOOLS,
    propose_aks_node_pool_scale,
    propose_vm_redeploy,
    propose_vm_resize,
    propose_vm_restart,
    propose_vmss_scale,
    query_aks_cluster_health,
    query_aks_node_pools,
    query_aks_upgrade_profile,
    query_activity_log,
    query_boot_diagnostics,
    query_disk_health,
    query_log_analytics,
    query_monitor_metrics,
    query_os_version,
    query_resource_health,
    query_vm_extensions,
    query_vm_sku_options,
    query_vmss_autoscale,
    query_vmss_instances,
    query_vmss_rolling_upgrade,
)
```

### Task 2 — Update COMPUTE_AGENT_SYSTEM_PROMPT allowed tools list

In the f-string that builds `COMPUTE_AGENT_SYSTEM_PROMPT`, the `.format()` call
lists only 5 tools. Update the `allowed_tools` list in the `.format()` call to
include all 20 tools so the system prompt accurately reflects what the agent can do.

### Task 3 — Update create_compute_agent() tools list

In `create_compute_agent()`, replace:
```python
tools=[
    query_activity_log,
    query_log_analytics,
    query_resource_health,
    query_monitor_metrics,
    query_os_version,
],
```
With all 20 tools.

### Task 4 — Update create_compute_agent_version() tools list

Same update as Task 3 for `create_compute_agent_version()`.

### Task 5 — Fix AMA status in vm_inventory.py

Extend `_build_vm_kql()` to join extension data for Azure VMs:
- Add KQL join against `Resources` where type =~ `microsoft.compute/virtualmachines/extensions`
  to find `AzureMonitorWindowsAgent`, `AzureMonitorLinuxAgent`, or `MicrosoftMonitoringAgent`
- Project a new `amaStatus` column: `installed` if AMA extension found, `not_installed` otherwise
- Arc VMs always return `unknown` (Arc extension data is not in ARG compute scope)

In `list_vms()`, use `row.get("amaStatus", "unknown")` instead of hardcoded `"unknown"`.

## Files Modified

- `agents/compute/agent.py` — imports, system prompt tool list, create_compute_agent(), create_compute_agent_version()
- `services/api-gateway/vm_inventory.py` — _build_vm_kql() + list_vms() AMA status

## Done Checklist

- [ ] All 20 tools imported in compute/agent.py
- [ ] create_compute_agent() registers all 20 tools
- [ ] create_compute_agent_version() registers all 20 tools
- [ ] COMPUTE_AGENT_SYSTEM_PROMPT lists all 20 tools
- [ ] vm_inventory _build_vm_kql includes AMA extension subquery for Azure VMs
- [ ] ama_status returns "installed"/"not_installed" for Azure VMs, "unknown" for Arc VMs
- [ ] All existing tests pass
- [ ] New tests cover: (a) all 20 tools present in agent tools list, (b) ama_status values
</content>
</invoke>