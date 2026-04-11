# Phase 40: Arc Agent Completion — Research

> Generated: 2026-04-11
> Goal: Bring Arc-connected resources to feature parity with Azure-native VMs.

---

## 1. Current State of Each Stub Tool

### `query_activity_log` — `agents/arc/tools.py` lines 71–112

**Status: STUB — returns empty list always**

```python
@ai_function
def query_activity_log(resource_ids: List[str], timespan_hours: int = 2) -> Dict[str, Any]:
    # ...
    with instrument_tool_call(...):
        return {
            "resource_ids": resource_ids,
            "timespan_hours": timespan_hours,
            "entries": [],           # ← STUB: always empty
            "query_status": "success",
        }
```

**Parameters:** `resource_ids: List[str]`, `timespan_hours: int = 2`

**Return shape required:**
```python
{
    "resource_ids": [...],
    "timespan_hours": int,
    "entries": [
        {
            "eventTimestamp": "ISO-8601",
            "operationName": str,
            "caller": str,
            "status": str,
            "resourceId": str,
            "level": str,
            "description": str,
        }
    ],
    "query_status": "success" | "error",
    "error": str,  # only on error
}
```

**What needs implementing:** Use `MonitorManagementClient.activity_logs.list()` with `filter_str` containing `eventTimestamp ge '...' and resourceId eq '...'`. Arc machine resource IDs follow the format `/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.HybridCompute/machines/{name}` — standard ARM format. The same `MonitorManagementClient` from `azure-mgmt-monitor` that the compute agent uses will work here because Activity Log is subscription-scoped, not resource-type specific.

**Reference implementation:** `agents/compute/tools.py` lines 175–278 — exact pattern to follow, including `_extract_subscription_id()` helper.

---

### `query_log_analytics` — `agents/arc/tools.py` lines 115–158

**Status: STUB — returns empty rows always**

```python
@ai_function
def query_log_analytics(workspace_id: str, kql_query: str, timespan: str = "PT2H") -> Dict[str, Any]:
    # ...
    with instrument_tool_call(...):
        return {
            "workspace_id": workspace_id,
            "kql_query": kql_query,
            "timespan": timespan,
            "rows": [],             # ← STUB: always empty
            "query_status": "success",
        }
```

**Parameters:** `workspace_id: str`, `kql_query: str`, `timespan: str = "PT2H"`

**Return shape required:**
```python
{
    "workspace_id": str,
    "kql_query": str,
    "timespan": str,
    "rows": [{"column": "value", ...}, ...],
    "query_status": "success" | "skipped" | "partial" | "error",
    "partial_error": str,  # only on partial
    "error": str,          # only on error
}
```

**What needs implementing:** Use `LogsQueryClient.query_workspace()` from `azure-monitor-query`. The workspace_id for Arc VMs comes from the AMA (Azure Monitor Agent) Log Analytics workspace where heartbeats are stored — the agent discovers it from DCR associations (or the operator provides it). The key Arc-specific KQL tables are `Heartbeat`, `AzureActivity`, `ConfigurationChange`, `Event`. Add empty workspace_id guard (return `query_status: "skipped"`) matching the compute pattern.

**Reference implementation:** `agents/compute/tools.py` lines 281–403 — exact same implementation, just change `agent_name` to `"arc-agent"`.

---

### `query_resource_health` — `agents/arc/tools.py` lines 161–198

**Status: STUB — returns "Unknown" always**

```python
@ai_function
def query_resource_health(resource_id: str) -> Dict[str, Any]:
    # ...
    with instrument_tool_call(...):
        return {
            "resource_id": resource_id,
            "availability_state": "Unknown",    # ← STUB
            "summary": "Resource Health query pending.",  # ← STUB
            "query_status": "success",
        }
```

**Parameters:** `resource_id: str`

**Return shape required:**
```python
{
    "resource_id": str,
    "availability_state": "Available" | "Degraded" | "Unavailable" | "Unknown",
    "summary": str | None,
    "reason_type": str | None,
    "occurred_time": "ISO-8601" | None,
    "query_status": "success" | "error",
    "error": str,  # only on error
}
```

