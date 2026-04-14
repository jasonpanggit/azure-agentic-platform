---
id: 47-1
phase: 47
title: App Service + Function App Agent
status: complete
tests_passed: 38
tests_failed: 0
---

# Phase 47 Summary — App Service + Function App Agent

## What Was Built

A new `appservice` domain agent with 6 `@ai_function` tools, full test coverage,
Dockerfile, and orchestrator wiring.

## Files Created

| File | Purpose |
|------|---------|
| `agents/appservice/__init__.py` | Package marker |
| `agents/appservice/tools.py` | 6 `@ai_function` tools |
| `agents/appservice/agent.py` | System prompt + `create_appservice_agent()` + `create_appservice_agent_version()` |
| `agents/appservice/requirements.txt` | `azure-mgmt-web>=7.3.0`, `azure-mgmt-monitor>=6.0.2`, `azure-monitor-query>=1.4.0` |
| `agents/appservice/Dockerfile` | Follows `agents/database/Dockerfile` pattern exactly |
| `agents/tests/appservice/__init__.py` | Test package marker |
| `agents/tests/appservice/test_appservice_tools.py` | 38 tests across 6 tool classes |

## Files Modified

| File | Change |
|------|--------|
| `agents/orchestrator/agent.py` | Added `"app-service": "appservice_agent"` to `DOMAIN_AGENT_MAP`; added `microsoft.web/sites` + `microsoft.web/serverfarms` to `RESOURCE_TYPE_TO_DOMAIN`; added App Service conversational routing keywords; updated tool allowlist; added `appservice` to `_A2A_DOMAINS` |

## Tools Implemented

| Tool | Code | Description |
|------|------|-------------|
| `get_app_service_health` | AS-WEB-001 | ARM: state, plan, SKU, SSL cert expiry, custom domains, worker count |
| `get_app_service_metrics` | AS-WEB-002 | Monitor: requests/sec, avg response time, http5xx_rate%, cpu%, memory% |
| `get_function_app_health` | AS-FUNC-001 | ARM + Monitor: runtime version, function count, invocations, failure rate, p95 ms, throttles |
| `query_app_insights_failures` | AS-AI-001 | Log Analytics KQL: top 5 exceptions + dependency failures |
| `propose_app_service_restart` | AS-REMEDI-001 | HITL proposal — `approval_required: True`, `risk_level: "low"` |
| `propose_function_app_scale_out` | AS-REMEDI-002 | HITL proposal — `approval_required: True`, `risk_level: "low"` |

## Test Results

```
38 passed, 0 failed, 1 warning (urllib3/LibreSSL — pre-existing env issue)
```

### Coverage by class

| Test Class | Tests | Focus |
|-----------|-------|-------|
| `TestAllowedMcpTools` | 4 | Entry count, expected names, no wildcards, type |
| `TestGetAppServiceHealth` | 5 | Success, error, SDK-missing, domain filtering, null plan |
| `TestGetAppServiceMetrics` | 5 | Computed rates, error, SDK-missing, zero requests, default hours |
| `TestGetFunctionAppHealth` | 5 | Success, error, SDK-missing, zero invocations, Monitor soft-fail |
| `TestQueryAppInsightsFailures` | 5 | Success, error, SDK-missing, partial failure, default hours |
| `TestProposeAppServiceRestart` | 6 | approval_required, risk_level, proposal_type, fields, action, reason |
| `TestProposeFunctionAppScaleOut` | 8 | approval_required, risk_level, proposal_type, instances, fields, action, reason, reversibility |

## Conventions Followed

- Lazy SDK imports with `try/except ImportError → None`
- `_log_sdk_availability()` called at module level
- `start_time = time.monotonic()` at entry of every tool
- `duration_ms` in BOTH `try` AND `except` blocks
- Tools NEVER raise — always return `{"query_status": "error", "error": str(e)}`
- `get_credential()`, `get_agent_identity()`, `instrument_tool_call()` throughout
- Dockerfile uses `ARG BASE_IMAGE` + `CMD ["python", "-m", "appservice.agent"]`
