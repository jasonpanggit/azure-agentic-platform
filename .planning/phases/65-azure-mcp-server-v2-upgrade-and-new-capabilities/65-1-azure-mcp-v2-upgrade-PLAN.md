---
id: 65-1
wave: 1
phase: 65
title: Azure MCP Server v2 Upgrade and New Capabilities
depends_on: []
files_modified:
  - services/azure-mcp-server/Dockerfile
  - agents/sre/tools.py
  - agents/sre/agent.py
  - CLAUDE.md
autonomous: true
---

## Objective

Upgrade Azure MCP Server from `@azure/mcp@2.0.0-beta.34` to `@azure/mcp@2.0.0` GA. Wire `containerapps` namespace tools into the SRE agent for platform self-monitoring. Update CLAUDE.md to reflect v2.0.0 GA status, new namespaces, and the repository move from `Azure/azure-mcp` (archived) to `microsoft/mcp`.

## must_haves

- Dockerfile ARG `AZURE_MCP_VERSION` is set to `2.0.0` (not `2.0.0-beta.34`)
- SRE agent `ALLOWED_MCP_TOOLS` list includes `containerapps.list_apps`, `containerapps.get_app`, and `containerapps.list_revisions`
- SRE agent system prompt mentions Container Apps self-monitoring capability
- CLAUDE.md Azure MCP Server section shows `2.0.0` GA version and includes new namespaces (`containerapps`, `deviceregistry`, `functions`, `azuremigrate`, `policy`, `pricing`, `wellarchitectedframework`)
- CLAUDE.md Summary table shows `2.0.0` for Azure MCP Server

## Tasks

<task id="65-1-T1">
<title>Upgrade Azure MCP Server Dockerfile to v2.0.0 GA</title>
<read_first>
- services/azure-mcp-server/Dockerfile
</read_first>
<action>
In `services/azure-mcp-server/Dockerfile`, change line 13:

FROM:
```
ARG AZURE_MCP_VERSION=2.0.0-beta.34
```

TO:
```
ARG AZURE_MCP_VERSION=2.0.0
```

Also update the top-of-file comment block to reflect v2.0.0 GA status. Change the existing architecture comment to note the upgrade:

```
# Azure MCP Server Container — v2.0.0 GA (microsoft/mcp)
```
</action>
<acceptance_criteria>
- `grep -c "AZURE_MCP_VERSION=2.0.0$" services/azure-mcp-server/Dockerfile` returns `1`
- `grep -c "2.0.0-beta" services/azure-mcp-server/Dockerfile` returns `0`
- `grep -c "v2.0.0 GA" services/azure-mcp-server/Dockerfile` returns `1`
</acceptance_criteria>
</task>

<task id="65-1-T2">
<title>Wire containerapps namespace into SRE agent ALLOWED_MCP_TOOLS</title>
<read_first>
- agents/sre/tools.py
</read_first>
<action>
In `agents/sre/tools.py`, extend the `ALLOWED_MCP_TOOLS` list (currently lines 49-56) to add 3 `containerapps` tools after the existing entries. The updated list should be:

```python
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "applicationinsights.query",
    "advisor.list_recommendations",
    "resourcehealth.get_availability_status",
    "resourcehealth.list_events",
    "containerapps.list_apps",
    "containerapps.get_app",
    "containerapps.list_revisions",
]
```

Also update the module docstring (lines 1-7) to include the new tools in the allowlist comment:

```python
"""SRE Agent tool functions — cross-domain monitoring and remediation proposal wrappers.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics, applicationinsights.query,
    advisor.list_recommendations, resourcehealth.get_availability_status,
    resourcehealth.list_events, containerapps.list_apps, containerapps.get_app,
    containerapps.list_revisions
"""
```
</action>
<acceptance_criteria>
- `grep -c "containerapps.list_apps" agents/sre/tools.py` returns `1`
- `grep -c "containerapps.get_app" agents/sre/tools.py` returns `1`
- `grep -c "containerapps.list_revisions" agents/sre/tools.py` returns `1`
- `grep -c "ALLOWED_MCP_TOOLS" agents/sre/tools.py` returns `1` (still exactly one definition)
- `grep -c "containerapps\." agents/sre/tools.py` returns `3`

Note: `advisor.list_recommendations` is already present in ALLOWED_MCP_TOOLS from v1. The
`advisor.get_recommendation` per-resource detail tool is deferred — exact v2 tool name to
be confirmed against a live v2.0.0 MCP server before adding to allowlist.
</acceptance_criteria>
</task>

