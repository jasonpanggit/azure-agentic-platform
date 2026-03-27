# Phase 5: Triage & Remediation + Web UI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 05-triage-remediation-web-ui
**Areas discussed:** Web UI layout & repo location, SSE streaming architecture, HITL gate & webhook callback, Runbook RAG data model & seeding, Workflow files idea (scoping discussion)

---

## Web UI Layout & Repo Location

| Option | Description | Selected |
|--------|-------------|----------|
| `services/web-ui/` | Follows existing services/ pattern; consistent monorepo structure | ✓ |
| `frontend/` at repo root | Separates frontend from Python services; breaks existing pattern | |
| Separate repo | Total isolation; loses monorepo convenience | |

**User's choice:** `services/web-ui/`

---

### Split-Pane Design

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed proportions | CSS-only; simpler state management | |
| Resizable with drag handle | Persisted in localStorage; react-resizable-panels | |
| Responsive (mobile tabs + desktop split) | Responsive breakpoint | |

**User's choice:** "I want a modern design — I leave it to you to recommend and decide."
**Notes:** Claude's discretion. Modern feel suggests resizable panel with a clean drag handle.

---

### Default Right-Pane Tab

| Option | Description | Selected |
|--------|-------------|----------|
| Alerts tab | Live incident feed — most actionable default | ✓ |
| Topology tab | Health overlay across subscriptions | |
| Audit Log tab | Last action view | |

**User's choice:** Alerts tab

---

### Mobile Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Desktop-only for Phase 5 | Min-width breakpoint; message for small screens | ✓ |
| Responsive (stacked on mobile) | Single-column stacked layout | |

**User's choice:** Desktop-only for Phase 5

---

## SSE Streaming Architecture

### SSE Endpoint Location

| Option | Description | Selected |
|--------|-------------|----------|
| Next.js /api/stream Route Handler | BFF pattern; no CORS; consistent with CLAUDE.md UI-008 | ✓ |
| api-gateway FastAPI SSE endpoint | All streaming in Python; adds CORS complexity | |

**User's choice:** Next.js `/api/stream` Route Handler

---

### Chat Conversation Initiation

| Option | Description | Selected |
|--------|-------------|----------|
| New `/api/v1/chat` on api-gateway | Gateway handles auth + rate limiting + correlation ID; clean separation from incident ingest | ✓ |
| Reuse `/api/v1/incidents` | Simpler but conflates operator chat with detection-fired incidents | |
| Direct Foundry SDK from Next.js BFF | Lighter; no Python gateway for chat | |

**User's choice:** New `POST /api/v1/chat` on api-gateway

---

### Token + Trace Stream Delivery

| Option | Description | Selected |
|--------|-------------|----------|
| Two separate EventSource connections | Independent Last-Event-ID cursors and reconnect per stream | ✓ |
| Single multiplexed stream | One EventSource; event type differentiates token vs trace | |

**User's choice:** Two separate EventSource connections

---

## HITL Gate & Webhook Callback

### Webhook Endpoint Location

| Option | Description | Selected |
|--------|-------------|----------|
| Add to api-gateway | Consistent with gateway as single public ingress; Web UI + Teams call same endpoint | ✓ |
| Separate approval Container App | More isolated; higher complexity | |

**User's choice:** Add to api-gateway

---

### Foundry Thread Parking

| Option | Description | Selected |
|--------|-------------|----------|
| Cosmos DB write + return, webhook resumes thread | No polling; agent turn completes; webhook posts new message to resume | ✓ |
| Async wait in agent process | Blocks resource; risks idle timeout | |
| Foundry native park (if available) | Research required; uncertain API | |

**User's choice:** Cosmos DB write + return, webhook resumes thread

---

### Resource Identity Certainty

| Option | Description | Selected |
|--------|-------------|----------|
| Snapshot at proposal + re-verify at execution | Two-point check; catches state drift between approval and execution | ✓ |
| Verify at approval time only | Simpler; misses drift during approval-to-execution window | |

**User's choice:** Snapshot at proposal + re-verify at execution

---

## Runbook RAG Data Model & Seeding

### PostgreSQL Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Single `runbooks` table | id, title, domain, version, content, embedding vector(1536) | ✓ |
| Chunked: runbooks + runbook_chunks | Two tables; better for long docs | |

**User's choice:** Single `runbooks` table

---

### Embedding Model

| Option | Description | Selected |
|--------|-------------|----------|
| Azure OpenAI text-embedding-3-small | 1536-dim; cost-effective; already in Foundry workspace | ✓ |
| Azure OpenAI ada-002 | Older model; same dimensions | |
| Local sentence-transformers | No API cost; overkill for this platform | |

**User's choice:** Azure OpenAI text-embedding-3-small

---

### Seed Data

| Option | Description | Selected |
|--------|-------------|----------|
| ~10 runbooks per domain (~60 total) | Realistic synthetic content; proves >0.75 cosine similarity | ✓ |
| Minimal seed (1-2 per domain) | Faster to build; poor operator experience | |
| No seed, empty library | Tests adjusted to check retrieval works when data exists | |

**User's choice:** ~10 runbooks per domain as fixtures

---

## Workflow Files Idea (Scoping Discussion)

**User's description:** Workflows are markdown files that define multi-step processes — calling agents, invoking runbooks as steps, integrating with external systems, and including HITL gates for destructive operations. Purpose: operators map the platform to their existing operational workflows.

| Option | Description | Selected |
|--------|-------------|----------|
| Include in Phase 5 | Full workflow engine in Phase 5 (~1-2 weeks additional) | |
| Foundation in Phase 5, execution later | Schema + storage only; step execution deferred | |
| Defer to a new phase | Full new capability; dedicated roadmap phase | ✓ |

**User's choice:** Defer to a new phase
**Notes:** User confirmed this is a distinct, substantial capability. Captured as a deferred idea in CONTEXT.md with recommendation to add as Phase 7.5 or v2 feature.

---

## Claude's Discretion

- Split-pane exact proportions and resize behavior (user explicitly deferred: "modern design — you decide")
- Alert feed SSE push mechanism (Cosmos DB change feed vs. polling)
- Fluent UI 2 component selection (chat bubbles, trace tree, proposal cards, alert feed items)
- MSAL PKCE token refresh and silent token acquisition
- PostgreSQL migration tooling for `runbooks` table
- Rate limiting implementation for REMEDI-006
- GitOps PR template format

## Deferred Ideas

- **Operator Workflow Files** — new capability; multi-step processes with agent/runbook/external system steps + workflow-level HITL; recommend Phase 7.5 or v2
- **APIM Standard v2** — threshold now met with Phase 5 APIs; deferred to Phase 6/7 to avoid Phase 5 scope creep
