---
phase: 40
plan: 1
title: "Arc Agent Completion"
wave: 1
status: pending
files_modified:
  - agents/arc/requirements.txt
  - agents/arc/tools.py
  - agents/arc/agent.py
  - agents/tests/arc/test_arc_tools_phase40.py
  - services/web-ui/components/VMDetailPanel.tsx
autonomous: true
---

# Plan 40-1: Arc Agent Completion

> Bring Arc-connected resources to feature parity with Azure-native VMs by replacing 3
> stub tools with real SDK implementations, registering 4 unregistered Phase 32 tools,
> adding 1 new HITL tool, and adding an Arc-specific hint in the VM Detail Panel.

---

## Goal

After this plan executes:
1. `query_activity_log`, `query_log_analytics`, and `query_resource_health` in `agents/arc/tools.py` use real Azure SDK calls (not empty stubs).
2. The 4 Phase 32 tools (`query_arc_extension_health`, `query_arc_connectivity`, `query_arc_guest_config`, `propose_arc_assessment`) are fully registered in `agents/arc/agent.py` (all 4 locations).
3. A new HITL tool `propose_arc_extension_install` exists in `agents/arc/tools.py` following the `propose_arc_assessment` pattern.
4. `agents/arc/requirements.txt` includes the 4 missing packages.
5. `VMDetailPanel.tsx` `VMDetail` interface has `vm_type?: string` and the metrics no-data message handles Arc VMs gracefully.
6. 15 new unit tests pass in `agents/tests/arc/test_arc_tools_phase40.py`.

---

## must_haves

- [ ] `query_activity_log` in `arc/tools.py` returns real `entries` list from `MonitorManagementClient.activity_logs.list()` — NOT the stub `entries: []`
- [ ] `query_log_analytics` in `arc/tools.py` uses `LogsQueryClient.query_workspace()` and returns `query_status: "skipped"` when `workspace_id` is empty
- [ ] `query_resource_health` in `arc/tools.py` uses `MicrosoftResourceHealth.availability_statuses.get_by_resource()` and returns real `availability_state`
- [ ] `propose_arc_extension_install` exists in `arc/tools.py` decorated with `@ai_function` and returns `{"status": "pending_approval", ...}`
- [ ] All 7 tools (`query_activity_log`, `query_log_analytics`, `query_resource_health`, `query_arc_extension_health`, `query_arc_connectivity`, `query_arc_guest_config`, `propose_arc_assessment`, `propose_arc_extension_install`) are present in `tools = [...]` list in `agent.py`
- [ ] `agents/arc/requirements.txt` contains `azure-mgmt-monitor`, `azure-monitor-query`, `azure-mgmt-resourcehealth`, `azure-mgmt-guestconfiguration`
- [ ] `VMDetail` interface in `VMDetailPanel.tsx` has `vm_type?: string`
- [ ] All 15 new tests in `test_arc_tools_phase40.py` pass

---

## Tasks

### Task 1 — Add 4 missing packages to `agents/arc/requirements.txt`

<read_first>
- `agents/arc/requirements.txt` — current contents (lines 1–16)
- `agents/compute/requirements.txt` — verify package names/version constraints used there
</read_first>

<action>
Append the following 4 lines to `agents/arc/requirements.txt` after the existing `httpx` line:

```
# Monitoring + Resource Health (stub implementations → real SDK calls, Phase 40)
azure-mgmt-monitor>=6.0.0
azure-monitor-query>=1.3.0
azure-mgmt-resourcehealth==1.0.0b6
azure-mgmt-guestconfiguration>=1.0.0
```

Note: `azure-mgmt-guestconfiguration` is already imported at tools.py line 37 but was missing from requirements.txt — this is a bug fix as well as an enabler.
</action>

<acceptance_criteria>
- `grep "azure-mgmt-monitor" agents/arc/requirements.txt` exits 0 and prints a line containing `azure-mgmt-monitor>=6.0.0`
- `grep "azure-monitor-query" agents/arc/requirements.txt` exits 0 and prints a line containing `azure-monitor-query>=1.3.0`
- `grep "azure-mgmt-resourcehealth" agents/arc/requirements.txt` exits 0 and prints `azure-mgmt-resourcehealth==1.0.0b6`
- `grep "azure-mgmt-guestconfiguration" agents/arc/requirements.txt` exits 0
</acceptance_criteria>

---

### Task 2 — Add lazy imports and `_extract_subscription_id` helper to `agents/arc/tools.py`

