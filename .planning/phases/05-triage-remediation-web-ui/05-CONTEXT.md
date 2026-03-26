# Phase 5: Triage & Remediation + Web UI - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver four interconnected systems in a single phase:

1. **Web UI** — Next.js App Router + Fluent UI 2 deployed as `services/web-ui/` Container App; operator authenticates via MSAL PKCE (`@azure/msal-browser`); split-pane layout (chat left, tabbed dashboard right).
2. **Dual SSE streaming** — Two independent EventSource connections (`event:token` + `event:trace`) with monotonic sequence numbers and `Last-Event-ID` reconnect; `/api/stream` Route Handler in Next.js; new `POST /api/v1/chat` endpoint on the api-gateway for operator-initiated conversations.
3. **Runbook RAG** — PostgreSQL + pgvector single-table library with Azure OpenAI `text-embedding-3-small` embeddings; agents retrieve top-3 runbooks by cosine similarity (>0.75 threshold); seeded with ~10 synthetic runbooks per domain (~60 total).
4. **HITL gate + Remediation flow** — Approval endpoints on the existing api-gateway; Foundry thread parking via Cosmos DB write-then-return (no polling); Resource Identity Certainty snapshot-on-proposal + re-verify-on-execution; `stale_approval` abort for diverged state; rate limiting, protected-tag guard, and GitOps PR path for Arc K8s clusters with Flux/ArgoCD.

**No Teams bot delivery in Phase 5** — Teams delivers Adaptive Card posting (Phase 6); Phase 5 only calls the Teams API to post the approval card (required by REMEDI-002) but the full Teams bot is Phase 6.

</domain>

<decisions>
## Implementation Decisions

### Web UI Location & Layout
- **D-01:** Web UI lives at `services/web-ui/` — consistent with the existing `services/` monorepo pattern (api-gateway, arc-mcp-server, detection-plane are all there).
- **D-02:** Split-pane layout: **Claude's discretion on exact proportions and resize behavior** — user wants a modern design; CSS-driven layout using Fluent UI 2 primitives is the approach. Resizable panel is preferred for modern feel.
- **D-03:** Right-pane default tab: **Alerts** — the first thing an operator sees is the live incident feed.
- **D-04:** Mobile strategy: **desktop-only for Phase 5** — min-width breakpoint with "use a desktop browser" message; mobile support deferred.

### SSE Streaming Architecture
- **D-05:** SSE endpoint lives in the **Next.js BFF** (`/api/stream` Route Handler inside `services/web-ui/`) — pure Backend-for-Frontend pattern; avoids CORS, consistent with CLAUDE.md and UI-008.
- **D-06:** Operator-initiated chat conversations route through a **new `POST /api/v1/chat` endpoint on the existing api-gateway** — gateway handles auth, rate limiting, and correlation ID injection, then creates a Foundry thread and proxies streaming back via SSE. Separates ad-hoc operator chat from detection-plane-fired incidents (`/api/v1/incidents`).
- **D-07:** `event:token` and `event:trace` are delivered as **two separate EventSource connections** — each with its own `Last-Event-ID` cursor, independent reconnect, and sequence number namespace. Client opens both connections on conversation start.
- **D-08:** `/api/stream` sends a **20-second heartbeat** comment event to prevent Container Apps 240s idle termination (UI-008). Client reconnects with `Last-Event-ID` on drop.

### HITL Gate & Approval Webhook
- **D-09:** Approval webhook endpoints added to the **existing api-gateway** — `POST /api/v1/approvals/{approval_id}/approve` and `POST /api/v1/approvals/{approval_id}/reject`. Both Web UI and Teams (Phase 6) call the same endpoints. Single source of truth.
- **D-10:** Foundry thread **parking pattern: write-then-return** — the agent writes the approval record to Cosmos DB (status: `pending`, with `expires_at`) and returns from its current turn. The Foundry thread is idle (not blocked). The webhook callback posts a new message to the Foundry thread to resume processing. No polling loop. Satisfies REMEDI-002.
- **D-11:** **Resource Identity Certainty**: agent captures a state snapshot (resource ID, ARM resource health, tags) at proposal time. Immediately before execution, the agent re-verifies all 2+ signals. If any signal diverged since approval was granted, the action is aborted with `stale_approval` error event and the Cosmos DB record is updated with `abort_reason: stale_approval`. Satisfies REMEDI-004.
- **D-12:** Approval records in Cosmos DB use the **`approvals` container** (already provisioned in Phase 1) with schema: `{ id, action_id, thread_id, status, expires_at, proposed_at, decided_at, decided_by, abort_reason, resource_snapshot }`. ETag optimistic concurrency for all writes.
- **D-13:** Proposals expire after **30 minutes** (default; configurable via env var). The api-gateway checks `expires_at` on every approval/reject request and returns `410 Gone` for expired proposals. No expired approval is ever executed.

