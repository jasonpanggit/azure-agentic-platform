---
plan: 37-2-agent-registration
status: complete
commit: c8fc27a
---

# Summary: Plan 37-2 — Agent Registration

## What was done

Registered the three new performance intelligence tools from Plan 37-1 in
`agents/compute/agent.py` at all four required locations.

## Changes

### File: `agents/compute/agent.py`

**Location 1 — Import block** (`from compute.tools import`):
- Added `detect_performance_drift`, `get_vm_forecast`, `query_vm_performance_baseline`
  in alphabetical position within the existing import list.

**Location 2 — System prompt allowed-tools list** (`.format(allowed_tools=...)` call):
- Appended `"get_vm_forecast"`, `"query_vm_performance_baseline"`, `"detect_performance_drift"`
  after `"query_ama_guest_metrics"`.

**Location 3 — `ChatAgent` `tools=[...]`** (in `create_compute_agent()`):
- Appended `get_vm_forecast`, `query_vm_performance_baseline`, `detect_performance_drift`
  after `query_ama_guest_metrics`.

**Location 4 — `PromptAgentDefinition` `tools=[...]`** (in `create_compute_agent_version()`):
- Appended `get_vm_forecast`, `query_vm_performance_baseline`, `detect_performance_drift`
  after `query_ama_guest_metrics`.

## Verification

```
grep -c "get_vm_forecast" agents/compute/agent.py           → 4 ✓
grep -c "query_vm_performance_baseline" agents/compute/agent.py → 4 ✓
grep -c "detect_performance_drift" agents/compute/agent.py  → 4 ✓
python3 -m py_compile agents/compute/agent.py               → SYNTAX OK ✓
```

## Acceptance criteria

- [x] All 3 tools imported in agent.py
- [x] All 3 tools in system-prompt allowed-tools list
- [x] All 3 tools in `ChatAgent` tools list
- [x] All 3 tools in `PromptAgentDefinition` tools list
- [x] `grep -c "get_vm_forecast" agents/compute/agent.py` → `4`
- [x] Syntax valid (`python3 -m py_compile`)