<read_first>
- `agents/arc/tools.py` — full file (lines 1–442); note current imports end at line 41
- `agents/compute/tools.py` lines 37–54 — lazy import pattern for the 3 new SDKs
- `agents/compute/tools.py` lines 152–172 — `_extract_subscription_id` helper
</read_first>

<action>
After the existing lazy imports block (after line 39 `GuestConfigurationClient = None`), add 3 new lazy import blocks and the `_extract_subscription_id` helper.

**Insert after line 39 in `agents/arc/tools.py`:**

```python
# Lazy import — azure-mgmt-monitor (activity log)
try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-monitor-query (log analytics)
try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-resourcehealth
try:
    from azure.mgmt.resourcehealth import MicrosoftResourceHealth
except ImportError:
    MicrosoftResourceHealth = None  # type: ignore[assignment,misc]
```

**Also add imports needed for the real implementations** — insert after the existing `from typing import Any, Dict, List` line:

```python
from datetime import datetime, timedelta, timezone
```

**Add `_extract_subscription_id` helper** — insert after the `ALLOWED_MCP_TOOLS` list and before the first `@ai_function` decorator (around line 68):

```python
def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an Azure resource ID.

    Args:
        resource_id: Azure resource ID in the form
            /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}

    Returns:
        Subscription ID string (lowercase).

    Raises:
        ValueError: If the subscription segment cannot be found.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot extract subscription_id from resource_id: {resource_id}"
        )
```
</action>

<acceptance_criteria>
- `grep "MonitorManagementClient" agents/arc/tools.py` exits 0 and matches at least 2 lines (import + None fallback)
- `grep "LogsQueryClient" agents/arc/tools.py` exits 0
- `grep "MicrosoftResourceHealth" agents/arc/tools.py` exits 0
- `grep "_extract_subscription_id" agents/arc/tools.py` exits 0 and shows a function definition line (`def _extract_subscription_id`)
- `grep "from datetime import" agents/arc/tools.py` exits 0
</acceptance_criteria>

---

### Task 3 — Replace `query_activity_log` stub with real implementation

<read_first>
- `agents/arc/tools.py` lines 71–112 — current stub implementation
- `agents/compute/tools.py` lines 175–278 — reference implementation to copy from
- Research note: use `start_time = time.monotonic()` **inside** the `with instrument_tool_call` block to stay consistent with compute agent (the Phase 32 tools use outside; the 3 original arc stubs should use the compute agent pattern since they started as compute copies — see research §8)
</read_first>

<action>
Replace the body of `query_activity_log` in `agents/arc/tools.py` (lines 95–112, inside the `with instrument_tool_call(...)` block) with the real implementation from `agents/compute/tools.py` lines 208–278, changing only:
- `agent_name="arc-agent"` in `instrument_tool_call` (already correct in existing stub)
- `agent_name="compute-agent"` → `agent_name="arc-agent"` in the `instrument_tool_call` call (already correct)

The complete replacement body inside the `with` block should be:

```python
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            start = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
            all_entries: List[Dict[str, Any]] = []

            for resource_id in resource_ids:
                sub_id = _extract_subscription_id(resource_id)
                client = MonitorManagementClient(credential, sub_id)
                filter_str = (
                    f"eventTimestamp ge '{start.isoformat()}' "
                    f"and resourceId eq '{resource_id}'"
                )
                events = client.activity_logs.list(filter=filter_str)
                for event in events:
                    all_entries.append(
                        {
                            "eventTimestamp": (
                                event.event_timestamp.isoformat()
                                if event.event_timestamp
                                else None
                            ),
                            "operationName": (
                                event.operation_name.value
                                if event.operation_name
                                else None
                            ),
                            "caller": event.caller,
                            "status": (
                                event.status.value if event.status else None
                            ),
                            "resourceId": event.resource_id,
                            "level": (
                                event.level.value if event.level else None
                            ),
                            "description": event.description,
                        }
                    )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_activity_log: complete | resources=%d entries=%d duration_ms=%.0f",
                len(resource_ids),
                len(all_entries),
                duration_ms,
            )
            return {
                "resource_ids": resource_ids,
                "timespan_hours": timespan_hours,
                "entries": all_entries,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_activity_log: failed | resources=%s error=%s duration_ms=%.0f",
                resource_ids,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_ids": resource_ids,
                "timespan_hours": timespan_hours,
                "entries": [],
                "query_status": "error",
                "error": str(e),
            }
```
</action>

