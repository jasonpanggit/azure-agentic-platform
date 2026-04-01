# Plan: Add `query_os_version` ARG Tool to Compute Agent

**Date:** 2026-04-01
**Research:** 260401-brt-RESEARCH.md
**Branch:** `feat/compute-query-os-version`

---

## Context

The compute agent currently has zero OS inventory capability — it cannot answer "what OS is this VM running?" without delegating to MCP `compute.get_vm`. The EOL agent already has `query_os_inventory` (eol/tools.py:400–511) which implements the exact ARG pattern we need. This task ports a focused subset of that logic into `compute/tools.py` as `query_os_version`, scoped to querying by specific resource IDs rather than full estate scanning.

---

## Tasks

### Task 1 — Add `query_os_version` to `agents/compute/tools.py`

**File:** `agents/compute/tools.py`

**Changes:**

1. Add imports at the top of the file (alongside existing imports):
   ```python
   from azure.mgmt.resourcegraph import ResourceGraphClient
   from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
   from shared.auth import get_credential  # already imported in eol/tools.py — confirm it's available in shared.auth
   ```

2. Add `"resourcegraph.query"` to `ALLOWED_MCP_TOOLS` (this tool uses the SDK directly, but listing it keeps the allowlist accurate for any future MCP surface — if resourcegraph is not an MCP tool, skip this and leave the list unchanged).
   > **Decision rule:** Only add to `ALLOWED_MCP_TOOLS` if `resourcegraph.query` is a real MCP tool name used in the platform. If ARG is always accessed via SDK (as in eol/tools.py which has no ARG entry in its ALLOWED_MCP_TOOLS), do NOT add it — keep ALLOWED_MCP_TOOLS for MCP-protocol tools only.

3. Add `query_os_version` function after `query_monitor_metrics`:

   ```python
   @ai_function
   def query_os_version(
       resource_ids: List[str],
       subscription_ids: List[str],
   ) -> Dict[str, Any]:
       """Query ARG for OS version details for specific compute resources.

       Covers both Azure VMs (microsoft.compute/virtualmachines) using
       instanceView osName with imageReference sku as fallback, and
       Arc-enabled servers (microsoft.hybridcompute/machines) using
       properties.osName and properties.osSku.

       Use this tool when the triage workflow identifies a potential EOL OS
       issue and the compute agent needs OS version context before routing
       to the EOL agent.

       Args:
           resource_ids: List of Azure resource IDs to query (VMs or Arc machines).
           subscription_ids: List of subscription IDs that contain the resources.

       Returns:
           Dict with keys:
               resource_ids (list): Resources queried.
               machines (list): Per-machine dicts with id, name, resourceGroup,
                   subscriptionId, osName, osVersion, osType, osSku (Arc),
                   imageReferenceSku (VM fallback), resourceType.
               total_count (int): Number of machines returned.
               query_status (str): "success" or "error".
       """
   ```

   **Implementation pattern** (mirror eol/tools.py lines 436–511 exactly):
   - Use `get_credential()` + `ResourceGraphClient(credential)`
   - VM KQL: `resources | where type == "microsoft.compute/virtualmachines"` — project `id, name, resourceGroup, subscriptionId, osName, osVersion, osType, publisher, offer, sku` + add `| extend resourceType = "vm"` at the end
   - Arc KQL: `resources | where type == "microsoft.hybridcompute/machines"` — project `id, name, resourceGroup, subscriptionId, osName, osVersion, osType, osSku, status` + add `| extend resourceType = "arc"`
   - For both queries: inject `| where id in~ (...)` filter using `resource_ids` before the final `| project` line
   - Paginate via `skip_token` loop (identical to eol pattern)
   - Return shape: `{"resource_ids", "machines", "total_count", "query_status"}` — add `"error": str(e)` on exception
   - Wrap in `instrument_tool_call(tracer, agent_name="compute-agent", tool_name="query_os_version", ...)`

### Task 2 — Wire `query_os_version` into `agents/compute/agent.py`

**File:** `agents/compute/agent.py`

**Changes:**

