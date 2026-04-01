# Orchestrator Agent

> **Note:** `docs/agents/orchestrator-agent.spec.md` is the Phase 2 design spec and is now superseded by this document. It references `HandoffOrchestrator` (removed) and a 6-domain routing model (pre-patch/eol). Treat this README as the authoritative reference for the current implementation.

---

## Overview

The Orchestrator is a `ChatAgent` (Microsoft Agent Framework) with a single Python tool: `classify_incident_domain`. It receives all chat and incident requests from the API gateway, determines which domain specialist should handle them, and delegates via **connected-agent tools** registered on the Foundry agent definition. The orchestrator itself never queries Azure resources or proposes remediations — all resource access is performed by the domain agents it routes to.

---

## Request Flow

```
Web UI / Microsoft Teams
    │
    │  HTTP POST /api/v1/chat  (SSE stream, bearer token)
    ▼
API Gateway  (ca-api-gateway-prod)
    │
    │  Foundry Responses API
    │  thread_id=<session>, agent_id=ORCHESTRATOR_AGENT_ID
    ▼
Orchestrator Agent  (ca-orchestrator-prod — Foundry Hosted Agent)
    │
    │  Layer 1: LLM routing via ORCHESTRATOR_SYSTEM_PROMPT (natural language rules)
    │  Layer 2: classify_incident_domain() Python tool (prefix + keyword fallback)
    │
    │  connected-agent tool call (Foundry wiring, not Python code)
    ▼
Domain Agent  (one of 8 — see table below)
    │
    ├─ @ai_function tools  (ARG, Log Analytics, Resource Health, etc.)
    └─ MCP tools           (Azure MCP Server or Arc MCP Server)
    │
    │  Response streams back up the chain
    ▼
SSE token stream → browser / Teams
```

**Key architectural note:** The orchestrator's connected-agent tool registrations live in the Foundry agent definition, provisioned by `scripts/provision-domain-agents.py`. The Python code in `agent.py` does NOT reference domain agent IDs directly. The `*_AGENT_ID` env vars on `ca-orchestrator-prod` are set for completeness and logging only — they have no effect on runtime routing.

---

## Domain Agent Map

| Domain | Connected-Agent Tool | Env Var (agent ID) | Routing Keywords (sample) | MCP Surface |
|--------|---------------------|--------------------|--------------------------|-------------|
| `compute` | `compute_agent` | `COMPUTE_AGENT_ID` | vm, virtual machine, aks, cpu, disk, scale set | Azure MCP (Foundry tool connection) |
| `network` | `network_agent` | `NETWORK_AGENT_ID` | network, vnet, nsg, load balancer, dns, firewall | Azure MCP (Foundry tool connection) |
| `storage` | `storage_agent` | `STORAGE_AGENT_ID` | storage, blob, file share, datalake, queue | Azure MCP (Foundry tool connection) |
| `security` | `security_agent` | `SECURITY_AGENT_ID` | defender, key vault, rbac, identity, certificate | Azure MCP (Foundry tool connection) |
| `arc` | `arc_agent` | `ARC_AGENT_ID` | arc, arc-enabled, hybrid, connected cluster, hybridcompute | Arc MCP (`ARC_MCP_SERVER_URL`) |
| `patch` | `patch_agent` | `PATCH_AGENT_ID` | patch, patching, update manager, missing patches, hotfix, kb article | Azure MCP (`AZURE_MCP_SERVER_URL`) |
| `eol` | `eol_agent` | `EOL_AGENT_ID` | end of life, eol, unsupported version, lifecycle, software expiry, version support | Azure MCP (`AZURE_MCP_SERVER_URL`) |
| `sre` | `sre_agent` | `SRE_AGENT_ID` | cross-domain, reliability, sla, latency, availability — **catch-all** | Azure MCP (Foundry tool connection) |

---

## Routing Logic — Two Layers

### Layer 1: LLM Routing (primary)

The `ORCHESTRATOR_SYSTEM_PROMPT` contains explicit natural-language routing rules for:

- **Type A — Structured JSON incidents** from the detection plane: use the `domain` field if present; call `classify_incident_domain` if absent or ambiguous.
- **Type B — Operator conversational queries**: route by topic keywords; preserve the operator's original message verbatim when calling the domain agent.

### Layer 2: Code-Based Classification (fallback)

`classify_incident_domain()` + `shared/routing.py:classify_query_text()` handle programmatic classification when the LLM defers or when a structured incident has no `domain` field.

**Priority order for code classification (most-specific first):**

```
arc → patch → eol → compute → network → storage → security → sre (catch-all)
```

- **`RESOURCE_TYPE_TO_DOMAIN`** maps 13 ARM resource type prefixes to 7 domains (`sre` is not in the map — it is the default when no prefix matches).
- **`QUERY_DOMAIN_KEYWORDS`** scans 7 domain keyword lists in the priority order above; tiebreak (equal vote count) falls to `sre`.

> **Note on `microsoft.lifecycle`:** This entry in `RESOURCE_TYPE_TO_DOMAIN` maps to `eol`. It is a synthetic prefix — no real Azure ARM resource type matches it. It is kept as a future-signal placeholder for Arc-related lifecycle events.

---

## MCP Server Mounting

