---
wave: 1
depends_on: []
files_modified:
  - agents/compute/tools.py
  - agents/compute/requirements.txt
autonomous: true
---

# Plan 36-1: In-Guest Diagnostic Tool Functions

## Goal

Add 4 new `@ai_function` tools to `agents/compute/tools.py` for in-guest VM diagnostics: `execute_run_command`, `parse_boot_diagnostics_serial_log`, `query_vm_guest_health`, and `query_ama_guest_metrics`. Fix missing `azure-mgmt-compute` in `requirements.txt`.

## must_haves

- `execute_run_command` function exists in `agents/compute/tools.py` with `@ai_function` decorator
- `execute_run_command` contains a hard block list for destructive commands (rm, kill, shutdown, reboot, format, fdisk, dd, mkfs, etc.)
- `execute_run_command` validates script length <= 1500 chars
- `execute_run_command` selects `RunShellScript` or `RunPowerShellScript` based on `os_type` parameter
- `parse_boot_diagnostics_serial_log` function exists with `@ai_function` decorator
- `parse_boot_diagnostics_serial_log` detects kernel panics, OOM kills, disk errors, and filesystem corruption
- `parse_boot_diagnostics_serial_log` limits download to first 50KB
- `query_vm_guest_health` function exists with `@ai_function` decorator
- `query_vm_guest_health` classifies heartbeat as healthy (<5min), stale (5-15min), or offline (>15min)
- `query_ama_guest_metrics` function exists with `@ai_function` decorator
- `query_ama_guest_metrics` returns hourly buckets with cpu_p50, cpu_p95, memory_avg_mb, disk_iops
- All 4 tools follow the existing pattern: `start_time = time.monotonic()`, `instrument_tool_call`, structured error dict (never raise), `duration_ms` in both try/except
- `azure-mgmt-compute>=30.0.0` is in `agents/compute/requirements.txt`

## Tasks

<task id="36-1-01">
<title>Add azure-mgmt-compute to requirements.txt</title>
<read_first>
- agents/compute/requirements.txt
</read_first>
<action>
Append `azure-mgmt-compute>=30.0.0` to `agents/compute/requirements.txt`. This package is already imported and used by 10+ existing tools but was never declared as an explicit dependency.

Final file content should be:
```
# Compute agent — Azure SDK dependencies for diagnostic tools.
azure-mgmt-resourcegraph>=8.0.1
azure-mgmt-monitor>=6.0.0
azure-monitor-query>=1.3.0
azure-mgmt-resourcehealth==1.0.0b6
azure-mgmt-compute>=30.0.0
```
</action>
<acceptance_criteria>
- `grep "azure-mgmt-compute>=30.0.0" agents/compute/requirements.txt` returns a match
- File has exactly 5 non-comment, non-blank lines
</acceptance_criteria>
</task>

<task id="36-1-02">
<title>Add execute_run_command tool</title>
<read_first>
- agents/compute/tools.py (full file — understand pattern from query_vm_extensions, query_boot_diagnostics)
- .planning/phases/36-os-level-in-guest-vm-diagnostics/36-RESEARCH.md (Section 2.1 Run Command API, Section 5 Safety Analysis)
- .planning/phases/36-os-level-in-guest-vm-diagnostics/36-CONTEXT.md (decisions section)
</read_first>
<action>
Add a new section at the end of `agents/compute/tools.py` (after the AKS tools section) with a comment header `# Phase 36 — In-Guest Diagnostic tools` and add `execute_run_command`:

**Block lists (module-level constants, placed above the function):**

```python
BLOCKED_COMMANDS_LINUX: List[str] = [
    "rm", "kill", "shutdown", "reboot", "halt", "poweroff", "init",
    "format", "fdisk", "dd", "mkfs", "parted", "wipefs",
    "systemctl stop", "systemctl disable", "systemctl mask",
    "apt", "apt-get", "yum", "dnf", "pip", "pip3",
    "curl -X DELETE", "wget --post",
    "chmod 000", "chown root",
    "iptables -F", "iptables -X",
    "userdel", "groupdel", "passwd",
    "mount", "umount",
    "> /dev/sda", "of=/dev/",
]

BLOCKED_COMMANDS_WINDOWS: List[str] = [
    "Remove-Item", "Stop-Computer", "Restart-Computer",
    "Format-Volume", "Clear-Disk",
    "Stop-Service", "Disable-Service",
    "Install-Package", "Install-Module",
    "Set-ExecutionPolicy Unrestricted",
    "Remove-WindowsFeature",
]

MAX_SCRIPT_LENGTH = 1500
```

**Function signature:**
```python
@ai_function
def execute_run_command(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    script: str,
    os_type: str,
    thread_id: str,
) -> Dict[str, Any]:
```

