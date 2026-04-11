# Phase 36: OS-Level In-Guest VM Diagnostics — Research

**Researched:** 2026-04-11
**Phase:** 36
**Goal:** See inside the VM, not just around it. Add 4 new `@ai_function` tools to the compute agent for in-guest diagnostics.

---

## 1. Scope Summary (from 36-CONTEXT.md)

| Tool | Purpose | SDK Surface |
|------|---------|-------------|
| `execute_run_command` | Safe in-guest script execution | `azure-mgmt-compute` `RunCommandInput` |
| `parse_boot_diagnostics_serial_log` | Kernel panic / OOM / disk error detection from serial log | HTTP GET on SAS URI from existing `query_boot_diagnostics` |
| `query_vm_guest_health` | Heartbeat + CPU + memory + disk pressure | `azure-monitor-query` `LogsQueryClient` (KQL on `Heartbeat` + `InsightsMetrics`) |
| `query_ama_guest_metrics` | Guest OS performance metrics over 24h | `azure-monitor-query` `LogsQueryClient` (KQL on `InsightsMetrics`) |

**Out of scope:** UI changes (Phase 41), forecasting (Phase 37), cost (Phase 39).

---

## 2. Azure SDK APIs — Detailed Research

### 2.1 Run Command API

**Package:** `azure-mgmt-compute` (already in `agents/compute/requirements.txt` — BUT version not specified, only `azure-mgmt-resourcegraph` and `azure-mgmt-monitor` are listed; `ComputeManagementClient` is imported with try/except guard at module level)

**Observation:** `azure-mgmt-compute` is NOT in `agents/compute/requirements.txt`. However, it IS imported in `tools.py` with a try/except guard and is used by multiple Phase 32 tools (`query_vm_extensions`, `query_boot_diagnostics`, `query_vm_sku_options`, `query_disk_health`, VMSS tools). This means it's available in the base image or pulled transitively. Need to verify — **add `azure-mgmt-compute>=30.0.0` to `requirements.txt` to be explicit.**

**API — Legacy (action-based):**
```python
from azure.mgmt.compute.models import RunCommandInput

parameters = RunCommandInput(
    command_id='RunShellScript',  # or 'RunPowerShellScript'
    script=['df -h', 'free -m']
)

poller = client.virtual_machines.begin_run_command(
    resource_group_name="rg",
    vm_name="vm",
    parameters=parameters
)
result = poller.result()
# result.value: list of InstanceViewStatus
# Each has .code, .message, .display_status
```

**API — New (resource-based):**
```python
from azure.mgmt.compute.models import VirtualMachineRunCommand

run_command = VirtualMachineRunCommand(
    location="eastus",
    source={"script": "df -h"},
    async_execution=False,
    timeout_in_seconds=300
)

poller = client.virtual_machine_run_commands.begin_create_or_update(
    resource_group_name="rg",
    vm_name="vm",
    run_command_name="myDiagnosticCommand",
    run_command=run_command
)
```

**Decision: Use legacy `begin_run_command`** — it's simpler for one-shot diagnostic scripts (no resource lifecycle to manage). The legacy API is stable and sufficient for read-only diagnostics. The new resource-based API is better for persistent/scheduled commands, which is out of scope.

**Key constraints from CONTEXT:**
- Max 1500 chars script body
- Read-only diagnostic commands only
- Hard block list: `rm`, `kill`, `shutdown`, `reboot`, `format`, `fdisk`, `dd`, `mkfs`, `systemctl stop`, `systemctl disable`, `apt`, `yum`, `dnf`, `pip install`
- Detect OS type from VM properties to choose `RunShellScript` vs `RunPowerShellScript`
- Returns: stdout, stderr, exit_code, duration_ms

**Important:** `begin_run_command` is a Long-Running Operation (LRO). The poller blocks until the command completes (or times out). Default timeout is 90 seconds. For agent tool calls, this is acceptable but we should set a reasonable ceiling to avoid blocking the agent thread.

**Poller result structure:**
```
result.value = [
    InstanceViewStatus(
        code="ComponentStatus/StdOut/succeeded",
        message="<stdout content>",
        display_status="Provisioning succeeded"
    ),
    InstanceViewStatus(
        code="ComponentStatus/StdErr/succeeded",
        message="<stderr content>",
        display_status="Provisioning succeeded"
    )
]
```
- `result.value[0].message` = stdout
- `result.value[1].message` = stderr (if present)
- Exit code is not directly returned — infer from stdout/stderr and code field

