---
plan: 38-2
title: "Agent Registration — 5 new tools in agent.py (4 locations each)"
wave: 2
depends_on:
  - 38-1
modifies:
  - agents/compute/agent.py
must_haves:
  - query_defender_tvm_cve_count registered in agent.py (grep -c = 4)
  - query_jit_access_status registered in agent.py (grep -c = 4)
  - query_effective_nsg_rules registered in agent.py (grep -c = 4)
  - query_backup_rpo registered in agent.py (grep -c = 4)
  - query_asr_replication_health registered in agent.py (grep -c = 4)
---

# Plan 38-2: Agent Registration

## Goal

Register all 5 new security tools in `agents/compute/agent.py` in exactly 4
locations: the `from compute.tools import (...)` block, the
`COMPUTE_AGENT_SYSTEM_PROMPT` allowed tools list, the `ChatAgent(tools=[...])`
list, and the `PromptAgentDefinition(tools=[...])` list.

---

## Read First

<read_first>
- `agents/compute/agent.py` — full file (4 registration locations, current tool list)
- `agents/compute/tools.py` — just the 5 new function signatures (verify exact names after 38-1 is applied)
</read_first>

---

## Acceptance Criteria

```bash
# Each of the 5 tools appears exactly 4 times in agent.py
grep -c "query_defender_tvm_cve_count" agents/compute/agent.py   # == 4
grep -c "query_jit_access_status" agents/compute/agent.py        # == 4
grep -c "query_effective_nsg_rules" agents/compute/agent.py      # == 4
grep -c "query_backup_rpo" agents/compute/agent.py               # == 4
grep -c "query_asr_replication_health" agents/compute/agent.py   # == 4
```

---

## Action

### The 4 locations in `agents/compute/agent.py`

All 4 edits are additive — append each tool name to the existing list.
Do NOT reorder existing tools. Always add the 5 new tools at the end of
each list, preserving the existing sequence.

---

### Location 1 — `from compute.tools import (...)` block (lines ~31–60)

Add 5 new imports at the end of the import list, before the closing `)`:

```python
    query_defender_tvm_cve_count,
    query_jit_access_status,
    query_effective_nsg_rules,
    query_backup_rpo,
    query_asr_replication_health,
```

The updated block tail should look like:

```python
from compute.tools import (
    ALLOWED_MCP_TOOLS,
    detect_performance_drift,
    execute_run_command,
    get_vm_forecast,
    parse_boot_diagnostics_serial_log,
    propose_aks_node_pool_scale,
    propose_vm_redeploy,
    propose_vm_resize,
    propose_vm_restart,
    propose_vmss_scale,
    query_aks_cluster_health,
    query_aks_node_pools,
    query_aks_upgrade_profile,
    query_activity_log,
    query_ama_guest_metrics,
    query_boot_diagnostics,
    query_disk_health,
    query_log_analytics,
    query_monitor_metrics,
    query_os_version,
    query_resource_health,
    query_vm_extensions,
    query_vm_guest_health,
    query_vm_performance_baseline,
    query_vm_sku_options,
    query_vmss_autoscale,
    query_vmss_instances,
    query_vmss_rolling_upgrade,
    query_defender_tvm_cve_count,
    query_jit_access_status,
    query_effective_nsg_rules,
    query_backup_rpo,
    query_asr_replication_health,
)
```

---

### Location 2 — `COMPUTE_AGENT_SYSTEM_PROMPT` allowed tools list (lines ~123–151)

The system prompt uses a `.format(allowed_tools=...)` call that builds the
tool list from `ALLOWED_MCP_TOOLS + [...]`. Add the 5 new tool names at the
end of the inline list, after `"detect_performance_drift"`:

```python
    "detect_performance_drift",
    "query_defender_tvm_cve_count",
    "query_jit_access_status",
    "query_effective_nsg_rules",
    "query_backup_rpo",
    "query_asr_replication_health",
]))
```

Also add a new section to the system prompt body explaining the security
tools, placed after the existing tool descriptions and before the Safety
Constraints block:

```
## VM Security & Compliance Tools

These tools provide per-VM security posture signals:

- `query_defender_tvm_cve_count`: Retrieve CVE counts by severity from
  Defender TVM. The `vm_risk_score` (critical×10 + high×5 + medium×2 + low×1)
  provides a single comparable number.
- `query_jit_access_status`: Check whether JIT access is configured for the
  VM and list any active sessions. `jit_enabled: false` is an expected
  "not configured" state, not an error.
- `query_effective_nsg_rules`: Get the evaluated NSG rules at the NIC level
  (includes both NIC and subnet NSGs). Rules with `priority < 200` are flagged
  as `high_priority` — investigate these first.
- `query_backup_rpo`: Check Azure Backup last backup time and RPO. If
  `backup_enabled` is false, the VM is unprotected.
- `query_asr_replication_health`: Check Azure Site Recovery replication health.
  If `asr_enabled` is false, the VM has no DR replication configured.
```

---

### Location 3 — `ChatAgent(tools=[...])` list (lines ~168–202)

Add 5 entries at the end of the `tools=[...]` list, after `detect_performance_drift`:

```python
        query_defender_tvm_cve_count,
        query_jit_access_status,
        query_effective_nsg_rules,
        query_backup_rpo,
        query_asr_replication_health,
```

The updated tail of the tools list:

```python
        tools=[
            # ... existing 27 tools ...
            get_vm_forecast,
            query_vm_performance_baseline,
            detect_performance_drift,
            query_defender_tvm_cve_count,
            query_jit_access_status,
            query_effective_nsg_rules,
            query_backup_rpo,
            query_asr_replication_health,
        ],
```

---

### Location 4 — `PromptAgentDefinition(tools=[...])` list (lines ~228–259)

Add 5 entries at the end of the `tools=[...]` list inside
`create_compute_agent_version()`, after `detect_performance_drift`:

```python
                detect_performance_drift,
                query_defender_tvm_cve_count,
                query_jit_access_status,
                query_effective_nsg_rules,
                query_backup_rpo,
                query_asr_replication_health,
```

---

## Verification

```bash
# Each tool must appear exactly 4 times (import + system_prompt + ChatAgent + PromptAgentDefinition)
grep -c "query_defender_tvm_cve_count" agents/compute/agent.py
grep -c "query_jit_access_status" agents/compute/agent.py
grep -c "query_effective_nsg_rules" agents/compute/agent.py
grep -c "query_backup_rpo" agents/compute/agent.py
grep -c "query_asr_replication_health" agents/compute/agent.py
# All must output 4

# Confirm agent.py still parses cleanly
python -c "import ast; ast.parse(open('agents/compute/agent.py').read()); print('OK')"
```
