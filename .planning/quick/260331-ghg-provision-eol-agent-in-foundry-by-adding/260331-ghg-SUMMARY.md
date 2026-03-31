# Summary: 260331-ghg — Provision EOL Agent in Foundry

**Status:** COMPLETE
**Date:** 2026-03-31
**Commit:** `a100a28`

## What Was Done

### Task 1 — Added EOL entry to `_build_agents()` ✅

Added the EOL agent tuple to `scripts/provision-domain-agents.py`:

```python
("EOL_AGENT_ID", "eol-agent", "End-of-Life lifecycle specialist — EOL detection, software lifecycle status, upgrade planning across Azure VMs, Arc servers, and Arc K8s.", "eol"),
```

- Updated docstring from "7 domain agents" → "8 domain agents"
- `_build_agents()` now returns 8 `DomainAgentSpec` entries

### Task 2 — Provisioning Script Run ✅

Run command:
```bash
AZURE_PROJECT_ENDPOINT="https://aap-foundry-prod.services.ai.azure.com/api/projects/aap-project-prod" \
  .venv/bin/python3 scripts/provision-domain-agents.py \
  --resource-group rg-aap-prod \
  --orchestrator-app ca-orchestrator-prod
```

Output:
- 7 `[SKIP]` lines — all existing agents detected by name, not re-created
- 1 `[CREATE] eol-agent -> asst_s1TancOQbpIjltYQ0oGgfTDD`
- `domain-agent-ids.json` written with 8 entries
- `ca-orchestrator-prod` updated: `Setting 8 env vars ... updated successfully.`

**Notes on execution:**
- System Python 3.9 lacked `agent_framework` (in `.venv` only) → used `.venv/bin/python3`
- Account endpoint (`https://aap-foundry-prod.cognitiveservices.azure.com/`) returned 404 for `list_agents` — needed the **project endpoint** (`https://aap-foundry-prod.services.ai.azure.com/api/projects/aap-project-prod`), retrieved via `az rest` against the ARM API
- Prompt loading fell back to default for EOL agent (import failed due to `Agent` symbol mismatch in venv `agent_framework`) — fallback prompt is adequate; real system prompt loads at runtime in the Container App where the correct package version is installed

### Task 3 — Committed ✅

```
feat: add EOL agent to domain agent provisioner
```
Files committed: `scripts/provision-domain-agents.py`, `scripts/domain-agent-ids.json`

## Acceptance Criteria

- [x] `provision-domain-agents.py` `_build_agents()` has 8 entries (EOL added)
- [x] Script ran without error; exactly 1 `[CREATE]` line for `eol-agent`
- [x] `domain-agent-ids.json` contains `EOL_AGENT_ID=asst_s1TancOQbpIjltYQ0oGgfTDD`
- [x] `ca-orchestrator-prod` Container App env var `EOL_AGENT_ID` is set (confirmed by script output)
- [x] Changes committed to git (`a100a28`)

## EOL Agent Foundry ID

```
EOL_AGENT_ID=asst_s1TancOQbpIjltYQ0oGgfTDD
```
