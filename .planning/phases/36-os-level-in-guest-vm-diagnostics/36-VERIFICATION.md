---
phase: 36
status: passed
verified_at: 2026-04-11
---

# Phase 36 Verification: OS-Level In-Guest VM Diagnostics

## Goal
Expose OS-level in-guest diagnostic capabilities through the compute agent — run commands inside VMs via Azure Run Command, parse boot diagnostics serial logs, query AMA heartbeat/guest health, and retrieve AMA hourly guest metrics.

## Verification Results

### Tools Implemented ✓
- [x] `execute_run_command` — Azure Run Command API, auto-detects Linux (RunShellScript) / Windows (RunPowerShellScript) via `os_type`, hard block list (22 Linux + 10 Windows destructive commands), 1500-char script limit, structured error dict (never raises)
- [x] `parse_boot_diagnostics_serial_log` — downloads SAS URI via `urllib.request`, detects kernel panics (`Kernel panic`, `BUG: unable to handle`), OOM kills (`Out of memory: Kill process`, `oom-kill`), disk errors (`I/O error`, `EXT4-fs error`, `XFS error`), filesystem corruption (`FILESYSTEM CORRUPTION DETECTED`, `fsck`); 50KB download limit; returns `detected_events` list + per-type summary counts
- [x] `query_vm_guest_health` — AMA heartbeat classification: `healthy` (< 5 min), `stale` (5–15 min), `offline` (> 15 min); latest CPU/memory/disk metrics from `InsightsMetrics` via Log Analytics; uses `resource_id` + `workspace_id` signature
- [x] `query_ama_guest_metrics` — hourly `InsightsMetrics` buckets over configurable `timespan_hours` (default 24h) returning `cpu_p50`, `cpu_p95`, `memory_avg_mb`, `disk_iops` per bucket; `_safe_float` helper handles None/empty KQL values

### Agent Registration ✓
- [x] All 4 tools imported in `agents/compute/agent.py` (lines 33–52)
- [x] All 4 tools registered in `COMPUTE_TOOLS` list (lines 141–144)
- [x] All 4 tools registered in `ChatAgent` tools list (lines 188–191)
- [x] All 4 tools registered in `PromptAgentDefinition` tools list (lines 242–245)

### Tests ✓
- [x] 20/20 unit tests passing — `agents/tests/compute/test_compute_guest_diagnostics.py`
- [x] `TestExecuteRunCommand` — 7 tests: Linux success, Windows success, blocked command, script too long, missing subscription, SDK unavailable, SDK exception
- [x] `TestParseBootDiagnosticsSerialLog` — 5 tests: kernel panic, OOM kill, disk error, clean log, download failure
- [x] `TestQueryVmGuestHealth` — 5 tests: healthy/stale/offline heartbeat classification, missing workspace, SDK exception
- [x] `TestQueryAmaGuestMetrics` — 3 tests: success with metrics, missing workspace, SDK exception

### Notes
- Signatures use `resource_id: str` instead of `(resource_group, vm_name, subscription_id)` for `query_vm_guest_health` and `query_ama_guest_metrics` — this is an intentional, cleaner deviation from the CONTEXT.md spec. `execute_run_command` retains the `(resource_group, vm_name, subscription_id)` decomposition as specified.
- `azure-mgmt-compute>=30.0.0` added to `agents/compute/requirements.txt` (was missing).
- `LogsQueryStatus` and `RunCommandInput` patched at `agents.compute.tools.*` in tests to avoid SDK import failures in the local test environment.

## Status: PASSED
