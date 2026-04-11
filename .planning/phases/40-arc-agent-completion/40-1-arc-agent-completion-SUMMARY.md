---
phase: 40
plan: 1
title: "Arc Agent Completion"
status: complete
completed_at: "2026-04-11"
branch: gsd/phase-40-arc-agent-completion
commits:
  - 5c7ef88  feat(arc): add 4 missing SDK packages to requirements.txt
  - 55c0677  feat(arc): add lazy imports and _extract_subscription_id helper
  - 2ee00db  feat(arc): replace query_activity_log stub with real MonitorManagementClient impl
  - ae557cb  feat(arc): replace query_log_analytics stub with real LogsQueryClient impl
  - 4efc320  feat(arc): replace query_resource_health stub with real MicrosoftResourceHealth impl
  - debc43b  feat(arc): add propose_arc_extension_install HITL tool
  - d6c265c  feat(arc): register all 8 tools in agent.py — import, tools list, version list, system prompt
  - 2b6f916  feat(web-ui): add vm_type to VMDetail interface and Arc-aware metrics message
  - 43c4775  test(arc): add 15 unit tests for Phase 40 stub replacements and HITL tool
---

# Summary — Plan 40-1: Arc Agent Completion

## What Was Done

Brought Arc-connected resources to feature parity with Azure-native VMs by:

1. **Task 1** — Added 4 missing SDK packages to `agents/arc/requirements.txt`:
   `azure-mgmt-monitor>=6.0.0`, `azure-monitor-query>=1.3.0`,
   `azure-mgmt-resourcehealth==1.0.0b6`, `azure-mgmt-guestconfiguration>=1.0.0`.

2. **Task 2** — Added 3 lazy import blocks (`MonitorManagementClient`, `LogsQueryClient`/`LogsQueryStatus`,
   `MicrosoftResourceHealth`) and `_extract_subscription_id` helper to `agents/arc/tools.py`.
   Also added `from datetime import datetime, timedelta, timezone`.

3. **Task 3** — Replaced `query_activity_log` stub (returned `entries: []`) with real
   `MonitorManagementClient.activity_logs.list()` implementation. `start_time` placed BEFORE
   the `with instrument_tool_call(...)` block per CLAUDE.md pattern.

4. **Task 4** — Replaced `query_log_analytics` stub with real `LogsQueryClient.query_workspace()`
   implementation. Handles empty `workspace_id` → `query_status: "skipped"`, SUCCESS/partial
   paths, and error dict fallback.

5. **Task 5** — Replaced `query_resource_health` stub (returned `"Resource Health query pending."`)
   with real `MicrosoftResourceHealth.availability_statuses.get_by_resource()` implementation.
   Returns `availability_state`, `summary`, `reason_type`, `occurred_time`.

6. **Task 6** — Added `propose_arc_extension_install` HITL tool following the `propose_arc_assessment`
   pattern. `risk_level="medium"`, `action="arc_extension_install"`, returns `pending_approval`.

7. **Task 7** — Registered all 8 tools in `agents/arc/agent.py` at all 4 locations:
   - Import block (lines 40–49)
   - `allowed_tools` format string in system prompt
   - `tools = [...]` list in `create_arc_agent()`
   - `tools=[...]` list in `create_arc_agent_version()`
   Also updated triage Steps 2, 3, added new Step 3b (guest config), updated Step 7 to mention
   `propose_arc_extension_install`.

8. **Task 8** — Added `vm_type?: string` to `VMDetail` interface in `VMDetailPanel.tsx`.
   Updated metrics no-data message to a 3-way check: deallocated → deallocated message;
   `vm_type === 'Arc VM'` → Log Analytics guidance; else → generic message.

9. **Task 9** — Created `agents/tests/arc/test_arc_tools_phase40.py` with 15 unit tests.
   Fixed pytest-asyncio `AsyncMock` auto-detection issue by using `new_callable=MagicMock`
   on `create_approval_record` patches.

## Verification Results

| Check | Result |
|-------|--------|
| `tools.py` parse | ✅ OK |
| `agent.py` parse | ✅ OK |
| 4 packages in requirements.txt | ✅ All 4 present |
| Stub string `"Resource Health query pending."` removed | ✅ Not found |
| `workspace_id is empty` guard present | ✅ Found |
| `propose_arc_extension_install` defined | ✅ Found |
| New tool count in agent.py (5 tools × multiple locations) | ✅ 25 matches |
| Phase 40 tests | ✅ 15/15 pass |
| All Arc tests (Phase 32 + 40) | ✅ 21/21 pass, 0 regressions |
| TypeScript compile | ✅ 0 errors |

## Files Modified

| File | Change |
|------|--------|
| `agents/arc/requirements.txt` | +6 lines: 4 new SDK packages |
| `agents/arc/tools.py` | +344 lines: lazy imports, helper, 3 real impls, 1 new HITL tool |
| `agents/arc/agent.py` | +39 lines: all 8 tools registered in 4 locations, triage steps updated |
| `services/web-ui/components/VMDetailPanel.tsx` | +3 lines: vm_type field + Arc metrics message |
| `agents/tests/arc/test_arc_tools_phase40.py` | +319 lines: 15 new unit tests (new file) |

## Lessons

- **AsyncMock auto-detection**: pytest-asyncio in `asyncio: mode=auto` promotes plain `MagicMock`
  patches on functions to `AsyncMock` when the test class is in async context. Fix: use
  `new_callable=MagicMock` on `@patch` decorators for synchronous callables that return dicts.
  The existing Phase 32 `TestProposeArcAssessment` test only called `assert_called_once()` and
  never asserted the return value, which masked this issue.
