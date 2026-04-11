# Phase 36: OS-Level In-Guest VM Diagnostics - Context

**Gathered:** 2026-04-11
**Status:** Ready for planning
**Mode:** Auto-generated (smart discuss — infrastructure/backend phase)

<domain>
## Phase Boundary

Phase 36 adds in-guest VM diagnostic capabilities to the compute agent. The goal is to see *inside* the VM, not just around it. Specifically:

1. **Azure Run Command** — safe in-guest script execution via `azure-mgmt-compute` `RunCommand` API
2. **Boot diagnostics serial log parsing** — download serial log content and parse for kernel panics, OOM kills, disk errors, filesystem corruption markers
3. **VM Guest Health** — heartbeat/memory/CPU/disk pressure tools using Azure VM Guest Health API or Log Analytics heartbeat queries
4. **AMA metrics** — surface guest OS metrics (CPU %, memory %, disk IOPS) via AMA → Log Analytics (`InsightsMetrics` table)

**Out of scope:** UI changes (frontend panel enhancements are Phase 41), forecasting (Phase 37), cost (Phase 39).

</domain>

<decisions>
## Implementation Decisions

### Azure Run Command
- Use `azure-mgmt-compute` `RunCommandDocument` — `VirtualMachines.begin_run_command` (async ARM operation)
- Command set: `RunShellScript` (Linux) or `RunPowerShellScript` (Windows) — detect from VM osType
- Safety limits: max 1500 chars script body, read-only diagnostic commands only (no apt/yum/rm etc.)
- Block list: destructive commands (`rm`, `kill`, `shutdown`, `reboot`, `format`, `fdisk`, `dd`, `mkfs`)
- Tool name: `execute_run_command(resource_group, vm_name, subscription_id, script, thread_id)`
- Returns: stdout, stderr, exit_code, duration_ms; errors return structured dict (never raise)

### Boot Diagnostics Serial Log Parsing
- Extend existing `query_boot_diagnostics` — it already returns `serial_log_uri`
- Add separate tool `parse_boot_diagnostics_serial_log` that downloads the SAS URI content via `requests.get`
- Parse for: kernel panic (`"Kernel panic"`, `"BUG: unable to handle"`), OOM kills (`"Out of memory: Kill process"`, `"oom-kill"`), disk errors (`"I/O error"`, `"EXT4-fs error"`, `"XFS error"`), filesystem corruption (`"FILESYSTEM CORRUPTION DETECTED"`, `"fsck"`)
- Returns: list of detected_events with type, line_number, excerpt; summary counts per type
- Limit: read first 50KB of serial log to avoid large downloads

### VM Guest Health
- Use Log Analytics `InsightsMetrics` table (populated by AMA) — not the deprecated VM Insights REST API
- Query: `InsightsMetrics | where Namespace == "Computer" | where Name in ("AvailableMemoryMB", "UtilizationPercentage", "LogicalDisk")` filtered by `_ResourceId`
- Heartbeat check: `Heartbeat | where _ResourceId =~ resource_id | where TimeGenerated > ago(5m) | summarize LastHeartbeat=max(TimeGenerated)`
- Tool name: `query_vm_guest_health(resource_group, vm_name, subscription_id, workspace_id, thread_id)`
- Returns: heartbeat_ok, last_heartbeat_minutes_ago, cpu_utilization_pct, available_memory_mb, disk_pressure_pct

### AMA Metrics Surface
- Reuse `query_log_analytics` infrastructure already in `tools.py`
- Add `query_ama_guest_metrics` tool querying `InsightsMetrics` for a time range
- Returns: cpu_p50, cpu_p95, memory_avg_mb, disk_iops per 1h buckets over last 24h
- Requires `workspace_id` param — passed from API gateway env var `LOG_ANALYTICS_WORKSPACE_ID`

### Agent Registration
- Register all 4 new tools in `agents/compute/agent.py` using the existing registration pattern
- Add to `COMPUTE_TOOLS` list and both `ChatAgent` tool lists

### Claude's Discretion
- Error handling pattern: follow existing tools.py convention (`start_time = time.monotonic()`, structured error dict, never raise)
- Test coverage: follow existing `tests/compute/` pattern with mock clients

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/compute/tools.py` — 20 registered `@ai_function` tools; `query_boot_diagnostics` already returns serial_log_uri; `query_log_analytics` is the pattern for LA queries
- `agents/compute/agent.py` — `COMPUTE_TOOLS` list + `ChatAgent` registration pattern; add new tools here
- `instrument_tool_call`, `get_credential`, `get_agent_identity` helpers used consistently across all tools
- `_extract_subscription_id(resource_id)` utility already exists

### Established Patterns
- Every tool: `start_time = time.monotonic()`, try/except, `duration_ms` in both branches, return structured dict never raise
- SDK null-guard: `if ComputeManagementClient is None: return {"error": "not installed"}`
- Log Analytics queries: use `LogsQueryClient` from `azure-monitor-query` (already imported)
- Tests: `tests/compute/` with `unittest.mock.patch` on SDK clients; test files follow `test_*_tools.py` pattern

### Integration Points
- `agents/compute/agent.py` — add new tools to `COMPUTE_TOOLS` and both agent constructor `tools=` lists
- `agents/compute/tools.py` — add 4 new `@ai_function` functions
- `services/api-gateway/vm_inventory.py` — AMA status already resolved from ARG (no change needed)
- `agents/tests/compute/` — add test file `test_compute_guest_tools.py`

</code_context>

<specifics>
## Specific Ideas

- The Run Command tool must include a **hard block list** for destructive commands. This is a safety constraint — operators should only be able to run diagnostic scripts (df, top, dmesg, ps, netstat, etc.).
- Serial log parsing should return excerpts (not full lines) — keep the payload small for agent context efficiency.
- Guest health heartbeat should classify: `healthy` (< 5 min ago), `stale` (5–15 min), `offline` (> 15 min).

</specifics>

<deferred>
## Deferred Ideas

- UI surface for run command output in VM detail panel → Phase 41 (VMSS/AKS tabs also updates VM panel)
- Run command history/audit log → future phase
- Scheduled diagnostic scripts → out of scope for this platform

</deferred>
