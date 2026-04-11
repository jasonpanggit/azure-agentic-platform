---
id: "29-01"
phase: 29
plan: 1
wave: 1
title: "Foundry Platform Migration — All Chunks"
objective: "Migrate all 9 agents from azure-ai-projects 1.x AgentsClient thread-run patterns to azure-ai-projects 2.0.x PromptAgentDefinition/Responses API patterns, with A2A orchestrator topology, OTel tracing to App Insights, new shared telemetry module, agent registration script, and Terraform updates."
autonomous: true
gap_closure: false
files_modified:
  - "agents/shared/telemetry.py"
  - "agents/shared/__init__.py"
  - "agents/compute/agent.py"
  - "agents/network/agent.py"
  - "agents/storage/agent.py"
  - "agents/security/agent.py"
  - "agents/arc/agent.py"
  - "agents/sre/agent.py"
  - "agents/patch/agent.py"
  - "agents/eol/agent.py"
  - "agents/orchestrator/agent.py"
  - "services/api-gateway/foundry.py"
  - "scripts/register_agents.py"
  - "infra/terraform/agents.tf"
  - "infra/terraform/variables.tf"
  - "agents/tests/shared/test_telemetry.py"
  - "agents/tests/test_agent_registration.py"
  - "agents/tests/test_orchestrator_a2a.py"
  - "agents/tests/test_foundry_responses_api.py"
  - "agents/tests/test_register_agents.py"
  - "agents/tests/integration/test_phase29_smoke.py"
task_count: 42
key_links: []
---

# Phase 29: Foundry Platform Migration — Implementation Plan

> **IMPORTANT**: This is a GSD wrapper plan. The full detailed implementation plan is at:
> `docs/superpowers/plans/2026-04-11-phase-29-foundry-platform-migration.md`
>
> **Read that file first.** Execute all 7 chunks in order:
> 1. Chunk 1: Shared Telemetry Module
> 2. Chunk 2: Agent Registration — `create_version` Pattern
> 3. Chunk 3: Orchestrator — A2A Topology
> 4. Chunk 4: API Gateway — Responses API Migration
> 5. Chunk 5: Agent Registration Script + Terraform
> 6. Chunk 6: OTel Span Attributes on Incident Runs
> 7. Chunk 7: Integration Smoke Test + Final Verification

## Goal

Migrate all 9 agents from `azure-ai-projects` 1.x / `AgentsClient` thread-run patterns to `azure-ai-projects` 2.0.x `PromptAgentDefinition` / Responses API patterns, making every agent version-tracked and visible in the Foundry portal, with A2A orchestrator topology and OTel tracing wired to App Insights.

## Architecture

Each domain agent gets a `create_version()` registration function in its `agent.py`. The API gateway's `foundry.py` is migrated from `AgentsClient` threads/runs to `openai.responses.create()` Responses API. A new `agents/shared/telemetry.py` module adds `AIProjectInstrumentor` setup. Terraform adds A2A connection resources and an App Insights → Foundry link.

## Execution Instructions

Read the full plan at `docs/superpowers/plans/2026-04-11-phase-29-foundry-platform-migration.md`.

Execute all tasks in all 7 chunks following the TDD approach:
1. Write failing tests first
2. Run tests to confirm they fail
3. Write minimal implementation
4. Run tests to confirm they pass
5. Commit atomically per chunk

## Key Technical Context

- `azure-ai-projects==2.0.x` breaking changes:
  - `AgentsClient` → `AIProjectClient`
  - threads/runs → Responses API (`openai.responses.create()`)
  - `create_agent` → `create_version` + `PromptAgentDefinition`
- `AIProjectInstrumentor` + `configure_azure_monitor` for Foundry portal OTel trace waterfall
- `A2APreviewTool` for orchestrator → domain agent topology visible in Foundry portal
- `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` env var required for GenAI span capture
- All `propose_*` tools: HITL only — `create_approval_record()` exclusively, zero ARM calls

## Success Criteria

- [ ] `agents/shared/telemetry.py` exists with `setup_foundry_tracing()` and all tests pass
- [ ] All 9 agents have `create_version()` registration functions and tests pass
- [ ] Orchestrator has `A2APreviewTool` topology and tests pass
- [ ] `services/api-gateway/foundry.py` uses Responses API and tests pass
- [ ] `scripts/register_agents.py` registers all agents and tests pass
- [ ] Terraform A2A connection resources updated
- [ ] OTel span attributes recorded on incident runs and tests pass
- [ ] Integration smoke test passes
