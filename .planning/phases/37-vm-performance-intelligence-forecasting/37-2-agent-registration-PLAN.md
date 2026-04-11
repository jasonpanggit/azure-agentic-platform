---
wave: 2
depends_on:
  - 37-1
files_modified:
  - agents/compute/agent.py
autonomous: true
---

# Plan 37-2: Agent Registration

Register the three new performance intelligence tools (`get_vm_forecast`,
`query_vm_performance_baseline`, `detect_performance_drift`) in
`agents/compute/agent.py` at all four required locations.

---

## Task 37-2-A: Add imports to agent.py import block

<read_first>
- agents/compute/agent.py (lines 31–57 — existing `from compute.tools import (...)` block)
- agents/compute/tools.py — confirm the exact function names defined in Plan 37-1
</read_first>

<action>
Edit the `from compute.tools import (...)` block in `agents/compute/agent.py`
to add the three new tool names. The current block ends with `query_vmss_rolling_upgrade,`.
Insert the three new imports at the end of the import list (before the closing `)`) in
alphabetical order relative to surrounding entries:

```python
from compute.tools import (
    ALLOWED_MCP_TOOLS,
    detect_performance_drift,        # NEW
    execute_run_command,
    get_vm_forecast,                 # NEW
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
    query_vm_performance_baseline,   # NEW
    query_vm_sku_options,
    query_vmss_autoscale,
    query_vmss_instances,
    query_vmss_rolling_upgrade,
)
```

Note: The exact ordering of the full import block should match the file — use
alphabetical placement for the 3 new names. The critical requirement is that
all three names appear in the `from compute.tools import` block.
</action>

<acceptance_criteria>
- `grep -n "detect_performance_drift" agents/compute/agent.py` returns a match in the import block
- `grep -n "get_vm_forecast" agents/compute/agent.py` returns a match in the import block
- `grep -n "query_vm_performance_baseline" agents/compute/agent.py` returns a match in the import block
- `python -c "from agents.compute import agent"` does not raise ImportError (syntax valid)
</acceptance_criteria>

---

## Task 37-2-B: Add tools to the `COMPUTE_AGENT_SYSTEM_PROMPT` allowed-tools list

<read_first>
- agents/compute/agent.py (lines 120–145 — the `.format(allowed_tools=...)` call that builds the system prompt)
</read_first>

<action>
In `agents/compute/agent.py`, find the `.format(allowed_tools="\n".join(...))` call
that constructs `COMPUTE_AGENT_SYSTEM_PROMPT`. Add the three new tool names to
the list inside that call. Insert them after `"query_ama_guest_metrics"`:

```python
    "query_ama_guest_metrics",
    "get_vm_forecast",
    "query_vm_performance_baseline",
    "detect_performance_drift",
```
</action>

<acceptance_criteria>
- `grep -n "get_vm_forecast" agents/compute/agent.py` returns at least 2 matches (import + system prompt list)
- `grep -n "query_vm_performance_baseline" agents/compute/agent.py` returns at least 2 matches
- `grep -n "detect_performance_drift" agents/compute/agent.py` returns at least 2 matches
</acceptance_criteria>

---

## Task 37-2-C: Add tools to `ChatAgent` tools list

<read_first>
- agents/compute/agent.py (lines 162–193 — `ChatAgent(...)` constructor `tools=[...]` list)
</read_first>

<action>
In `agents/compute/agent.py`, find the `tools=[...]` list inside the `ChatAgent(...)`
constructor in `create_compute_agent()`. Add the three new tools after
`query_ama_guest_metrics`:

```python
            query_ama_guest_metrics,
            get_vm_forecast,
            query_vm_performance_baseline,
            detect_performance_drift,
        ],
```
</action>

<acceptance_criteria>
- `grep -n "get_vm_forecast" agents/compute/agent.py` returns at least 3 matches (import + prompt list + ChatAgent)
- The three tools appear consecutively after `query_ama_guest_metrics` in the ChatAgent block
- File is syntactically valid Python (no missing commas or brackets)
</acceptance_criteria>

---

## Task 37-2-D: Add tools to `PromptAgentDefinition` tools list

<read_first>
- agents/compute/agent.py (lines 215–248 — `PromptAgentDefinition(...)` `tools=[...]` list inside `create_compute_agent_version()`)
</read_first>

<action>
In `agents/compute/agent.py`, find the `tools=[...]` list inside the
`PromptAgentDefinition(...)` call in `create_compute_agent_version()`.
Add the three new tools after `query_ama_guest_metrics`:

```python
                query_ama_guest_metrics,
                get_vm_forecast,
                query_vm_performance_baseline,
                detect_performance_drift,
            ],
```
</action>

<acceptance_criteria>
- `grep -n "get_vm_forecast" agents/compute/agent.py` returns at least 4 matches
  (import block + system prompt list + ChatAgent tools + PromptAgentDefinition tools)
- `grep -c "get_vm_forecast" agents/compute/agent.py` outputs `4`
- `grep -c "query_vm_performance_baseline" agents/compute/agent.py` outputs `4`
- `grep -c "detect_performance_drift" agents/compute/agent.py` outputs `4`
</acceptance_criteria>

---

## Verification

```bash
# Confirm all 4 registration locations for each tool
grep -c "get_vm_forecast" agents/compute/agent.py
# Expected: 4

grep -c "query_vm_performance_baseline" agents/compute/agent.py
# Expected: 4

grep -c "detect_performance_drift" agents/compute/agent.py
# Expected: 4

# Confirm file is valid Python
python -m py_compile agents/compute/agent.py && echo "SYNTAX OK"
```

## must_haves

- All 3 tools appear in the `from compute.tools import` block
- All 3 tools appear in the `COMPUTE_AGENT_SYSTEM_PROMPT` allowed-tools list
- All 3 tools appear in the `ChatAgent` tools list
- All 3 tools appear in the `PromptAgentDefinition` tools list
- `grep -c "get_vm_forecast" agents/compute/agent.py` returns `4`