### 2.2 Boot Diagnostics Serial Log

**Existing tool:** `query_boot_diagnostics` in `tools.py` already returns `serial_log_uri` (SAS URL to blob).

**New tool:** `parse_boot_diagnostics_serial_log` will:
1. Call `query_boot_diagnostics` internally (or accept `serial_log_uri` as parameter — CONTEXT says "separate tool that downloads the SAS URI content")
2. Download first 50KB of serial log via HTTP GET on the SAS URI
3. Parse for known error patterns

**HTTP client for downloading:**
- `requests` is NOT a guaranteed dependency (removed from `azure-identity` transitive deps in v1.19+)
- **Use `urllib.request.urlopen`** (stdlib, always available) for the SAS URI download
- Alternative: `azure.core.pipeline` — overkill for a simple GET

**Pattern matching — regex patterns from CONTEXT:**

| Category | Patterns |
|----------|----------|
| Kernel panic | `"Kernel panic"`, `"BUG: unable to handle"` |
| OOM kills | `"Out of memory: Kill process"`, `"oom-kill"`, `"oom_reaper"` |
| Disk errors | `"I/O error"`, `"EXT4-fs error"`, `"XFS error"`, `"blk_update_request: I/O error"` |
| FS corruption | `"FILESYSTEM CORRUPTION DETECTED"`, `"fsck"` |

**Return structure:**
```python
{
    "detected_events": [
        {"type": "oom_kill", "line_number": 142, "excerpt": "Out of memory: Kill process 1234 (java)..."},
        {"type": "disk_error", "line_number": 305, "excerpt": "EXT4-fs error (device sda1): ..."},
    ],
    "summary": {"kernel_panic": 0, "oom_kill": 1, "disk_error": 1, "fs_corruption": 0},
    "serial_log_size_bytes": 32768,
    "truncated": false,
    "query_status": "success"
}
```

**Excerpt length:** Keep excerpts to ~200 chars max to avoid bloating agent context.

### 2.3 VM Guest Health (Heartbeat + InsightsMetrics)

**Package:** `azure-monitor-query` (already in `requirements.txt` as `azure-monitor-query>=1.3.0`)

**KQL — Heartbeat check:**
```kql
Heartbeat
| where _ResourceId =~ "{resource_id}"
| where TimeGenerated > ago(15m)
| summarize LastHeartbeat = max(TimeGenerated)
| extend MinutesAgo = datetime_diff('minute', now(), LastHeartbeat)
```

**Heartbeat classification (from CONTEXT):**
- `healthy`: < 5 min ago
- `stale`: 5–15 min ago
- `offline`: > 15 min

**Key fields in Heartbeat table:**
- `Category`: `"Azure Monitor Agent"` (AMA) vs `"Direct Agent"` (legacy MMA)
- `OSType`: `Windows` / `Linux`
- `ComputerEnvironment`: `Azure` / `Non-Azure`
- `Computer`: hostname

**KQL — Guest health metrics:**
```kql
InsightsMetrics
| where _ResourceId =~ "{resource_id}"
| where TimeGenerated > ago(5m)
| where Namespace in ("Processor", "Memory", "LogicalDisk")
| summarize
    cpu_pct = avgif(Val, Namespace == "Processor" and Name == "UtilizationPercentage"),
    available_memory_mb = avgif(Val, Namespace == "Memory" and Name == "AvailableMB"),
    disk_free_pct = avgif(Val, Namespace == "LogicalDisk" and Name == "FreeSpacePercentage")
```

**InsightsMetrics table namespaces (populated by AMA + VM Insights DCR):**

| Namespace | Name | Unit |
|-----------|------|------|
| Processor | UtilizationPercentage | % |
| Memory | AvailableMB | MB |
| Memory | UsedMB | MB |
| LogicalDisk | FreeSpacePercentage | % |
| LogicalDisk | FreeSpaceMB | MB |
| LogicalDisk | TransfersPerSecond | count/s |
| LogicalDisk | ReadsPerSecond | count/s |
| LogicalDisk | WritesPerSecond | count/s |
| LogicalDisk | ReadBytesPerSecond | B/s |
| LogicalDisk | WriteBytesPerSecond | B/s |
| Network | ReadBytesPerSecond | B/s |
| Network | WriteBytesPerSecond | B/s |