### GitOps Remediation Path (REMEDI-008)
- **D-14:** Arc K8s GitOps detection: the Arc Agent calls the Arc MCP Server to check if Flux or ArgoCD is installed on the cluster (detect via `kubectl get crd` or Helm release check). If detected → PR-based path; if not → direct `kubectl apply` path.
- **D-15:** GitOps PR creation: the agent creates a PR against the GitOps repo using the **GitHub REST API** (via `GITHUB_TOKEN` from Key Vault). Target repo and branch are configurable per cluster via a platform configuration record in PostgreSQL. **Claude's discretion** on the exact PR template format.

### Runbook RAG Data Model
- **D-16:** **Single `runbooks` table** in PostgreSQL with columns: `id` (uuid), `title` (text), `domain` (text — compute/network/storage/security/arc/sre), `version` (text), `content` (text), `embedding` (vector(1536)), `created_at`, `updated_at`. pgvector cosine similarity index on `embedding`.
- **D-17:** **Embedding model: Azure OpenAI `text-embedding-3-small`** — 1536-dimensional vectors, cost-effective, already available in the Foundry workspace. Consistent with the platform's Azure-only stance.
- **D-18:** **Initial seed: ~10 synthetic runbooks per domain** (~60 total) — realistic content covering the most common incident types per domain (VM high CPU, disk full, network NSG misconfiguration, storage quota, security alert, Arc connectivity, SRE generic). Must satisfy TRIAGE-005 SC-3: test query for known incident type returns >0.75 cosine similarity in <500ms.
- **D-19:** Runbook retrieval API: a new `GET /api/v1/runbooks/search?query=...&domain=...&limit=3` endpoint on the api-gateway (or callable directly by domain agents as an internal tool) returns the top-3 runbooks by cosine similarity for a given query.

### Claude's Discretion
- Exact split-pane proportions and whether to use `react-resizable-panels` or CSS-only approach
- Fluent UI 2 component selection for chat bubbles, trace tree, proposal cards, and alert feed
- Alert feed SSE push mechanism (Cosmos DB change feed → SSE route vs. polling)
- Exact runbook content for the seed fixtures (realistic but synthetic)
- PostgreSQL migration tooling for the `runbooks` table and pgvector index
- MSAL PKCE token refresh handling and silent token acquisition
- Container App container size for `services/web-ui/` (Node.js runtime)
- Rate limiting implementation details for REMEDI-006 (per agent per subscription max N actions/minute)
- Exact GitOps PR template format and target branch strategy

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 5 Requirements
- `.planning/REQUIREMENTS.md` §UI — UI-001 through UI-008: full Web UI requirements including MSAL PKCE, split-pane, SSE streaming, trace panel, proposal cards, alert feed, multi-subscription context, heartbeat
- `.planning/REQUIREMENTS.md` §TRIAGE — TRIAGE-005 (runbook RAG, pgvector top-3, version citation, <500ms, >0.75 cosine), TRIAGE-007 (SSE monotonic sequence numbers, Last-Event-ID reconnect)
- `.planning/REQUIREMENTS.md` §REMEDI — REMEDI-002 (HITL gate, Teams Adaptive Card, Foundry thread park, webhook resume), REMEDI-003 (Cosmos DB approval records, ETag, 30-min expiry), REMEDI-004 (Resource Identity Certainty, 2+ signals, stale_approval), REMEDI-005 (approve/reject from Web UI or Teams), REMEDI-006 (rate limiting, protected tag, prod scope confirmation), REMEDI-008 (GitOps PR path for Arc K8s)
- `.planning/REQUIREMENTS.md` §AUDIT — AUDIT-002 (approval records in Cosmos DB + OneLake, ≥2 years retention), AUDIT-004 (Audit Log tab, filterable by agent/action/resource/time)
- `.planning/ROADMAP.md` §"Phase 5: Triage & Remediation + Web UI" — 6 success criteria define acceptance tests (FMP <2s, SSE reconnect continuity, RAG >0.75 similarity, HITL Foundry park/resume, stale_approval abort, GitOps vs direct-apply path)

