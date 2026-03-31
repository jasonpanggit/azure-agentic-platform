# Plan: Fix Orchestrator Domain Agent Routing

**ID:** 260331-ize
**Date:** 2026-03-31
**Mode:** quick
**Status:** READY

## Problem Summary

Three bugs prevent the orchestrator from routing to domain agents:

| # | Severity | Bug |
|---|----------|-----|
| 1 | Critical | Orchestrator has no `connected_agent` tools registered on the Foundry assistant — it answers from its own knowledge |
| 2 | Critical | `*_AGENT_ID` env vars not set on `ca-orchestrator-prod` Container App — Terraform wired them but the `az containerapp update` step from the last run only targeted `ca-orchestrator-prod`, not the provisioned agent IDs |
| 3 | Minor | `scripts/update-domain-agent-prompts.py` AGENT_MAP missing EOL entry |

## Root Cause Analysis

### Bug 1 — No connected_agent tools on orchestrator
`agents/orchestrator/agent.py` `create_orchestrator()` only registers `[classify_incident_domain]` as a Python-side tool — it does **not** call `client.update_agent(tools=[{"type": "connected_agent", ...}])` to register domain agents on the Foundry assistant definition. The `DOMAIN_AGENT_MAP` dict exists only for Python routing logic context — the actual Foundry wiring was never done.

The `configure-orchestrator.py` script handles MCP tools via direct REST but has no connected_agent logic. `provision-domain-agents.py` creates agents and sets env vars on `ca-orchestrator-prod` but never calls the Foundry API to register them as tools on the orchestrator assistant.

### Bug 2 — Env vars not on ca-orchestrator-prod
`domain-agent-ids.json` has all 8 IDs from the last provisioning run. The `provision-domain-agents.py` script's `set_container_app_env_vars()` call apparently ran but the env vars are not present (previous quick task 260331-ghg only verified EOL_AGENT_ID was set; full set not confirmed). The wire script will set all 8 idempotently.

### Bug 3 — EOL missing from update-domain-agent-prompts.py
`AGENT_MAP` has 7 entries (compute, network, storage, security, sre, arc, patch) — EOL (`asst_s1TancOQbpIjltYQ0oGgfTDD`, `EOL_AGENT_SYSTEM_PROMPT`) is absent.

## Key Facts

- **Orchestrator agent ID:** read from `ORCHESTRATOR_AGENT_ID` env var (not hardcoded)
- **Domain agent IDs:** all 8 in `scripts/domain-agent-ids.json`
- **SDK to use:** `azure.ai.agents.AgentsClient` (same pattern as all other scripts — `auth.py` uses it, `provision-domain-agents.py` uses it)
- **connected_agent tool format:** `{"type": "connected_agent", "id": "<asst_xxx>", "name": "<tool_name>"}` — the `name` must match what the orchestrator system prompt calls (e.g., `"compute_agent"`, `"eol_agent"`)
- **Tool name mapping:** `DOMAIN_AGENT_MAP` in `agent.py` has the canonical env_var→tool_name mapping; `domain-agent-ids.json` keys map as: `COMPUTE_AGENT_ID` → `"compute_agent"`, etc.
- **MCP tools must be preserved:** `configure-orchestrator.py` shows the orchestrator may already have MCP tools. The wire script must read current tools and append connected_agent entries (not replace all tools).
- **Existing `configure-orchestrator.py`:** handles instructions + MCP but not connected_agent tools; extend via a new `--wire-domain-agents` flag or a new standalone script. A standalone script is cleaner.

## Tasks

### Task 1 — Fix Bug 3: Add EOL to `update-domain-agent-prompts.py`
**File:** `scripts/update-domain-agent-prompts.py`
**Change:** Add `"eol": ("asst_s1TancOQbpIjltYQ0oGgfTDD", "EOL_AGENT_SYSTEM_PROMPT")` to `AGENT_MAP`

```python
AGENT_MAP = {
    "compute":  ("asst_LRwIRuuMi0vxzfe0sN6Gl7ro", "COMPUTE_AGENT_SYSTEM_PROMPT"),
    "network":  ("asst_xgfrgpYy3t0tHMz6XtuZSfkt", "NETWORK_AGENT_SYSTEM_PROMPT"),
    "storage":  ("asst_eyJ5bKQLMpuC17sfeZZmwOkI", "STORAGE_AGENT_SYSTEM_PROMPT"),
    "security": ("asst_E3zcct7P9mKHlqcRzU5CGbp4", "SECURITY_AGENT_SYSTEM_PROMPT"),
    "sre":      ("asst_nSWrfRFyGhMqmtgzuWF4GgKH", "SRE_AGENT_SYSTEM_PROMPT"),
    "arc":      ("asst_xTN3oTWku0R5Cbxsf56WkEdP", "ARC_AGENT_SYSTEM_PROMPT"),
    "patch":    ("asst_XxAMxgwC9NAlKqqN7FLRiA3O", "PATCH_AGENT_SYSTEM_PROMPT"),
    "eol":      ("asst_s1TancOQbpIjltYQ0oGgfTDD", "EOL_AGENT_SYSTEM_PROMPT"),  # ADD THIS
}
```

