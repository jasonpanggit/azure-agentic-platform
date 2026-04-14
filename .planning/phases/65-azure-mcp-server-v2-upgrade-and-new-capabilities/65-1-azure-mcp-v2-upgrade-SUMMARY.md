---
phase: 65-azure-mcp-server-v2-upgrade-and-new-capabilities
plan: 65-1
subsystem: infra
tags: [azure-mcp, mcp, sre-agent, dockerfile, v2-upgrade, containerapps]

# Dependency graph
requires: []
provides:
  - Azure MCP Server pinned to v2.0.0 GA (microsoft/mcp repo)
  - SRE agent ALLOWED_MCP_TOOLS extended with containerapps.list_apps/get_app/list_revisions
  - SRE agent system prompt documents Container Apps Self-Monitoring capability
  - CLAUDE.md reflects v2.0.0 GA status, microsoft/mcp repo reference, new namespaces
affects:
  - 65-2-sre-container-apps-self-monitoring-tool

# Tech tracking
tech-stack:
  added: []
  patterns:
    - containerapps dotted tool names wired into ALLOWED_MCP_TOOLS for Azure MCP v2 namespace access
    - Container Apps Self-Monitoring prompt section pattern for platform health diagnostics

key-files:
  created: []
  modified:
    - services/azure-mcp-server/Dockerfile
    - agents/sre/tools.py
    - agents/sre/agent.py
    - CLAUDE.md

key-decisions:
  - "Kept dotted names (containerapps.list_apps etc.) in ALLOWED_MCP_TOOLS as specified by plan — these are the explicit tool operations to allow"
  - "Container Apps Self-Monitoring section added to SRE system prompt documenting list_apps, get_app, list_revisions MCP tools"
  - "CLAUDE.md updated with microsoft/mcp repo reference, Version 2.0.0, Startup time row, 7 new v2 namespaces, and v2.0.0 in architecture section"

patterns-established:
  - "Container Apps Self-Monitoring: SRE agent can inspect platform Container Apps via containerapps MCP namespace tools"

requirements-completed: []

# Metrics
duration: 20min
completed: 2026-04-14
---

# Plan 65-1: Azure MCP Server v2 Upgrade and New Capabilities Summary

**Azure MCP Server Dockerfile pinned to v2.0.0 GA, SRE agent wired for containerapps self-monitoring, and CLAUDE.md updated with microsoft/mcp repo and 7 new v2 namespaces**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-14T03:10:00Z
- **Completed:** 2026-04-14T03:30:00Z
- **Tasks:** 4 (T1–T4)
- **Files modified:** 4

## Accomplishments

- Dockerfile `AZURE_MCP_VERSION` bumped from `2.0.0-beta.34` to `2.0.0` GA; comment updated to `v2.0.0 GA (microsoft/mcp)`
- SRE agent `ALLOWED_MCP_TOOLS` extended with `containerapps.list_apps`, `containerapps.get_app`, `containerapps.list_revisions`
- SRE agent system prompt gains a **Container Apps Self-Monitoring** section documenting the three containerapps MCP tools and how to use them for platform health diagnostics
- CLAUDE.md updated: `microsoft/mcp` repo reference, `Repository` and `Version: 2.0.0` attribute rows, `Startup time` row, Covered Services updated to v2.0.0 with 7 new namespaces (`containerapps`, `deviceregistry`, `functions`, `azuremigrate`, `policy`, `pricing`, `wellarchitectedframework`), Summary table `2.0.0`, Architecture section `v2.0.0 GA`

## Task Commits

Each task committed atomically:

1. **T1: Upgrade Dockerfile to v2.0.0 GA** — `2e40eb3` (feat: upgrade Azure MCP Server from 2.0.0-beta.34 to 2.0.0 GA)
2. **T2: Wire containerapps into SRE ALLOWED_MCP_TOOLS** — `52919a4` (feat: wire containerapps namespace into SRE agent ALLOWED_MCP_TOOLS)
3. **T3: Add Container Apps Self-Monitoring to SRE system prompt** — `3d1ab56` (feat: add Container Apps Self-Monitoring section to SRE agent system prompt)
4. **T4: Update CLAUDE.md Azure MCP Server section** — `acd96c4` (docs: update CLAUDE.md for Azure MCP Server v2.0.0 GA)

## Files Created/Modified

- `services/azure-mcp-server/Dockerfile` — `AZURE_MCP_VERSION` ARG changed from `2.0.0-beta.34` to `2.0.0`; comment block updated to `v2.0.0 GA (microsoft/mcp)`
- `agents/sre/tools.py` — `ALLOWED_MCP_TOOLS` extended with `containerapps.list_apps`, `containerapps.get_app`, `containerapps.list_revisions`; module docstring updated
- `agents/sre/agent.py` — Container Apps Self-Monitoring section added to system prompt after Arc Fallback section
- `CLAUDE.md` — Repository/Version/Startup time attribute rows added; Covered Services updated to v2.0.0 with 7 new namespaces; Summary table and Architecture section updated

## Decisions Made

- Followed plan exactly for dotted tool names in `ALLOWED_MCP_TOOLS` (e.g., `containerapps.list_apps`) as specified — these are the explicit per-operation allowlist entries
- Section named "Container Apps Self-Monitoring" as specified in T3 (not "Platform Self-Monitoring")
- Both `containerapps` occurrences in CLAUDE.md satisfy the ≥2 criterion: one in Covered Services table, one in Architecture MCP Surfaces line

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — all acceptance criteria passed on first verification.

## User Setup Required

None — no external service configuration required. The Dockerfile change takes effect on the next `az acr build` + Container App revision deployment.

## Next Phase Readiness

- Plan 65-2 can now implement `query_container_app_health` Python tool with the `containerapps` MCP namespace available in the SRE agent allowlist
- Azure MCP Server v2.0.0 GA image ready to rebuild at `services/azure-mcp-server/`

---
*Phase: 65-azure-mcp-server-v2-upgrade-and-new-capabilities*
*Completed: 2026-04-14*