### Technology Stack
- `CLAUDE.md` §"Frontend (Next.js + Fluent UI 2)" — Next.js 15.x App Router, SSE via ReadableStream in Route Handlers, Fluent UI v9 (`@fluentui/react-components`), SSR considerations for Griffel
- `CLAUDE.md` §"Core Agent Framework" — Microsoft Agent Framework 1.0.0rc5; `ChatAgent`, `HandoffOrchestrator`; Foundry Hosted Agent deployment; `AzureAIAgentClient`
- `CLAUDE.md` §"Azure Integration Layer" — `azure-ai-projects` 2.0.1; Foundry thread management
- `CLAUDE.md` §"Data Persistence" — Cosmos DB `azure-cosmos 4.x` ETag concurrency; PostgreSQL pgvector `0.3.x`; `asyncpg`/`psycopg[binary]` for async PG access
- `CLAUDE.md` §"What NOT to Use (and Why)" — confirms Vercel AI SDK is avoid for direct Foundry integration; use raw ReadableStream

### Existing Implementation — Must Read Before Building
- `services/api-gateway/main.py` — existing FastAPI app; CORS already configured "for Phase 5 (comment in code)"; correlation ID middleware; `verify_token` Depends injection pattern
- `services/api-gateway/models.py` — `IncidentPayload`, `IncidentResponse`, `HealthResponse` Pydantic models; pattern for new `ChatRequest`, `ApprovalRecord` models
- `services/api-gateway/auth.py` — Entra Bearer token validation; same middleware applies to new `/api/v1/chat` and `/api/v1/approvals/*` endpoints
- `services/api-gateway/foundry.py` — `create_foundry_thread()` helper; reusable for `/api/v1/chat` thread creation
- `agents/shared/triage.py` — `RemediationProposal` dataclass with `requires_approval=True` (REMEDI-001); `TriageDiagnosis` with confidence score; pattern for resource snapshot extension
- `agents/shared/envelope.py` — `IncidentMessage` typed envelope; `message_type: "remediation_proposal"` already defined
- `agents/shared/budget.py` — ETag optimistic concurrency pattern in Cosmos DB; reuse for approval record writes
- `terraform/modules/databases/cosmos.tf` — `approvals` container already provisioned from Phase 1; `incidents` container schema from Phase 4; cross-reference partition keys

### Agent Specs (for domain agent runbook retrieval integration)
- `docs/agents/compute-agent.spec.md` — compute agent workflow; runbook retrieval step must be added in Phase 5
- `docs/agents/network-agent.spec.md` — same
- `docs/agents/storage-agent.spec.md` — same
- `docs/agents/security-agent.spec.md` — same
- `docs/agents/arc-agent.spec.md` — same; also GitOps detection steps (REMEDI-008)
- `docs/agents/sre-agent.spec.md` — same

