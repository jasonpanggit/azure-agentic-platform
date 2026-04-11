---
id: "29-01"
phase: 29
plan: 1
title: "Foundry Platform Migration — All Chunks"
status: complete
started: "2026-04-11"
completed: "2026-04-11"
commits: 7
tests_added: 38
tests_total_pass: 1161
tests_pre_existing_failures: 8
---

# Phase 29-01 Summary: Foundry SDK Migration

## What Was Done

Migrated all 9 agents from `azure-ai-projects` 1.x / `AgentsClient` thread-run patterns to `azure-ai-projects` 2.0.x `PromptAgentDefinition` / Responses API patterns, with A2A orchestrator topology, OTel tracing wired to App Insights, agent registration script, and Terraform updates.

## Chunks Executed

### Chunk 1: Shared Telemetry Module
- Created `agents/shared/telemetry.py` with `setup_foundry_tracing()` and `get_tracer()`
- `AIProjectInstrumentor` integration with `ImportError` guard for older SDK versions
- Auto-sets `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` env var
- 5 tests added in `agents/tests/shared/test_telemetry.py`

### Chunk 2: Agent Registration — `create_version` Pattern
- Added `create_*_agent_version()` to all 8 domain agents: compute, arc, eol, network, patch, security, sre, storage
- Each wraps `PromptAgentDefinition` with the agent's system prompt and tool list
- `AIProjectClient` and `PromptAgentDefinition` imports with `ImportError` guard
- Updated `conftest.py` to stub `MCPTool` for test compatibility
- 10 tests added in `agents/tests/shared/test_agent_registration.py`

### Chunk 3: Orchestrator — A2A Topology
- Added `create_orchestrator_agent_version()` with `A2APreviewTool` wiring for all 8 domain agents
- Connection lookup via `project.connections.get()` for each domain
- `_A2A_DOMAINS` list defining the 8 domain agent connection names
- 3 tests added in `agents/tests/shared/test_orchestrator_a2a.py`

### Chunk 4: API Gateway — Responses API Migration
- Migrated `services/api-gateway/foundry.py` from `AgentsClient` threads/runs to `AIProjectClient` Responses API
- `dispatch_to_orchestrator()`: single `openai.responses.create()` call with `agent_reference`
- `build_incident_message()`: typed envelope builder (AGENT-002)
- Backward-compat `_get_foundry_client()` preserved for chat.py, vm_chat.py, approvals.py
- Backward-compat `create_foundry_thread()` alias mapping thread_id -> response_id
- OTel span attributes: `incident.id`, `incident.domain`, `agent.name` on `foundry.responses_create` span
- 5 new tests in `test_foundry_v2.py` + 12 existing foundry tests pass (zero regressions)

### Chunk 5: Agent Registration Script + Terraform
- Created `scripts/register_agents.py` — registers all 9 agents via `create_version()` with orchestrator last
- Terraform: `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` and `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` on all agent Container Apps
- Terraform: `ORCHESTRATOR_AGENT_NAME=aap-orchestrator` env var on orchestrator + api-gateway
- Terraform: 8 `azapi_resource` A2A connections (`RemoteA2A` category) for domain agent topology
- Terraform: 8 new endpoint variables (`compute_agent_endpoint`, `arc_agent_endpoint`, etc.)
- Added `scripts/` to `pyproject.toml` testpaths
- 3 tests added in `scripts/tests/test_register_agents.py`

### Chunk 6: OTel Span Attributes on Incident Runs
- Verified `incident.id`, `incident.domain`, `agent.name` span attributes on `foundry.responses_create`
- Verified `agent.domain`, `agent.correlation_id` on `agent.orchestrator` span
- 3 tests added in `services/api-gateway/tests/test_foundry_spans.py`

### Chunk 7: Integration Smoke Test + Final Verification
- Comprehensive smoke test verifying all Phase 29 wiring:
  - All 9 `create_*_agent_version` functions importable
  - Shared telemetry module importable
  - Registration script importable
  - Responses API dispatch importable
  - Backward-compat aliases importable
  - Consistent `aap-{domain}-agent` naming across all 8 domain agents
  - Orchestrator registers 8 A2A connections