**Logic:**
1. `start_time = time.monotonic()`, `agent_id = get_agent_identity()`
2. `instrument_tool_call(...)` context manager
3. Validate `os_type` is "Linux" or "Windows" — return error dict if not
4. Validate `len(script) <= MAX_SCRIPT_LENGTH` — return error dict if exceeded
5. Select block list: `BLOCKED_COMMANDS_LINUX` for Linux, `BLOCKED_COMMANDS_WINDOWS` for Windows
6. Check each line of `script.lower()` against each blocked command (case-insensitive substring match via `blocked.lower() in line`). Return error dict with `"blocked_command"` key if match found.
7. SDK null-guard: `if ComputeManagementClient is None: return {"error": "azure-mgmt-compute not installed", ...}`
8. Create client, build `RunCommandInput`:
   ```python
   from azure.mgmt.compute.models import RunCommandInput
   parameters = RunCommandInput(
       command_id="RunShellScript" if os_type == "Linux" else "RunPowerShellScript",
       script=script.splitlines(),
   )
   ```
9. Call `client.virtual_machines.begin_run_command(resource_group, vm_name, parameters)` and `.result()`
10. Extract stdout from `result.value[0].message` and stderr from `result.value[1].message` (if exists)
11. Return `{"vm_name", "os_type", "stdout", "stderr", "command_id", "query_status": "success", "duration_ms"}`
12. Except block: return structured error dict with `duration_ms`

**Add `RunCommandInput` to the existing `azure.mgmt.compute` try/except import block at module top:**
```python
try:
    from azure.mgmt.compute import ComputeManagementClient
    from azure.mgmt.compute.models import RunCommandInput
except ImportError:
    ComputeManagementClient = None
    RunCommandInput = None
```
</action>
<acceptance_criteria>
- `grep -c "@ai_function" agents/compute/tools.py` returns a count >= 24 (20 existing + 4 new)
- `grep "def execute_run_command" agents/compute/tools.py` returns a match
- `grep "BLOCKED_COMMANDS_LINUX" agents/compute/tools.py` returns a match
- `grep "BLOCKED_COMMANDS_WINDOWS" agents/compute/tools.py` returns a match
- `grep "MAX_SCRIPT_LENGTH = 1500" agents/compute/tools.py` returns a match
- `grep "RunCommandInput" agents/compute/tools.py` returns matches (import + usage)
- `grep "RunShellScript" agents/compute/tools.py` returns a match
- `grep "RunPowerShellScript" agents/compute/tools.py` returns a match
- `grep "start_time = time.monotonic()" agents/compute/tools.py` returns matches for every tool (including new ones)
- The function never raises — only returns dicts (verify by reading source: no bare `raise` outside the ImportError guard)
</acceptance_criteria>
</task>

<task id="36-1-03">
<title>Add parse_boot_diagnostics_serial_log tool</title>
<read_first>
- agents/compute/tools.py (read the query_boot_diagnostics tool for pattern reference)
- .planning/phases/36-os-level-in-guest-vm-diagnostics/36-RESEARCH.md (Section 2.2)
</read_first>
<action>
Add `parse_boot_diagnostics_serial_log` in the Phase 36 section of `tools.py`.

**Add `import urllib.request` at the top of the file (stdlib, already available).**

**Module-level regex patterns constant:**
```python
SERIAL_LOG_PATTERNS: Dict[str, List[str]] = {
    "kernel_panic": ["Kernel panic", "BUG: unable to handle"],
    "oom_kill": ["Out of memory: Kill process", "oom-kill", "oom_reaper"],
    "disk_error": ["I/O error", "EXT4-fs error", "XFS error", "blk_update_request: I/O error"],
    "fs_corruption": ["FILESYSTEM CORRUPTION DETECTED", "fsck"],
}

SERIAL_LOG_MAX_BYTES = 50 * 1024  # 50KB
SERIAL_LOG_EXCERPT_MAX_CHARS = 200
```

**Function signature:**
```python
@ai_function
def parse_boot_diagnostics_serial_log(
    serial_log_uri: str,
    thread_id: str,
) -> Dict[str, Any]:
```

