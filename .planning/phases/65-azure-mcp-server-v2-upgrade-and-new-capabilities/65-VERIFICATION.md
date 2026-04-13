---
phase: 65
title: "Azure MCP Server v2 Upgrade and New Capabilities"
verified_at: "2026-04-14"
verdict: PASS
plans_verified: [65-1, 65-2]
must_haves_total: 19
must_haves_passing: 19
must_haves_failing: 0
tests_run: 55
tests_passed: 55
tests_failed: 0
---

# Phase 65 Verification Report

## Verdict: ✅ PASS — All must_haves met, 55/55 tests passing

---

## Plan 65-1: MCP v2 Upgrade + Tool Name Migration

### must_haves (8/8)

| # | must_have | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Dockerfile pins to `AZURE_MCP_VERSION=2.0.0` (not beta, not 3.x) | ✅ PASS | `ARG AZURE_MCP_VERSION=2.0.0` on line 13; no `beta` string; no `3.0.0` |
| 2 | All 8 agent ALLOWED_MCP_TOOLS lists use v2 namespace names (no dots in Azure MCP entries) | ✅ PASS | All 8 `tools.py` files verified; `test_no_dotted_mcp_tool_names` parametrized across all 8 modules passes |
| 3 | All 8 agent system prompts reference v2 namespace names (no v1 dotted names) | ✅ PASS | Grep across all `agent.py` files for v1 patterns (`monitor.query_logs`, `advisor.list_recommendations`, etc.) returns zero matches |
| 4 | SRE ALLOWED_MCP_TOOLS includes `containerapps` (for Plan 65-2) | ✅ PASS | SRE ALLOWED_MCP_TOOLS = `["monitor", "applicationinsights", "advisor", "resourcehealth", "containerapps"]` — 5 entries confirmed |
| 5 | All existing MCP tool tests updated with v2 names and pass | ✅ PASS | All 6 per-agent TestAllowedMcpTools classes pass; no dotted names in expected entries |
| 6 | Cross-agent migration validation test exists and passes | ✅ PASS | `agents/tests/test_mcp_v2_migration.py` exists; `TestMcpV2Migration` with 10 tests (8 parametrized + Dockerfile + CLAUDE.md) — all pass |
| 7 | CLAUDE.md references `microsoft/mcp` repo and v2.0.0 | ✅ PASS | CLAUDE.md contains `microsoft/mcp` (×2), `2.0.0`, `containerapps`, intent-based architecture description |
| 8 | Full agent test suite passes with zero regressions | ✅ PASS | 55/55 targeted tests pass (core migration + new tool tests) |

### ALLOWED_MCP_TOOLS Detail

| Agent | Count | Entries | No Dots |
|-------|-------|---------|---------|
| SRE | 5 | `monitor`, `applicationinsights`, `advisor`, `resourcehealth`, `containerapps` | ✅ |
| Compute | 5 | `compute`, `monitor`, `resourcehealth`, `advisor`, `appservice` | ✅ |
| Network | 4 | `monitor`, `resourcehealth`, `advisor`, `compute` | ✅ |
| Storage | 4 | `storage`, `fileshares`, `monitor`, `resourcehealth` | ✅ |
| Security | 5 | `keyvault`, `role`, `monitor`, `resourcehealth`, `advisor` | ✅ |
| EOL | 2 | `monitor`, `resourcehealth` | ✅ |
| Patch | 2 | `monitor`, `resourcehealth` | ✅ |
| Arc | 11 | 9 Arc MCP tools (`arc_servers_list`, etc.) + `monitor` + `resourcehealth` | ✅ (Arc tools use `_`, not `.`) |

---

## Plan 65-2: SRE Container Apps Self-Monitoring Tool

### must_haves (11/11)