<acceptance_criteria>
- `grep "MonitorManagementClient(credential" agents/arc/tools.py` exits 0 (real SDK instantiation present)
- `grep "activity_logs.list" agents/arc/tools.py` exits 0
- `grep '"entries": \[\]' agents/arc/tools.py` — should only appear in the error path, NOT as the sole return value in the success path. Run: `python -c "import ast, sys; src=open('agents/arc/tools.py').read(); tree=ast.parse(src); print('parse OK')"` exits 0
- `grep "_extract_subscription_id(resource_id)" agents/arc/tools.py` exits 0
</acceptance_criteria>

---

### Task 4 — Replace `query_log_analytics` stub with real implementation

<read_first>
- `agents/arc/tools.py` lines 115–158 — current stub implementation
- `agents/compute/tools.py` lines 281–403 — reference implementation
</read_first>

<action>
Replace the body of `query_log_analytics` in `agents/arc/tools.py` (inside the `with instrument_tool_call(...)` block) with the real implementation. The `instrument_tool_call` call already has `agent_name="arc-agent"`. Full replacement body:

```python
        start_time = time.monotonic()

        # Guard: empty workspace_id means no Log Analytics configured — skip gracefully
        if not workspace_id:
            logger.warning(
                "query_log_analytics: skipped | workspace_id is empty — no Log Analytics workspace configured"
            )
            return {
                "workspace_id": workspace_id,
                "kql_query": kql_query,
                "timespan": timespan,
                "rows": [],
                "query_status": "skipped",
            }

        try:
            if LogsQueryClient is None:
                raise ImportError("azure-monitor-query is not installed")

            credential = get_credential()
            client = LogsQueryClient(credential)
            response = client.query_workspace(
                workspace_id=workspace_id,
                query=kql_query,
                timespan=timespan,
            )

            if response.status == LogsQueryStatus.SUCCESS:
                rows: List[Dict[str, Any]] = []
                for table in response.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        rows.append(
                            dict(
                                zip(
                                    col_names,
                                    [str(v) if v is not None else None for v in row],
                                )
                            )
                        )
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.info(
                    "query_log_analytics: complete | workspace=%s rows=%d duration_ms=%.0f",
                    workspace_id,
                    len(rows),
                    duration_ms,
                )
                return {
                    "workspace_id": workspace_id,
                    "kql_query": kql_query,
                    "timespan": timespan,
                    "rows": rows,
                    "query_status": "success",
                }
            else:
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.warning(
                    "query_log_analytics: partial | workspace=%s duration_ms=%.0f error=%s",
                    workspace_id,
                    duration_ms,
                    response.partial_error,
                )
                return {
                    "workspace_id": workspace_id,
                    "kql_query": kql_query,
                    "timespan": timespan,
                    "rows": [],
                    "query_status": "partial",
                    "partial_error": str(response.partial_error),
                }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_log_analytics: failed | workspace=%s error=%s duration_ms=%.0f",
                workspace_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "workspace_id": workspace_id,
                "kql_query": kql_query,
                "timespan": timespan,
                "rows": [],
                "query_status": "error",
                "error": str(e),
            }
```
</action>

<acceptance_criteria>
- `grep "LogsQueryClient(credential)" agents/arc/tools.py` exits 0
- `grep "query_workspace" agents/arc/tools.py` exits 0
- `grep 'query_status.*skipped' agents/arc/tools.py` exits 0 (empty workspace guard present)
- `grep "LogsQueryStatus.SUCCESS" agents/arc/tools.py` exits 0
- `python -c "import ast; ast.parse(open('agents/arc/tools.py').read()); print('OK')"` exits 0
</acceptance_criteria>

---

### Task 5 — Replace `query_resource_health` stub with real implementation

<read_first>
- `agents/arc/tools.py` lines 161–198 — current stub returning `"Unknown"` always
- `agents/compute/tools.py` lines 406–494 — reference implementation
</read_first>

<action>
Replace the body of `query_resource_health` in `agents/arc/tools.py` (inside the `with instrument_tool_call(...)` block) with the real implementation. Full replacement body:

