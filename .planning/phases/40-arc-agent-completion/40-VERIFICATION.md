---
phase: 40
status: passed
verified: 2026-04-11
must_haves_total: 9
must_haves_verified: 9
---

# Phase 40 Verification — Arc Agent Completion

## Verification Method

Each must-have was checked by reading the implementation files directly and running
the test suite. No inferences — every item below is confirmed against actual source.

---

## Must-Have Results

### MH-1 — `query_activity_log` uses real `MonitorManagementClient` ✅ PASS

**Evidence:** `agents/arc/tools.py` lines 157–195.

- `MonitorManagementClient` lazily imported at line 44–46.
- `MonitorManagementClient(credential, sub_id)` instantiated at line 166.
- `client.activity_logs.list(filter=filter_str)` called at line 171.
- Stub `entries: []` only appears in the error path (line 222), not as the sole
  success-path return value.
- `_extract_subscription_id(resource_id)` helper present at lines 90–110.

---

### MH-2 — `query_log_analytics` uses real `LogsQueryClient` ✅ PASS

**Evidence:** `agents/arc/tools.py` lines 266–350.

- Empty `workspace_id` guard at line 267 returns `query_status: "skipped"` (line 275).
- `LogsQueryClient(credential)` instantiated at line 284.
- `client.query_workspace(...)` called at line 285–289.
- `LogsQueryStatus.SUCCESS` branch at line 291 returns parsed rows.
- Error path returns `query_status: "error"` (line 348).

---

### MH-3 — `query_resource_health` uses real `MicrosoftResourceHealth` ✅ PASS

**Evidence:** `agents/arc/tools.py` lines 386–438.

- `MicrosoftResourceHealth(credential, sub_id)` instantiated at line 392.
- `client.availability_statuses.get_by_resource(resource_uri=resource_id, expand="recommendedActions")` called at lines 393–396.
- Returns `availability_state`, `summary`, `reason_type`, `occurred_time` (lines 410–421).
- Stub string `"Resource Health query pending."` confirmed absent — verified by
  `test_no_longer_returns_stub_pending_message` (which inspects the function source
  at runtime and passes).

---

### MH-4 — `propose_arc_extension_install` HITL tool with `pending_approval` return ✅ PASS

**Evidence:** `agents/arc/tools.py` lines 685–766.

- Decorated with `@ai_function` at line 685.
- `proposal["action"] = "arc_extension_install"` at line 732.
- `create_approval_record(..., risk_level="medium")` called at line 746–754.
- Returns `{"status": "pending_approval", "approval_id": ..., "message": ..., "duration_ms": ...}`
  at lines 756–762.
- Error path returns `{"status": "error", ...}` (never raises).

---

### MH-5 — All 8 tools registered in `agent.py` at all 4 locations ✅ PASS

**Evidence:** `agents/arc/agent.py`.

The plan required 8 tools (the plan text says "All 7 tools" in one bullet but lists 8 names,
and the goal section says 8; the implementation registers all 8).

| Location | Tools registered |
|----------|-----------------|
| **Import block** (lines 40–50) | All 8 imported by name |
| **`allowed_tools` format string** (lines 141–153) | All 8 listed in the `ALLOWED_MCP_TOOLS + [...]` concat |
| **`tools = [...]` in `create_arc_agent()`** (lines 177–186) | All 8 present |
| **`tools=[...]` in `create_arc_agent_version()`** (lines 234–243) | All 8 present |

Tools confirmed at all 4 locations:
`query_activity_log`, `query_log_analytics`, `query_resource_health`,
`query_arc_extension_health`, `query_arc_connectivity`, `query_arc_guest_config`,
`propose_arc_assessment`, `propose_arc_extension_install`.

System prompt triage workflow also updated: Step 2 references `query_arc_connectivity`,
Step 3 references `query_arc_extension_health`, new Step 3b covers `query_arc_guest_config`,
Step 7 mentions `propose_arc_extension_install`.