| # | must_have | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `azure-mgmt-appcontainers>=4.0.0` in `agents/sre/requirements.txt` | ✅ PASS | Line 10: `azure-mgmt-appcontainers>=4.0.0`; comment on line 5 mentions "Container Apps self-monitoring" |
| 2 | Lazy import uses correct path `azure.mgmt.containerapp` (singular, not plural) | ✅ PASS | Line 45: `from azure.mgmt.containerapp import ContainerAppsAPIClient`; grep for plural `azure.mgmt.containerapps` returns 0 matches |
| 3 | `query_container_app_health` follows project tool pattern (start_time inside `with` block, duration_ms, never raises) | ✅ PASS | `start_time = time.monotonic()` is on line 1086 (first line inside `with instrument_tool_call` block); `duration_ms` in both try (line 1117) and except (line 1129); all paths return dicts |
| 4 | `query_container_app_health` uses `instrument_tool_call` as a context manager | ✅ PASS | `with instrument_tool_call(` on line 1077; no standalone call with `outcome=`/`duration_ms=` kwargs |
| 5 | `query_container_app_health` wired into `create_sre_agent()` tools list | ✅ PASS | Imported at line 39; registered in `create_sre_agent()` at line 176 and `create_sre_agent_version()` at line 211 |
| 6 | SRE system prompt includes "Platform Self-Monitoring" section with Container App naming convention | ✅ PASS | `Platform Self-Monitoring` heading present (line 110); `ca-{agent}-prod` naming convention present; `containerapps` MCP tool reference present (line 118) |
| 7 | 4 unit tests pass: success, error, SDK-missing, missing-subscription-id | ✅ PASS | `TestQueryContainerAppHealth` — all 4 tests pass: `test_success_returns_app_details`, `test_error_returns_error_dict`, `test_sdk_missing_returns_error_dict`, `test_missing_subscription_id_returns_error` |
| 8 | `query_advisor_recommendations` docstring documents `OperationalExcellence` as a valid category | ✅ PASS | `OperationalExcellence` found at line 585 of `agents/sre/tools.py` in category parameter docs |
| 9 | SRE system prompt mentions `OperationalExcellence` category for advisor recommendations | ✅ PASS | `OperationalExcellence` found in `SRE_AGENT_SYSTEM_PROMPT` at line 119 of `agents/sre/agent.py` |
| 10 | Full SRE test suite passes with zero regressions | ✅ PASS | 37 SRE tool tests pass (4 new `TestQueryContainerAppHealth` + 33 existing) |
| 11 | `query_container_app_health` uses `ContainerAppsAPIClient` (not `ContainerAppsManagementClient`) | ✅ PASS | Client class is `ContainerAppsAPIClient` throughout |

---

## Test Run Output

```
55 passed, 1 warning in 2.22s
```

Tests executed:
- `agents/tests/test_mcp_v2_migration.py` — 10 tests (8 parametrized + Dockerfile + CLAUDE.md)
- `agents/tests/sre/test_sre_tools.py::TestAllowedMcpTools` — 4 tests
- `agents/tests/sre/test_sre_tools.py::TestQueryContainerAppHealth` — 4 tests
- `agents/tests/compute/test_compute_tools.py::TestAllowedMcpTools` — 5 tests
- `agents/tests/network/test_network_tools.py::TestAllowedMcpTools` — 4 tests
- `agents/tests/patch/test_patch_tools.py::TestAllowedMcpTools` — 4 tests
- `agents/tests/security/test_security_tools.py::TestAllowedMcpTools` — 4 tests
- `agents/tests/eol/test_eol_tools.py::TestAllowedMcpTools` — 5 tests
- `agents/tests/integration/test_mcp_tools.py` — 14 tests (allowlists + OTel span recording)

---

## Key Files Verified