- 9 tests added in `agents/tests/integration/test_phase29_smoke.py`

## Files Changed

### New Files (10)
- `agents/shared/telemetry.py` — Foundry-native telemetry module
- `agents/tests/shared/test_telemetry.py` — telemetry tests
- `agents/tests/shared/test_agent_registration.py` — registration tests
- `agents/tests/shared/test_orchestrator_a2a.py` — orchestrator A2A tests
- `agents/tests/integration/test_phase29_smoke.py` — smoke tests
- `scripts/__init__.py` — package init
- `scripts/register_agents.py` — agent registration script
- `scripts/tests/__init__.py` — test package init
- `scripts/tests/test_register_agents.py` — registration script tests
- `services/api-gateway/tests/test_foundry_v2.py` — Responses API tests
- `services/api-gateway/tests/test_foundry_spans.py` — span attribute tests

### Modified Files (12)
- `agents/compute/agent.py` — added `create_compute_agent_version()`
- `agents/arc/agent.py` — added `create_arc_agent_version()`
- `agents/eol/agent.py` — added `create_eol_agent_version()`
- `agents/network/agent.py` — added `create_network_agent_version()`
- `agents/patch/agent.py` — added `create_patch_agent_version()`
- `agents/security/agent.py` — added `create_security_agent_version()`
- `agents/sre/agent.py` — added `create_sre_agent_version()`
- `agents/storage/agent.py` — added `create_storage_agent_version()`
- `agents/orchestrator/agent.py` — added `create_orchestrator_agent_version()` with A2A
- `services/api-gateway/foundry.py` — migrated to Responses API
- `terraform/modules/agent-apps/main.tf` — GenAI tracing env vars + A2A connections
- `terraform/modules/agent-apps/variables.tf` — A2A endpoint variables
- `conftest.py` — MCPTool stub for test compatibility
- `pyproject.toml` — added scripts/ to testpaths

## Test Results

- **38 new tests added** across 7 test files
- **1161 tests pass** (full suite)
- **8 pre-existing failures** unchanged (eol agent stub tests, patch tool count, approval lifecycle)
- **Zero regressions** introduced

## Commits (7)

1. `e20953a` — feat(phase-29): add shared/telemetry.py with AIProjectInstrumentor setup
2. `733b11b` — feat(phase-29): add create_version registration to all 8 domain agents
3. `b6315c6` — feat(phase-29): add orchestrator A2A topology registration
4. `09b723f` — feat(phase-29): migrate api-gateway foundry.py to Responses API (2.0.x)
5. `1befe1e` — feat(phase-29): add registration script, Terraform A2A connections and GenAI tracing
6. `6002261` — test(phase-29): add span attribute assertions for incident dispatch
7. `147c339` — test(phase-29): add integration smoke tests for Phase 29 agent registration

## Technical Decisions

1. **`description` removed from `PromptAgentDefinition`**: The installed SDK (2.0.1) doesn't accept a `description` kwarg on `PromptAgentDefinition`. Removed to match actual API.

2. **Backward-compat `_get_foundry_client()`**: Preserved the `AgentsClient` factory function because `chat.py`, `vm_chat.py`, `approvals.py`, and their tests depend on `client.threads`, `client.messages`, `client.runs` sub-operation groups. These will be migrated in a future phase.

3. **Module-level `AgentsClient` import**: Kept `from azure.ai.agents import AgentsClient` at module level in `foundry.py` because existing tests patch `services.api_gateway.foundry.AgentsClient` at module scope.

4. **OTel provider singleton**: Combined span attribute assertions into a single test because OTel's `set_tracer_provider()` only works once per process.

5. **`MCPTool` stub**: Added to `conftest.py` agent_framework stub because the EOL agent imports `MCPTool` from `agent_framework`.