1. Add `query_os_version` to the import from `compute.tools`:
   ```python
   from compute.tools import (
       ALLOWED_MCP_TOOLS,
       query_activity_log,
       query_log_analytics,
       query_monitor_metrics,
       query_resource_health,
       query_os_version,        # ← add
   )
   ```

2. Add `query_os_version` to the `tools=[...]` list in `create_compute_agent()`.

3. Add `query_os_version` to the `COMPUTE_AGENT_SYSTEM_PROMPT` allowed tools list (the `.format(allowed_tools=...)` call at line 87). It's already auto-generated from the list — just adding it to the `tools=[...]` list in point 2 will surface it. No manual prompt edit needed.

4. Optionally add a brief mention in the system prompt triage steps, e.g. under step 5 (correlate/hypothesise):
   > "If OS version is relevant to the hypothesis (suspected EOL), call `query_os_version` before routing to the EOL domain."

### Task 3 — Add unit tests in `agents/tests/compute/`

**New files:**
- `agents/tests/compute/__init__.py` (empty)
- `agents/tests/compute/test_compute_tools.py`

**Test structure** (follow `tests/eol/test_eol_tools.py` pattern — class-per-concern, one assert per test):

```
TestAllowedMcpTools
  - test_allowed_tools_is_list
  - test_no_wildcard_in_allowed_tools
  - test_allowed_tools_contains_expected_entries  (spot-check 3 existing tools)

TestQueryOsVersion
  - test_returns_success_status_on_empty_response
      Mock: ResourceGraphClient.resources returns response with data=[], skip_token=None
      Assert: result["query_status"] == "success"
      Assert: result["machines"] == []
      Assert: result["total_count"] == 0

  - test_returns_vm_machines_with_resource_type_field
      Mock: first call returns 1 VM row {"id": "...", "name": "vm1", "osName": "Ubuntu 22.04", "resourceType": "vm"}, skip_token=None for both queries
      Assert: len(result["machines"]) == 1
      Assert: result["machines"][0]["resourceType"] == "vm"

  - test_returns_arc_machines_with_resource_type_field
      Mock: first query returns [], second (Arc) returns 1 row {"osType": "linux", "osSku": "22.04", "resourceType": "arc"}
      Assert: result["machines"][0]["osSku"] == "22.04"

  - test_paginates_via_skip_token
      Mock: first response has skip_token="tok1", second has skip_token=None; each yields 1 row
      Assert: result["total_count"] == 2  (pagination collected both pages)

  - test_returns_error_status_on_exception
      Mock: ResourceGraphClient raises Exception("ARG unavailable")
      Assert: result["query_status"] == "error"
      Assert: "ARG unavailable" in result["error"]

  - test_filters_by_resource_ids_in_kql
      Mock: capture the QueryRequest passed to client.resources
      Assert: the KQL string contains `in~` with the provided resource ID

TestComputeAgentWiring
  - test_query_os_version_in_agent_tools
      Import create_compute_agent; mock get_foundry_client
      Assert: any(t.__name__ == "query_os_version" for t in agent._tools)
      (or however agent_framework exposes the tools list — adapt to actual API)
```

---

## Acceptance Criteria

- [ ] `query_os_version` is importable from `agents.compute.tools`
- [ ] `query_os_version` appears in the `tools=[...]` list in `create_compute_agent()`
- [ ] All 7 unit tests pass: `pytest agents/tests/compute/test_compute_tools.py -v`
- [ ] No wildcards introduced in `ALLOWED_MCP_TOOLS`
- [ ] File stays under 300 lines (currently 216; new tool adds ~55 lines → ~271 total ✓)
- [ ] No mutations to existing tool return shapes

---

## Notes

- `get_credential` is already imported in `eol/tools.py` from `shared.auth` — confirm `shared/auth.py` exports it before writing the import.
- `ResourceGraphClient` and `QueryRequest` are from `azure-mgmt-resource-graph`. Confirm this package is already in `agents/requirements.txt` (it almost certainly is, given eol/tools.py uses it).
- The `resourceType` field (`"vm"` vs `"arc"`) is added via KQL `| extend resourceType = "vm"` so the caller can distinguish the two resource types without inspecting the resource ID.
- Do NOT refactor eol/tools.py — this is an additive-only change.