```python
        start_time = time.monotonic()
        try:
            if MicrosoftResourceHealth is None:
                raise ImportError("azure-mgmt-resourcehealth is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(resource_id)
            client = MicrosoftResourceHealth(credential, sub_id)
            status = client.availability_statuses.get_by_resource(
                resource_uri=resource_id,
                expand="recommendedActions",
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            availability_state = (
                status.properties.availability_state.value
                if status.properties.availability_state
                else "Unknown"
            )
            logger.info(
                "query_resource_health: complete | resource=%s state=%s duration_ms=%.0f",
                resource_id,
                availability_state,
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "availability_state": availability_state,
                "summary": status.properties.summary,
                "reason_type": status.properties.reason_type,
                "occurred_time": (
                    status.properties.occurred_time.isoformat()
                    if status.properties.occurred_time
                    else None
                ),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_resource_health: failed | resource=%s error=%s duration_ms=%.0f",
                resource_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_id": resource_id,
                "availability_state": "Unknown",
                "summary": None,
                "reason_type": None,
                "occurred_time": None,
                "query_status": "error",
                "error": str(e),
            }
```
</action>

<acceptance_criteria>
- `grep "MicrosoftResourceHealth(credential" agents/arc/tools.py` exits 0
- `grep "availability_statuses.get_by_resource" agents/arc/tools.py` exits 0
- `grep "reason_type" agents/arc/tools.py` exits 0 (new field present in return)
- `grep '"Resource Health query pending\."' agents/arc/tools.py` returns no matches (stub string gone)
- `python -c "import ast; ast.parse(open('agents/arc/tools.py').read()); print('OK')"` exits 0
</acceptance_criteria>

---

### Task 6 — Add `propose_arc_extension_install` HITL tool to `agents/arc/tools.py`

<read_first>
- `agents/arc/tools.py` lines 383–441 — `propose_arc_assessment` as the exact pattern to follow
- Research §4e — full parameter list and proposal dict structure
</read_first>

<action>
Append the following new `@ai_function` after the `propose_arc_assessment` function (after line 441, at end of file):

```python

@ai_function
def propose_arc_extension_install(
    resource_id: str,
    resource_group: str,
    machine_name: str,
    subscription_id: str,
    extension_name: str,
    extension_publisher: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose installing an Arc extension on a machine — HITL ApprovalRecord only.

    Common use case: proposing AMA (AzureMonitorWindowsAgent / AzureMonitorLinuxAgent)
    installation when Arc VM has no Log Analytics workspace heartbeat.

    REMEDI-001: No ARM call. Approval required before execution.

    Args:
        resource_id: Full ARM resource ID of the Arc machine.
        resource_group: Resource group name.
        machine_name: Arc machine name.
        subscription_id: Azure subscription ID.
        extension_name: Extension type name (e.g., "AzureMonitorWindowsAgent").
        extension_publisher: Extension publisher (e.g., "Microsoft.Azure.Monitor").
        incident_id: Foundry incident ID.
        thread_id: Foundry thread ID.
        reason: Human-readable reason for the install proposal.

    Returns:
        Dict with status "pending_approval", approval_id, message, duration_ms.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="arc-agent",
        agent_id=agent_id,
        tool_name="propose_arc_extension_install",
        tool_parameters={"machine_name": machine_name, "extension_name": extension_name, "reason": reason},
        correlation_id=machine_name,
        thread_id=thread_id,
    ):
        try:
            proposal = {
                "action": "arc_extension_install",
                "resource_id": resource_id,
                "resource_group": resource_group,
                "machine_name": machine_name,
                "subscription_id": subscription_id,
                "extension_name": extension_name,
                "extension_publisher": extension_publisher,
                "reason": reason,
                "description": f"Install extension '{extension_name}' on Arc VM '{machine_name}': {reason}",
                "target_resources": [resource_id],
                "estimated_impact": "Extension install — may restart Arc agent briefly",
                "reversible": True,
            }

            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id=incident_id,
                agent_name="arc-agent",
                proposal=proposal,
                resource_snapshot={"machine_name": machine_name, "extension_name": extension_name},
                risk_level="medium",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"Arc extension install proposal created for '{extension_name}' on '{machine_name}'. Awaiting approval.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("propose_arc_extension_install error: %s", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}
```
</action>

<acceptance_criteria>
- `grep "def propose_arc_extension_install" agents/arc/tools.py` exits 0
- `grep '"action": "arc_extension_install"' agents/arc/tools.py` exits 0
- `grep '"status": "pending_approval"' agents/arc/tools.py` exits 0 (at least 2 matches — one for each HITL tool)
- `grep 'risk_level="medium"' agents/arc/tools.py` exits 0 (medium risk for extension install)
- `python -c "import ast; ast.parse(open('agents/arc/tools.py').read()); print('OK')"` exits 0
</acceptance_criteria>

---

### Task 7 — Register all 8 tools in `agents/arc/agent.py` (4 locations)