No trailing newline issue to fix — file already ends with `\n` (line 94 is `    main()`).

---

### Task 2 — Fix Bugs 1 + 2: Create `scripts/wire-domain-agents.py`

**New file:** `scripts/wire-domain-agents.py`

This script does three things atomically and idempotently:

1. **Read** `domain-agent-ids.json` for the 8 domain agent IDs
2. **Foundry API** — register all 8 as `connected_agent` tools on the orchestrator assistant (preserving any existing MCP tools, using read-then-patch pattern)
3. **Container App** — set all 8 `*_AGENT_ID` env vars on `ca-orchestrator-prod`

**Tool name derivation:**
```
COMPUTE_AGENT_ID  → "compute_agent"
NETWORK_AGENT_ID  → "network_agent"
STORAGE_AGENT_ID  → "storage_agent"
SECURITY_AGENT_ID → "security_agent"
SRE_AGENT_ID      → "sre_agent"
ARC_AGENT_ID      → "arc_agent"
PATCH_AGENT_ID    → "patch_agent"
EOL_AGENT_ID      → "eol_agent"
```
(Strip `_AGENT_ID` suffix, lowercase, append `_agent`)

**Idempotency logic:**
- Fetch current orchestrator tools via `client.get_agent(agent_id)`
- Filter out any existing `connected_agent` type tools (stale registrations)
- Keep all non-`connected_agent` tools (MCP, function tools)
- Build new connected_agent tool list from `domain-agent-ids.json`
- Call `client.update_agent(tools=merged_tools)`

**connected_agent tool SDK format** (from azure-ai-agents SDK):
```python
from azure.ai.agents.models import ConnectedAgentDetails, ConnectedAgentToolDefinition

# Build one ConnectedAgentToolDefinition per domain agent:
tool = ConnectedAgentToolDefinition(
    connected_agent=ConnectedAgentDetails(
        id=agent_id,
        name=tool_name,  # e.g. "compute_agent"
        description=description,
    )
)
```
If the SDK models aren't available (version mismatch), fall back to raw dict via direct REST (same pattern as `add_mcp_tools()` in configure-orchestrator.py).

**Script interface:**
```
python3 scripts/wire-domain-agents.py [--dry-run] [--resource-group rg-aap-prod] [--orchestrator-app ca-orchestrator-prod]
```

**Environment variables required:**
- `AZURE_PROJECT_ENDPOINT` or `FOUNDRY_ACCOUNT_ENDPOINT`
- `ORCHESTRATOR_AGENT_ID`

---

### Task 3 — Run the wire script against prod

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
source .venv/bin/activate  # or whatever venv name

# Dry run first
python3 scripts/wire-domain-agents.py --dry-run

# Execute
python3 scripts/wire-domain-agents.py \
    --resource-group rg-aap-prod \
    --orchestrator-app ca-orchestrator-prod

# Verify
python3 scripts/configure-orchestrator.py --show
```

**Verification criteria:**
- `configure-orchestrator.py --show` prints 8+ tools including `connected_agent` entries for all domains
- `az containerapp show --name ca-orchestrator-prod --resource-group rg-aap-prod --query "properties.template.containers[0].env"` shows all 8 `*_AGENT_ID` vars

---

## Execution Order

```
Task 1  →  Task 2  →  Task 3
(fix file)  (new script)  (run it)
```

Tasks 1 and 2 are independent code changes; Task 3 depends on Task 2.

## Files Changed

| File | Change |
|------|--------|
| `scripts/update-domain-agent-prompts.py` | Add EOL entry to AGENT_MAP |
| `scripts/wire-domain-agents.py` | New script (create) |

## Risk

- **MCP tool preservation:** If `get_agent()` returns tools in a format that makes filtering tricky, the script must handle both SDK model objects and raw dicts gracefully. Print current tool types before patching for visibility.
- **connected_agent SDK support:** `azure-ai-agents` 1.1.0 stable may not expose `ConnectedAgentToolDefinition` — fall back to raw REST identical to `add_mcp_tools()` pattern if import fails.
- **ca-orchestrator-prod restart:** `az containerapp update --set-env-vars` triggers a revision; expect ~30s for new revision to become active.
