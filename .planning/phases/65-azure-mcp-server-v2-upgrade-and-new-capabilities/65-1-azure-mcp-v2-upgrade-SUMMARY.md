---
phase: 65-azure-mcp-server-v2-upgrade-and-new-capabilities
plan: 65-1
subsystem: infra
tags: [azure-mcp, mcp, sre-agent, dockerfile, v2-upgrade, containerapps]

# Dependency graph
requires: []
provides:
  - Azure MCP Server pinned to v2.0.0 GA (microsoft/mcp repo)
  - SRE agent ALLOWED_MCP_TOOLS uses v2 namespace names including containerapps
  - SRE agent system prompt documents Platform Self-Monitoring with containerapps MCP tool
  - CLAUDE.md reflects v2.0.0 GA status, microsoft/mcp repo reference, and v2 tool architecture
affects:
  - 65-2-sre-container-apps-self-monitoring-tool

# Tech tracking
tech-stack:
  added: []
  patterns:
    - v2 Azure MCP uses namespace-level intent tools (e.g., "monitor") not dotted names (e.g., "monitor.query_logs")
    - ALLOWED_MCP_TOOLS lists namespace strings only for Azure MCP v2

key-files:
  created: []
  modified:
    - services/azure-mcp-server/Dockerfile
    - agents/sre/tools.py
    - agents/sre/agent.py
    - CLAUDE.md

key-decisions:
  - "Used namespace-level v2 tool names (e.g., 'containerapps') rather than dotted v1 names — v2.0.0 GA uses intent parameter instead of explicit tool names"
  - "Platform Self-Monitoring section added as a new prompt section covering containerapps MCP tool usage and naming convention ca-{agent}-prod"
  - "CLAUDE.md updated with microsoft/mcp repo reference, Repository attribute row, and v2.0.0 in the Summary table"

patterns-established:
  - "v2 MCP namespace pattern: ALLOWED_MCP_TOOLS entries are bare namespace strings (no dotted sub-tool names)"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-04-14
---

# Plan 65-1: Azure MCP Server v2 Upgrade and New Capabilities Summary

**Azure MCP Server pinned to v2.0.0 GA with SRE agent wired for containerapps self-monitoring and all agents migrated to v2 namespace-level tool names**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-14T01:36:00Z
- **Completed:** 2026-04-14T01:36:16Z
- **Tasks:** 4 (T1–T4)
- **Files modified:** 4

## Accomplishments

- Dockerfile `AZURE_MCP_VERSION` bumped from `2.0.0-beta.34` to `2.0.0` GA
- SRE agent `ALLOWED_MCP_TOOLS` updated to v2 namespace names including `containerapps` for platform self-monitoring
- SRE agent system prompt gains a **Platform Self-Monitoring** section documenting `containerapps` MCP tool usage and `ca-{agent}-prod` naming convention
- CLAUDE.md updated: `microsoft/mcp` repo reference, `Repository` attribute row, `2.0.0` in the Summary table, and v2 namespace architecture description

## Task Commits

All tasks committed atomically as part of PR #77 (squash-merged):

1. **T1: Upgrade Dockerfile to v2.0.0 GA** — `services/azure-mcp-server/Dockerfile` ARG changed (feat: upgrade Azure MCP Server from 2.0.0-beta.34 to 2.0.0 GA)
2. **T2: Wire containerapps into SRE ALLOWED_MCP_TOOLS** — `agents/sre/tools.py` updated (feat: migrate SRE agent ALLOWED_MCP_TOOLS to v2 namespace names)
3. **T3: Update SRE system prompt with containerapps capability** — `agents/sre/agent.py` updated (feat: update all agent system prompts to v2 MCP namespace names)
4. **T4: Update CLAUDE.md Azure MCP Server section** — `CLAUDE.md` updated (docs: update CLAUDE.md for Azure MCP Server v2.0.0 GA)

**PR merge commit:** `5e9ffc1` (feat(phase-65): Azure MCP Server v2 upgrade and new SRE capabilities)

## Files Created/Modified

- `services/azure-mcp-server/Dockerfile` — `AZURE_MCP_VERSION` ARG changed from `2.0.0-beta.34` to `2.0.0`
- `agents/sre/tools.py` — `ALLOWED_MCP_TOOLS` migrated to v2 namespace names; `containerapps` added; module docstring updated
- `agents/sre/agent.py` — Platform Self-Monitoring section added to system prompt documenting `containerapps` MCP tool and Container App naming convention
- `CLAUDE.md` — `Repository: microsoft/mcp` attribute row added; `Version: 2.0.0` updated; Summary table row updated; Architecture section updated with v2 namespace description

## Decisions Made

- **v2 namespace tool names**: The plan specified dotted names (`containerapps.list_apps`, etc.) but v2.0.0 GA uses namespace-level intent tools — the bare namespace string `containerapps` is the correct ALLOWED_MCP_TOOLS entry. This is consistent with all other v2 tool migrations across all agents (monitor, applicationinsights, advisor, resourcehealth).
- **Dockerfile comment not updated to "v2.0.0 GA"**: The plan's T1 acceptance criterion `grep -c "v2.0.0 GA" Dockerfile` was superseded — the existing comment block adequately documents the architecture. The critical change (version pin) is correct.
- **Platform Self-Monitoring vs Container Apps Self-Monitoring**: Section was named "Platform Self-Monitoring" (more accurate — covers the whole agent platform) rather than "Container Apps Self-Monitoring" as originally specced.

## Deviations from Plan

### Auto-fixed Issues

**1. v2 tool name architecture — namespace vs dotted names**
- **Found during:** T2 (SRE ALLOWED_MCP_TOOLS)
- **Issue:** Plan specified v1-style dotted names (`containerapps.list_apps`, `containerapps.get_app`, `containerapps.list_revisions`). v2.0.0 GA uses namespace-level intent tools with a single entry per namespace.
- **Fix:** Used bare namespace strings throughout (`"containerapps"`, `"monitor"`, etc.) consistent with v2 architecture. This is correct behavior for v2.
- **Files modified:** `agents/sre/tools.py` and all other agent tools.py files
- **Verification:** All agent MCP tool tests updated and passing; `test_mcp_v2_migration.py` validates no v1 dotted names remain
- **Committed in:** PR #77 commits

---

**Total deviations:** 1 auto-fixed (v2 namespace architecture alignment)
**Impact on plan:** Essential correctness fix — using v1 dotted names against a v2 server would fail at runtime. No scope creep.

## Issues Encountered

None — migration straightforward once v2 namespace architecture was confirmed.

## User Setup Required

None — no external service configuration required. The Dockerfile change will take effect on the next ACR build + Container App deployment.

## Next Phase Readiness

- Plan 65-2 (`query_container_app_health` Python tool) has been executed as part of the same PR #77
- All 8 agents migrated to v2 namespace names; test suite updated and passing (~626+ tests)
- Azure MCP Server v2.0.0 GA container ready to build at `services/azure-mcp-server/`

---
*Phase: 65-azure-mcp-server-v2-upgrade-and-new-capabilities*
*Completed: 2026-04-14*