**Logic:**
1. Standard pattern: `start_time`, `agent_id`, `instrument_tool_call`
2. Validate `serial_log_uri` is not empty — return error dict if empty
3. Download first 50KB via `urllib.request.urlopen(serial_log_uri)` then `.read(SERIAL_LOG_MAX_BYTES)`. Decode as UTF-8 with `errors="replace"`.
4. Split content into lines. For each line, check against each pattern category in `SERIAL_LOG_PATTERNS` (case-insensitive via `pattern.lower() in line.lower()`).
5. When match found, create event dict: `{"type": category, "line_number": line_idx + 1, "excerpt": line[:SERIAL_LOG_EXCERPT_MAX_CHARS].strip()}`
6. Build summary dict counting events per category: `{"kernel_panic": N, "oom_kill": N, "disk_error": N, "fs_corruption": N}`
7. Return:
   ```python
   {
       "detected_events": detected_events,
       "summary": summary,
       "serial_log_size_bytes": len(content_bytes),
       "truncated": len(content_bytes) >= SERIAL_LOG_MAX_BYTES,
       "total_events": len(detected_events),
       "query_status": "success",
       "duration_ms": duration_ms,
   }
   ```
8. Except block: structured error dict with `duration_ms`
</action>
<acceptance_criteria>
- `grep "def parse_boot_diagnostics_serial_log" agents/compute/tools.py` returns a match
- `grep "SERIAL_LOG_PATTERNS" agents/compute/tools.py` returns a match
- `grep "SERIAL_LOG_MAX_BYTES" agents/compute/tools.py` returns a match
- `grep "urllib.request" agents/compute/tools.py` returns a match
- `grep "Kernel panic" agents/compute/tools.py` returns a match
- `grep "oom-kill" agents/compute/tools.py` returns a match
- `grep "I/O error" agents/compute/tools.py` returns a match
- `grep "SERIAL_LOG_EXCERPT_MAX_CHARS = 200" agents/compute/tools.py` returns a match
</acceptance_criteria>
</task>

<task id="36-1-04">
<title>Add query_vm_guest_health tool</title>
<read_first>
- agents/compute/tools.py (read query_log_analytics for LogsQueryClient pattern)
- .planning/phases/36-os-level-in-guest-vm-diagnostics/36-RESEARCH.md (Section 2.3)
</read_first>
<action>
Add `query_vm_guest_health` in the Phase 36 section of `tools.py`.

**Function signature:**
```python
@ai_function
def query_vm_guest_health(
    resource_id: str,
    workspace_id: str,
    thread_id: str,
) -> Dict[str, Any]:
```

**Logic:**
1. Standard pattern: `start_time`, `agent_id`, `instrument_tool_call`
2. Guard: if `not workspace_id`, return `{"query_status": "skipped", "reason": "workspace_id is empty"}`
3. SDK null-guard: `if LogsQueryClient is None: return error dict`
4. Create `LogsQueryClient(credential)`
5. **Heartbeat KQL:**
   ```python
   heartbeat_kql = (
       "Heartbeat"
       f' | where _ResourceId =~ "{resource_id}"'
       " | where TimeGenerated > ago(15m)"
       " | summarize LastHeartbeat = max(TimeGenerated)"
       " | extend MinutesAgo = datetime_diff('minute', now(), LastHeartbeat)"
   )
   ```
6. Execute via `client.query_workspace(workspace_id=workspace_id, query=heartbeat_kql, timespan="PT15M")`
7. Extract `minutes_ago` from result row. Classify:
   - `minutes_ago < 5` → `"healthy"`
   - `5 <= minutes_ago <= 15` → `"stale"`
   - `minutes_ago > 15` or no rows → `"offline"`
8. **Guest metrics KQL:**
   ```python
   metrics_kql = (
       "InsightsMetrics"
       f' | where _ResourceId =~ "{resource_id}"'
       " | where TimeGenerated > ago(5m)"
       ' | where Namespace in ("Processor", "Memory", "LogicalDisk")'
       " | summarize"
       '     cpu_pct = avgif(Val, Namespace == "Processor" and Name == "UtilizationPercentage"),'
       '     available_memory_mb = avgif(Val, Namespace == "Memory" and Name == "AvailableMB"),'
       '     disk_free_pct = avgif(Val, Namespace == "LogicalDisk" and Name == "FreeSpacePercentage")'
   )
   ```
9. Execute and extract values (default to `None` if empty)
10. Return:
    ```python
    {
        "resource_id": resource_id,
        "heartbeat_status": heartbeat_status,  # "healthy" / "stale" / "offline"
        "last_heartbeat_minutes_ago": minutes_ago,
        "cpu_utilization_pct": cpu_pct,
        "available_memory_mb": available_memory_mb,
        "disk_free_pct": disk_free_pct,
        "ama_data_available": cpu_pct is not None or available_memory_mb is not None,
        "query_status": "success",
        "duration_ms": duration_ms,
    }
    ```
