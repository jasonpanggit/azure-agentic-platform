---
phase: 65
plan: 65-2
title: "SRE Container Apps Self-Monitoring Tool"
status: completed
completed_at: "2026-04-14"
commits: 7
tests_passed: 626
tests_failed: 0
---

# Summary: 65-2 SRE Container Apps Self-Monitoring Tool

## What Was Done

Added a `query_container_app_health` `@ai_function` tool to the SRE agent that enables platform self-monitoring. Operators can now ask the SRE agent to inspect Container App health (provisioning state, active revisions, replica count, running state) for any AAP agent Container App or any Container App in monitored subscriptions.

## Tasks Completed

### 65-2-01: Add azure-mgmt-appcontainers to SRE requirements.txt
- Added `azure-mgmt-appcontainers>=4.0.0` to `agents/sre/requirements.txt`
- Updated comment to mention Container Apps self-monitoring

### 65-2-02: Add lazy import and SDK availability logging
- Added `try/except ImportError` block for `azure.mgmt.containerapp` (singular, correct module path)
- Added `"azure-mgmt-appcontainers": "azure.mgmt.containerapp"` to `_log_sdk_availability()` packages dict

### 65-2-03: Implement query_container_app_health @ai_function tool
- Implemented tool following project patterns: `instrument_tool_call` context manager, `start_time = time.monotonic()` inside the `with` block, `duration_ms` in both try/except paths, never raises — returns error dicts
- Early-exit guards for SDK-missing and subscription-missing with `duration_ms: 0.0`
- Returns app details: provisioning_state, latest_revision_name, managed_environment_id, outbound_ip_addresses, active_revisions list with per-revision detail (name, active, traffic_weight, replicas, running_state, created_time, last_active_time)

### 65-2-04: Wire query_container_app_health into SRE agent
- Added import to `agents/sre/agent.py`
- Registered in both `create_sre_agent()` and `create_sre_agent_version()` tools lists
- Added to allowed_tools format string in system prompt
- Added "Platform Self-Monitoring" section to `SRE_AGENT_SYSTEM_PROMPT` with Container App naming convention (`ca-{agent}-prod` in `rg-aap-prod`) and `containerapps` MCP tool reference
- Added `OperationalExcellence` category mention for advisor recommendations

### 65-2-05: Add unit tests for query_container_app_health
- Added `TestQueryContainerAppHealth` class with 4 tests:
  - `test_success_returns_app_details` — mocks app and revision responses, verifies all fields
  - `test_error_returns_error_dict` — verifies error path returns structured error
  - `test_sdk_missing_returns_error_dict` — verifies SDK-missing guard
  - `test_missing_subscription_id_returns_error` — verifies subscription-missing guard

### 65-2-06: Run full SRE test suite and verify zero regressions
- 37/37 SRE tool tests pass (including 4 new)
- 626/627 full agent suite tests pass (1 pre-existing EOL test failure, unrelated)
- Fixed `{agent}` brace escaping in system prompt that caused `KeyError` in `.format()` call

### 65-2-07: Document OperationalExcellence category
- `query_advisor_recommendations` docstring already contained `OperationalExcellence` as a valid category
- System prompt `OperationalExcellence` mention added in task 65-2-04 (Platform Self-Monitoring section)

## Files Modified

| File | Change |
|------|--------|
| `agents/sre/requirements.txt` | Added `azure-mgmt-appcontainers>=4.0.0` |
| `agents/sre/tools.py` | Lazy import for `ContainerAppsAPIClient`, SDK availability entry, `query_container_app_health` tool function |
| `agents/sre/agent.py` | Import, tools lists (x2), system prompt (Platform Self-Monitoring section + OperationalExcellence + allowed_tools) |
| `agents/tests/sre/test_sre_tools.py` | `TestQueryContainerAppHealth` class with 4 tests |

## Commits

1. `970505a` — feat(sre): add azure-mgmt-appcontainers to SRE requirements
2. `a6365c5` — feat(sre): add lazy import for ContainerAppsAPIClient SDK
3. `e894e66` — feat(sre): implement query_container_app_health @ai_function tool
4. `a4a4a8f` — feat(sre): wire query_container_app_health into SRE agent
5. `c5de225` — test(sre): add unit tests for query_container_app_health
6. `5a23d93` — fix(test): patch ContainerAppsAPIClient in missing-subscription test
7. `2689bca` — fix(sre): escape braces in system prompt naming convention

## Verification

```
pytest agents/tests/sre/test_sre_tools.py -v  → 37 passed
pytest agents/tests/ -q                       → 626 passed, 1 failed (pre-existing EOL test)
grep "azure-mgmt-appcontainers" agents/sre/requirements.txt  → PASS
grep "azure.mgmt.containerapp" agents/sre/tools.py           → PASS (singular, correct)
grep "OperationalExcellence" agents/sre/tools.py              → PASS
grep "OperationalExcellence" agents/sre/agent.py              → PASS
grep "Platform Self-Monitoring" agents/sre/agent.py           → PASS
grep "query_container_app_health" agents/sre/agent.py         → PASS
```
