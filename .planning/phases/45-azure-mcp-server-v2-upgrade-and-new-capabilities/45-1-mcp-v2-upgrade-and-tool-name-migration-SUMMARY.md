---
phase: 45-azure-mcp-server-v2-upgrade-and-new-capabilities
plan: 45-1
subsystem: agents
tags: [azure-mcp, mcp-v2, tool-migration, namespace-tools]

requires:
  - phase: none
    provides: existing v1 MCP tool integrations across all 8 agents
provides:
  - Azure MCP Server upgraded to 2.0.0 GA (from beta.34)
  - All 8 agent ALLOWED_MCP_TOOLS migrated from v1 dotted names to v2 namespace names
  - SRE agent containerapps namespace added for Plan 45-2
  - Cross-agent MCP v2 migration validation test
  - CLAUDE.md updated with microsoft/mcp repo, v2.0.0, intent-based architecture
affects: [45-2-sre-container-apps-self-monitoring-tool]

tech-stack:
  added: []
  patterns: [v2-namespace-mcp-tools]

key-files:
  created:
    - agents/tests/test_mcp_v2_migration.py
  modified:
    - services/azure-mcp-server/Dockerfile
    - agents/sre/tools.py
    - agents/compute/tools.py
    - agents/network/tools.py
    - agents/storage/tools.py
    - agents/security/tools.py
    - agents/eol/tools.py
    - agents/patch/tools.py
    - agents/arc/tools.py
    - agents/sre/agent.py
    - agents/network/agent.py
    - agents/storage/agent.py
    - agents/security/agent.py
    - agents/eol/agent.py
    - agents/patch/agent.py
    - agents/tests/sre/test_sre_tools.py
    - agents/tests/compute/test_compute_tools.py
    - agents/tests/network/test_network_tools.py
    - agents/tests/patch/test_patch_tools.py
    - agents/tests/security/test_security_tools.py
    - agents/tests/eol/test_eol_tools.py
    - agents/tests/integration/test_mcp_tools.py
    - agents/tests/patch/test_patch_agent.py
    - CLAUDE.md

key-decisions:
  - "v2 namespace names are broader than v1 dotted names — acceptable because agents are constrained by system prompt instructions and all namespaces are read-only"
  - "containerapps added to SRE ALLOWED_MCP_TOOLS preemptively for Plan 45-2 self-monitoring capability"
  - "Arc MCP tool names (arc_servers_list, etc.) are unchanged — they come from custom FastMCP server, not Azure MCP Server"
  - "OTel span test fixtures using compute.list_vms as tool_name argument preserved — these are test data, not allowlist entries"

patterns-established:
  - "v2-namespace-mcp-tools: All ALLOWED_MCP_TOOLS entries must be v2 namespace names (no dots in Azure MCP entries). Arc MCP tools use underscores."

requirements-completed: []

duration: 18min
completed: 2026-04-14
---

# Plan 45-1: MCP v2 Upgrade + Tool Name Migration Summary

**Azure MCP Server upgraded to 2.0.0 GA with all 8 agent ALLOWED_MCP_TOOLS migrated from 131+ v1 dotted names to 61 v2 namespace names**

## Performance

- **Duration:** 18 min
- **Tasks:** 17
- **Files modified:** 25
- **Files created:** 1

## Accomplishments
- Upgraded Azure MCP Server Dockerfile from 2.0.0-beta.34 to 2.0.0 GA
- Migrated all 8 agent ALLOWED_MCP_TOOLS lists from v1 dotted names to v2 namespace names (e.g., `monitor.query_logs` → `monitor`)
- Updated all agent system prompts to reference v2 namespace names
- Updated all existing MCP tool tests + added `test_allowed_mcp_tools_no_dotted_names` to every agent
- Created cross-agent MCP v2 migration validation test (`test_mcp_v2_migration.py`) with parametrized checks across 8 modules
- Added `containerapps` to SRE ALLOWED_MCP_TOOLS for Plan 45-2 self-monitoring
- Updated CLAUDE.md with microsoft/mcp repo reference, v2.0.0 version, intent-based tool architecture

## Task Commits

1. **Task 45-1-01: Update Dockerfile ARG** - `83134b5` (feat)
2. **Task 45-1-02: Migrate SRE ALLOWED_MCP_TOOLS** - `501825f` (feat)
3. **Task 45-1-03..09: Migrate all other agent ALLOWED_MCP_TOOLS** - `b72b174` (feat)
4. **Task 45-1-10..11: Update all agent system prompts** - `c4d209b` (feat)
5. **Task 45-1-12..14: Update all MCP tool tests** - `e58a597` (test)
6. **Task 45-1-15: Cross-agent migration validation test** - `9d14e94` (test)
7. **Task 45-1-16: Update CLAUDE.md** - `7a50bef` (docs)
8. **Task 45-1-17: Fix patch agent test** - `f54133c` (fix)

## Files Created/Modified
- `services/azure-mcp-server/Dockerfile` - Version pin 2.0.0
- `agents/*/tools.py` (8 files) - ALLOWED_MCP_TOOLS v2 namespace names
- `agents/*/agent.py` (6 files) - System prompt v2 references
- `agents/tests/*/test_*_tools.py` (6 files) - Updated test assertions
- `agents/tests/integration/test_mcp_tools.py` - Integration test updates
- `agents/tests/patch/test_patch_agent.py` - v2 names + tool count fix
- `agents/tests/test_mcp_v2_migration.py` - New cross-agent validation
- `CLAUDE.md` - v2.0.0, microsoft/mcp repo, intent-based architecture

## Decisions Made
- CONTEXT.md "keep advisor.list_recommendations" decision overridden — v1 dotted names don't exist in v2
- Pre-existing patch agent tool count bug (7 vs actual 8) fixed alongside v2 migration
- OTel span test fixtures (`compute.list_vms` as tool_name parameter) intentionally preserved — test data, not allowlist entries

## Deviations from Plan

### Auto-fixed Issues

**1. Pre-existing tool count bug in test_patch_agent.py**
- **Found during:** Task 45-1-17 (full test suite run)
- **Issue:** `test_create_patch_agent_registers_all_seven_tools` asserted 7 tools but agent registers 8 (discover_arc_workspace added after test was written)
- **Fix:** Renamed test and changed assertion from 7 to 8
- **Verification:** All patch agent tests pass

---

**Total deviations:** 1 auto-fixed (pre-existing bug)
**Impact on plan:** Necessary for correctness. No scope creep.

## Issues Encountered
- 1 pre-existing flaky test (`test_eol_stub_fixes.py::test_calls_monitor_management_client_activity_logs`) fails in full suite due to mock patch bleeding but passes in isolation — not caused by our changes

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 45-2 (SRE Container Apps self-monitoring) can proceed — `containerapps` already in SRE ALLOWED_MCP_TOOLS
- All agents ready for v2 MCP Server deployment
- Dockerfile rebuild needed: `az acr build` with updated Dockerfile

---
*Phase: 45-azure-mcp-server-v2-upgrade-and-new-capabilities*
*Completed: 2026-04-14*