<read_first>
- `agents/arc/agent.py` full file (lines 1–227)
- Current import block at lines 40–45: only imports 3 tools
- Current `tools = [...]` at line 153: only lists 3 tools
- Current `## Allowed Tools` system prompt at lines 124–130: only 3 tools in the concat
- Current `create_arc_agent_version()` tools list at lines 205–210: only 3 tools
</read_first>

<action>
Apply the following 4 changes to `agents/arc/agent.py`:

**Location 1 — Import block (lines 40–45):** Expand to import all 8 tools:

```python
from arc.tools import (
    ALLOWED_MCP_TOOLS,
    propose_arc_assessment,
    propose_arc_extension_install,
    query_activity_log,
    query_arc_connectivity,
    query_arc_extension_health,
    query_arc_guest_config,
    query_log_analytics,
    query_resource_health,
)
```

**Location 2 — System prompt `## Allowed Tools` section (line 128):** The format string already generates from `ALLOWED_MCP_TOOLS + [...]`. Change the hardcoded list to include all 8 tools:

```python
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS + [
            "query_activity_log",
            "query_log_analytics",
            "query_resource_health",
            "query_arc_extension_health",
            "query_arc_connectivity",
            "query_arc_guest_config",
            "propose_arc_assessment",
            "propose_arc_extension_install",
        ]
    )
```

**Location 3 — `tools = [...]` list in `create_arc_agent()` (line 153):** Replace the 3-item list with all 8 tools:

```python
    tools = [
        query_activity_log,
        query_log_analytics,
        query_resource_health,
        query_arc_extension_health,
        query_arc_connectivity,
        query_arc_guest_config,
        propose_arc_assessment,
        propose_arc_extension_install,
    ]
```

**Location 4 — `create_arc_agent_version()` tools list (lines 205–210):** Replace the 3-item list with all 8 tools:

```python
            tools=[
                query_activity_log,
                query_log_analytics,
                query_resource_health,
                query_arc_extension_health,
                query_arc_connectivity,
                query_arc_guest_config,
                propose_arc_assessment,
                propose_arc_extension_install,
            ],
```

Also update the system prompt triage steps to reference the new tools. In the `## Mandatory Triage Workflow (TRIAGE-006)` section:
- Step 2 should reference `query_arc_connectivity` (instead of only listing `arc_servers_list`)
- Step 3 should reference `query_arc_extension_health` (instead of only listing `arc_extensions_list`)
- Add a new step after Step 3 (before Step 4 GitOps): **Step 3b — Guest Config Compliance:** "For Arc servers, call `query_arc_guest_config` to check policy assignment compliance state."
- Step 7 Remediation: mention `propose_arc_extension_install` as the tool for proposing extension installs when AMA is missing.
</action>

<acceptance_criteria>
- `grep "query_arc_extension_health" agents/arc/agent.py` exits 0 and shows at least 3 matches (import + tools list + version tools list)
- `grep "propose_arc_extension_install" agents/arc/agent.py` exits 0 and shows at least 3 matches
- `grep "query_arc_guest_config" agents/arc/agent.py` exits 0
- `grep "query_arc_connectivity" agents/arc/agent.py` exits 0
- `python -c "import ast; ast.parse(open('agents/arc/agent.py').read()); print('OK')"` exits 0
- The `tools = [` list inside `create_arc_agent()` has exactly 8 entries (count via `grep -c "query_\|propose_" agents/arc/agent.py` ≥ 8 in the tools block)
</acceptance_criteria>

---

### Task 8 — Add `vm_type?: string` to `VMDetail` interface in `VMDetailPanel.tsx` and update Arc metrics message

<read_first>
- `services/web-ui/components/VMDetailPanel.tsx` lines 1–60 — `VMDetail` interface at lines 11–26
- `services/web-ui/components/VMDetailPanel.tsx` lines 842–860 — the metrics no-data branch at line 848–852
</read_first>

<action>
**Change 1 — Add `vm_type` to `VMDetail` interface:**

In the `VMDetail` interface (after `power_state: string` on line 20), add:
```typescript
  vm_type?: string
```

**Change 2 — Update the metrics no-data message:**

At lines 850–852, the current code is:
```tsx
                    {vm?.power_state === 'deallocated'
                      ? 'No metrics — VM is deallocated. Start the VM to collect data.'
                      : 'No metrics available'}
```