**What needs implementing:** Use `MicrosoftResourceHealth.availability_statuses.get_by_resource(resource_uri=resource_id, expand="recommendedActions")` from `azure-mgmt-resourcehealth`. This works for Arc machines because Azure Resource Health covers `Microsoft.HybridCompute/machines` resource type — Arc machines are registered as ARM resources and get health events from the Azure platform.

**Reference implementation:** `agents/compute/tools.py` lines 406–494 — exact same implementation, just change `agent_name` to `"arc-agent"`.

---

## 2. Arc MCP Server Tool Inventory

Located at `services/arc-mcp-server/tools/`. All tools are mounted via `MCPTool` in `agent.py` when `ARC_MCP_SERVER_URL` is set.

### `arc_servers.py` tools:
| Tool Name (in `ALLOWED_MCP_TOOLS`) | Function | Status |
|---|---|---|
| `arc_servers_list` | Lists all Arc-enabled HybridCompute machines by subscription, exhausting nextLink | ✅ Real |
| `arc_servers_get` | Gets a single Arc machine with extension health detail | ✅ Real |
| `arc_extensions_list` | Lists all extensions on an Arc machine with health status | ✅ Real |

### `arc_k8s.py` tools:
| Tool Name | Function | Status |
|---|---|---|
| `arc_k8s_list` | Lists all Arc-enabled Kubernetes clusters, optionally with Flux configs | ✅ Real |
| `arc_k8s_get` | Gets a single Arc K8s cluster with Flux status | ✅ Real |
| `arc_k8s_gitops_status` | Gets Flux GitOps reconciliation status for a cluster | ✅ Real |

### `arc_data.py` tools:
| Tool Name | Function | Status |
|---|---|---|
| `arc_data_sql_mi_list` | Lists Arc-enabled SQL Managed Instances in a subscription | ✅ Real |
| `arc_data_postgresql_list` | Lists Arc-enabled PostgreSQL instances in a subscription | ✅ Real |
| `arc_data_sql_mi_get` | Gets a single Arc SQL MI by name | ✅ Real |

**Note:** The Arc MCP Server has NO tool for activity logs, log analytics, or resource health — those are correctly implemented as `@ai_function` tools in the Arc agent's `tools.py`.

**Key finding:** The Phase 32 tools `query_arc_extension_health`, `query_arc_connectivity`, `query_arc_guest_config`, and `propose_arc_assessment` are **already real implementations** (not stubs) — they use `HybridComputeManagementClient` and `GuestConfigurationClient` with try/except and `duration_ms`. Tests exist in `agents/tests/arc/test_arc_new_tools.py`. However, **these 4 tools are NOT registered in `agent.py`** (agent.py only imports and registers the 3 stub tools).

---

## 3. Required New Packages (Delta from Current `requirements.txt`)

**Current `agents/arc/requirements.txt`:**
```
azure-mgmt-hybridcompute==9.0.0
azure-mgmt-hybridkubernetes==1.1.0
azure-mgmt-azurearcdata==1.0.0
azure-mgmt-kubernetesconfiguration==3.1.0
httpx>=0.27.0
```

**Missing packages needed for stub implementations:**

| Package | Version | Purpose | Already in compute? |
|---|---|---|---|
| `azure-mgmt-monitor` | `>=6.0.0` | Activity Log via `MonitorManagementClient.activity_logs.list()` | ✅ Yes |
| `azure-monitor-query` | `>=1.3.0` | Log Analytics via `LogsQueryClient.query_workspace()` | ✅ Yes |
| `azure-mgmt-resourcehealth` | `==1.0.0b6` | Resource Health via `MicrosoftResourceHealth.availability_statuses.get_by_resource()` | ✅ Yes |

**Already present (Phase 32 tools):**
- `azure-mgmt-hybridcompute==9.0.0` — used by `query_arc_extension_health`, `query_arc_connectivity` ✅
- `azure-mgmt-guestconfiguration` — **NOT in requirements.txt** ⚠️

