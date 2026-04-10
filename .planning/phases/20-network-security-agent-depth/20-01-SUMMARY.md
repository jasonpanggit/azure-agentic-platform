---
phase: 20-network-security-agent-depth
plan: "01"
subsystem: agents
tags: [azure-mgmt-network, network-agent, sdk, mcp, expressroute, nsg, vnet, load-balancer, network-watcher]

# Dependency graph
requires:
  - phase: 02-agent-core
    provides: ChatAgent pattern, shared auth/otel, agent.py/tools.py scaffold
provides:
  - 7 real azure-mgmt-network SDK tools in Network agent (query_nsg_rules, query_vnet_topology, query_load_balancer_health, query_peering_status, query_flow_logs, query_expressroute_health, check_connectivity)
  - _extract_subscription_id and _log_sdk_availability helpers for network tools
  - Expanded ALLOWED_MCP_TOOLS with compute.list_vms (5 total)
  - Updated triage workflow (10 steps) with ExpressRoute, connectivity, and flow log steps
affects: [orchestrator, network-tests, detection-plane]

# Tech tracking
tech-stack:
  added: [azure-mgmt-network (NetworkManagementClient, ConnectivityParameters, ConnectivitySource, ConnectivityDestination)]
  patterns: [LRO timeout handling (120s), lazy SDK imports with try/except, structured error dicts]

key-files:
  created: []
  modified:
    - agents/network/tools.py
    - agents/network/agent.py

key-decisions:
  - "Combined tasks 20-01-01 and 20-01-02 into a single file write since both modify tools.py — avoids merge conflicts and keeps the file coherent"
  - "check_connectivity uses nested try/except for LRO timeout vs general errors, returning distinct query_status values (timeout vs error)"
  - "Flow log analytics_config extracted via nested network_watcher_flow_analytics_configuration to match SDK object hierarchy"

patterns-established:
  - "Network tool pattern: NetworkManagementClient(credential, subscription_id) per call — no shared client"
  - "LRO pattern: poller.result(timeout=120) with inner try/except returning query_status=timeout"
  - "All network tools accept subscription_id as explicit parameter (not extracted from resource_id)"

requirements-completed: [PROD-003]

# Metrics
duration: 8min
completed: 2026-04-10
---

# Plan 20-01: Network Agent Real SDK Tools Summary

**7 real azure-mgmt-network SDK tools replacing stubs — NSG rules, VNet topology, load balancer health, peering status, flow logs, ExpressRoute health, and Network Watcher connectivity check with 120s LRO timeout**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-10
- **Completed:** 2026-04-10
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- Replaced all 4 stub tools with real `azure-mgmt-network` SDK implementations making actual Azure API calls
- Added 3 new tools: `query_flow_logs` (flow log configs), `query_expressroute_health` (circuit + BGP peering), `check_connectivity` (Network Watcher LRO diagnostic)
- Updated Network agent system prompt with 10-step triage workflow including ExpressRoute, connectivity diagnosis, and flow log verification
- Expanded `ALLOWED_MCP_TOOLS` to 5 entries (added `compute.list_vms` for VM NIC inspection)
- All 7 tools follow established pattern: `instrument_tool_call`, `start_time`, `duration_ms`, never raise

## Task Commits

Each task was committed atomically:

1. **Tasks 20-01-01 + 20-01-02: Real SDK tools + 3 new tools** - `d51b124` (feat)
2. **Task 20-01-03: Register tools in agent.py, expand system prompt** - `3f9f02a` (feat)

_Note: Tasks 01 and 02 were combined into one commit since both modify tools.py — avoids partial file states._

## Files Created/Modified

- `agents/network/tools.py` — Full rewrite: 207 lines of stubs → 831 lines of real SDK implementations. 7 `@ai_function` tools, `_extract_subscription_id`, `_log_sdk_availability`, lazy imports for `NetworkManagementClient` + connectivity models.
- `agents/network/agent.py` — Updated imports (7 tools), expanded `ChatAgent(tools=[...])` to 7 entries, added steps 5-7 to triage workflow (ExpressRoute, connectivity, flow logs), renumbered to 10 steps, updated Allowed Tools section to 12 entries (5 MCP + 7 SDK).

## Decisions Made

- **Combined tasks 01 + 02 commit:** Both tasks modify `tools.py` — a single coherent write avoids partial file states between commits while both tasks are verified independently.
- **Nested try/except for LRO timeout:** `check_connectivity` uses an inner `try/except` around `poller.result(timeout=120)` to distinguish timeout from general SDK errors, returning `query_status: "timeout"` vs `"error"`.
- **Explicit `subscription_id` parameter:** All 7 tools accept `subscription_id` as a parameter rather than extracting it from a resource_id, giving the LLM explicit control over subscription targeting.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Network agent has 7 fully implemented SDK tools ready for production
- Agent system prompt covers comprehensive 10-step triage workflow
- Ready for integration testing with live Azure subscriptions
- Tests for these tools will be added in plan 20-03 (if planned) or separate test phase

---
*Phase: 20-network-security-agent-depth*
*Plan: 20-01*
*Completed: 2026-04-10*