---

### MH-6 — 4 SDK packages in `agents/arc/requirements.txt` ✅ PASS

**Evidence:** `agents/arc/requirements.txt` lines 17–21.

```
azure-mgmt-monitor>=6.0.0       ✅ line 18
azure-monitor-query>=1.3.0      ✅ line 19
azure-mgmt-resourcehealth==1.0.0b6  ✅ line 20
azure-mgmt-guestconfiguration>=1.0.0  ✅ line 21
```

---

### MH-7 — `vm_type?: string` in `VMDetail` interface ✅ PASS

**Evidence:** `services/web-ui/components/VMDetailPanel.tsx`.

- `vm_type?: string` at line 24 (inside `interface VMDetail`).
- Three-way metrics no-data check at lines 851–855:
  - deallocated → deallocated message
  - `vm?.vm_type === 'Arc VM'` → Arc Log Analytics guidance message (line 853–854)
  - else → generic "No metrics available"

---

### MH-8 — 15 new tests in `test_arc_tools_phase40.py` all pass ✅ PASS

**Evidence:** pytest run output.

```
======================== 15 passed, 1 warning in 0.97s =========================
```

All 15 tests collected and passed. One LibreSSL/urllib3 compatibility warning
(pre-existing environment issue, unrelated to Phase 40).

Test classes:
- `TestQueryActivityLogArc` — 3 tests (sdk path, sdk missing, sdk exception)
- `TestQueryLogAnalyticsArc` — 3 tests (success rows, skipped on empty workspace, sdk missing)
- `TestQueryResourceHealthArc` — 3 tests (real state, sdk missing, stub string gone)
- `TestProposeArcExtensionInstall` — 3 tests (pending approval, medium risk, error on exception)
- `TestArcAgentRegistration` — 3 tests (8 tools importable, prompt contains new tool, prompt lists all 8)

---

### MH-9 — 21 total arc tests pass (no regressions) ✅ PASS

**Evidence:** pytest run over `agents/tests/arc/`.

```
======================== 21 passed, 2 warnings in 0.73s ========================
```

- 6 pre-existing Phase 32 tests in `test_arc_new_tools.py` — all pass.
- 15 new Phase 40 tests in `test_arc_tools_phase40.py` — all pass.
- 2 warnings: one LibreSSL/urllib3 (environment, pre-existing), one `AsyncMockMixin`
  coroutine-not-awaited in `test_arc_new_tools.py::TestProposeArcAssessment` — this is
  a pre-existing issue in the Phase 32 test file (noted in the SUMMARY lessons section)
  and does not affect test pass/fail status.

---

## Summary Table

| # | Must-Have | Status | Evidence location |
|---|-----------|--------|-------------------|
| 1 | `query_activity_log` uses `MonitorManagementClient` | ✅ PASS | `agents/arc/tools.py:157–195` |
| 2 | `query_log_analytics` uses `LogsQueryClient` + skipped guard | ✅ PASS | `agents/arc/tools.py:266–350` |
| 3 | `query_resource_health` uses `MicrosoftResourceHealth` | ✅ PASS | `agents/arc/tools.py:386–438` |
| 4 | `propose_arc_extension_install` HITL with `pending_approval` | ✅ PASS | `agents/arc/tools.py:685–766` |
| 5 | All 8 tools registered in `agent.py` at all 4 locations | ✅ PASS | `agents/arc/agent.py:40–243` |
| 6 | 4 SDK packages in `requirements.txt` | ✅ PASS | `agents/arc/requirements.txt:18–21` |
| 7 | `vm_type?: string` in `VMDetail` interface | ✅ PASS | `VMDetailPanel.tsx:24,851–855` |
| 8 | 15 new tests all pass | ✅ PASS | pytest: 15 passed, 0 failed |
| 9 | 21 total arc tests pass (no regressions) | ✅ PASS | pytest: 21 passed, 0 failed |