| Agent | MCP Server Used | How Mounted | Env Var |
|-------|----------------|-------------|---------|
| compute, network, storage, security, sre | Azure MCP Server (`@azure/mcp`) | Foundry agent tool connection (provisioning time) | n/a — wired at Foundry level |
| `arc` | Custom Arc MCP Server | `MCPTool` from `azure.ai.projects.models` (`server_label=`, `server_url=`) | `ARC_MCP_SERVER_URL` |
| `patch` | Azure MCP Server | `MCPTool` from `azure.ai.projects.models` (`server_label=`, `server_url=`) | `AZURE_MCP_SERVER_URL` |
| `eol` | Azure MCP Server | `MCPStreamableHTTPTool` from `agent_framework` (`name=`, `url=`) | `AZURE_MCP_SERVER_URL` |

**Graceful degradation:** All three Python-mounted agents check that the URL env var is non-empty before constructing the tool object. If empty, MCP tools are silently skipped and only the `@ai_function` Python tools are registered. No startup error is raised.

**G-02 note:** The EOL agent uses `MCPStreamableHTTPTool` (agent_framework class) while patch and arc agents use `MCPTool` (azure.ai.projects.models class). The constructor signatures differ (`name`/`url` vs `server_label`/`server_url`). See comment in `agents/eol/agent.py` above the `MCPStreamableHTTPTool` instantiation for details and the pending verification TODO.

---

## Required Env Vars — Operator Checklist

| Variable | Container(s) | Required? | Notes |
|----------|--------------|-----------|-------|
| `AZURE_PROJECT_ENDPOINT` | all | ✅ Yes | Foundry project endpoint URL |
| `FOUNDRY_ACCOUNT_ENDPOINT` | all | ✅ Yes | Foundry account endpoint URL |
| `ORCHESTRATOR_AGENT_ID` | api-gateway, orchestrator | ✅ Yes | Used by api-gateway to dispatch requests; orchestrator reads it only for log messages — actual connected-agent routing is wired at the Foundry agent definition level |
| `COMPUTE_AGENT_ID` | orchestrator, api-gateway | Set at provisioning | Set by `scripts/provision-domain-agents.py` |
| `NETWORK_AGENT_ID` | orchestrator, api-gateway | Set at provisioning | Set by `scripts/provision-domain-agents.py` |
| `STORAGE_AGENT_ID` | orchestrator, api-gateway | Set at provisioning | Set by `scripts/provision-domain-agents.py` |
| `SECURITY_AGENT_ID` | orchestrator, api-gateway | Set at provisioning | Set by `scripts/provision-domain-agents.py` |
| `SRE_AGENT_ID` | orchestrator, api-gateway | Set at provisioning | Set by `scripts/provision-domain-agents.py` |
| `ARC_AGENT_ID` | orchestrator, api-gateway | Set at provisioning | Set by `scripts/provision-domain-agents.py` |
| `PATCH_AGENT_ID` | orchestrator, api-gateway | Set at provisioning | Set by `scripts/provision-domain-agents.py` |
| `EOL_AGENT_ID` | orchestrator, api-gateway | Set at provisioning | Set by `scripts/provision-domain-agents.py` |
| `ARC_MCP_SERVER_URL` | arc | Optional | Enables Arc MCP tools; graceful skip if empty. Set to `ca-arc-mcp-server-prod` internal URL after image is built and deployed. |
| `AZURE_MCP_SERVER_URL` | patch, eol | Optional | Enables Azure MCP tools for patch and EOL agents; graceful skip if empty. Set to the Container App URL where `@azure/mcp` runs. Wired via Terraform `azure_mcp_server_url` variable. |
| `POSTGRES_DSN` | eol | Optional | PostgreSQL DSN for EOL cache (24 h TTL); graceful skip if empty |
| `PGVECTOR_CONNECTION_STRING` | api-gateway | Optional | PostgreSQL + pgvector for runbook RAG search; 503 returned if empty and runbook search is called |

---

## Known Limitations

1. **`ORCHESTRATOR_AGENT_ID` on `ca-orchestrator-prod` is logging-only.** The orchestrator agent reads this env var in one log line (`agent.py`) but does not use it for dispatch. The actual connected-agent tool registrations are set on the Foundry agent definition at provisioning time. Do not assume changing this env var re-routes traffic.

2. **EOL agent MCP tool class differs from patch/arc.** `MCPStreamableHTTPTool` (agent_framework) vs `MCPTool` (azure.ai.projects.models) — see G-02 comment in `agents/eol/agent.py`. Needs prod verification before this discrepancy can be resolved.

3. **Connected-agent wiring requires re-provisioning after agent ID changes.** If a domain agent is re-created in Foundry (new `asst_xxx` ID), `scripts/provision-domain-agents.py` must be re-run to update the connected-agent tool registrations on the orchestrator Foundry agent definition. Terraform env vars alone are not sufficient.

4. **`microsoft.lifecycle` is a synthetic ARM prefix.** No real Azure ARM resource type matches this prefix. It is retained in `RESOURCE_TYPE_TO_DOMAIN` as a forward-compatibility signal for future Arc lifecycle events.

---

## Related Files

| File | Purpose |
|------|---------|
| `agents/orchestrator/agent.py` | Orchestrator `ChatAgent` implementation, `classify_incident_domain` tool |
| `agents/shared/routing.py` | `RESOURCE_TYPE_TO_DOMAIN`, `QUERY_DOMAIN_KEYWORDS`, `classify_query_text()` |
| `scripts/provision-domain-agents.py` | Provisions all 8 domain agents in Foundry and registers connected-agent tools on orchestrator |
| `scripts/update-domain-agent-prompts.py` | Updates system prompts on all domain agents in Foundry |
| `terraform/modules/agent-apps/` | Container App definitions for all agents including env var wiring |
| `docs/agents/orchestrator-agent.spec.md` | Phase 2 design spec — **superseded by this README** |
