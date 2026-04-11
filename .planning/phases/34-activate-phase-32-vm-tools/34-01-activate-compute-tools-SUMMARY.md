---
plan_id: "34-01"
phase: "34"
status: complete
one_liner: "Wired all 20 compute tools into the agent + fixed AMA status from hardcoded 'unknown' to ARG extension lookup"
completed_at: 2026-04-11
key-files:
  modified:
    - agents/compute/agent.py
    - services/api-gateway/vm_inventory.py
    - services/api-gateway/tests/test_vm_inventory.py
  created:
    - agents/tests/compute/test_compute_agent_registration.py
    - .planning/phases/34-activate-phase-32-vm-tools/34-01-activate-compute-tools-PLAN.md
---

# Summary — Plan 34-01: Activate Phase 32 VM Tools

## What Was Done

### 1. Compute Agent Tool Registration (`agents/compute/agent.py`)

All 15 Phase 32 tools were added to the import block and registered in both
`create_compute_agent()` and `create_compute_agent_version()`. The system prompt's
allowed tools list was also updated.

**Before:** 5 tools registered (query_activity_log, query_log_analytics,
query_resource_health, query_monitor_metrics, query_os_version)

**After:** 20 tools registered — adds:
- `query_vm_extensions` — VM extension inventory
- `query_boot_diagnostics` — Boot diagnostics serial log
- `query_vm_sku_options` — Available VM SKUs for resize
- `query_disk_health` — Disk IOPS/throughput/health
- `propose_vm_restart` — HITL-gated restart proposal
- `propose_vm_resize` — HITL-gated resize proposal
- `propose_vm_redeploy` — HITL-gated redeploy proposal
- `query_vmss_instances` — VMSS instance list
- `query_vmss_autoscale` — Autoscale profile
- `query_vmss_rolling_upgrade` — Rolling upgrade status
- `propose_vmss_scale` — HITL-gated VMSS scale proposal
- `query_aks_cluster_health` — AKS cluster health
- `query_aks_node_pools` — AKS node pool status
- `query_aks_upgrade_profile` — Available Kubernetes upgrades
- `propose_aks_node_pool_scale` — HITL-gated AKS node pool scale proposal

### 2. AMA Status Fix (`services/api-gateway/vm_inventory.py`)

The `_build_vm_kql()` function was extended to perform a `leftouter` join against
`Microsoft.Compute/virtualMachines/extensions` resources, looking for:
- `AzureMonitorWindowsAgent`
- `AzureMonitorLinuxAgent`
- `MicrosoftMonitoringAgent`

The ARG query now projects `amaStatus`:
- Azure VMs: `"installed"` if AMA extension found, `"not_installed"` otherwise
- Arc VMs: always `"unknown"` (Arc extension data not in ARG compute scope)

The VM assembly loop replaced the hardcoded `"unknown"` with `row.get("amaStatus", "unknown")`.

## Tests

| File | Tests | Result |
|------|-------|--------|
| `test_compute_agent_registration.py` (new) | 5 | PASSED |
| `test_vm_inventory.py` (extended) | 7 new + 21 existing = 28 total | PASSED |

Full suite: **1,278 passed**, 9 pre-existing failures (EOL agent, approval lifecycle
— confirmed on main before this change), 0 new failures.

## Verification

All 5 done checklist items confirmed:
- [x] All 20 tools imported in compute/agent.py
- [x] create_compute_agent() registers all 20 tools
- [x] create_compute_agent_version() registers all 20 tools
- [x] COMPUTE_AGENT_SYSTEM_PROMPT lists all 20 tools
- [x] vm_inventory _build_vm_kql includes AMA extension subquery for Azure VMs
- [x] ama_status returns "installed"/"not_installed" for Azure VMs, "unknown" for Arc VMs
- [x] All existing tests pass (no regressions)
- [x] New tests cover all changes
</content>
</invoke>