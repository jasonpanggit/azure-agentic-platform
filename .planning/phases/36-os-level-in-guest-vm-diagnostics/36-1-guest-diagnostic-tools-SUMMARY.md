---
phase: 36-os-level-in-guest-vm-diagnostics
plan: 1
subsystem: agents
tags: [azure-mgmt-compute, run-command, boot-diagnostics, heartbeat, ama, insights-metrics, kql]

requires:
  - phase: 32-vm-domain-depth
    provides: Compute agent tool patterns, Phase 32 section structure
provides:
  - execute_run_command tool with destructive command block lists
  - parse_boot_diagnostics_serial_log tool with pattern detection
  - query_vm_guest_health tool with heartbeat classification
  - query_ama_guest_metrics tool with hourly time-series buckets
  - azure-mgmt-compute declared in requirements.txt
affects: [36-2-agent-registration, 36-3-guest-diagnostic-tests]

tech-stack:
  added: []
  patterns: [run-command-safety-blocklist, serial-log-pattern-detection, heartbeat-health-classification]

key-files:
  created: []
  modified:
    - agents/compute/tools.py
    - agents/compute/requirements.txt

key-decisions:
  - "Block list uses case-insensitive substring match for maximum safety coverage"
  - "Serial log download limited to 50KB to prevent memory issues with large logs"
  - "Heartbeat classification thresholds: <5min healthy, 5-15min stale, >15min offline"
  - "_safe_float helper handles None, empty string, and non-numeric KQL values"

patterns-established:
  - "Phase 36 section header in tools.py for in-guest diagnostic tools"
  - "BLOCKED_COMMANDS_LINUX/WINDOWS constants for command safety validation"
  - "SERIAL_LOG_PATTERNS dict for extensible boot error detection"

requirements-completed: []

duration: 15min
completed: 2026-04-11
---

# Plan 36-1: In-Guest Diagnostic Tool Functions Summary

**4 new @ai_function tools for in-guest VM diagnostics: run command execution with safety block lists, serial log parsing, heartbeat health classification, and AMA hourly metrics time-series**

## Performance

- **Duration:** 15 min
- **Started:** 2026-04-11
- **Completed:** 2026-04-11
- **Tasks:** 5
- **Files modified:** 2

## Accomplishments
- Added `execute_run_command` with hard block lists for destructive commands (22 Linux, 10 Windows), 1500-char script limit, and RunShellScript/RunPowerShellScript selection
- Added `parse_boot_diagnostics_serial_log` detecting kernel panics, OOM kills, disk errors, and filesystem corruption in serial console logs (50KB limit)
- Added `query_vm_guest_health` classifying heartbeat as healthy/stale/offline with latest CPU/memory/disk metrics from AMA InsightsMetrics
- Added `query_ama_guest_metrics` returning hourly buckets with cpu_p50, cpu_p95, memory_avg_mb, and disk_iops for trend analysis
- Declared `azure-mgmt-compute>=30.0.0` in requirements.txt (was imported but never declared)

## Task Commits

Each task was committed atomically:

1. **Task 01: Add azure-mgmt-compute to requirements.txt** - `2e68c70` (feat)
2. **Task 02: Add execute_run_command tool** - `a31b1cf` (feat)
3. **Task 03: Add parse_boot_diagnostics_serial_log tool** - `46fbd05` (feat)
4. **Task 04: Add query_vm_guest_health tool** - `def3445` (feat)
5. **Task 05: Add query_ama_guest_metrics tool** - `cbf4edb` (feat)

## Files Created/Modified
- `agents/compute/requirements.txt` - Added azure-mgmt-compute>=30.0.0 dependency
- `agents/compute/tools.py` - Added Phase 36 section with 4 new @ai_function tools, RunCommandInput import, urllib.request import, safety constants, serial log pattern constants, and _safe_float helper

## Decisions Made
None - followed plan as specified

## Deviations from Plan
None - plan executed exactly as written

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 4 tools ready for agent registration (Plan 36-2)
- All 4 tools ready for unit tests (Plan 36-3)
- Total @ai_function count in compute agent: 25 (21 existing + 4 new)

---
*Phase: 36-os-level-in-guest-vm-diagnostics*
*Completed: 2026-04-11*