Replace with a 3-way check:
```tsx
                    {vm?.power_state === 'deallocated'
                      ? 'No metrics — VM is deallocated. Start the VM to collect data.'
                      : vm?.vm_type === 'Arc VM'
                      ? 'Arc VMs use Log Analytics for telemetry — ARM metrics are not available. Use AI Investigation to query Heartbeat and Event tables.'
                      : 'No metrics available'}
```
</action>

<acceptance_criteria>
- `grep "vm_type" services/web-ui/components/VMDetailPanel.tsx` exits 0 and shows at least 2 matches (interface declaration + metrics condition)
- `grep "Arc VMs use Log Analytics" services/web-ui/components/VMDetailPanel.tsx` exits 0
- `grep "vm_type\?: string" services/web-ui/components/VMDetailPanel.tsx` exits 0
- `cd services/web-ui && npx tsc --noEmit 2>&1 | head -20` exits 0 (no TypeScript errors)
</acceptance_criteria>

---

### Task 9 — Write 15 unit tests in `agents/tests/arc/test_arc_tools_phase40.py`

<read_first>
- `agents/tests/arc/test_arc_new_tools.py` — full file (the Phase 32 test pattern to follow exactly)
- `agents/arc/tools.py` — post-changes version, to understand exact return shapes
</read_first>

<action>
Create `agents/tests/arc/test_arc_tools_phase40.py` with the following test structure (15 tests total):

