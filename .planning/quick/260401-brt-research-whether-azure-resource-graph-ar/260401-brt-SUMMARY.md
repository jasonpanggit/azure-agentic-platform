# Summary: Add `query_os_version` ARG Tool to Compute Agent

**Task:** 260401-brt
**Branch:** `feat/compute-query-os-version`
**Commit:** f0cd530
**Date:** 2026-04-01
**Status:** ✅ Complete — 10/10 tests pass

---

## What Was Done

### Task 1 — `agents/compute/tools.py`

Added `query_os_version` `@ai_function` after `query_monitor_metrics`. The function:

- Lazily imports `ResourceGraphClient`, `QueryRequest`, `QueryRequestOptions` from `azure-mgmt-resourcegraph` with `ImportError` guard (mirrors `eol/tools.py` pattern exactly).
- Adds `get_credential` to the existing import from `shared.auth`.
- Builds two KQL queries:
  - **VM query:** `microsoft.compute/virtualmachines` — projects `osName` from `properties.extended.instanceView.osName`, `osVersion` from instanceView, `osType` from storageProfile, plus `publisher`, `offer`, `imageReferenceSku` from `properties.storageProfile.imageReference`. Adds `| extend resourceType = "vm"`.
  - **Arc query:** `microsoft.hybridcompute/machines` — projects `osName`, `osVersion`, `osType`, `osSku`, `status` from `properties.*`. Adds `| extend resourceType = "arc"`.
- Inlines `| where id in~ (...)` filter directly into the KQL string for the provided `resource_ids`.
- Paginates via `skip_token` loop (identical pattern to `eol/tools.py` lines 481–496).
- Returns `{"resource_ids", "machines", "total_count", "query_status"}` on success; adds `"error"` key on exception.
- Wrapped in `instrument_tool_call(tracer, agent_name="compute-agent", ...)`.

**`ALLOWED_MCP_TOOLS` unchanged** — ARG is accessed via SDK (not MCP protocol), consistent with `eol/tools.py`.

### Task 2 — `agents/compute/agent.py`

- Added `query_os_version` to the import from `compute.tools`.
- Added `query_os_version` to the `tools=[...]` list in `create_compute_agent()` (5 tools total).
- Added `"query_os_version"` to the `COMPUTE_AGENT_SYSTEM_PROMPT` allowed tools `.format()` call.
- Added triage step 5 guidance: "If OS version is relevant to the hypothesis (e.g., suspected EOL OS), call `query_os_version` before routing to the EOL domain."

### Task 3 — `agents/tests/compute/`

Created two new files:

- `agents/tests/compute/__init__.py` (empty package marker)
- `agents/tests/compute/test_compute_tools.py` — 10 unit tests across 3 test classes:

| Class | Tests |
|---|---|
| `TestAllowedMcpTools` | `test_allowed_tools_is_list`, `test_no_wildcard_in_allowed_tools`, `test_allowed_tools_contains_expected_entries` |
| `TestQueryOsVersion` | `test_returns_success_status_on_empty_response`, `test_returns_vm_machines_with_resource_type_field`, `test_returns_arc_machines_with_resource_type_field`, `test_paginates_via_skip_token`, `test_returns_error_status_on_exception`, `test_filters_by_resource_ids_in_kql` |
| `TestComputeAgentWiring` | `test_query_os_version_in_agent_tools` (uses `sys.modules` mock pattern from `test_eol_agent.py`) |

### Task 4 — `agents/compute/requirements.txt`

Added `azure-mgmt-resourcegraph>=8.0.1` (same version pin as `eol/requirements.txt`).

---

## Acceptance Criteria

| Criterion | Status |
|---|---|
| `query_os_version` importable from `agents.compute.tools` | ✅ |
| `query_os_version` in `tools=[...]` in `create_compute_agent()` | ✅ |
| All 10 unit tests pass: `pytest agents/tests/compute/test_compute_tools.py -v` | ✅ 10/10 |
| No wildcards in `ALLOWED_MCP_TOOLS` | ✅ |
| No mutations to existing tool return shapes | ✅ |
| `eol/tools.py` unchanged (additive-only) | ✅ |

---

## Notes

- `tools.py` is 339 lines (plan estimated ~271; KQL string content + `ImportError` guard + docstring account for the difference — well within the 800-line global max).
- `resourceType` field is added via inline KQL `| extend resourceType = "vm"/"arc"` rather than post-processing in Python, keeping the pattern clean.
- The `| where id in~` filter is inlined into the KQL string at build time (not inserted via string manipulation), which is simpler than the eol/tools.py multi-line KQL + line-pop approach.
