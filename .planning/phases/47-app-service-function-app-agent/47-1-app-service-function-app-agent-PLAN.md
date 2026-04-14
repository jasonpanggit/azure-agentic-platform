---
id: 47-1
wave: 1
phase: 47
title: App Service + Function App Agent
depends_on: []
files_modified:
  - agents/appservice/__init__.py
  - agents/appservice/agent.py
  - agents/appservice/tools.py
  - agents/appservice/requirements.txt
  - agents/appservice/Dockerfile
  - agents/tests/appservice/__init__.py
  - agents/tests/appservice/test_appservice_tools.py
  - agents/orchestrator/agent.py
autonomous: true
---

# Phase 47 — App Service + Function App Agent

## Goal

Add a new `appservice` domain agent that monitors, diagnoses, and proposes safe
restarts/scaling for Azure App Service plans, Web Apps, and Function Apps.

## Scope

### New Agent: `agents/appservice/`

Six `@ai_function` tools covering the full diagnostic lifecycle:

| Tool | Purpose |
|------|---------|
| `get_app_service_health` | ARM health: site status, plan, SKU, SSL cert expiry, custom domains, worker count |
| `get_app_service_metrics` | Azure Monitor: requests/sec, avg response time, http5xx_rate%, cpu_percent, memory_percent |
| `get_function_app_health` | ARM + KQL: function count, runtime version, invocation count, failure rate, p95 duration, throttle count |
| `query_app_insights_failures` | Log Analytics KQL: top 5 exceptions by count + dependency failures |
| `propose_app_service_restart` | HITL approval proposal — risk_level: low |
| `propose_function_app_scale_out` | HITL approval proposal — risk_level: low |

### Orchestrator Wiring

- Add `"app-service": "appservice_agent"` to `DOMAIN_AGENT_MAP`
- Add `microsoft.web/sites` and `microsoft.web/serverfarms` resource type entries
- Add conversational routing for "app service", "function app", "web app" keywords
- Update tool allowlist in system prompt

### Tests: `agents/tests/appservice/`

40+ pytest tests covering:
- `TestAllowedMcpTools` — entry count, expected entries, no wildcards
- `TestGetAppServiceHealth` — success, error, SDK-missing
- `TestGetAppServiceMetrics` — success, error, SDK-missing
- `TestGetFunctionAppHealth` — success, error, SDK-missing (LAW client)
- `TestQueryAppInsightsFailures` — success, error, SDK-missing
- `TestProposeAppServiceRestart` — always succeeds, approval_required=True
- `TestProposeFunctionAppScaleOut` — always succeeds, approval_required=True

## Conventions (exact match to agents/database pattern)

- Module docstring listing all tools
- Lazy SDK imports with `try/except ImportError → None`
- `@ai_function` decorator on every tool
- `start_time = time.monotonic()` at entry of every tool
- `duration_ms` computed in BOTH try AND except blocks
- Tools NEVER raise — return `{"query_status": "error", "error": str(e), "duration_ms": duration_ms}`
- Use `get_credential()`, `get_agent_identity()`, `instrument_tool_call()`
- `_log_sdk_availability()` called at module level
- `_extract_subscription_id(resource_id)` helper

## Execution Order

1. Create `agents/appservice/__init__.py`
2. Create `agents/appservice/tools.py` (6 tools)
3. Create `agents/appservice/agent.py` (system prompt + factory)
4. Create `agents/appservice/requirements.txt`
5. Create `agents/appservice/Dockerfile`
6. Create `agents/tests/appservice/__init__.py`
7. Create `agents/tests/appservice/test_appservice_tools.py` (40+ tests)
8. Update `agents/orchestrator/agent.py` (DOMAIN_AGENT_MAP + routing)
9. Run tests — verify all pass
10. Commit on branch `gsd/phase-47-appservice-agent`