```python
"""Tests for Phase 40 Arc agent stub replacements and new HITL tool."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch


def _instr_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


# ── query_activity_log ────────────────────────────────────────────────────────

class TestQueryActivityLogArc:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MonitorManagementClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_entries_from_sdk(self, mock_cred, mock_mon_cls, mock_id, mock_instr):
        """Real SDK path returns parsed activity log entries."""
        mock_instr.return_value = _instr_mock()
        mock_mon = MagicMock()
        mock_mon_cls.return_value = mock_mon
        event = MagicMock()
        event.event_timestamp.isoformat.return_value = "2026-04-11T10:00:00+00:00"
        event.operation_name.value = "Microsoft.HybridCompute/machines/write"
        event.caller = "admin@contoso.com"
        event.status.value = "Succeeded"
        event.resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"
        event.level.value = "Informational"
        event.description = "Arc machine updated"
        mock_mon.activity_logs.list.return_value = [event]

        from agents.arc.tools import query_activity_log

        result = query_activity_log(
            ["/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"],
            timespan_hours=2,
        )
        assert result["query_status"] == "success"
        assert len(result["entries"]) == 1
        assert result["entries"][0]["operationName"] == "Microsoft.HybridCompute/machines/write"

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MonitorManagementClient", None)
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        """Returns error dict (not raises) when azure-mgmt-monitor not installed."""
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_activity_log

        result = query_activity_log(["/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"])
        assert result["query_status"] == "error"
        assert "error" in result

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MonitorManagementClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_on_sdk_exception(self, mock_cred, mock_mon_cls, mock_id, mock_instr):
        """SDK raises → returns error dict, not propagates exception."""
        mock_instr.return_value = _instr_mock()
        mock_mon = MagicMock()
        mock_mon_cls.return_value = mock_mon
        mock_mon.activity_logs.list.side_effect = Exception("ARM 403 Forbidden")

        from agents.arc.tools import query_activity_log

        result = query_activity_log(["/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"])
        assert result["query_status"] == "error"
        assert "ARM 403" in result["error"]


# ── query_log_analytics ───────────────────────────────────────────────────────

class TestQueryLogAnalyticsArc:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.LogsQueryClient")
    @patch("agents.arc.tools.LogsQueryStatus")
    @patch("agents.arc.tools.get_credential")
    def test_returns_rows_on_success(self, mock_cred, mock_status_cls, mock_client_cls, mock_id, mock_instr):
        """SUCCESS status returns parsed rows."""
        mock_instr.return_value = _instr_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_status_cls.SUCCESS = "SUCCESS"

        col = MagicMock(); col.name = "Computer"
        table = MagicMock()
        table.columns = [col]
        table.rows = [["arc-vm1"]]
        response = MagicMock()
        response.status = "SUCCESS"
        response.tables = [table]
        mock_client.query_workspace.return_value = response

        from agents.arc.tools import query_log_analytics

        result = query_log_analytics("ws-id", "Heartbeat | limit 10", "PT2H")
        assert result["query_status"] == "success"
        assert len(result["rows"]) == 1
        assert result["rows"][0]["Computer"] == "arc-vm1"

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.get_credential")
    def test_skips_when_workspace_id_empty(self, mock_cred, mock_id, mock_instr):
        """Empty workspace_id returns query_status='skipped' without calling SDK."""
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_log_analytics

        result = query_log_analytics("", "Heartbeat | limit 10", "PT2H")
        assert result["query_status"] == "skipped"
        assert result["rows"] == []

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.LogsQueryClient", None)
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        """Returns error dict when azure-monitor-query not installed."""
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_log_analytics

        result = query_log_analytics("ws-id", "Heartbeat | limit 10", "PT2H")
        assert result["query_status"] == "error"


# ── query_resource_health ─────────────────────────────────────────────────────

class TestQueryResourceHealthArc:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MicrosoftResourceHealth")
    @patch("agents.arc.tools.get_credential")
    def test_returns_real_availability_state(self, mock_cred, mock_rh_cls, mock_id, mock_instr):
        """Real SDK path returns availability_state from ARM."""
        mock_instr.return_value = _instr_mock()
        mock_rh = MagicMock()
        mock_rh_cls.return_value = mock_rh
        status = MagicMock()
        status.properties.availability_state.value = "Available"
        status.properties.summary = "The resource is available."
        status.properties.reason_type = None
        status.properties.occurred_time = None
        mock_rh.availability_statuses.get_by_resource.return_value = status

        from agents.arc.tools import query_resource_health

        result = query_resource_health(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"
        )
        assert result["query_status"] == "success"
        assert result["availability_state"] == "Available"
        assert result["summary"] == "The resource is available."

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MicrosoftResourceHealth", None)
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        """Returns error dict when azure-mgmt-resourcehealth not installed."""
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_resource_health

        result = query_resource_health(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"
        )
        assert result["query_status"] == "error"
        assert result["availability_state"] == "Unknown"

    def test_no_longer_returns_stub_pending_message(self):
        """Confirm stub string 'Resource Health query pending.' is gone from source."""
        from agents.arc import tools as arc_tools

        src = inspect.getsource(arc_tools.query_resource_health)
        assert "Resource Health query pending." not in src
        assert "MicrosoftResourceHealth" in src


# ── propose_arc_extension_install ─────────────────────────────────────────────

class TestProposeArcExtensionInstall:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.create_approval_record")
    def test_creates_pending_approval(self, mock_create, mock_id, mock_instr):
        """Returns pending_approval status with approval_id from create_approval_record."""
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_ext_001", "status": "pending"}

        from agents.arc.tools import propose_arc_extension_install

        result = propose_arc_extension_install(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1",
            resource_group="rg",
            machine_name="arc-vm1",
            subscription_id="sub",
            extension_name="AzureMonitorWindowsAgent",
            extension_publisher="Microsoft.Azure.Monitor",
            incident_id="inc-001",
            thread_id="t1",
            reason="AMA missing — no Heartbeat in Log Analytics",
        )
        assert result["status"] == "pending_approval"
        assert result["approval_id"] == "appr_ext_001"
        assert "arc-vm1" in result["message"]
        assert "AzureMonitorWindowsAgent" in result["message"]

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.create_approval_record")
    def test_calls_create_approval_with_medium_risk(self, mock_create, mock_id, mock_instr):
        """Approval record is created with risk_level='medium'."""
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_002"}

        from agents.arc.tools import propose_arc_extension_install

        propose_arc_extension_install(
            resource_id="/subscriptions/sub/rg/providers/Microsoft.HybridCompute/machines/vm",
            resource_group="rg",
            machine_name="vm",
            subscription_id="sub",
            extension_name="AzureMonitorLinuxAgent",
            extension_publisher="Microsoft.Azure.Monitor",
            incident_id="inc-002",
            thread_id="t2",
            reason="AMA missing",
        )
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["risk_level"] == "medium"
        assert call_kwargs["proposal"]["action"] == "arc_extension_install"

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.create_approval_record")
    def test_returns_error_on_exception(self, mock_create, mock_id, mock_instr):
        """create_approval_record raises → returns error dict, not propagates."""
        mock_instr.return_value = _instr_mock()
        mock_create.side_effect = Exception("Cosmos unavailable")

        from agents.arc.tools import propose_arc_extension_install

        result = propose_arc_extension_install(
            resource_id="/subscriptions/sub/rg/providers/Microsoft.HybridCompute/machines/vm",
            resource_group="rg",
            machine_name="vm",
            subscription_id="sub",
            extension_name="AzureMonitorLinuxAgent",
            extension_publisher="Microsoft.Azure.Monitor",
            incident_id="inc-003",
            thread_id="t3",
            reason="AMA missing",
        )
        assert result["status"] == "error"
        assert "Cosmos unavailable" in result["message"]


# ── agent.py registration ─────────────────────────────────────────────────────

class TestArcAgentRegistration:
    def test_all_8_tools_importable_from_agent_module(self):
        """All 8 @ai_function tools can be imported from arc.agent module."""
        from agents.arc import agent as arc_agent

        expected = [
            "query_activity_log",
            "query_log_analytics",
            "query_resource_health",
            "query_arc_extension_health",
            "query_arc_connectivity",
            "query_arc_guest_config",
            "propose_arc_assessment",
            "propose_arc_extension_install",
        ]
        # All tools are re-exported via the import block in agent.py
        import arc.tools as arc_tools
        for name in expected:
            assert hasattr(arc_tools, name), f"Tool '{name}' missing from arc.tools"

    def test_propose_arc_extension_install_in_allowed_tools_prompt(self):
        """The system prompt contains propose_arc_extension_install in Allowed Tools."""
        from agents.arc.agent import ARC_AGENT_SYSTEM_PROMPT

        assert "propose_arc_extension_install" in ARC_AGENT_SYSTEM_PROMPT

    def test_system_prompt_contains_all_8_ai_function_tools(self):
        """The Allowed Tools section of the system prompt lists all 8 ai_function tools."""
        from agents.arc.agent import ARC_AGENT_SYSTEM_PROMPT

        for tool_name in [
            "query_activity_log",
            "query_log_analytics",
            "query_resource_health",
            "query_arc_extension_health",
            "query_arc_connectivity",
            "query_arc_guest_config",
            "propose_arc_assessment",
            "propose_arc_extension_install",
        ]:
            assert tool_name in ARC_AGENT_SYSTEM_PROMPT, (
                f"Tool '{tool_name}' not found in ARC_AGENT_SYSTEM_PROMPT"
            )
```
</action>