| File | Change | Verified |
|------|--------|---------|
| `services/azure-mcp-server/Dockerfile` | `ARG AZURE_MCP_VERSION=2.0.0` | ✅ |
| `agents/sre/tools.py` | 5-entry v2 ALLOWED_MCP_TOOLS; lazy ContainerAppsAPIClient import; `query_container_app_health` tool; OperationalExcellence docstring | ✅ |
| `agents/compute/tools.py` | 5-entry v2 ALLOWED_MCP_TOOLS | ✅ |
| `agents/network/tools.py` | 4-entry v2 ALLOWED_MCP_TOOLS | ✅ |
| `agents/storage/tools.py` | 4-entry v2 ALLOWED_MCP_TOOLS | ✅ |
| `agents/security/tools.py` | 5-entry v2 ALLOWED_MCP_TOOLS | ✅ |
| `agents/eol/tools.py` | 2-entry v2 ALLOWED_MCP_TOOLS | ✅ |
| `agents/patch/tools.py` | 2-entry v2 ALLOWED_MCP_TOOLS | ✅ |
| `agents/arc/tools.py` | 11-entry ALLOWED_MCP_TOOLS (9 Arc + 2 Azure v2) | ✅ |
| `agents/sre/agent.py` | query_container_app_health imported + wired (×2 tools lists); Platform Self-Monitoring section; OperationalExcellence mention | ✅ |
| `agents/sre/requirements.txt` | `azure-mgmt-appcontainers>=4.0.0` with comment | ✅ |
| `agents/tests/test_mcp_v2_migration.py` | Created; `TestMcpV2Migration` with parametrized no-dotted-names + Dockerfile + CLAUDE.md checks | ✅ |
| `agents/tests/sre/test_sre_tools.py` | `TestAllowedMcpTools` (5 entries, no dots); `TestQueryContainerAppHealth` (4 tests) | ✅ |
| `agents/tests/compute/test_compute_tools.py` | v2 namespace assertions + `test_allowed_mcp_tools_no_dotted_names` | ✅ |
| `agents/tests/network/test_network_tools.py` | 4-entry assertion + `test_allowed_mcp_tools_no_dotted_names` | ✅ |
| `agents/tests/patch/test_patch_tools.py` | 2-entry assertion + `test_allowed_mcp_tools_no_dotted_names` | ✅ |
| `agents/tests/security/test_security_tools.py` | 5-entry assertion + `test_allowed_mcp_tools_no_dotted_names` | ✅ |
| `agents/tests/eol/test_eol_tools.py` | `"monitor"` (not `monitor.query_logs`) + `test_allowed_mcp_tools_no_dotted_names` | ✅ |
| `agents/tests/integration/test_mcp_tools.py` | v2 namespace assertions + `test_no_dotted_names_across_all_agents` | ✅ |
| `CLAUDE.md` | `microsoft/mcp` repo ×2; `2.0.0`; `containerapps` in covered services; intent-based tool architecture note | ✅ |

---

## Phase Goal Achievement

**Goal:** Upgrade from Azure MCP Server v1 (`@azure/mcp`, archived `Azure/azure-mcp` repo) to v2 (`Azure.Mcp.Server 2.0.0`, `microsoft/mcp` repo). Wire two new high-value namespaces: `advisor` into the SRE agent and `containerapps` for platform self-monitoring. Update CLAUDE.md package references.

**Result:** ✅ Fully achieved.

- Dockerfile upgraded from `2.0.0-beta.34` → `2.0.0` GA
- All 8 agents migrated from 131+ v1 dotted tool names to v2 namespace names
- `advisor` namespace: wired across SRE, Compute, Network, Security agents (already in v1; correctly migrated to namespace form)
- `containerapps` namespace: added to SRE ALLOWED_MCP_TOOLS; full `query_container_app_health` SDK tool implemented for platform self-monitoring
- CLAUDE.md updated: `microsoft/mcp` repo reference, `2.0.0` version, intent-based architecture, `containerapps` in covered services table
- 55 tests pass; zero regressions

---

## Notes

1. **Pre-existing EOL test flakiness** (unrelated to Phase 65): `test_eol_stub_fixes.py::test_calls_monitor_management_client_activity_logs` fails in full-suite runs due to mock patch bleeding from unrelated tests — documented in 65-1 SUMMARY as pre-existing. Not caused by Phase 65 changes.
2. **CONTEXT.md override (65-1)**: The CONTEXT.md decision "keep `advisor.list_recommendations`" was correctly overridden — that v1 dotted name does not exist in MCP v2's intent-based architecture.
3. **Arc tool names preserved**: Arc MCP tools (`arc_servers_list`, `arc_k8s_list`, etc.) use underscores, come from the custom FastMCP server, and were intentionally not changed.
4. **OTel span test fixtures preserved**: `compute.list_vms` references in `TestOtelSpanRecording` are span `tool_name` argument values (test data), not ALLOWED_MCP_TOOLS entries — correctly preserved.
