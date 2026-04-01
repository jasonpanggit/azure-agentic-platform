# Research — Validate Orchestrator Wiring and Routing
**Task:** 260401-e74
**Date:** 2026-04-01

---

## 1. Domain Agent Registration — Status: COMPLETE ✅

All 8 domain agents are registered in the orchestrator's `DOMAIN_AGENT_MAP` and in the system prompt routing rules:

| Domain | Tool Name in Prompt | `DOMAIN_AGENT_MAP` Key | `provision-domain-agents.py` | `update-domain-agent-prompts.py` |
|---|---|---|---|---|
| compute | `compute_agent` | ✅ | ✅ | ✅ `asst_LRwIRuuMi0vxzfe0sN6Gl7ro` |
| network | `network_agent` | ✅ | ✅ | ✅ `asst_xgfrgpYy3t0tHMz6XtuZSfkt` |
| storage | `storage_agent` | ✅ | ✅ | ✅ `asst_eyJ5bKQLMpuC17sfeZZmwOkI` |
| security | `security_agent` | ✅ | ✅ | ✅ `asst_E3zcct7P9mKHlqcRzU5CGbp4` |
| sre | `sre_agent` | ✅ | ✅ | ✅ `asst_nSWrfRFyGhMqmtgzuWF4GgKH` |
| arc | `arc_agent` | ✅ | ✅ | ✅ `asst_xTN3oTWku0R5Cbxsf56WkEdP` |
| patch | `patch_agent` | ✅ | ✅ | ✅ `asst_XxAMxgwC9NAlKqqN7FLRiA3O` |
| eol | `eol_agent` | ✅ | ✅ | ✅ `asst_s1TancOQbpIjltYQ0oGgfTDD` |

The orchestrator's system prompt tool allowlist is also complete:
```
compute_agent, network_agent, storage_agent, security_agent,
arc_agent, sre_agent, patch_agent, eol_agent, classify_incident_domain
```

**Note:** Connected-agent wiring in Foundry (the actual `asst_xxx` connection) is done at provisioning time via `provision-domain-agents.py`. The orchestrator Python code does NOT reference agent IDs directly — those are registered on the Foundry agent definition itself. The env vars (`COMPUTE_AGENT_ID`, etc.) are set on `ca-orchestrator-prod` but are not read by `orchestrator/agent.py`; they appear to be provisioned for completeness / future use.

---

## 2. MCP Server Wiring — Status: PARTIAL ⚠️

### Azure MCP Server
- **Patch agent** and **EOL agent** both mount `AZURE_MCP_SERVER_URL` via `MCPTool` / `MCPStreamableHTTPTool` respectively.
- **`AZURE_MCP_SERVER_URL` is NOT wired in Terraform** (`agent-apps/main.tf` has no `AZURE_MCP_SERVER_URL` env block, `agent-apps/variables.tf` has no `azure_mcp_server_url` variable for patch/eol).
- **Compute, network, storage, security, sre agents** rely on Azure MCP tools listed in their `ALLOWED_MCP_TOOLS` but do **not** explicitly mount via `MCPTool` in their `agent.py` — the Azure MCP tool access is presumably configured at the Foundry agent level (tool connections), not via `MCPTool` constructor injection.

### Arc MCP Server
- **Arc agent** mounts `ARC_MCP_SERVER_URL` via `MCPTool` — this IS wired in Terraform (`agent-apps/main.tf` lines 211–217, `variables.tf` has `arc_mcp_server_url` variable).
- `ca-arc-mcp-server-prod` Terraform infra code is in `modules/arc-mcp-server/` but operator must still build+push the image and run `terraform apply` (quick task 260331-chg was Terraform-only).

### MCP Tool Inconsistency: EOL Agent Uses Different Tool Class
- **EOL agent** uses `MCPStreamableHTTPTool` (from `agent_framework`) with a different constructor signature (`name=`, `url=`) vs. all other agents that use `MCPTool` from `azure.ai.projects.models` (`server_label=`, `server_url=`).
- This is a **potential bug** — if `MCPStreamableHTTPTool` is the agent-framework class and `MCPTool` is the azure-ai-projects class, the Azure MCP Server may not mount correctly for the EOL agent. The import in `agents/eol/agent.py` is `from agent_framework import Agent, MCPStreamableHTTPTool`, while patch agent uses `from azure.ai.projects.models import MCPTool`.