11. Except block: structured error dict
</action>
<acceptance_criteria>
- `grep "def query_vm_guest_health" agents/compute/tools.py` returns a match
- `grep "heartbeat_status" agents/compute/tools.py` returns a match
- `grep '"healthy"' agents/compute/tools.py` returns a match (heartbeat classification)
- `grep '"stale"' agents/compute/tools.py` returns a match
- `grep '"offline"' agents/compute/tools.py` returns a match
- `grep "ama_data_available" agents/compute/tools.py` returns a match
- `grep "InsightsMetrics" agents/compute/tools.py` returns matches (in this tool and the next)
- `grep "Heartbeat" agents/compute/tools.py` returns a match
</acceptance_criteria>
</task>

<task id="36-1-05">
<title>Add query_ama_guest_metrics tool</title>
<read_first>
- agents/compute/tools.py (read query_log_analytics and query_vm_guest_health for pattern)
- .planning/phases/36-os-level-in-guest-vm-diagnostics/36-RESEARCH.md (Section 2.4)
</read_first>
<action>
Add `query_ama_guest_metrics` in the Phase 36 section of `tools.py`.

**Function signature:**
```python
@ai_function
def query_ama_guest_metrics(
    resource_id: str,
    workspace_id: str,
    timespan_hours: int = 24,
    thread_id: str = "",
) -> Dict[str, Any]:
```

**Logic:**
1. Standard pattern: `start_time`, `agent_id`, `instrument_tool_call`
2. Guard: if `not workspace_id`, return `{"query_status": "skipped", "reason": "workspace_id is empty"}`
3. SDK null-guard
4. **KQL query:**
   ```python
   kql = (
       "InsightsMetrics"
       f' | where _ResourceId =~ "{resource_id}"'
       f" | where TimeGenerated > ago({timespan_hours}h)"
       ' | where Namespace in ("Processor", "Memory", "LogicalDisk")'
       " | summarize"
       '     cpu_p50 = percentile(iff(Namespace == "Processor" and Name == "UtilizationPercentage", Val, real(null)), 50),'
       '     cpu_p95 = percentile(iff(Namespace == "Processor" and Name == "UtilizationPercentage", Val, real(null)), 95),'
       '     memory_avg_mb = avg(iff(Namespace == "Memory" and Name == "AvailableMB", Val, real(null))),'
       '     disk_iops = avg(iff(Namespace == "LogicalDisk" and Name == "TransfersPerSecond", Val, real(null)))'
       "     by bin(TimeGenerated, 1h)"
       " | order by TimeGenerated asc"
   )
   ```
5. Execute via `client.query_workspace(workspace_id=workspace_id, query=kql, timespan=f"PT{timespan_hours}H")`
6. Parse response tables into buckets list:
   ```python
   buckets = []
   for row in rows:
       buckets.append({
           "timestamp": row.get("TimeGenerated"),
           "cpu_p50": _safe_float(row.get("cpu_p50")),
           "cpu_p95": _safe_float(row.get("cpu_p95")),
           "memory_avg_mb": _safe_float(row.get("memory_avg_mb")),
           "disk_iops": _safe_float(row.get("disk_iops")),
       })
   ```
   Add a small helper `_safe_float(val)` that returns `float(val)` if val is not None and not empty string, else `None`.
7. Return:
   ```python
   {
       "resource_id": resource_id,
       "workspace_id": workspace_id,
       "timespan_hours": timespan_hours,
       "buckets": buckets,
       "total_buckets": len(buckets),
       "query_status": "success",
       "duration_ms": duration_ms,
   }
   ```
8. Except block: structured error dict
</action>
<acceptance_criteria>
- `grep "def query_ama_guest_metrics" agents/compute/tools.py` returns a match
- `grep "cpu_p50" agents/compute/tools.py` returns a match
- `grep "cpu_p95" agents/compute/tools.py` returns a match
- `grep "disk_iops" agents/compute/tools.py` returns a match
- `grep "total_buckets" agents/compute/tools.py` returns a match
- `grep "TransfersPerSecond" agents/compute/tools.py` returns a match
- `grep "timespan_hours" agents/compute/tools.py` returns matches
- `grep "_safe_float" agents/compute/tools.py` returns a match
</acceptance_criteria>
</task>

## Verification

```bash
# All 4 new functions exist with @ai_function decorator
grep -c "def execute_run_command\|def parse_boot_diagnostics_serial_log\|def query_vm_guest_health\|def query_ama_guest_metrics" agents/compute/tools.py
# Expected: 4

# Safety constants exist
grep "BLOCKED_COMMANDS_LINUX\|BLOCKED_COMMANDS_WINDOWS\|MAX_SCRIPT_LENGTH\|SERIAL_LOG_PATTERNS\|SERIAL_LOG_MAX_BYTES" agents/compute/tools.py

# requirements.txt has azure-mgmt-compute
grep "azure-mgmt-compute" agents/compute/requirements.txt

# No bare raise in any Phase 36 function (they return error dicts)
# Verify by reading the new section
```
