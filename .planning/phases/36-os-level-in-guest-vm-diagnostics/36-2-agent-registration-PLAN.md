---
wave: 2
depends_on:
  - 36-1-guest-diagnostic-tools-PLAN.md
files_modified:
  - agents/compute/agent.py
autonomous: true
---

# Plan 36-2: Register In-Guest Tools in Compute Agent

## Goal

Import and register all 4 new Phase 36 tools (`execute_run_command`, `parse_boot_diagnostics_serial_log`, `query_vm_guest_health`, `query_ama_guest_metrics`) in `agents/compute/agent.py` — add to imports, system prompt allowed tools list, `create_compute_agent()` tools list, and `create_compute_agent_version()` tools list.

## must_haves

- All 4 new tools imported from `compute.tools` in `agent.py`
- All 4 new tool names listed in the system prompt `allowed_tools` list
- All 4 new tools passed to `ChatAgent(tools=[...])` in `create_compute_agent()`
- All 4 new tools passed to `PromptAgentDefinition(tools=[...])` in `create_compute_agent_version()`
- System prompt includes guidance on in-guest diagnostics workflow

## Tasks

<task id="36-2-01">
<title>Add imports for 4 new tools</title>
<read_first>
- agents/compute/agent.py (full file — understand current import block from compute.tools)
- agents/compute/tools.py (verify the 4 new function names exist)
</read_first>
<action>
In `agents/compute/agent.py`, extend the existing import block from `compute.tools` to include the 4 new functions. The current import block is:

```python
from compute.tools import (
    ALLOWED_MCP_TOOLS,
    propose_aks_node_pool_scale,
    ...
    query_vmss_rolling_upgrade,
)
```

Add these 4 new imports in alphabetical order within the existing import block:

```python
    execute_run_command,
    parse_boot_diagnostics_serial_log,
    query_ama_guest_metrics,
    query_vm_guest_health,
```

The full import list should now have 24 items (20 existing + 4 new).
</action>
<acceptance_criteria>
- `grep "execute_run_command" agents/compute/agent.py` returns a match
- `grep "parse_boot_diagnostics_serial_log" agents/compute/agent.py` returns a match
- `grep "query_vm_guest_health" agents/compute/agent.py` returns a match
- `grep "query_ama_guest_metrics" agents/compute/agent.py` returns a match
- All 4 appear in the `from compute.tools import (...)` block
</acceptance_criteria>
</task>

<task id="36-2-02">
<title>Update system prompt with in-guest tools and workflow guidance</title>
<read_first>
- agents/compute/agent.py (read COMPUTE_AGENT_SYSTEM_PROMPT and the allowed_tools format string)
</read_first>
<action>
1. Add the 4 new tool names to the `ALLOWED_MCP_TOOLS + [...]` list used in the system prompt `allowed_tools` format string. Add after `"propose_aks_node_pool_scale"`:

```python
    "execute_run_command",
    "parse_boot_diagnostics_serial_log",
    "query_vm_guest_health",
    "query_ama_guest_metrics",
```

2. Add a new section to `COMPUTE_AGENT_SYSTEM_PROMPT` before the `## Safety Constraints` section:

```
## In-Guest Diagnostics (Phase 36)

When VM-level metrics and Resource Health are inconclusive, use in-guest tools:

1. **Guest health first:** Call `query_vm_guest_health` to check AMA heartbeat status and
   current CPU/memory/disk pressure from InsightsMetrics.

2. **AMA metrics history:** Call `query_ama_guest_metrics` for 24h P50/P95 CPU, memory,
   and disk IOPS to identify gradual degradation.

3. **Boot diagnostics:** Call `query_boot_diagnostics` then pass the serial_log_uri to
   `parse_boot_diagnostics_serial_log` to detect kernel panics, OOM kills, and disk errors.

4. **Run Command (last resort):** Use `execute_run_command` ONLY when other tools are
   insufficient. This executes scripts inside the VM guest OS. Only diagnostic commands
   are permitted — destructive commands are blocked. Examples:
   - Linux: `df -h`, `free -m`, `dmesg | tail -50`, `ps aux --sort=-%mem | head -20`
   - Windows: `Get-Process | Sort-Object CPU -Descending | Select-Object -First 20`
```

3. Add to the `## Safety Constraints` section:

```
- MUST NOT use execute_run_command for destructive operations. Only diagnostic read-only scripts.
- execute_run_command scripts are limited to 1500 characters.
```
</action>
<acceptance_criteria>
- `grep "In-Guest Diagnostics" agents/compute/agent.py` returns a match
- `grep "execute_run_command" agents/compute/agent.py` returns at least 4 matches (import, prompt tools list, prompt guidance, safety constraint)
- `grep "parse_boot_diagnostics_serial_log" agents/compute/agent.py` returns at least 3 matches (import, prompt tools list, prompt guidance)
- `grep "query_vm_guest_health" agents/compute/agent.py` returns at least 3 matches
- `grep "query_ama_guest_metrics" agents/compute/agent.py` returns at least 3 matches
- `grep "1500 characters" agents/compute/agent.py` returns a match
</acceptance_criteria>
</task>

<task id="36-2-03">
<title>Add 4 new tools to ChatAgent and PromptAgentDefinition tool lists</title>
<read_first>
- agents/compute/agent.py (read create_compute_agent and create_compute_agent_version functions)
</read_first>
<action>
1. In `create_compute_agent()`, add the 4 new tools to the `ChatAgent(tools=[...])` list. Add after `propose_aks_node_pool_scale`:

```python
            execute_run_command,
            parse_boot_diagnostics_serial_log,
            query_vm_guest_health,
            query_ama_guest_metrics,
```

2. In `create_compute_agent_version()`, add the same 4 tools to the `PromptAgentDefinition(tools=[...])` list in the same position.

Both lists should now have 24 tools each (20 existing + 4 new).
</action>
<acceptance_criteria>
- `python3 -c "import ast; tree = ast.parse(open('agents/compute/agent.py').read()); print('OK')"` exits 0 (valid Python syntax)
- `grep -c "execute_run_command" agents/compute/agent.py` returns at least 5 (import + prompt list + prompt guidance + ChatAgent tools + PromptAgentDefinition tools)
- `grep -c "query_vm_guest_health" agents/compute/agent.py` returns at least 4
- `grep -c "query_ama_guest_metrics" agents/compute/agent.py` returns at least 4
- `grep -c "parse_boot_diagnostics_serial_log" agents/compute/agent.py` returns at least 4
</acceptance_criteria>
</task>

## Verification

```bash
# Valid Python
python3 -c "import ast; tree = ast.parse(open('agents/compute/agent.py').read()); print('OK')"

# All 4 new tools appear in each of the 4 locations (import, prompt, ChatAgent, PromptAgentDefinition)
for tool in execute_run_command parse_boot_diagnostics_serial_log query_vm_guest_health query_ama_guest_metrics; do
  count=$(grep -c "$tool" agents/compute/agent.py)
  echo "$tool: $count occurrences (expect >= 4)"
done
```