**Important note:** `InsightsMetrics` data is only available if:
1. Azure Monitor Agent (AMA) is installed on the VM
2. A Data Collection Rule (DCR) with VM Insights performance counters is associated
3. The DCR is sending data to the target Log Analytics workspace

If AMA is not installed, the queries will return empty results — tool should handle gracefully.

### 2.4 AMA Guest Metrics (24h rollup)

**KQL:**
```kql
InsightsMetrics
| where _ResourceId =~ "{resource_id}"
| where TimeGenerated > ago(24h)
| where Namespace in ("Processor", "Memory", "LogicalDisk")
| summarize
    cpu_p50 = percentile(iff(Namespace == "Processor" and Name == "UtilizationPercentage", Val, real(null)), 50),
    cpu_p95 = percentile(iff(Namespace == "Processor" and Name == "UtilizationPercentage", Val, real(null)), 95),
    memory_avg_mb = avg(iff(Namespace == "Memory" and Name == "AvailableMB", Val, real(null))),
    disk_iops = avg(iff(Namespace == "LogicalDisk" and Name == "TransfersPerSecond", Val, real(null)))
    by bin(TimeGenerated, 1h)
| order by TimeGenerated asc
```

**Parameters:**
- `workspace_id`: Passed from API gateway env var `LOG_ANALYTICS_WORKSPACE_ID`
- `resource_id`: Full Azure resource ID (for `_ResourceId` filter)
- `timespan`: Default 24h

**Return structure:**
```python
{
    "resource_id": "...",
    "workspace_id": "...",
    "buckets": [
        {"timestamp": "2026-04-11T00:00:00Z", "cpu_p50": 12.3, "cpu_p95": 45.6, "memory_avg_mb": 2048, "disk_iops": 120},
        ...
    ],
    "total_buckets": 24,
    "query_status": "success"
}
```

---

## 3. Existing Code — What to Reuse

### 3.1 Tool pattern (CRITICAL — must follow exactly)

Every tool in `tools.py` follows this pattern:

```python
@ai_function
def tool_name(param1: str, param2: str, ...) -> Dict[str, Any]:
    """Docstring with purpose and Args/Returns."""
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="tool_name",
        tool_parameters={...},
        correlation_id="...",
        thread_id="...",
    ):
        try:
            if SdkClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {"error": "sdk-package not installed", "duration_ms": duration_ms}

            credential = get_credential()
            client = SdkClient(credential, subscription_id)
            # ... SDK calls ...
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {... "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("tool_name error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}
```

**Key invariants:**
- `@ai_function` decorator (from `agent_framework`)
- `start_time = time.monotonic()` at entry
- `duration_ms` in BOTH try and except blocks
- Never raise — return structured error dict
- SDK null-guard before any SDK call
- `instrument_tool_call` context manager for OTel

### 3.2 Agent registration pattern

In `agents/compute/agent.py`:
1. Import all tool functions from `compute.tools`
2. List them in `COMPUTE_AGENT_SYSTEM_PROMPT` (allowed tools section)
3. Pass to `ChatAgent(tools=[...])` in `create_compute_agent()`
4. Pass to `PromptAgentDefinition(tools=[...])` in `create_compute_agent_version()`

### 3.3 Existing boot diagnostics tool

`query_boot_diagnostics` already returns `serial_log_uri`. The new `parse_boot_diagnostics_serial_log` tool can:
- Accept `serial_log_uri` as a parameter (agent calls `query_boot_diagnostics` first, then passes the URI)
- OR accept `resource_group`, `vm_name`, `subscription_id` and call the boot diagnostics API internally

