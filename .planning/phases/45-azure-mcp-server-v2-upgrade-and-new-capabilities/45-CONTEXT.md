# Phase 45: Azure MCP Server v2 Upgrade and New Capabilities - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Upgrade from Azure MCP Server v1 beta (`@azure/mcp@2.0.0-beta.34`, archived `Azure/azure-mcp` repo) to v2 GA (`@azure/mcp@2.0.0`, `microsoft/mcp` repo). Wire two new high-value namespaces: `advisor` into the SRE agent and `containerapps` for platform self-monitoring. Update CLAUDE.md package references.

**Specific changes:**
1. Dockerfile: bump `AZURE_MCP_VERSION` from `2.0.0-beta.34` → `2.0.0`
2. SRE agent: verify `advisor` namespace tools are wired; add `advisor.get_recommendation` and broader advisor coverage
3. Orchestrator/SRE agent: add `containerapps` namespace tools for self-monitoring
4. CLAUDE.md: update Azure MCP Server section with v2.0.0 GA, new namespaces, startup improvement (1-2s vs 20s)

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase.

- `containerapps` namespace to be wired into the SRE agent (not orchestrator) — SRE agent is the natural home for platform health diagnostics
- CLAUDE.md update: add `containerapps`, `deviceregistry`, `functions`, `azuremigrate`, `policy`, `pricing`, `wellarchitectedframework` to new namespaces table
- Keep the proxy.js pattern unchanged — it works and is not part of the upgrade

</decisions>

<code_context>
## Existing Code Insights

### Key files to change
- `services/azure-mcp-server/Dockerfile` — bump AZURE_MCP_VERSION from 2.0.0-beta.34 to 2.0.0
- `agents/sre/tools.py` — ALLOWED_MCP_TOOLS already has `advisor.list_recommendations`; add `containerapps.*` tools
- `agents/sre/agent.py` — update system prompt to document containerapps capability
- `CLAUDE.md` — update Azure MCP Server section (version, new namespaces, startup time)

### Established Patterns
- ALLOWED_MCP_TOOLS list in each agent defines permitted MCP tool names
- No test changes needed for Dockerfile bump (infrastructure)
- SRE agent follows the module-level SDK scaffold pattern

### Integration Points
- CI/CD pipeline (`azure-mcp-server-build.yml`) triggers on changes to `services/azure-mcp-server/**`
- Startup time: ~20s → 1-2s — update health check probe timing if needed

</code_context>

<specifics>
## Specific Ideas

- The `advisor` namespace is already in ALLOWED_MCP_TOOLS for SRE — confirm it aligns with v2 tool names
- `containerapps` tools: `containerapps.list_apps`, `containerapps.get_app`, `containerapps.list_revisions` — scope to platform's own Container Apps environment for self-monitoring
- No unit test changes needed for the Dockerfile version bump; pure infrastructure
- SRE agent system prompt should mention containerapps as a capability for "why is agent X slow?" diagnostics

</specifics>

<deferred>
## Deferred Ideas

- `pricing` namespace — not core to AIOps value; no current use case
- `azuremigrate` namespace — relevant only for resource lifecycle tracking; deferred
- `wellarchitectedframework` namespace — useful for governance reviews; not operational
- v3.0.0-beta.1 tracking — breaking namespace changes + MCP protocol v1.1.0; wait for GA
- Docker image size reduction verification in prod — advisory, not blocking

</deferred>
