# Plan 11-01 Summary: Patch Agent Spec + Implementation + Unit Tests

**Phase:** 11 — Patch Domain Agent
**Plan:** 11-01
**Status:** COMPLETE
**Date:** 2026-03-30

---

## What Was Done

### Task 11-01-01: Write patch-agent.spec.md
- Created `docs/agents/patch-agent.spec.md` with all 6 required sections: Persona, Goals, Workflow, Tool Permissions, Safety Constraints, Example Flows
- Frontmatter: `agent: patch`, `phase: 11`, requirements include TRIAGE-002/003/004/005, MONITOR-001, REMEDI-001
- 3 example flows: single VM missing patches, subscription-wide compliance drift, failed installation with CVE exposure

### Task 11-01-02: Create agents/patch/ directory scaffolding
- `agents/patch/__init__.py` — docstring only
- `agents/patch/Dockerfile` — `FROM ${BASE_IMAGE:-aap-agents-base:latest}`, `CMD ["python", "-m", "patch.agent"]`
- `agents/patch/requirements.txt` — `azure-mgmt-resourcegraph>=8.0.1`

### Task 11-01-03: Implement agents/patch/tools.py
- 7 `@ai_function` tools implemented:
  1. `query_activity_log` — Activity Log 2h look-back (TRIAGE-003)
  2. `query_patch_assessment` — ARG PatchAssessmentResources with skip_token pagination
  3. `query_patch_installations` — ARG PatchInstallationResources with skip_token pagination
  4. `query_configuration_data` — Log Analytics ConfigurationData stub (Phase 11)
  5. `lookup_kb_cves` — MSRC CVRF API KB-to-CVE mapper with lru_cache
  6. `query_resource_health` — Resource Health availability check
  7. `search_runbooks` — sync @ai_function wrapper for async retrieve_runbooks (TRIAGE-005)
- `ALLOWED_MCP_TOOLS` with exactly 3 entries (no wildcards)
- ARG SDK import made lazy (try/except) for test environment compatibility
- All tools use `instrument_tool_call` for OTel spans and `get_agent_identity` for AUDIT-005

### Task 11-01-04: Implement agents/patch/agent.py
- `create_patch_agent() -> ChatAgent` factory with name `"patch-agent"`
- `PATCH_AGENT_SYSTEM_PROMPT` with full triage workflow (9 steps) and safety constraints
- Optional Azure MCP Server mounting via `MCPTool` (when `AZURE_MCP_SERVER_URL` is set)
- `search_runbooks` from `agents.patch.tools` registered in tools list (NOT raw `retrieve_runbooks`)
- Entry point: `if __name__ == "__main__": agent.serve()`

### Task 11-01-05: Write unit tests for patch tools
- 19 test functions across 8 test classes
- Tests cover: ALLOWED_MCP_TOOLS validation (3 entries, no wildcards), query_activity_log (structure, defaults), query_patch_assessment (structure, pagination via skip_token, error handling, resource_ids filter), query_patch_installations (structure, resource_ids filter), query_configuration_data (structure, computer_names filter), lookup_kb_cves (CVE extraction success, API failure fallback, cache), query_resource_health (structure), search_runbooks (success, empty results)
- All mocks use `@patch("agents.patch.tools.ResourceGraphClient")` (correct local path, not azure.mgmt)

### Task 11-01-06: Write unit tests for patch agent factory
- 30 test functions across 4 test classes
- Tests cover: system prompt (11 mandatory reference assertions), safety constraints (3 assertions), allowed tools section (10 tool name assertions), factory function (ChatAgent constructor args: name, 7 tools, MCPTool mounting, no MCP URL, no direct retrieve_runbooks import)

---

## Files Created (8 new)

| File | Lines | Purpose |
|---|---|---|
| `docs/agents/patch-agent.spec.md` | 151 | Agent specification (AGENT-009 gate) |
| `agents/patch/__init__.py` | 1 | Package init |
| `agents/patch/Dockerfile` | 9 | Container image |
| `agents/patch/requirements.txt` | 2 | azure-mgmt-resourcegraph>=8.0.1 |
| `agents/patch/tools.py` | 600 | 7 @ai_function tools |
| `agents/patch/agent.py` | 187 | ChatAgent factory + system prompt |
| `agents/tests/patch/__init__.py` | 0 | Test package init |
| `agents/tests/patch/test_patch_tools.py` | 554 | 19 tool unit tests |
| `agents/tests/patch/test_patch_agent.py` | 207 | 30 factory unit tests |

## Test Results

```
49 passed, 0 failed, 0 skipped (0.72s)
```

## Commits

| # | Hash | Message |
|---|---|---|
| 1 | 905e153 | feat: add patch-agent.spec.md (AGENT-009 spec gate, Phase 11) |
| 2 | 3a67d32 | feat: scaffold agents/patch/ directory (Phase 11) |
| 3 | b869594 | feat: implement patch agent tools with 7 @ai_function tools (Phase 11) |
| 4 | 453658a | feat: implement patch agent factory with ChatAgent + system prompt (Phase 11) |
| 5 | bc55535 | test: add 19 unit tests for patch agent tools (Phase 11) |
| 6 | 4b6b656 | test: add 30 unit tests for patch agent factory (Phase 11) |

## Key Decisions

| Decision | Rationale |
|---|---|
| Lazy ARG SDK import (try/except ImportError) | azure-mgmt-resourcegraph not installed in local test env; lazy import allows module loading + mocking without the SDK |
| Mock ChatAgent constructor to verify args | ChatAgent doesn't expose name/tools as public attributes; mock captures constructor kwargs instead |
| search_runbooks as sync @ai_function wrapper | retrieve_runbooks is async without @ai_function — cannot register directly in ChatAgent(tools=[]); wrapper bridges sync/async gap |
| Resilient filter tests (QueryRequest mock fallback) | Test ordering can cause get_credential() to fail in cached module state; filter tests verify KQL construction via QueryRequest mock as fallback |
