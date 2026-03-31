# Summary: Fix Orchestrator Domain Agent Routing

**ID:** 260331-ize
**Date:** 2026-03-31
**Status:** COMPLETE

## What Was Done

### Task 1 — Bug 3: EOL entry added to `update-domain-agent-prompts.py`
Added `"eol": ("asst_s1TancOQbpIjltYQ0oGgfTDD", "EOL_AGENT_SYSTEM_PROMPT")` to `AGENT_MAP` — the script now covers all 8 domain agents instead of 7.

### Task 2 — Bugs 1+2: Created `scripts/wire-domain-agents.py`
New idempotent script that:
- Reads all 8 agent IDs from `scripts/domain-agent-ids.json`
- Fetches current orchestrator tools, drops stale `connected_agent` entries, preserves `function`/MCP tools
- Registers all 8 domains as `ConnectedAgentToolDefinition` objects on the Foundry orchestrator assistant
- Sets all 8 `*_AGENT_ID` env vars + `ORCHESTRATOR_AGENT_ID` on `ca-orchestrator-prod`
- Supports `--dry-run`, `--no-deploy`, `--resource-group`, `--orchestrator-app`, `--orchestrator-agent-id`

### Task 3 — Script executed against prod
Orchestrator agent ID discovered: `asst_NeBVjCA5isNrIERoGYzRpBTu` (name: `AAP Orchestrator`)

**Dry run output:** showed 7 stale `connected_agent` tools to drop, 1 `function` tool to preserve, 8 new tools to register, 9 env vars to set.

**Live run:** succeeded on first attempt.

## Verification Results

### Foundry tool state (`configure-orchestrator.py --show`)
```
ID: asst_NeBVjCA5isNrIERoGYzRpBTu
Name: AAP Orchestrator
Model: gpt-4o
Instructions: 3676 chars
Tools: 9 configured
  [function]          classify_incident_domain
  [connected_agent]   compute_agent  → asst_LRwIRuuMi0vxzfe0sN6Gl7ro
  [connected_agent]   network_agent  → asst_xgfrgpYy3t0tHMz6XtuZSfkt
  [connected_agent]   storage_agent  → asst_eyJ5bKQLMpuC17sfeZZmwOkI
  [connected_agent]   security_agent → asst_E3zcct7P9mKHlqcRzU5CGbp4
  [connected_agent]   sre_agent      → asst_nSWrfRFyGhMqmtgzuWF4GgKH
  [connected_agent]   arc_agent      → asst_xTN3oTWku0R5Cbxsf56WkEdP
  [connected_agent]   patch_agent    → asst_XxAMxgwC9NAlKqqN7FLRiA3O
  [connected_agent]   eol_agent      → asst_s1TancOQbpIjltYQ0oGgfTDD
```

### Container App env vars (`az containerapp show`)
All 9 env vars confirmed on `ca-orchestrator-prod`:
```
COMPUTE_AGENT_ID       asst_LRwIRuuMi0vxzfe0sN6Gl7ro
NETWORK_AGENT_ID       asst_xgfrgpYy3t0tHMz6XtuZSfkt
STORAGE_AGENT_ID       asst_eyJ5bKQLMpuC17sfeZZmwOkI
SECURITY_AGENT_ID      asst_E3zcct7P9mKHlqcRzU5CGbp4
SRE_AGENT_ID           asst_nSWrfRFyGhMqmtgzuWF4GgKH
ARC_AGENT_ID           asst_xTN3oTWku0R5Cbxsf56WkEdP
PATCH_AGENT_ID         asst_XxAMxgwC9NAlKqqN7FLRiA3O
EOL_AGENT_ID           asst_s1TancOQbpIjltYQ0oGgfTDD
ORCHESTRATOR_AGENT_ID  asst_NeBVjCA5isNrIERoGYzRpBTu
```

## Files Changed

| File | Change |
|------|--------|
| `scripts/update-domain-agent-prompts.py` | Added EOL entry to AGENT_MAP |
| `scripts/wire-domain-agents.py` | New script (created) |

## Commit

`d9a58b5` — feat: wire domain agents to orchestrator as connected_agent tools

## Remaining Blockers

The orchestrator routing is now fully wired. The remaining chat blocker is:

- **F-01**: `Azure AI Developer` RBAC still missing on Foundry for `ca-api-gateway-prod` managed identity `69e05934-...` — the API gateway needs this role to call the orchestrator Foundry thread API. Wire script sets env vars on `ca-orchestrator-prod`; the gateway itself also needs `ORCHESTRATOR_AGENT_ID` set (or reads from its own env).

To set `ORCHESTRATOR_AGENT_ID` on the **API gateway** too:
```bash
az containerapp update --name ca-api-gateway-prod --resource-group rg-aap-prod \
  --set-env-vars "ORCHESTRATOR_AGENT_ID=asst_NeBVjCA5isNrIERoGYzRpBTu"
```