<acceptance_criteria>
- `python -m pytest agents/tests/arc/test_arc_tools_phase40.py -v 2>&1 | tail -30` shows 15 passed, 0 failed
- `grep "def test_" agents/tests/arc/test_arc_tools_phase40.py | wc -l` prints `15`
- No `import pytest` errors — the test file uses only `unittest.mock` and `inspect`
</acceptance_criteria>

---

## Verification

Run the following to confirm the plan is complete:

```bash
# 1. Python syntax check
python -c "import ast; ast.parse(open('agents/arc/tools.py').read()); print('tools.py: OK')"
python -c "import ast; ast.parse(open('agents/arc/agent.py').read()); print('agent.py: OK')"

# 2. Requirements delta present
grep "azure-mgmt-monitor" agents/arc/requirements.txt
grep "azure-monitor-query" agents/arc/requirements.txt
grep "azure-mgmt-resourcehealth" agents/arc/requirements.txt
grep "azure-mgmt-guestconfiguration" agents/arc/requirements.txt

# 3. Stubs gone
python -c "
src = open('agents/arc/tools.py').read()
assert 'Resource Health query pending.' not in src, 'resource health stub still present'
assert 'query_status.*skipped' not in src or 'workspace_id is empty' in src, 'log analytics empty guard missing'
print('stubs removed: OK')
"

# 4. New HITL tool present
grep "def propose_arc_extension_install" agents/arc/tools.py

# 5. All 8 tools in agent.py
grep -c "query_arc_extension_health\|query_arc_connectivity\|query_arc_guest_config\|propose_arc_assessment\|propose_arc_extension_install" agents/arc/agent.py

# 6. Run Phase 40 tests
python -m pytest agents/tests/arc/test_arc_tools_phase40.py -v

# 7. Run all arc tests (no regressions)
python -m pytest agents/tests/arc/ -v

# 8. TypeScript check
cd services/web-ui && npx tsc --noEmit 2>&1 | head -5
```

### Expected outcomes

| Check | Expected |
|-------|----------|
| `tools.py` parse | OK |
| `agent.py` parse | OK |
| 4 packages in requirements.txt | All 4 present |
| Stub string gone | Not found |
| `propose_arc_extension_install` defined | Found |
| Tool count in agent.py | ≥ 5 matches for new tools |
| Phase 40 tests | 15/15 pass |
| All arc tests | No regressions vs. Phase 32 baseline (4 tests) |
| TypeScript compile | 0 errors |
