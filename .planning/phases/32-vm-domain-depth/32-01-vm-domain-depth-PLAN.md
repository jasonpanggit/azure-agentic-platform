---
id: "32-01"
phase: 32
plan: 1
wave: 1
title: "VM Domain Depth — All Chunks"
objective: "Bring the VM domain (Azure VM, Arc VM, VMSS, AKS) and Patch/EOL agents to world-class depth by fixing 5 triage stubs and adding 17+ new tools covering diagnostics, HITL remediation proposals, VMSS scaling, AKS cluster health, and Arc guest configuration."
autonomous: true
gap_closure: false
files_modified:
  - "agents/patch/tools.py"
  - "agents/eol/tools.py"
  - "agents/tests/patch/test_patch_stub_fixes.py"
  - "agents/tests/eol/test_eol_stub_fixes.py"
  - "agents/compute/tools.py"
  - "agents/tests/compute/test_new_vm_tools.py"
  - "agents/vmss/tools.py"
  - "agents/vmss/__init__.py"
  - "agents/tests/vmss/test_vmss_tools.py"
  - "agents/aks/tools.py"
  - "agents/aks/__init__.py"
  - "agents/tests/aks/test_aks_tools.py"
  - "agents/arc/tools.py"
  - "agents/tests/arc/test_arc_enhancements.py"
  - "agents/tests/integration/test_phase32_smoke.py"
task_count: 48
key_links: []
---

# Phase 32: VM Domain Depth — Implementation Plan

> **IMPORTANT**: This is a GSD wrapper plan. The full detailed implementation plan is at:
> `docs/superpowers/plans/2026-04-11-phase-32-vm-domain-depth.md`
>
> **Read that file first.** Execute all 6 chunks in order:
> 1. Chunk 1: Stub Fixes — Patch and EOL Agents
> 2. Chunk 2: New Compute Agent Tools — Azure VM
> 3. Chunk 3: VMSS Tools
> 4. Chunk 4: AKS Tools
> 5. Chunk 5: Arc Agent Enhancements
> 6. Chunk 6: Final Verification

## Goal

Bring the VM domain (Azure VM, Arc VM, VMSS, AKS) and Patch/EOL agents to world-class depth by fixing 5 triage stubs and adding 17+ new tools covering diagnostics, HITL remediation proposals, VMSS scaling, AKS cluster health, and Arc guest configuration.

## Architecture

All new tools follow the existing `agents/compute/tools.py` pattern:
- Lazy SDK imports (`try/except ImportError`)
- `@ai_function` decorator
- `instrument_tool_call` span wrapping
- `try/except` returning structured error dicts (never raise)
- All `propose_*` tools call ONLY `approval_manager.create_approval_record()` — zero ARM mutations

## Key Technical Notes

- **Stub fixes**: Replace `return {"status": "not_implemented"}` stubs with real implementations matching the compute agent's `query_activity_log` / `query_resource_health` pattern
- **`propose_vm_restart`**: MUST use `create_approval_record()` only — test must assert `virtual_machines.restart` is NOT in the function source (use `inspect.getsource`)
- **Arc guest config**: Use `GuestConfigurationClient.guest_configuration_assignment_reports.list()` from `azure-mgmt-guestconfiguration` — NOT `machine_run_commands`
- **VMSS tools**: `azure-mgmt-compute` `VirtualMachineScaleSetsOperations` — `list_instances()`, `get_instance_view()`
- **AKS tools**: `azure-mgmt-containerservice` `ManagedClustersOperations` — `get()`, `list_cluster_admin_credentials()`
- **Tool function convention** (from CLAUDE.md): `start_time = time.monotonic()` at entry; `duration_ms` in both try and except blocks; return structured dicts
- **All tools**: Never raise — return `{"status": "error", "message": str(e), "duration_ms": ...}`

## New Tools Being Added

**Chunk 1 (stub fixes):**
- `agents/patch/tools.py`: fix `query_patch_activity_log`, `query_patch_resource_health`
- `agents/eol/tools.py`: fix `query_eol_activity_log`, `query_eol_resource_health`, `query_eol_metrics`

**Chunk 2 (Azure VM):**
- `agents/compute/tools.py`: `propose_vm_restart`, `propose_vm_stop`, `query_vm_boot_diagnostics`, `query_vm_run_command_history`, `query_vm_network_topology`

**Chunk 3 (VMSS):**
- `agents/vmss/tools.py` (new file): `query_vmss_instances`, `query_vmss_instance_view`, `query_vmss_activity_log`, `propose_vmss_scale`

**Chunk 4 (AKS):**
- `agents/aks/tools.py` (new file): `query_aks_cluster_health`, `query_aks_node_pools`, `query_aks_upgrade_profile`, `propose_aks_node_pool_scale`

**Chunk 5 (Arc enhancements):**
- `agents/arc/tools.py`: `query_arc_guest_config` (using `GuestConfigurationClient`)

## Success Criteria

- [ ] All 5 stub `return {"status": "not_implemented"}` are fixed with real implementations
- [ ] `propose_vm_restart` and `propose_vmss_scale` use only `create_approval_record()` — no ARM calls
- [ ] VMSS tools module created (`agents/vmss/tools.py`)
- [ ] AKS tools module created (`agents/aks/tools.py`)
- [ ] Arc guest config uses `GuestConfigurationClient` not `machine_run_commands`
- [ ] All new tools have tests
- [ ] Integration smoke test passes