**Decision: Accept `serial_log_uri` directly.** This avoids making two ARM calls in one tool. The agent will naturally call `query_boot_diagnostics` first (it's already in the triage workflow), then pass the URI to the parser.

### 3.4 Log Analytics query pattern

`query_log_analytics` already exists and uses `LogsQueryClient`. The guest health and AMA metrics tools will follow the same pattern but with pre-built KQL queries rather than accepting arbitrary KQL.

### 3.5 Test pattern

Tests are in `agents/tests/compute/test_compute_new_tools.py`:
- `unittest.mock.patch` on SDK clients
- `_instrument_mock()` helper for OTel context manager
- Separate test class per tool
- Test both happy path and SDK-missing error path

---

## 4. Dependency Analysis

### Current compute agent dependencies:
```
# requirements-base.txt (all agents)
azure-identity>=1.17.0
azure-cosmos>=4.7.0
agent-framework==1.0.0b260107
azure-ai-projects==2.0.0b3
azure-ai-agents==1.2.0b5
azure-monitor-opentelemetry>=1.6.0

# agents/compute/requirements.txt
azure-mgmt-resourcegraph>=8.0.1
azure-mgmt-monitor>=6.0.0
azure-monitor-query>=1.3.0
azure-mgmt-resourcehealth==1.0.0b6
```

### Missing but needed:
| Package | Needed for | Action |
|---------|-----------|--------|
| `azure-mgmt-compute>=30.0.0` | Run Command (`RunCommandInput`, `begin_run_command`) | **Add to requirements.txt** — it's already used by Phase 32 tools but not declared |

### Already available (no changes needed):
| Package | Needed for |
|---------|-----------|
| `azure-monitor-query>=1.3.0` | `LogsQueryClient` for Heartbeat and InsightsMetrics KQL |
| `urllib.request` (stdlib) | Download serial log from SAS URI |

### NOT needed:
| Package | Reason |
|---------|--------|
| `requests` | Use `urllib.request` instead — `requests` is no longer a transitive dep of `azure-identity>=1.19.0` |

---

## 5. Safety Analysis — Run Command

The Run Command tool is the most safety-critical addition in this phase. Key mitigations:

### 5.1 Block list (hard-coded, not configurable)

**Linux (`RunShellScript`):**
```python
BLOCKED_COMMANDS = [
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
```

**Windows (`RunPowerShellScript`):**
```python
BLOCKED_COMMANDS_WINDOWS = [
    "Remove-Item", "Stop-Computer", "Restart-Computer",
    "Format-Volume", "Clear-Disk",
    "Stop-Service", "Disable-Service",
    "Install-Package", "Install-Module",
    "Set-ExecutionPolicy Unrestricted",
    "Remove-WindowsFeature",
]
```

### 5.2 Script validation logic
1. Check script length <= 1500 chars
2. Check each line against block list (case-insensitive)
3. Check for pipe to destructive commands (e.g., `| rm`, `| dd`)
4. Reject scripts that contain shell redirect to device files (`> /dev/`)
5. Return structured error if validation fails — do NOT call ARM

### 5.3 Allowed diagnostic commands (guidance, not enforced)
```
# Linux
df -h, free -m, top -bn1, dmesg | tail -50, ps aux --sort=-%mem | head -20,
cat /var/log/syslog | tail -100, journalctl -n 50 --no-pager,
netstat -tlnp, ss -tlnp, uptime, cat /etc/os-release,
systemctl list-units --state=failed, lsblk, cat /proc/meminfo

# Windows
Get-Process | Sort-Object CPU -Descending | Select-Object -First 20,
Get-EventLog -LogName System -EntryType Error -Newest 20,
Get-Service | Where-Object {$_.Status -eq 'Stopped'},
Get-PSDrive -PSProvider FileSystem, systeminfo,
Get-WmiObject Win32_OperatingSystem | Select-Object LastBootUpTime
```

### 5.4 OS type detection
- Use `osType` from VM properties (already available via `query_os_version` ARG tool or from the VM model's `storage_profile.os_disk.os_type`)
- If OS type is unknown, return error — do not guess

---

## 6. Implementation Plan Outline

### File changes:

| File | Change |
|------|--------|
| `agents/compute/tools.py` | Add 4 new `@ai_function` tools (~200-250 lines total) |
| `agents/compute/agent.py` | Import + register 4 new tools in `create_compute_agent()` + `create_compute_agent_version()` + system prompt |
| `agents/compute/requirements.txt` | Add `azure-mgmt-compute>=30.0.0` |
| `agents/tests/compute/test_compute_guest_tools.py` | New test file (~200-250 lines) |

### Tool signatures:

```python
@ai_function
def execute_run_command(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    script: str,
    os_type: str,  # "Linux" or "Windows"
    thread_id: str,
) -> Dict[str, Any]: ...

@ai_function
def parse_boot_diagnostics_serial_log(
    serial_log_uri: str,
    thread_id: str,
) -> Dict[str, Any]: ...

@ai_function
def query_vm_guest_health(
    resource_id: str,
    workspace_id: str,
    thread_id: str,
) -> Dict[str, Any]: ...

@ai_function
def query_ama_guest_metrics(
    resource_id: str,
    workspace_id: str,
    timespan_hours: int = 24,
    thread_id: str = "",
) -> Dict[str, Any]: ...
```

### Test plan:

| Test class | Tests |
|-----------|-------|
| `TestExecuteRunCommand` | Happy path Linux, happy path Windows, blocked command rejected, script too long, SDK missing, exception handling |
| `TestParseBootDiagnosticsSerialLog` | Kernel panic detected, OOM kill detected, disk error detected, clean log (no events), download failure, truncation at 50KB |
| `TestQueryVmGuestHealth` | Healthy heartbeat, stale heartbeat, offline (no heartbeat), SDK missing, empty InsightsMetrics |
| `TestQueryAmaGuestMetrics` | Happy path with 24 hourly buckets, empty results (no AMA), workspace_id empty (skip gracefully) |

---

## 7. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Run Command executes destructive script | HIGH | Hard block list + 1500 char limit + agent instructions say "diagnostic only" |
| Serial log download fails (expired SAS) | LOW | Return structured error; agent can re-call `query_boot_diagnostics` for fresh URI |
| InsightsMetrics empty (AMA not installed) | MEDIUM | Return empty metrics with `ama_data_available: false` indicator — agent adapts |
| Run Command timeout (VM agent unresponsive) | MEDIUM | LRO poller has default 90s timeout; acceptable for diagnostic scripts |
| `azure-mgmt-compute` not in requirements.txt | LOW | Fix: explicitly add it — already used by 10+ existing tools |
| Large serial log blocks agent context | MEDIUM | 50KB download limit + 200-char excerpts per event |

---

## 8. Open Questions for Planning

1. **Should `execute_run_command` require `incident_id`?** Other diagnostic tools don't require it, but approval-gated tools do. Since Run Command is diagnostic (read-only), it should NOT require incident_id — keep it consistent with `query_vm_extensions`, `query_boot_diagnostics`, etc.

2. **Should the block list be configurable via environment variable?** Decision from CONTEXT: "hard block list" — so NO, it's hard-coded. This is the safer default. An operator who needs to run destructive commands should use the Azure Portal or CLI directly.

3. **Should `parse_boot_diagnostics_serial_log` also check Windows serial logs?** Windows VMs have different serial log formats (SAC channel, boot log). The regex patterns in CONTEXT are Linux-focused. Decision: Linux patterns first; Windows patterns can be added in a future phase if needed. The tool should still work on Windows serial logs — it just may not detect as many event types.

4. **How to resolve `_ResourceId` in KQL?** The `_ResourceId` field in Log Analytics uses the full ARM resource ID (e.g., `/subscriptions/.../providers/Microsoft.Compute/virtualMachines/vm-name`). Use case-insensitive match (`=~`) since ARM resource IDs may have inconsistent casing. The tools will accept `resource_id` as a parameter (full ARM ID) and use it directly in KQL filters.

---

## 9. Sources

- [VirtualMachinesOperations.begin_run_command (Azure Python SDK)](https://learn.microsoft.com/en-us/python/api/azure-mgmt-compute/azure.mgmt.compute.v2024_07_01.operations.virtualmachinesoperations?view=azure-python)
- [RunCommandInput Class (Azure Python SDK)](https://learn.microsoft.com/en-us/python/api/azure-mgmt-compute/azure.mgmt.compute.v2024_07_01.models.runcommandinput?view=azure-python)
- [Run scripts in a Linux VM using Run Command](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/run-command)
- [Run scripts in a Windows VM using Run Command](https://learn.microsoft.com/en-us/azure/virtual-machines/windows/run-command)
- [InsightsMetrics table reference](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/insightsmetrics)
- [azure-identity removes requests dependency (PR #37898)](https://github.com/Azure/azure-sdk-for-python/pull/37898)
- [azure-mgmt-compute on PyPI](https://pypi.org/project/azure-mgmt-compute/)