**Additional gap found:** `azure-mgmt-guestconfiguration` is imported in `tools.py` at line 37 (`from azure.mgmt.guestconfiguration import GuestConfigurationClient`) but is **not listed in `requirements.txt`**. This needs to be added.

**Full delta to add to `agents/arc/requirements.txt`:**
```
azure-mgmt-monitor>=6.0.0
azure-monitor-query>=1.3.0
azure-mgmt-resourcehealth==1.0.0b6
azure-mgmt-guestconfiguration>=1.0.0
```

---

## 4. Implementation Approach for Each Tool

### 4a. `query_activity_log` (STUB → REAL)

**Approach:** Copy the compute agent's implementation verbatim, changing only:
- `agent_name="arc-agent"` in `instrument_tool_call`
- Import `MonitorManagementClient` via lazy import with try/except
- Add `_extract_subscription_id()` helper if not already present (can copy from compute agent)

**Arc-specific consideration:** Arc machine resource IDs look like:
```
/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.HybridCompute/machines/{name}
```
This is standard ARM format — `_extract_subscription_id()` works unchanged.

**Filter string:** Identical to compute agent:
```python
filter_str = (
    f"eventTimestamp ge '{start.isoformat()}' "
    f"and resourceId eq '{resource_id}'"
)
```

---

### 4b. `query_log_analytics` (STUB → REAL)

**Approach:** Copy the compute agent's implementation verbatim, changing only:
- `agent_name="arc-agent"` in `instrument_tool_call`
- Import `LogsQueryClient, LogsQueryStatus` via lazy import with try/except

**Arc-specific KQL context:** The docstring already mentions the correct tables: `Heartbeat`, `AzureActivity`, `ConfigurationChange`, `Event`. The agent (guided by the system prompt) will build appropriate KQL. No changes needed to the function logic.

**Empty workspace_id guard:** Already documented in the compute agent — if `workspace_id` is empty, return `query_status: "skipped"`. Critical for Arc because not all Arc machines will have AMA installed and linked to a workspace.

---

### 4c. `query_resource_health` (STUB → REAL)

**Approach:** Copy the compute agent's implementation verbatim, changing only:
- `agent_name="arc-agent"` in `instrument_tool_call`
- Import `MicrosoftResourceHealth` via lazy import with try/except

**Arc-specific note:** Azure Resource Health supports `Microsoft.HybridCompute/machines` — Arc servers appear in Resource Health with `availability_state` values of `Available`, `Degraded`, `Unavailable`. The same SDK call works unchanged.

---

### 4d. Register Phase 32 tools in `agent.py`

**Current state:** `agent.py` line 40-45 imports only 3 tools:
```python
from arc.tools import (
    ALLOWED_MCP_TOOLS,
    query_activity_log,
    query_log_analytics,
    query_resource_health,
)
```

And `tools = [query_activity_log, query_log_analytics, query_resource_health]` (line 153).

The 4 Phase 32 tools (`query_arc_extension_health`, `query_arc_connectivity`, `query_arc_guest_config`, `propose_arc_assessment`) are fully implemented in `tools.py` but never imported or registered in `agent.py`.

**Fix:**
1. Add the 4 new tools to the import block in `agent.py`
2. Add them to the `tools = [...]` list
3. Update the system prompt's `## Allowed Tools` list
4. Update `create_arc_agent_version()` tools list

**System prompt update:** Add new tools to Step 2 (connectivity check uses `query_arc_connectivity`), Step 3 (extension health uses `query_arc_extension_health`), and add Step for guest config (uses `query_arc_guest_config`).

---

### 4e. New HITL tool: `propose_arc_extension_install`