<task id="65-1-T3">
<title>Update SRE agent system prompt with containerapps capability</title>
<read_first>
- agents/sre/agent.py
- agents/sre/tools.py
</read_first>
<action>
In `agents/sre/agent.py`, update the `SRE_AGENT_SYSTEM_PROMPT` string to add a Container Apps self-monitoring section after the "Arc Fallback (Phase 2)" section (around line 106) and before "Safety Constraints":

Add this section:

```
## Container Apps Self-Monitoring

You can inspect the platform's own Container Apps infrastructure using MCP tools:
- `containerapps.list_apps` — list all Container Apps in an environment (check replica counts, provisioning state)
- `containerapps.get_app` — get detailed status of a specific Container App (active revision, ingress config, replicas)
- `containerapps.list_revisions` — list revision history for a Container App (traffic weights, active/inactive, creation times)

Use these tools to diagnose platform health issues like "why is agent X slow?" or "is the API gateway healthy?" by checking revision status, replica counts, and provisioning state.
```

No changes to the `create_sre_agent()` function or tool registration — the containerapps tools are MCP tools accessed via the MCP server, not `@ai_function` tools.
</action>
<acceptance_criteria>
- `grep -c "Container Apps Self-Monitoring" agents/sre/agent.py` returns `1`
- `grep -c "containerapps.list_apps" agents/sre/agent.py` returns `1`
- `grep -c "containerapps.get_app" agents/sre/agent.py` returns `1`
- `grep -c "containerapps.list_revisions" agents/sre/agent.py` returns `1`
- `python -c "import ast; ast.parse(open('agents/sre/agent.py').read())"` exits with code 0 (valid Python syntax)
</acceptance_criteria>
</task>

<task id="65-1-T4">
<title>Update CLAUDE.md Azure MCP Server section and version table</title>
<read_first>
- CLAUDE.md
</read_first>
<action>
Make the following updates to `CLAUDE.md`:

**1. Azure MCP Server attribute table (lines 86-92):**

Update the Package and Distribution rows to reflect the repo move and v2.0.0:

```markdown
### Azure MCP Server (GA)
| Attribute | Value |
|---|---|
| **Package** | `@azure/mcp` (npm, run as sidecar) OR invoke via `npx @azure/mcp@latest start` |
| **Distribution** | npm package `@azure/mcp`; also `azmcp` binary. Repository: `microsoft/mcp` (formerly `Azure/azure-mcp`, now archived) |
| **Version** | `2.0.0` |
| **Status** | ✅ **GA** |
| **Authentication** | Entra ID via `DefaultAzureCredential` / managed identity |
```

**2. Covered Services table (lines 93-107):**

Update the header to say `(confirmed in v2.0.0, April 2026)` and add new rows:

After `| Containers | \`acr\` (list) |` add:

```markdown
| Container Apps | `containerapps` (list apps, get app, list revisions) |
| IoT / Device Registry | `deviceregistry` |
| Serverless Functions | `functions` |
| Migration | `azuremigrate` |
| Governance | `policy` (extended) |
| Cost / Pricing | `pricing` |
| Architecture Review | `wellarchitectedframework` |
```

**3. Summary: Versions At a Glance table (line 308):**

Change:
```
| Azure MCP Server | `@azure/mcp` (npm) | GA | ✅ GA |
```
To:
```
| Azure MCP Server | `@azure/mcp` (npm) | `2.0.0` | ✅ GA |
```

**4. Architecture > MCP Surfaces section (line 386):**

Update to mention v2.0.0:
```
- **Azure MCP Server** (v2.0.0 GA) — `ca-azure-mcp-prod`, internal-only Container App; covers ARM, Compute, Storage, Databases, Monitoring, Security, Messaging, Container Apps, Functions
```

**5. Add startup time note to Azure MCP Server attribute table:**

After the `| **Status** | ✅ **GA** |` row, add:
```markdown
| **Startup time** | ~1–2 seconds (down from ~20s in v1 beta) |
```
</action>
<acceptance_criteria>
- `grep -c "microsoft/mcp" CLAUDE.md` returns at least `1`
- `grep -c "Azure/azure-mcp" CLAUDE.md` returns at least `1` (mentioned as "formerly archived")
- `grep -c "confirmed in v2\.0\.0" CLAUDE.md` returns `1`
- `grep -c "containerapps" CLAUDE.md` returns at least `2` (covered services table + architecture section)
- `grep -c "deviceregistry" CLAUDE.md` returns at least `1`
- `grep -c "wellarchitectedframework" CLAUDE.md` returns at least `1`
- The Summary table row for Azure MCP Server contains `2.0.0`
- `grep "Azure MCP Server.*2.0.0" CLAUDE.md` returns at least `1` match
</acceptance_criteria>
</task>
