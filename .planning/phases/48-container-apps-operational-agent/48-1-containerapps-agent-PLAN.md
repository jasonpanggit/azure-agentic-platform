# Phase 48-1: Container Apps Operational Agent — PLAN

## Goal
Add Container Apps self-monitoring and operational diagnostics. The Container Apps
Agent covers all `microsoft.app/containerapps` and `microsoft.app/managedenvironments`
resources across monitored subscriptions, including the platform's own agent containers.

## Scope
- `agents/containerapps/__init__.py` — package marker
- `agents/containerapps/tools.py` — 6 `@ai_function` tools
- `agents/containerapps/agent.py` — system prompt + factory functions
- `agents/containerapps/requirements.txt` — dependencies
- `agents/containerapps/Dockerfile` — container image
- `agents/tests/containerapps/__init__.py` — test package marker
- `agents/tests/containerapps/test_containerapps_tools.py` — 36+ unit tests
- `agents/orchestrator/agent.py` — wire `container-apps` domain + resource types

## Tools

| Tool | SDK | HITL? |
|------|-----|-------|
| `list_container_apps` | `azure-mgmt-appcontainers` | No |
| `get_container_app_health` | `azure-mgmt-appcontainers` | No |
| `get_container_app_metrics` | `azure-monitor-query` | No |
| `get_container_app_logs` | `azure-monitor-query` (KQL) | No |
| `propose_container_app_scale` | n/a — HITL proposal only | Yes (low) |
| `propose_container_app_revision_activate` | n/a — HITL proposal only | Yes (medium) |

## Conventions
- Follow `agents/appservice/tools.py` exactly: lazy SDK imports, never-raise, `duration_ms`
  in both `try` and `except`, `@ai_function`, `instrument_tool_call`, `get_credential`,
  `get_agent_identity`

## Orchestrator Wiring
- Add `"container-apps"` → `"containerapps_agent"` to `DOMAIN_AGENT_MAP`
- Add `"microsoft.app/containerapps"` and `"microsoft.app/managedenvironments"` to
  `RESOURCE_TYPE_TO_DOMAIN`
- Add natural-language keywords to system prompt routing rules
- Add `"containerapps"` to `_A2A_DOMAINS`

## Test Plan
- 36+ unit tests covering success, error, and SDK-missing paths for every tool
- HITL tools: approval_required, risk_level, proposal_type, all_fields_present,
  proposed_action content, reason preserved, reversibility text

## Tasks
- [ ] Create planning PLAN.md
- [ ] Implement `agents/containerapps/tools.py`
- [ ] Implement `agents/containerapps/agent.py`
- [ ] Update `agents/containerapps/__init__.py`
- [ ] Update `agents/containerapps/requirements.txt`
- [ ] Verify `agents/containerapps/Dockerfile` (already correct)
- [ ] Implement `agents/tests/containerapps/__init__.py`
- [ ] Implement `agents/tests/containerapps/test_containerapps_tools.py`
- [ ] Update `agents/orchestrator/agent.py`
- [ ] Run tests — all pass
- [ ] Create SUMMARY.md
- [ ] Commit