**Purpose:** HITL-gated extension install for an Arc machine (e.g., installing AMA when it's missing).

**Pattern:** Follow `propose_arc_assessment` exactly (lines 383-441 in `tools.py`):
- `create_approval_record(container=None, ...)` with `risk_level="medium"` (extension installs can fail or cause agent restart)
- Returns `{"status": "pending_approval", "approval_id": ..., "message": ..., "duration_ms": ...}`
- No ARM call — approval only

**Parameters:**
```python
def propose_arc_extension_install(
    resource_id: str,
    resource_group: str,
    machine_name: str,
    subscription_id: str,
    extension_name: str,      # e.g., "AzureMonitorWindowsAgent"
    extension_publisher: str, # e.g., "Microsoft.Azure.Monitor"
    incident_id: str,
    thread_id: str,
    reason: str,
) -> Dict[str, Any]:
```

**Proposal dict:**
```python
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
```

---

## 5. HITL Pattern Confirmation

**Pattern from `propose_vm_restart` (compute agent, lines 991–1054):**

```python
@ai_function
def propose_vm_restart(...) -> Dict[str, Any]:
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(...):
        try:
            proposal = { "action": ..., "description": ..., ... }
            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id=incident_id,
                agent_name="compute-agent",
                proposal=proposal,
                resource_snapshot={...},
                risk_level="medium",
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"...",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("...", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}
```

**Confirmed:** `propose_arc_extension_install` follows the same pattern exactly. `container=None` is correct — `create_approval_record` in `agents/shared/approval_manager.py` handles the None case (creates in-memory or Cosmos). The `propose_arc_assessment` tool already confirms this pattern works in the Arc agent context.

---

## 6. Web UI Changes Needed

### VMTab.tsx — No changes needed for list view

The VM list already:
- Shows `vm_type: "Arc VM" | "Azure VM"` with a `VMTypeBadge`
- Shows `power_state` which maps to "Connected"/"Disconnected" for Arc VMs via `PowerStateBadge` (handles `connected`/`disconnected` states)
- Shows health, EOL date, alerts

**No column changes required.**

### VMDetailPanel.tsx — Arc-specific panel adaptation needed

The `VMDetailPanel` is currently designed for Azure-native VMs. For Arc VMs it opens when clicking an Arc row in VMTab. Current behavior:
- Fetches from `/api/proxy/vms/{encoded}` → returns Arc VM data (resource_group, location, etc.)
- Shows `vm.power_state` via `PowerBadge` — Arc uses "Connected"/"Disconnected", not "running"/"stopped"
- Shows metrics via `/api/proxy/vms/{encoded}/metrics` — **Azure Monitor metrics don't apply to Arc VMs** (Arc uses AMA → Log Analytics, not Azure Monitor ARM metrics)
- Shows `ama_status` — still relevant (Arc should show AMA status)

**The main gap:** The metrics sparklines section will show "No metrics available" for Arc VMs (they don't expose ARM metrics directly). The panel should gracefully handle this for Arc VMs and instead show:
1. Arc connectivity status (already available from `vm.power_state` mapped to Connected/Disconnected)
2. Extension health summary (from `query_arc_extension_health` — but this is agent-side, not a REST endpoint yet)

**Scope decision for this phase:** The VMDetailPanel already handles `vm.power_state === 'deallocated'` with a "VM is deallocated" message. A similar check for Arc VMs (where `vm.vm_type === 'Arc VM'`) showing "Arc VMs use Log Analytics for metrics — use AI Investigation" is sufficient for parity.

**Minimal UI change needed:**
- In the metrics section of `VMDetailPanel.tsx`, when the VM is an Arc VM and metrics return empty, show an Arc-specific message instead of generic "No metrics available"
- Requires `vm_type` to be passed from the VMTab click through to the VMDetailPanel

**Actually — the VMDetailPanel currently receives `resourceId` and `resourceName` but NOT `vm_type`.** The `/api/proxy/vms/{encoded}` response DOES include `vm_type` (it's in the `VMDetail` interface via the backend). However the `VMDetail` interface in `VMDetailPanel.tsx` line 11 does NOT have `vm_type`.

**Fix:** Add `vm_type?: string` to `VMDetail` interface and use it in the metrics "no data" message.

---

## 7. Arc Agent `agent.py` — 4 Registration Locations

From reading `agent.py`:

1. **Import block** (line 40–45): `from arc.tools import (ALLOWED_MCP_TOOLS, query_activity_log, ...)`
2. **`tools = [...]` list** (line 153): Base tools list before MCP tool is appended
3. **System prompt `## Allowed Tools` section** (lines 124–130): Formatted from `ALLOWED_MCP_TOOLS + [...]`
4. **`create_arc_agent_version()` tools list** (lines 205–211): For Foundry PromptAgentDefinition

All 4 must be updated when new `@ai_function` tools are added.

---

## 8. `start_time` Position — Subtle Pattern Difference

The **Phase 32 tools** (already real) use `start_time = time.monotonic()` OUTSIDE the `with instrument_tool_call(...)` block:

```python
start_time = time.monotonic()  # before the with block
agent_id = get_agent_identity()

with instrument_tool_call(...):
    try:
        ...
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return {..., "duration_ms": duration_ms}
    except Exception as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        ...
```

The **compute agent tools** (activity log, resource health, etc.) use `start_time` INSIDE the `with instrument_tool_call(...)` block. Both are valid — use the Phase 32 pattern (start_time outside) for the stub replacements to be consistent within `arc/tools.py`.

---

## 9. Recommended Plan Structure

### Recommendation: 1 Plan (40-1)

This phase is purely backend + minor UI. The work is:
- 3 stub replacements (copy-from-compute pattern, well-understood)
- 4 tool registrations in agent.py (pure wiring)
- 1 new HITL tool (`propose_arc_extension_install`)
- 3 new packages in requirements.txt
- Minor VMDetailPanel UI fix (Arc metrics message)
- Tests for all 3 stub replacements + new HITL tool

**Estimated scope:** ~350 lines of code (mostly copy-of-compute patterns), ~12-15 new tests. No new infrastructure, no Terraform changes, no new endpoints.

**Wave breakdown within the single plan:**

| Wave | Work | Notes |
|------|------|-------|
| Wave 1 | `requirements.txt` additions + lazy imports in `tools.py` | 4 new packages, 3 new import blocks |
| Wave 2 | Replace 3 stubs with real implementations | Copy-from-compute, change `agent_name` |
| Wave 3 | Add `propose_arc_extension_install` HITL tool | Follow `propose_arc_assessment` pattern |
| Wave 4 | Wire all 7 tools into `agent.py` (4 Phase 32 + 3 stubs now real) | 4 locations in agent.py |
| Wave 5 | Tests for stubs + new HITL tool | ~12 tests using mock pattern from `test_arc_new_tools.py` |
| Wave 6 | VMDetailPanel Arc metrics message + `vm_type` in VMDetail interface | ~10 lines of TSX |

---

## 10. Key Implementation Notes

1. **`_extract_subscription_id()` helper:** The compute agent has this at ~line 150–172. The Arc agent does NOT currently have it. It must be added or the import moved to shared. **Recommendation:** Copy the function directly into `arc/tools.py` (same approach as compute agent — it's small and self-contained).

2. **`time.monotonic()` placement:** Use the Phase 32 pattern (before the `with` block) for all 3 stub replacements to maintain consistency within `arc/tools.py`.

3. **`duration_ms` in stubs:** The current stubs do NOT record `duration_ms`. The real implementations must add it.

4. **`LogsQueryStatus` import:** Both `LogsQueryClient` and `LogsQueryStatus` must be imported together from `azure.monitor.query`.

5. **Arc Resource Health confirmation:** `Microsoft.HybridCompute/machines` is a supported resource type for Azure Resource Health. The `get_by_resource()` API uses the full ARM resource URI — same as for VMs. No Arc-specific special handling needed.

6. **No new API gateway endpoints needed:** The stub replacements are purely agent-side. The web UI change is cosmetic only (Arc metrics message). No new proxy routes needed.

7. **No new Terraform changes:** The 3 packages (`azure-mgmt-monitor`, `azure-monitor-query`, `azure-mgmt-resourcehealth`) use the same RBAC permissions the Arc agent already has (Reader on Arc subscriptions). No additional role assignments needed.

8. **Test count target:** ~15 new unit tests:
   - 3 tests per stub (success, SDK missing, error path) = 9 tests
   - 3 tests for `propose_arc_extension_install` (success, error, approval record call) = 3 tests
   - 3 tests for `agent.py` wiring (imports resolve, tool count, system prompt contains new tools) = 3 tests

---

## RESEARCH COMPLETE
