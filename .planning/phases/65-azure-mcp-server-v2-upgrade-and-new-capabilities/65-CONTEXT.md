# Phase 65: Azure MCP Server v2 Upgrade and New Capabilities - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure + integration phase)

<domain>
## Phase Boundary

Upgrade the Azure MCP Server from `@azure/mcp` (archived `Azure/azure-mcp` repo, v0.x beta) to
`Azure.Mcp.Server 2.0.0` (`microsoft/mcp` repo, GA April 10, 2026). Then wire two new high-value
namespaces into existing agents:

1. **`advisor` namespace** — already accessible via MCP; add to SRE agent's `ALLOWED_MCP_TOOLS`
   allowlist and expand the structured `query_advisor_recommendations` Python tool with v2-specific
   fields (OperationalExcellence category, metadata improvements).
2. **`containerapps` namespace** — new in v2; add a `query_container_app_health` Python tool
   to the SRE agent for platform self-monitoring (inspect own agent Container App health,
   revision status, scaling events).

Out of scope: `pricing`, `azuremigrate`, `wellarchitectedframework` namespaces (deferred to seed
`.planning/seeds/azure-mcp-v2-agent-enhancements.md`). v3.0.0-beta not to be used.

</domain>

<decisions>
## Implementation Decisions

### Package Upgrade
- Update `services/azure-mcp-server/Dockerfile` ARG `AZURE_MCP_VERSION` from `2.0.0-beta.34` to `2.0.0`
- The npm package is now published under the `microsoft/mcp` repo; package name on npm is `@azure/mcp`
  (confirmed: the npm package name stays `@azure/mcp` even though the repo moved — the registry
  entry was transferred, not renamed). No package name change needed.
- Update CLAUDE.md Azure MCP Server section to reflect new repo `microsoft/mcp`, v2.0.0 GA status
- CI workflow build context is `services/azure-mcp-server/` — no change needed

### advisor Namespace (SRE Agent)
- `advisor.list_recommendations` already in `ALLOWED_MCP_TOOLS` — keep it; it now gets richer
  structured output from v2 (more metadata, OperationalExcellence category support)
- Add `advisor.get_recommendation` to `ALLOWED_MCP_TOOLS` if available in v2 (check namespace)
- Expand `query_advisor_recommendations` to include `OperationalExcellence` as a valid category
  filter (currently accepted but not documented in docstring)
- Update SRE system prompt to mention OperationalExcellence category

### containerapps Namespace (SRE Agent — Self-Monitoring)
- Add new `@ai_function` tool: `query_container_app_health(container_app_name, resource_group)`
  in `agents/sre/tools.py`
- Uses `azure-mgmt-appcontainers` SDK (lazy import pattern, same as other tools)
- Returns: app name, provisioning state, revision name, active revision traffic %, replica count,
  running status, last modified time
- Add `containerapps.list` and `containerapps.get` to `ALLOWED_MCP_TOOLS` if available in v2
- Add `query_container_app_health` to SRE agent's tool list and system prompt

### Claude's Discretion
- Exact MCP tool names for advisor/containerapps namespaces in v2 — verify from v2 tool list
  during implementation and add whatever is available
- Whether to add `azure-mgmt-appcontainers` to SRE requirements.txt or use MCP-only path —
  use SDK path (consistent with other SRE tools, more structured output)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/sre/tools.py` — `query_advisor_recommendations()` already exists (lines 569–690);
  extend with OperationalExcellence category doc update only
- `agents/sre/tools.py` — `_log_sdk_availability()`, `_extract_subscription_id()`,
  `instrument_tool_call()`, lazy import pattern — all reusable for `query_container_app_health`
- `agents/sre/agent.py` — `ALLOWED_MCP_TOOLS` list and `create_sre_agent()` tools=[...] list —
  both need updating
- `services/azure-mcp-server/Dockerfile` — single `ARG AZURE_MCP_VERSION` line to update
- `CLAUDE.md` — Azure MCP Server section needs repo/version update

### Established Patterns
- Tool pattern: `start_time = time.monotonic()` at entry; `duration_ms` in both try/except
- Tool pattern: never raise — return structured error dicts
- Tool pattern: lazy import with `try/except ImportError; X = None` + `_log_sdk_availability()`
- MCP allowlist: explicit string list `ALLOWED_MCP_TOOLS` in `tools.py`, not wildcards
- `@ai_function` decorator on all tool functions exposed to the LLM

### Integration Points
- `agents/sre/tools.py` — add `query_container_app_health` function
- `agents/sre/agent.py` — add to `ALLOWED_MCP_TOOLS`, `tools=[...]`, system prompt
- `agents/sre/requirements.txt` — add `azure-mgmt-appcontainers>=3.0.0`
- `services/azure-mcp-server/Dockerfile` — bump `AZURE_MCP_VERSION`
- `CLAUDE.md` — update Azure MCP Server section

</code_context>

<specifics>
## Specific Ideas

- The `containerapps` self-monitoring use case: an operator asks "why is the compute agent slow?"
  → SRE agent calls `query_container_app_health("ca-compute-prod", "rg-aap-prod")` and returns
  revision status, replica count, and scaling events. This is a concrete demo-able capability.
- MCP v2 security hardening (KQL injection prevention) is automatic — no code changes needed in
  the SRE agent since it uses parameterized MCP tool calls already.
- 1-2s startup improvement is automatic — no Container App config changes needed.

</specifics>

<deferred>
## Deferred Ideas

- `pricing` namespace — not core to AIOps value; no current use case
- `azuremigrate` namespace — relevant only if resource lifecycle tracking enters scope
- `wellarchitectedframework` namespace — useful for governance reviews; not operational
- `3.0.0-beta.1` namespace realignment + MCP protocol v1.1.0 — wait for GA
- (All captured in `.planning/seeds/azure-mcp-v2-agent-enhancements.md`)

</deferred>