---

## 3. Routing Logic — Status: SOLID ✅ (with minor gaps)

Routing operates at **two layers**:

### Layer 1 — Foundry Agent System Prompt (LLM routing)
The orchestrator's `ORCHESTRATOR_SYSTEM_PROMPT` contains explicit natural-language routing rules for both structured incidents (Type A) and conversational queries (Type B). Routing is keyword-based in the prompt.

### Layer 2 — Code-based classification (fallback)
`classify_incident_domain()` tool + `shared/routing.py:classify_query_text()` handle structured classification:

- `RESOURCE_TYPE_TO_DOMAIN` maps 13 ARM resource type prefixes → 7 domains (no `sre` entry — correct, it's the catch-all)
- `QUERY_DOMAIN_KEYWORDS` in `shared/routing.py` maps 6 ordered domain entries: arc → patch → eol → compute → network → storage → security (no sre — correct, it's the default fallback)

**Routing priority order is correct:** Arc/patch/eol (specific) before compute/network/storage/security (broad).

### Gap: System Prompt vs. Code Keyword Divergence
The system prompt for conversational routing lists "arc", "hybrid" etc. but does NOT include all keywords from `QUERY_DOMAIN_KEYWORDS`. Examples of keywords in code that are NOT in the system prompt:
- "hybrid server", "hybrid servers", "hybridcompute", "arc machines" → arc
- "hotfix", "kb article", "pending patches", "patch status" → patch
- "software expiry", "version support", "eol status", "lifecycle check" → eol

This is acceptable — the system prompt provides the LLM guidance while code handles programmatic fallback. But they should be kept aligned to prevent LLM routing diverging from code routing.

---

## 4. Env Var Completeness

### Per-container env var matrix:

| Env Var | orchestrator | api-gateway | arc | patch | eol | other agents |
|---|---|---|---|---|---|---|
| `FOUNDRY_ACCOUNT_ENDPOINT` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `AZURE_PROJECT_ENDPOINT` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ORCHESTRATOR_AGENT_ID` | ✅ (dynamic) | ✅ (dynamic) | — | — | — | — |
| `COMPUTE_AGENT_ID` | ✅ (dynamic) | ✅ (dynamic) | — | — | — | — |
| `NETWORK_AGENT_ID` | ✅ | ✅ | — | — | — | — |
| `STORAGE_AGENT_ID` | ✅ | ✅ | — | — | — | — |
| `SECURITY_AGENT_ID` | ✅ | ✅ | — | — | — | — |
| `SRE_AGENT_ID` | ✅ | ✅ | — | — | — | — |
| `ARC_AGENT_ID` | ✅ | ✅ | — | — | — | — |
| `PATCH_AGENT_ID` | ✅ | ✅ | — | — | — | — |
| `EOL_AGENT_ID` | ✅ | ✅ | — | — | — | — |
| `ARC_MCP_SERVER_URL` | — | — | ✅ (dynamic) | — | — | — |
| `AZURE_MCP_SERVER_URL` | — | — | — | ❌ MISSING | ❌ MISSING | — |
| `POSTGRES_DSN` | — | — | — | — | ✅ (dynamic) | — |
| `PGVECTOR_CONNECTION_STRING` | — | ✅ (dynamic) | — | — | — | — |

**Critical gap:** `AZURE_MCP_SERVER_URL` is used by patch agent and EOL agent but is **not declared as a Terraform variable** and **not wired as an env var** in `agent-apps/main.tf`. Both agents have graceful degradation (if URL is empty, MCP is skipped), but Azure MCP tools in those agents' `ALLOWED_MCP_TOOLS` lists are unreachable at runtime.

**Observation:** `orchestrator/agent.py` reads `ORCHESTRATOR_AGENT_ID` only for a log message (line 247) — it does NOT use it for dispatch. The orchestrator's connected-agent tools are wired at the Foundry level, not in Python. The env vars on `ca-orchestrator-prod` are correct but the orchestrator code itself doesn't need them.

---

## 5. Documentation Gaps

### What exists:
- `docs/agents/orchestrator-agent.spec.md` — covers Phase 2 concepts (HandoffOrchestrator, 6 domains) but is **stale**: still references Phase 2 routing with 6 domains (no patch/eol), still references `HandoffOrchestrator` class (not used in current code), references example flows that predate the current ChatAgent/connected-agent pattern.
- Domain agent spec files exist for all 8 domains in `docs/agents/`.

### What is missing:
1. **No routing flow doc** — no document explains the full end-to-end flow: API gateway → orchestrator → domain agent → MCP server. This is the most actionable gap.
2. **`orchestrator-agent.spec.md` is stale** — needs updating for patch/eol domains, connected-agent pattern, and current routing logic.
3. **No `agents/orchestrator/README.md`** — nothing close to the agent container to explain the wiring.
4. **No MCP wiring doc** — which agents mount which MCP servers, what tools are exposed, what env vars configure them.

### Recommended doc location:
- `agents/orchestrator/README.md` — routing logic, env vars, flow diagram
- OR `docs/agents/orchestrator-agent.spec.md` updated to current state (already exists, preferred)

---

## 6. Wiring Gaps and Bugs — Summary

| # | Severity | Description |
|---|---|---|
| G-01 | **HIGH** | `AZURE_MCP_SERVER_URL` not wired in Terraform for patch and EOL agents — Azure MCP tools in `ALLOWED_MCP_TOOLS` are unreachable at runtime. Both agents degrade gracefully but silently. |
| G-02 | **MEDIUM** | EOL agent uses `MCPStreamableHTTPTool` (agent_framework class) while patch/arc agents use `MCPTool` (azure.ai.projects.models class). Constructor signatures differ (`name`/`url` vs `server_label`/`server_url`). Risk: wrong tool class or API mismatch at runtime. |
| G-03 | **MEDIUM** | `orchestrator-agent.spec.md` is stale — references 6-domain routing (pre-patch/eol), `HandoffOrchestrator`, and Phase 2 example flows. Misleads readers about current behavior. |
| G-04 | **LOW** | System prompt routing keywords and `QUERY_DOMAIN_KEYWORDS` in `shared/routing.py` are not fully aligned — code has more specific keywords than the prompt. Not a functional bug (both route correctly) but creates maintenance drift risk. |
| G-05 | **LOW** | `orchestrator/agent.py` reads `ORCHESTRATOR_AGENT_ID` env var only for a log message — the variable has no runtime effect on routing. This is expected (Foundry wires it), but a comment should make this explicit so future devs don't assume it drives dispatch. |
| G-06 | **INFO** | `microsoft.lifecycle` entry in `RESOURCE_TYPE_TO_DOMAIN` maps to `eol` — this is a synthetic prefix, not an actual Azure ARM type. It's correct intent but documents a made-up resource type that will never match real ARM resource IDs. Consider removing or documenting as intentional. |

---

## Actionable Gap List (Prioritized)

1. **[HIGH] Wire `AZURE_MCP_SERVER_URL` in Terraform** for patch and eol agents (`agent-apps/variables.tf` + `main.tf`). This is Phase 14 M1 work (backlog item GAP-001–004).
2. **[MEDIUM] Investigate EOL agent MCP tool class** — confirm `MCPStreamableHTTPTool` from `agent_framework` is the correct class or switch to `MCPTool` from `azure.ai.projects.models` for consistency.
3. **[MEDIUM] Update `orchestrator-agent.spec.md`** — add patch/eol domains, replace HandoffOrchestrator references with connected-agent pattern, update example flows.
4. **[LOW] Add comment in orchestrator/agent.py** explaining that `ORCHESTRATOR_AGENT_ID` is used for logging only — actual dispatch wiring is at the Foundry agent level.
5. **[LOW] Add `agents/orchestrator/README.md`** (or update spec) documenting the routing flow end-to-end with env var table.
