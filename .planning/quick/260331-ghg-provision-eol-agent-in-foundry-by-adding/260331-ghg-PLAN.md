# Plan: Provision EOL Agent in Foundry

**ID:** 260331-ghg
**Mode:** quick
**Created:** 2026-03-31

## Context

Phase 12 (EOL Domain Agent) is code-complete, but `domain-agent-ids.json` only has 7 entries
(compute, network, storage, security, sre, arc, patch). The EOL agent has never been provisioned
in Foundry, so `EOL_AGENT_ID` is missing from the orchestrator Container App — EOL incidents
cannot be routed.

**Current state of `domain-agent-ids.json`:** 7 agents provisioned, no `EOL_AGENT_ID` key.

**EOL agent details (from `agents/eol/agent.py`):**
- Prompt constant: `EOL_AGENT_SYSTEM_PROMPT`
- `name` in `create_eol_agent()`: `"eol-agent"`
- Description: `"End-of-Life lifecycle specialist — EOL detection, software lifecycle status, upgrade planning across Azure VMs, Arc servers, and Arc K8s."`
- Module path: `agents.eol.agent`

**Target Container App:** `ca-orchestrator-prod` (default in script).

---

## Tasks

### Task 1 — Add EOL entry to `_build_agents()` in `provision-domain-agents.py`

Add one tuple to the `specs` list in `_build_agents()`, matching the patch-agent pattern
(most recently added):

```python
("EOL_AGENT_ID", "eol-agent", "End-of-Life lifecycle specialist — EOL detection, software lifecycle status, upgrade planning across Azure VMs, Arc servers, and Arc K8s.", "eol"),
```

- `env_var`: `EOL_AGENT_ID`
- `name`: `eol-agent` (must match the `name=` kwarg in `create_eol_agent()` so `list_existing_agents` skip-check works)
- `description`: verbatim from `agent.py`'s `create_eol_agent()` description field
- `domain`: `eol` → `_load_prompt("eol")` will import `agents.eol.agent` and find `EOL_AGENT_SYSTEM_PROMPT`

File: `scripts/provision-domain-agents.py`, line ~63 (after `PATCH_AGENT_ID` tuple, before closing `]`).

**Do NOT touch existing 7 entries** — the script skips agents that already exist by name, so
re-provisioning is safe, but unnecessary churn should be avoided.

---

### Task 2 — Run provisioning script (EOL agent only will be created)

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform

python3 scripts/provision-domain-agents.py \
  --resource-group rg-aap-prod \
  --orchestrator-app ca-orchestrator-prod
```

Expected output:
- 7 `[SKIP]` lines (existing agents)
- 1 `[CREATE] eol-agent -> asst_xxx` line
- `domain-agent-ids.json` updated with `EOL_AGENT_ID` key
- `az containerapp update` sets all 8 env vars on `ca-orchestrator-prod`

If `AZURE_PROJECT_ENDPOINT` is not set in the shell, export it first:

```bash
export AZURE_PROJECT_ENDPOINT="<value from prod-ops.md or Key Vault>"
```

**Verify:** After the script completes, confirm `EOL_AGENT_ID` is present:
```bash
cat scripts/domain-agent-ids.json | python3 -m json.tool
```

---

### Task 3 — Commit the provisioning script change

```bash
git add scripts/provision-domain-agents.py scripts/domain-agent-ids.json
git commit -m "feat: add EOL agent to domain agent provisioner"
```

The `domain-agent-ids.json` update is committed alongside the script change so the
recorded Foundry IDs stay in sync with the codebase.

---

## Acceptance Criteria

- [ ] `provision-domain-agents.py` `_build_agents()` has 8 entries (EOL added)
- [ ] Script runs without error; exactly 1 `[CREATE]` line for `eol-agent`
- [ ] `domain-agent-ids.json` contains `EOL_AGENT_ID` key with a valid `asst_xxx` value
- [ ] `ca-orchestrator-prod` Container App env var `EOL_AGENT_ID` is set (confirmed by script output)
- [ ] Changes committed to git

## What NOT to do

- Do not re-provision any of the 7 existing agents (they already have valid IDs)
- Do not change any orchestrator routing code — Phase 12 already wired EOL routing
- Do not modify `domain-agent-ids.json` by hand — let the script write it