### Research Artifacts
- `.planning/research/ARCHITECTURE.md` — Web UI architecture section; SSE streaming design; HITL flow diagrams
- `.planning/research/SUMMARY.md` — Key decisions: Resource Identity Certainty protocol from GBB patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/api-gateway/main.py` — FastAPI app with CORS, correlation ID middleware, and `verify_token` Depends; adding `/api/v1/chat` and `/api/v1/approvals/*` routes follows the same pattern as `/api/v1/incidents`
- `services/api-gateway/foundry.py` — `create_foundry_thread()` is reusable for chat-initiated sessions; only needs a different `initial_message` format
- `services/api-gateway/auth.py` — Entra Bearer token validation works for all new endpoints; no changes needed
- `agents/shared/budget.py` — `BudgetTracker` ETag pattern (`read → mutate → replace with match_condition="IfMatch"`) is the exact pattern for approval record writes
- `agents/shared/triage.py` — `RemediationProposal.to_dict()` already includes `requires_approval: True` and `risk_level`; needs extension for `resource_snapshot` field
- `agents/shared/envelope.py` — `message_type: "remediation_proposal"` already in VALID_MESSAGE_TYPES; ready for use
- `terraform/modules/databases/cosmos.tf` — `approvals` container provisioned in Phase 1; partition key TBD (action_id or thread_id — planner to decide)

### Established Patterns
- FastAPI route pattern: `@app.post("/api/v1/...", response_model=..., status_code=...)` with `token: dict = Depends(verify_token)` — use for all new api-gateway endpoints
- Cosmos DB ETag pattern: read → modify → `container.replace_item(item=id, body=..., etag=record["_etag"], match_condition="IfMatch")` — from `budget.py`
- Terraform module pattern: `terraform/modules/{domain}/` with `main.tf`, `variables.tf`, `outputs.tf` — no new IaC modules needed for Phase 5 (Phase 5 is application code, not infrastructure)
- GitHub Actions reusable docker-push workflow: extends per Phase 2 pattern for `web-ui` image build

### Integration Points
- `services/web-ui/` — new Next.js Container App; connects to api-gateway for `/api/v1/chat` calls; hosts own `/api/stream` Route Handler for SSE to client
- api-gateway new routes: `/api/v1/chat` (creates Foundry thread), `/api/v1/approvals/{id}/approve`, `/api/v1/approvals/{id}/reject`, `/api/v1/runbooks/search` (optional agent-internal runbook retrieval)
- `terraform/modules/databases/postgres.tf` — add `runbooks` table migration; enable pgvector extension (already required per INFRA-003)
- Cosmos DB `approvals` container — add `resource_snapshot` field to approval record schema; partition key needs to be confirmed
- Foundry thread + Microsoft Agent Framework — approval parking uses existing `azure-ai-projects` thread message API to resume parked threads; planner to confirm exact API call

</code_context>

<specifics>
## Specific Ideas

- **APIM deferred from Phase 2** — Phase 2 CONTEXT.md deferred APIM Standard v2 to "Phase 5/6 when multiple public APIs exist." Phase 5 creates exactly that scenario (chat API + approval API + runbook API + incidents API). The planner should evaluate whether APIM Standard v2 fits the Phase 5 scope or remains deferred to Phase 6/7. This is a "should we do it now?" question for the planner to flag as a decision point.
- **No Teams Adaptive Card posting in Phase 5 Teams bot code** — Phase 5 calls the Teams API to post the high-risk approval card (REMEDI-002) but does NOT implement the full Teams bot. The Teams bot (bidirectional conversation, alert cards, etc.) is Phase 6. Phase 5 only needs Teams outbound for the HITL card.
- **GitOps repo configuration** — REMEDI-008 requires knowing the GitOps repo URL and target branch per Arc K8s cluster. This configuration lives in a PostgreSQL table (platform settings). Planner to include schema definition for this config table.

</specifics>

<deferred>
## Deferred Ideas

### Operator Workflow Files
A user-defined workflow capability was explored during discussion: markdown files defining multi-step processes (calling agents, runbooks, external systems, HITL gates) that agents can retrieve via RAG when an incident matches a known workflow pattern. The purpose is to let operators map the platform to their existing operational workflows (potentially integrating with ITSM, change management, or other systems). This is a new capability with its own phase-worth of scope:
- Workflow schema and storage (separate from runbooks)
- Step execution engine (sequential/conditional/parallel steps)
- External system integration connectors
- Workflow-level HITL gates (not just remediation-level)
- Workflow retrieval and matching logic
- UI for workflow authoring and status tracking

**Recommendation:** Add as Phase 7.5 or v2 feature. Phase 5 delivers the runbook RAG foundation that this capability would extend.

### APIM Standard v2
Phase 2 deferred Azure API Management Standard v2 to Phase 5/6. With Phase 5 adding `/api/v1/chat`, `/api/v1/approvals/*`, and `/api/v1/runbooks/search`, the justification threshold is now met. Deferred to Phase 6 or Phase 7 to avoid scope creep in Phase 5 — review at Phase 6 planning.

### Reviewed Todos (not folded)
No pending todos were matched to Phase 5 scope.

</deferred>

---

*Phase: 05-triage-remediation-web-ui*
*Context gathered: 2026-03-27*
