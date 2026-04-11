---
id: "30-01"
phase: 30
plan: 1
wave: 1
title: "SOP Engine — All Chunks"
objective: "Build the SOP engine: provision a Foundry-managed vector store for SOP markdown files, add a PostgreSQL sops metadata table, implement a per-incident SOP selector with grounding instructions, add the sop_notify tool to all agents, add 3 new Teams card types for SOP notifications, create the SOP upload script, and provision ACS Email via Terraform."
autonomous: true
gap_closure: false
files_modified:
  - "services/api-gateway/migrations/007_sops.sql"
  - "services/api-gateway/tests/test_sops_migration.py"
  - "agents/shared/sop_store.py"
  - "agents/shared/sop_loader.py"
  - "agents/tests/shared/test_sop_store.py"
  - "agents/tests/shared/test_sop_loader.py"
  - "agents/shared/sop_notify.py"
  - "agents/tests/shared/test_sop_notify.py"
  - "services/teams-bot/src/card-builder.ts"
  - "services/teams-bot/src/types.ts"
  - "services/teams-bot/src/tests/card-builder.test.ts"
  - "scripts/upload_sops.py"
  - "agents/tests/test_upload_sops.py"
  - "infra/terraform/acs.tf"
  - "infra/terraform/variables.tf"
  - "agents/tests/integration/test_phase30_smoke.py"
task_count: 50
key_links: []
---

# Phase 30: SOP Engine — Implementation Plan

> **IMPORTANT**: This is a GSD wrapper plan. The full detailed implementation plan is at:
> `docs/superpowers/plans/2026-04-11-phase-30-sop-engine.md`
>
> **Read that file first.** Execute all 8 chunks in order:
> 1. Chunk 1: PostgreSQL Migration — `sops` Table
> 2. Chunk 2: SOP Store — Foundry Vector Store Provisioning
> 3. Chunk 3: SOP Loader — Per-Incident Selection
> 4. Chunk 4: `sop_notify` Tool
> 5. Chunk 5: Teams Bot — New SOP Card Types
> 6. Chunk 6: SOP Upload Script
> 7. Chunk 7: Terraform — ACS Email + SOP Vector Store Env Var
> 8. Chunk 8: Phase 30 Integration Smoke Test

## Goal

Build the SOP engine: provision a Foundry-managed vector store for SOP markdown files, add a PostgreSQL metadata table, implement a per-incident SOP selector, inject grounding instructions into each agent run, add the `sop_notify` tool to all agents, and add 3 new Teams card types for SOP notifications.

## Architecture

`agents/shared/sop_store.py` handles vector store provisioning (called only by `scripts/upload_sops.py`).
`agents/shared/sop_loader.py` does a fast PostgreSQL lookup to select the right SOP filename, then returns a grounding instruction that tells the agent to use `file_search` to retrieve the content.
Each domain agent's request handler calls `select_sop_for_incident()` before invoking the Responses API.
`sop_notify` is a shared `@ai_function` added to all agents.
ACS Email is provisioned for email notifications.
Three new Teams card types are added to the bot.

## Key Technical Context

- Vector store provisioned via `project.get_openai_client()` → `openai.vector_stores.create(name="aap-sops-v1")` (Basic setup — no storage account needed)
- SOP loader SQL uses tag overlap: `ARRAY(SELECT unnest(scenario_tags) INTERSECT SELECT unnest($3::text[]))` for tag matching
- `sop_notify` uses `channels: list[Literal["teams","email"]]` — NO "both" shorthand
- `provision_sop_vector_store()` is called EXCLUSIVELY by `scripts/upload_sops.py`, never by agents
- SHA-256 content hash (`sops.content_hash`) for upload idempotency
- Teams bot: extend `CardType = "alert" | "approval" | "outcome" | "reminder" | "sop_notification" | "sop_escalation" | "sop_summary"`
- ACS Email: `azure-communication-email` package, `EmailClient` from `azure.communication.email`
- All agents have `sop_notify` added to their tools list (8 domain agents — NOT the orchestrator)

## Dependencies

- **Depends on Phase 29**: Uses `AIProjectClient` pattern and `project.get_openai_client()` from Phase 29 SDK migration

## Success Criteria

- [ ] `services/api-gateway/migrations/007_sops.sql` exists with `sops` table definition
- [ ] `agents/shared/sop_store.py` exists with `provision_sop_vector_store()`
- [ ] `agents/shared/sop_loader.py` exists with `select_sop_for_incident()`
- [ ] `agents/shared/sop_notify.py` exists with `sop_notify` @ai_function
- [ ] Teams bot has 3 new card types (sop_notification, sop_escalation, sop_summary)
- [ ] `scripts/upload_sops.py` exists with SHA-256 idempotency check
- [ ] Terraform provisions ACS Email resource
- [ ] Integration smoke test passes
