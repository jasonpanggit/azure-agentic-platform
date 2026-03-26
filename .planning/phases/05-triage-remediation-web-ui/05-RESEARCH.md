# Phase 5: Triage & Remediation + Web UI - Research

**Researched:** 2026-03-27
**Status:** Complete - ready for planning
**Phase Requirements:** TRIAGE-005, TRIAGE-007, REMEDI-002, REMEDI-003, REMEDI-004, REMEDI-005, REMEDI-006, REMEDI-008, UI-001, UI-002, UI-003, UI-004, UI-005, UI-006, UI-007, UI-008, AUDIT-002, AUDIT-004

---

## Table of Contents

1. [Phase Scope Summary](#1-phase-scope-summary)
2. [Web UI Architecture](#2-web-ui-architecture)
3. [SSE Streaming Architecture](#3-sse-streaming-architecture)
4. [Runbook RAG System](#4-runbook-rag-system)
5. [HITL Approval Gate](#5-hitl-approval-gate)
6. [Resource Identity Certainty](#6-resource-identity-certainty)
7. [GitOps Remediation Path](#7-gitops-remediation-path)
8. [API Gateway Extensions](#8-api-gateway-extensions)
9. [Audit Trail](#9-audit-trail)
10. [Existing Code Reuse Map](#10-existing-code-reuse-map)
11. [Technical Risks & Mitigations](#11-technical-risks--mitigations)
12. [Package & Version Matrix](#12-package--version-matrix)
13. [Work Decomposition Candidates](#13-work-decomposition-candidates)
14. [Validation Architecture](#validation-architecture)

---

## 1. Phase Scope Summary

Phase 5 delivers four interconnected systems on top of the Phase 1-4 foundation:

| System | Primary Requirements | Key Artifacts |
|--------|---------------------|---------------|
| **Web UI** | UI-001 through UI-008 | `services/web-ui/` (new Next.js Container App) |
| **Dual SSE Streaming** | TRIAGE-007, UI-003, UI-004, UI-008 | `/api/stream` Route Handler + SSE client hooks |
| **Runbook RAG** | TRIAGE-005 | PostgreSQL `runbooks` table + embedding pipeline + agent integration |
| **HITL + Remediation** | REMEDI-002 through REMEDI-008, AUDIT-002 | Approval endpoints on api-gateway + Cosmos DB records + agent logic |

**What Phase 5 does NOT deliver:**
- No Teams bot (Phase 6) -- but Phase 5 posts the Adaptive Card to Teams via Teams API for REMEDI-002
- No Terraform IaC changes (all infra already provisioned in Phases 1-4)
- No APIM (deferred to Phase 6/7 per 05-CONTEXT.md)
- No Playwright E2E against deployed infra (Phase 7) -- but Phase 5 tests run locally/in CI against mocks

---

## 2. Web UI Architecture

### 2.1 Technology Stack

| Component | Package | Version | Notes |
|-----------|---------|---------|-------|
| Framework | `next` | 15.x | App Router, Node.js runtime (NOT Edge -- needed for Azure SDK calls) |
| UI Library | `@fluentui/react-components` | 9.73.4 | Griffel CSS-in-JS; all components `"use client"` |
| Auth | `@azure/msal-browser` + `@azure/msal-react` | latest v3 | PKCE is default in v3; `MsalProvider` wraps app in client component |
| Split pane | `react-resizable-panels` | latest | `PanelGroup` + `Panel` + `PanelResizeHandle`; SSR-safe; `autoSaveId` for layout persistence |
| Markdown | `react-markdown` | latest | For rendering agent responses with markdown formatting |

### 2.2 MSAL PKCE Integration

**Key findings from research:**

- `@azure/msal-browser` v3+ uses PKCE with Authorization Code Flow by default -- no extra config needed.
- MSAL is client-side only. In Next.js App Router, every MSAL-using component MUST have `"use client"` directive.
- `MsalProvider` wraps the app in a Client Component (typically `app/providers.tsx`).
- `msalInstance.initialize()` MUST complete before calling login methods (MSAL v3 requirement).
- `msalInstance.handleRedirectPromise()` must be called early to handle redirect flows.
- Silent token acquisition via `acquireTokenSilent()` handles token refresh automatically.
- Scopes needed: `api://aiops-web-ui/incidents.read`, `api://aiops-web-ui/approvals.write`.
- Auth state exists only on client; server components CANNOT access MSAL tokens directly -- API calls go through Route Handlers or the BFF pattern.

**Implementation pattern:**
```
app/
  layout.tsx          -- imports Providers (client component)
  providers.tsx       -- "use client"; MsalProvider + FluentProvider
  page.tsx            -- server component; minimal shell
  (auth)/
    login/page.tsx    -- login redirect
    callback/page.tsx -- handle redirect promise
```

**Risk:** Hydration mismatches between server and client for auth-dependent UI. Mitigation: `AuthenticatedTemplate`/`UnauthenticatedTemplate` from `@azure/msal-react` with a loading skeleton on first render.

### 2.3 Split-Pane Layout (UI-002)

**Decision from CONTEXT:** Claude's discretion on proportions. Research recommendation:

- Use `react-resizable-panels` (by bvaughn) -- production-tested, SSR-safe, minimal bundle size.
- Default split: **35% chat / 65% dashboard** (operator workflow prioritizes dashboard initially).
- Minimum chat panel: 25%; minimum dashboard panel: 40%.
- `autoSaveId="aap-main-layout"` persists resize state to localStorage.
- Right-pane tabs (from UI-002): Alerts (default), Topology, Resources, Audit Log.
- Fluent UI v9 `TabList` + `Tab` components for right-pane tab navigation.

**Desktop-only (D-04):** CSS `min-width: 1200px` with Fluent `MessageBar` for sub-breakpoint devices.

### 2.4 Fluent UI v9 Component Strategy

**Key finding:** Fluent UI v9 does NOT ship a dedicated chat/message-bubble component. Options:

| Option | Verdict |
|--------|---------|
| `@fluentui-contrib/react-chat` | Community contrib with `ChatMessage`, `ChatMyMessage`. Check maturity before adopting. |
| Custom bubbles with Fluent v9 primitives | `Card` + `Text` + `makeStyles` + `tokens`. Full control, no external dependency. |
| `@fluentui/react-northstar` Chat | REJECT -- legacy, Teams-specific, being deprecated. |

**Recommendation:** Build custom chat bubbles using Fluent v9 primitives (`Card`, `Text`, `Avatar`, `Persona`, `makeStyles`). This avoids contrib package maturity risks and gives full control over streaming behavior (cursor animation, agent name annotation, proposal card embedding).

**Components to build:**
| Component | Fluent v9 Base | Purpose |
|-----------|---------------|---------|
| `ChatBubble` | `Card` + `Text` | Agent message with streaming cursor |
| `AgentAvatar` | `Avatar` + `Persona` | Agent name + domain badge |
| `ThinkingIndicator` | `Spinner` + `Text` | Shown during handoff gaps |
| `ProposalCard` | `Card` + `Button` + `Badge` + `CountdownTimer` | Approve/Reject + expiry timer (UI-005) |
| `TraceTree` | `Tree` + `TreeItem` | Expandable JSON tree for traces (UI-004) |
| `AlertFeed` | `DataGrid` + `Badge` + `FilterBar` | Real-time alert list with filters (UI-006) |
| `SubscriptionSelector` | `Combobox` + `Tag` | Multi-subscription picker (UI-007) |
| `AuditLogViewer` | `DataGrid` + `FilterBar` | Agent action history (AUDIT-004) |

### 2.5 Next.js App Router SSR Considerations

- Fluent UI v9 uses Griffel (CSS-in-JS). For SSR, need `createDOMRenderer` + `renderToStyleElements` in `app/layout.tsx`.
- All interactive components (chat, alerts, traces) are `"use client"` -- server components only used for layout shell and static UI.
- `export const runtime = 'nodejs'` on API Route Handlers -- NOT Edge (Azure SDK requires Node.js APIs).
- `export const dynamic = 'force-dynamic'` on SSE route to prevent caching.

### 2.6 Container App Deployment

- New Container App: `web-ui` in the existing Container Apps environment.
- Dockerfile: `FROM node:20-slim` -> `npm ci --production` -> `npm run build` -> `npx next start`.
- Port: 3000 (Next.js default).
- Environment variables: `NEXT_PUBLIC_AZURE_CLIENT_ID`, `NEXT_PUBLIC_TENANT_ID`, `NEXT_PUBLIC_REDIRECT_URI`, `API_GATEWAY_URL` (internal FQDN).
- Public ingress enabled (operator-facing).
- Container size: 1 vCPU / 2 GiB RAM (Node.js runtime; sufficient for BFF + SSE proxying).
- GitHub Actions workflow: extends existing `docker-push.yml` reusable workflow pattern.

---

## 3. SSE Streaming Architecture

### 3.1 Architecture Decision: Two EventSource Connections (D-07)

Per CONTEXT decision D-07, the client opens **two separate EventSource connections** -- one for `event:token` and one for `event:trace`. Each has its own `Last-Event-ID` cursor and sequence namespace.

**Research insight from ARCHITECTURE.md Section 3.1:** The original architecture doc shows a SINGLE SSE connection with two event types multiplexed via `event:` field. D-07 overrides this to two connections for independent reconnect resilience. The planner MUST reconcile this -- the CONTEXT decision (D-07) takes precedence.

**Why two connections is better for this platform:**
- Independent reconnect: losing the trace stream doesn't affect token rendering.
- Separate `Last-Event-ID` namespaces prevent ID collisions.
- Different buffer requirements: token events are ephemeral (can miss a few), trace events must be durable (tool calls, approvals are auditable).
- Separate backpressure: trace events can be large (JSON payloads); token events are tiny deltas.

### 3.2 SSE Route Handler Design (`/api/stream`)

The Next.js BFF hosts the SSE endpoint (D-05). It proxies from the Foundry thread stream.

**Implementation pattern:**
```
Browser EventSource                Next.js /api/stream              API Gateway / Foundry
     |                                    |                                |
     |-- GET /api/stream?thread=X ------->|                                |
     |   Last-Event-ID: 42               |-- Foundry thread.stream(X) --->|
     |                                    |                                |
     |<-- event: token\n                  |<-- text_delta chunk ----------|
     |    data: {"delta":"...","seq":43}  |                                |
     |<-- event: trace\n                  |<-- tool_call event -----------|
     |    data: {"type":"tool","seq":44}  |                                |
     |<-- : heartbeat\n\n                 |  (20s timer)                   |
```

**Key implementation details:**

1. **ReadableStream in Route Handler** -- Native Web API, no framework dependency. Use `new ReadableStream({ async start(controller) { ... } })`.
2. **Heartbeat timer (UI-008):** Send SSE comment (`: heartbeat\n\n`) every 20 seconds. Azure Container Apps idle timeout is 240 seconds (confirmed by [Microsoft Tech Community](https://techcommunity.microsoft.com/blog/appsonazure/mcp-with-sse-on-azure-container-apps-a-quick-guide/4408635)). 20-second interval provides 12x safety margin.
3. **`request.signal.addEventListener('abort', ...)` for cleanup** -- detect client disconnect, stop streaming, clear heartbeat interval.
4. **Monotonic sequence numbers (TRIAGE-007):** Global counter per stream, incremented for every event (token OR trace). Client validates monotonicity on receive.
5. **`Last-Event-ID` reconnect (TRIAGE-007):** Server-side ring buffer per thread (in-memory Map, bounded size ~1000 events). On reconnect with `Last-Event-ID`, replay missed events from buffer before resuming live stream.

### 3.3 Event Buffer Strategy for Reconnection

**Research finding (production patterns):**

The `Last-Event-ID` reconnect requires server-side event buffering. Options evaluated:

| Strategy | Verdict | Rationale |
|----------|---------|-----------|
| **In-memory ring buffer (per thread)** | RECOMMENDED for Phase 5 | Simple, sufficient for single-instance Container App; bounded memory; events are ephemeral per-conversation |
| Redis Streams | Overkill for Phase 5 | Adds infrastructure dependency; valuable for multi-instance horizontal scaling (Phase 7+ if needed) |
| Cosmos DB event log | Too expensive | Writing every SSE event to Cosmos is cost-prohibitive and adds latency |

**Ring buffer specification:**
- Max 1000 events per thread (configurable).
- Keyed by `thread_id` in a `Map<string, CircularBuffer>`.
- Events evicted on thread completion or after 30-minute TTL.
- On reconnect: scan buffer for events with `seq > Last-Event-ID`, replay in order.

### 3.4 Foundry Thread Streaming Integration

**How to consume the Foundry thread as an SSE source:**

The `azure-ai-projects` SDK (`AIProjectClient.agents`) exposes streaming via `create_and_process_run` with streaming mode, or via polling with `get_run` + `list_messages`. The architecture doc (Section 3.4) shows an async generator `streamFoundryThread()` that yields typed chunks.

**Key API calls (azure-ai-projects 2.0.1):**
- `client.agents.create_thread()` -- create conversation thread
- `client.agents.create_message(thread_id, role, content)` -- add message
- `client.agents.create_run(thread_id, assistant_id)` -- start run
- `client.agents.submit_tool_outputs_to_run(thread_id, run_id, tool_outputs)` -- resume after tool call / approval
- Streaming: iterate over run events via the Responses API SSE format

**The BFF translates Foundry events to our SSE format:**
- `thread.message.delta` -> `event: token`
- `thread.run.step.created` (tool_call type) -> `event: trace`
- Handoff detection -> synthetic `event: trace` (handoff_start/handoff_end)
- Approval gate detection -> `event: trace` (approval_gate)
- `thread.run.completed` -> `event: done`

### 3.5 Alert Feed SSE (UI-006)

Decision from CONTEXT: Claude's discretion on whether to use Cosmos DB change feed -> SSE or polling.

**Research recommendation: Cosmos DB change feed -> internal push -> SSE**

Pattern:
1. A lightweight background process in the api-gateway (or a separate sidecar) subscribes to the Cosmos DB change feed on the `incidents` container.
2. Changes are pushed to an in-memory pub/sub (e.g., Python `asyncio.Queue` per subscriber, or a simple broadcast pattern).
3. The SSE route in Next.js BFF polls the api-gateway's alert stream endpoint.
4. Client receives `event: alert` events on a separate EventSource connection.

**Alternative (simpler for Phase 5):** Polling with 5-second interval from the Web UI to `GET /api/v1/incidents?since={timestamp}`. Cosmos DB change feed integration deferred to Phase 7 optimization.

**Recommendation for planner:** Start with polling (simpler, fewer moving parts), flag change feed as Phase 7 optimization.

---

## 4. Runbook RAG System

### 4.1 Data Model (D-16)

Single `runbooks` table in PostgreSQL:

```sql
CREATE TABLE runbooks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    domain      TEXT NOT NULL CHECK (domain IN ('compute','network','storage','security','arc','sre')),
    version     TEXT NOT NULL DEFAULT '1.0',
    content     TEXT NOT NULL,
    embedding   vector(1536) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index for cosine similarity (preferred over IVFFlat for better recall)
CREATE INDEX idx_runbooks_embedding ON runbooks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Domain filter index for filtered vector search
CREATE INDEX idx_runbooks_domain ON runbooks (domain);
```

**Key research finding:** pgvector 0.7+ supports HNSW indexing, which is preferred over IVFFlat for better recall quality. HNSW does not require a training step and works well with small collections (~60 runbooks).

### 4.2 Embedding Pipeline

**Model:** Azure OpenAI `text-embedding-3-small` (D-17) -- 1536 dimensions, already deployed in Foundry workspace.

**Embedding generation flow:**
1. Seed script reads runbook content from markdown files (or inline fixtures).
2. Calls Azure OpenAI embedding endpoint via `openai` Python SDK (with Azure config).
3. Inserts into PostgreSQL with the embedding vector.

**Python library choice for pgvector:**
- `pgvector` Python package (`pip install pgvector`) -- provides `register_vector()` for asyncpg.
- Use `asyncpg` for async PostgreSQL access (matches existing project's async pattern).
- Alternative: `psycopg[binary]` with pgvector support -- both are listed in CLAUDE.md.

**Recommendation:** Use `asyncpg` + `pgvector` for the runtime search path (async, high performance). Use `psycopg[binary]` for the seed script (simpler sync API for one-time bulk insert).

### 4.3 Retrieval API

**Decision D-19:** `GET /api/v1/runbooks/search?query=...&domain=...&limit=3` on the api-gateway.

**Implementation flow:**
1. Receive query text + optional domain filter.
2. Generate embedding for query text via Azure OpenAI.
3. Execute pgvector cosine similarity search:
   ```sql
   SELECT id, title, domain, version, content,
          1 - (embedding <=> $1::vector) AS similarity
   FROM runbooks
   WHERE ($2::text IS NULL OR domain = $2)
   ORDER BY embedding <=> $1::vector
   LIMIT $3
   ```
4. Filter results by similarity threshold (>0.75 per TRIAGE-005).
5. Return top-3 results with `{ title, domain, version, similarity, content_excerpt }`.

**Performance target:** <500ms end-to-end (TRIAGE-005 SC-3). With ~60 runbooks and HNSW index, this is easily achievable -- pgvector HNSW on 60 vectors is sub-millisecond; the bottleneck will be the embedding API call (~100-200ms).

**Optimization:** Cache embeddings for frequent queries using an LRU cache (configurable TTL).

### 4.4 Agent Integration

Domain agents need a `retrieve_runbooks` tool/function that:
1. Takes the incident context (symptoms, resource type, domain).
2. Constructs a search query from the diagnosis hypothesis.
3. Calls the runbook retrieval API (or directly queries PostgreSQL if internal).
4. Includes the top-3 runbooks in the triage response with name, version, and relevance score.

**Integration pattern:** Add `retrieve_runbooks` as an `@ai_function` tool on each domain agent. The tool calls the api-gateway's `/api/v1/runbooks/search` endpoint internally.

### 4.5 Seed Data Strategy (D-18)

~10 synthetic runbooks per domain (~60 total). Categories per domain:

| Domain | Runbook Topics |
|--------|---------------|
| Compute | VM high CPU, VM high memory, VM disk full, VM unresponsive, VMSS scaling failure, App Service 5xx errors, Function App timeout, AKS node NotReady, batch job failure, VM extension failure |
| Network | NSG rule misconfiguration, load balancer health probe failure, DNS resolution failure, VPN gateway disconnect, application gateway 502, ExpressRoute circuit down, NIC detached, DDoS attack detected, peering misconfiguration, traffic manager failover |
| Storage | Storage account throttling, blob access denied, file share quota exceeded, storage replication lag, CORS misconfiguration, lifecycle management failure, data lake permission error, queue processing backlog, table storage timeout, disk snapshot failure |
| Security | Key Vault access denied, Defender alert critical, unauthorized access attempt, certificate expiry imminent, RBAC misconfiguration, managed identity failure, network exposure detected, encryption key rotation failure, compliance violation, secret exposure |
| Arc | Arc server disconnected, Arc agent version outdated, extension install failure, policy compliance drift, GitOps reconciliation failure, Arc K8s node NotReady, Arc data service unavailable, hybrid connectivity lost, guest configuration failure, Arc enrollment error |
| SRE | Alert storm detected, cascading failure, resource quota exhaustion, deployment rollback needed, change-caused incident, monitoring gap detected, incident correlation workflow, capacity planning trigger, performance degradation cross-domain, service dependency failure |

### 4.6 Database Migration Strategy

**Decision from CONTEXT:** Claude's discretion on migration tooling.

**Recommendation:** Use a simple SQL migration script (not a full migration framework like Alembic) since this is a single-table addition to an already-provisioned PostgreSQL server.

```
services/api-gateway/migrations/
  001_create_runbooks_table.sql    -- CREATE TABLE + indexes
  002_seed_runbooks.py             -- Python script to embed and insert seed data
```

The migration runs via the same CI pattern as Phase 1's pgvector setup -- temporary firewall rule on the VNet-isolated PostgreSQL server from GitHub Actions runner.

---

## 5. HITL Approval Gate

### 5.1 Thread Parking Pattern (D-10)

**Write-then-return pattern (NOT polling):**

1. Agent produces a `RemediationProposal` with `risk_level: high|critical`.
2. Agent writes an approval record to Cosmos DB (`approvals` container) with `status: pending`, `expires_at: now + 30min`.
3. Agent captures a resource state snapshot (for Resource Identity Certainty -- see Section 6).
4. Agent posts an Adaptive Card to Teams channel via Teams API (outbound only -- no bot needed).
5. Agent returns from its current turn. The Foundry thread is **idle** (not blocked, not polling).
6. The webhook callback (from Teams card action or Web UI button) posts a new message to the Foundry thread to resume.

**Critical research finding on Foundry thread resume:**

The `azure-ai-projects` SDK supports resuming a parked thread via:
```python
# When approval webhook fires:
client.agents.create_message(
    thread_id=thread_id,
    role="user",
    content=json.dumps({
        "message_type": "approval_response",
        "approval_id": approval_id,
        "status": "approved",  # or "rejected"
        "decided_by": user_id,
    })
)
# Then create a new run to continue processing
client.agents.create_run(
    thread_id=thread_id,
    assistant_id=agent_id,
)
```

This is the "inject approval result into Foundry thread" pattern from ARCHITECTURE.md Section 6.2. The key insight: the thread is NOT "suspended" -- it's simply idle with no active run. The webhook creates a new message + new run to resume.

### 5.2 Approval Record Schema (D-12)

```json
{
    "id": "appr_<uuid>",
    "action_id": "act_<uuid>",
    "thread_id": "thread_<id>",
    "incident_id": "inc_<id>",
    "agent_name": "compute",
    "status": "pending | approved | rejected | expired | executed | aborted",
    "risk_level": "high | critical",
    "proposed_at": "2026-03-27T14:30:00Z",
    "expires_at": "2026-03-27T15:00:00Z",
    "decided_at": null,
    "decided_by": null,
    "executed_at": null,
    "abort_reason": null,
    "resource_snapshot": {
        "resource_id": "/subscriptions/.../providers/.../vm-prod-01",
        "provisioning_state": "Succeeded",
        "tags": {"environment": "production", "team": "platform"},
        "resource_health": "Available",
        "snapshot_hash": "sha256:abc123..."
    },
    "proposal": {
        "description": "Restart VM vm-prod-01",
        "target_resources": ["/subscriptions/.../vm-prod-01"],
        "estimated_impact": "~2 min downtime",
        "risk_level": "high",
        "reversibility": "reversible",
        "action_type": "restart"
    }
}
```

**Partition key:** `/thread_id` (already provisioned in Phase 1 cosmos.tf).
**ETag concurrency:** All writes use `match_condition="IfMatch"` (reuse pattern from `BudgetTracker`).

### 5.3 Approval API Endpoints (D-09)

Added to the existing api-gateway:

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `POST /api/v1/approvals/{id}/approve` | POST | Entra Bearer | Approve a pending proposal |
| `POST /api/v1/approvals/{id}/reject` | POST | Entra Bearer | Reject a pending proposal |
| `GET /api/v1/approvals/{id}` | GET | Entra Bearer | Get approval status |
| `GET /api/v1/approvals?thread_id=X` | GET | Entra Bearer | List approvals for a thread |

**Expiry enforcement (D-13):**
- On every `approve`/`reject` request, check `expires_at`. If `now() > expires_at`, return `410 Gone` and update record to `status: expired`.
- Background: no background job needed for expiry. Expiry is enforced lazily (check-on-access) plus the agent checks expiry before execution.

### 5.4 Teams Adaptive Card Posting (REMEDI-002 partial)

Phase 5 only needs outbound card posting (no bot). Pattern:

1. Agent detects high-risk proposal.
2. Api-gateway (or agent directly) calls Teams Graph API to post an Adaptive Card to a configured channel.
3. Card includes `Action.Submit` buttons for Approve/Reject that POST back to the api-gateway webhook endpoints.

**Research finding on bot-less Teams integration:**
- As of 2025, Microsoft is retiring O365 Connectors. The recommended path is the **Workflows app** (Power Automate triggered).
- However, for programmatic card posting from a backend service, the Microsoft Graph API (`POST /teams/{team-id}/channels/{channel-id}/messages`) with an app registration (not a bot) works.
- `Action.Http` in Adaptive Cards can POST directly to an external URL (the api-gateway approval endpoint).
- This requires the app registration to have `ChannelMessage.Send` permission.

**Important constraint:** Adaptive Card `Action.Http` works from Outlook but has limited support in Teams. For Teams, `Action.Submit` with a bot backend is the standard pattern. Since Phase 5 is NOT building the full bot, the planner has two options:

1. **Use Power Automate / Workflows app** to post the card and handle button actions (no code).
2. **Register a minimal bot** (Azure Bot Service + app registration) that can post cards and receive action submissions. This is a lightweight shim that forwards to the api-gateway webhook.

**Recommendation for planner:** Option 2 (minimal bot shim) is more aligned with Phase 6's full Teams bot. Phase 5 creates the bot registration and minimal message handler; Phase 6 extends it to full two-way conversation.

### 5.5 Rate Limiting (REMEDI-006)

**Decision from CONTEXT:** Claude's discretion on implementation details.

**Recommendation:** In-memory rate limiter in the api-gateway using a sliding window counter per `(agent_name, subscription_id)` pair.

- Default: max 5 remediation actions per agent per subscription per minute (configurable via env var).
- Storage: Python `dict` with TTL-based cleanup (sufficient for single-instance; upgrade to Redis in Phase 7 if scaling).
- Protected tag guard: before executing, check resource tags. If `protected: true` tag exists, reject with `403`.
- Production scope confirmation: if `subscription_id` matches a configured prod subscription list, require explicit `scope_confirmed: true` in the approval payload.

---

## 6. Resource Identity Certainty

### 6.1 Protocol (D-11, REMEDI-004)

**From ARCHITECTURE.md Section 12, refined by D-11:**

**Snapshot at proposal time:**
- Resource ID (full ARM path)
- ARM provisioning state
- Resource tags (full tag map)
- ARM Resource Health availability state
- Resource-type-specific fields (e.g., `power_state` for VMs, `replica_count` for K8s deployments)
- SHA-256 hash of the above concatenated fields

**Re-verification before execution:**
1. Re-read resource via Azure MCP Server (or Arc MCP Server).
2. Compute hash of current state using same fields.
3. Compare against `resource_snapshot.snapshot_hash` from the approval record.
4. If hash diverges: abort with `stale_approval` error, update Cosmos DB record with `abort_reason: stale_approval`, notify operator.
5. If hash matches: proceed with execution.

### 6.2 Implementation on Shared Agent Code

Extend `agents/shared/triage.py`:

- Add `ResourceSnapshot` dataclass with fields: `resource_id`, `provisioning_state`, `tags`, `resource_health`, `snapshot_hash`, `captured_at`.
- Add `capture_resource_snapshot()` function that reads resource state and computes hash.
- Add `verify_resource_identity()` function that compares snapshot hash against current state.
- Extend `RemediationProposal` to include `resource_snapshot` field.

### 6.3 Signal Independence

The "2 independent signals" requirement (REMEDI-004) is satisfied by:
1. **Signal 1:** Resource ID match (exact ARM path comparison).
2. **Signal 2:** Resource state hash (includes provisioning_state + tags + resource_health).
3. **Signal 3 (bonus):** Subscription/resource group existence check (ARM 404 detection).

Signals 1 and 2 are always used. Signal 3 is a safety net for deleted/moved resources.

---

## 7. GitOps Remediation Path

### 7.1 Detection Logic (D-14, REMEDI-008)

The Arc Agent checks for GitOps controller presence on Arc K8s clusters:

1. Call Arc MCP Server: `arc_k8s_gitops_status(cluster_resource_id)`.
2. If Flux configurations returned with non-empty results -> GitOps-managed -> PR path.
3. If no Flux configs and no ArgoCD CRDs detected -> non-GitOps -> direct `kubectl apply` path.

**Detection via Arc MCP Server (already implemented in Phase 3):**
- `arc_k8s_gitops_status()` tool returns Flux configuration list.
- Empty list = no GitOps; non-empty = Flux-managed.
- ArgoCD detection: check for `argocd` namespace or ArgoCD CRD via `kubectl get crd` (requires exec capability or Arc extension check).

### 7.2 GitOps PR Creation (D-15)

**Configuration table in PostgreSQL:**
```sql
CREATE TABLE gitops_cluster_config (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_resource_id TEXT NOT NULL UNIQUE,
    gitops_repo_url TEXT NOT NULL,
    target_branch   TEXT NOT NULL DEFAULT 'main',
    github_token_kv_ref TEXT NOT NULL,  -- Key Vault secret reference
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**PR creation flow:**
1. Agent determines GitOps path is needed.
2. Queries `gitops_cluster_config` table for repo URL and branch.
3. Retrieves GitHub PAT from Key Vault.
4. Creates a feature branch: `aiops/fix-{incident_id}-{short_description}`.
5. Commits the updated YAML manifest.
6. Creates PR via GitHub REST API (`POST /repos/{owner}/{repo}/pulls`).
7. Posts PR link back to the incident record and operator.

**PR template (from ARCHITECTURE.md Section 14.3):**
- Branch: `aiops/fix-{incident_id}-{short_description}`
- Title: `[AAP] {remediation_summary}`
- Body: incident reference, RCA summary, change description, test plan, rollback instructions.

### 7.3 Playwright Test Design

Two separate tests per SC-6:
1. **GitOps path test:** Mock Arc K8s cluster with Flux detected -> assert PR creation API called -> assert correct branch name and PR body.
2. **Direct-apply path test:** Mock Arc K8s cluster without GitOps -> assert `kubectl apply` path taken -> assert no PR created.

---

## 8. API Gateway Extensions

### 8.1 New Endpoints

| Endpoint | Method | Model | Status Code | Purpose |
|----------|--------|-------|-------------|---------|
| `POST /api/v1/chat` | POST | `ChatRequest` -> `ChatResponse` | 202 | Create Foundry thread for operator-initiated chat (D-06) |
| `POST /api/v1/approvals/{id}/approve` | POST | `ApprovalAction` -> `ApprovalResponse` | 200 / 410 | Approve pending proposal |
| `POST /api/v1/approvals/{id}/reject` | POST | `ApprovalAction` -> `ApprovalResponse` | 200 / 410 | Reject pending proposal |
| `GET /api/v1/approvals/{id}` | GET | -> `ApprovalRecord` | 200 / 404 | Get approval status |
| `GET /api/v1/approvals` | GET | `?thread_id=X` -> `list[ApprovalRecord]` | 200 | List approvals for thread |
| `GET /api/v1/runbooks/search` | GET | `?query=X&domain=Y&limit=3` -> `list[RunbookResult]` | 200 | Search runbooks by vector similarity |
| `GET /api/v1/incidents` | GET | `?since=X&sub=Y&severity=Z` -> `list[IncidentSummary]` | 200 | List incidents (for alert feed) |

### 8.2 New Pydantic Models

Add to `services/api-gateway/models.py`:

```python
class ChatRequest(BaseModel):
    message: str
    incident_id: Optional[str] = None  # optionally attach to existing incident

class ChatResponse(BaseModel):
    thread_id: str
    status: str = "created"

class ApprovalAction(BaseModel):
    decided_by: str
    scope_confirmed: Optional[bool] = None  # required for prod subscriptions

class ApprovalResponse(BaseModel):
    approval_id: str
    status: str  # approved, rejected, expired, error

class ApprovalRecord(BaseModel):
    id: str
    action_id: str
    thread_id: str
    status: str
    proposed_at: str
    expires_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    proposal: dict

class RunbookResult(BaseModel):
    id: str
    title: str
    domain: str
    version: str
    similarity: float
    content_excerpt: str

class IncidentSummary(BaseModel):
    incident_id: str
    severity: str
    domain: str
    status: str
    created_at: str
    title: Optional[str] = None
```

### 8.3 Auth Scope Extension

The existing `EntraTokenValidator` in `auth.py` validates against `incidents.write` scope. Phase 5 needs additional scopes:
- `api://aiops-web-ui/incidents.read` -- for alert feed
- `api://aiops-web-ui/approvals.write` -- for approve/reject actions
- `api://aiops-web-ui/chat.write` -- for initiating chat

The Entra app registration needs these scopes added. This is a configuration change, not a code change (the validator checks audience, not specific scopes in the current implementation).

---

## 9. Audit Trail

### 9.1 Cosmos DB + OneLake Dual Write (AUDIT-002)

Every approval state transition must be written to both:
1. **Cosmos DB `approvals` container** (hot-path query) -- already handled by the approval endpoints.
2. **Fabric OneLake** (long-term retention >=2 years) -- requires a sync mechanism.

**OneLake sync options:**

| Option | Verdict | Rationale |
|--------|---------|-----------|
| Cosmos DB change feed -> Azure Function -> OneLake write | Recommended | Decoupled, reliable, uses existing Fabric OneLake lakehouse from Phase 4 |
| Dual-write in api-gateway (write to both Cosmos and OneLake on each request) | Acceptable for Phase 5 | Simpler, but tightly coupled; OneLake write failure shouldn't block the approval |
| Cosmos DB Analytical Store -> Synapse Link -> OneLake | Over-engineered | Adds Synapse Link complexity; overkill for approval records |

**Recommendation for Phase 5:** Dual-write with non-blocking OneLake write (fire-and-forget with error logging). The api-gateway writes to Cosmos DB (blocking, must succeed) and then asynchronously writes to OneLake (non-blocking, logged on failure). Phase 7 can add a change-feed-based sync for reliability.

### 9.2 Audit Log Tab (AUDIT-004)

The Web UI Audit Log tab queries the api-gateway for agent action history.

**Data source:** OpenTelemetry spans in Application Insights (already exported per AUDIT-001 from Phase 2).

**API:** A new `GET /api/v1/audit?incident_id=X&agent=Y&action=Z&from=T1&to=T2` endpoint on the api-gateway that queries Application Insights via the Log Analytics query API (KQL).

**UI component:** `DataGrid` with columns: timestamp, agent, tool, action, resource, outcome, duration. Filterable by agent, action type, resource, time range.

---

## 10. Existing Code Reuse Map

| Existing Asset | Reuse in Phase 5 | Notes |
|---------------|-------------------|-------|
| `services/api-gateway/main.py` | Add new route handlers (chat, approvals, runbooks, incidents list) | Same FastAPI app, same middleware, same auth |
| `services/api-gateway/auth.py` | Use `verify_token` Depends for all new endpoints | No changes needed; scope validation is audience-level |
| `services/api-gateway/foundry.py` | Reuse `_get_foundry_client()` and `create_foundry_thread()` for chat endpoint | Only needs different `initial_message` format for chat vs. incident |
| `services/api-gateway/models.py` | Add new Pydantic models alongside existing ones | Pattern established |
| `agents/shared/triage.py` | Extend `RemediationProposal` with `resource_snapshot` field | Add `ResourceSnapshot` class |
| `agents/shared/envelope.py` | Add `"approval_request"` and `"approval_response"` to `VALID_MESSAGE_TYPES` | One-line additions |
| `agents/shared/budget.py` | Reuse ETag optimistic concurrency pattern for approval record writes | Same `read -> mutate -> replace with IfMatch` pattern |
| `terraform/modules/databases/cosmos.tf` | `approvals` container already provisioned (partition key: `/thread_id`) | No Terraform changes needed |
| `terraform/modules/databases/postgres.tf` | pgvector extension already enabled; add `runbooks` table via migration script | SQL migration, not Terraform |
| `.github/workflows/docker-push.yml` | Reuse for `web-ui` container image build | New workflow file that calls reusable workflow |
| `services/api-gateway/Dockerfile` | Pattern for `services/web-ui/Dockerfile` | Adapt for Node.js |
| Agent spec files (`docs/agents/*.spec.md`) | Add runbook retrieval step to workflow for all 6 domain agents | Spec update (documentation) |

---

## 11. Technical Risks & Mitigations

### Risk 1: Foundry Thread Resume Latency (HIGH)

**Risk:** The "inject message + create new run" pattern for resuming parked threads may have high latency (Foundry cold start for a new run).

**Mitigation:**
- SC-4 requires resume within 5 seconds of webhook callback.
- The Foundry Hosted Agent container should be warm (min replicas = 1 per agent).
- Measure resume latency in integration tests. If >5s, explore Foundry "warm pool" configuration or accept slightly longer resume times for cold-start scenarios.

### Risk 2: MSAL Hydration Mismatch (MEDIUM)

**Risk:** Next.js SSR renders unauthenticated state; client hydrates with MSAL-authenticated state, causing React hydration errors.

**Mitigation:**
- Use `AuthenticatedTemplate`/`UnauthenticatedTemplate` from `@azure/msal-react`.
- Show a loading skeleton on first render until MSAL initialization completes.
- Set `suppressHydrationWarning` on auth-dependent elements if needed.

### Risk 3: SSE Connection Stability on Container Apps (MEDIUM)

**Risk:** Azure Container Apps silently drops idle connections at 240 seconds. Heartbeat failures could cause data loss.

**Mitigation:**
- 20-second heartbeat interval (12x safety margin).
- Client-side `EventSource` automatic reconnect with `Last-Event-ID`.
- Server-side ring buffer for event replay.
- Confirmed by [Microsoft Tech Community article](https://techcommunity.microsoft.com/blog/appsonazure/mcp-with-sse-on-azure-container-apps-a-quick-guide/4408635): heartbeat is the recommended approach.

### Risk 4: pgvector Performance with Azure OpenAI Embedding Latency (LOW)

**Risk:** Embedding API call adds 100-200ms to every search; total must be <500ms.

**Mitigation:**
- pgvector HNSW search on 60 vectors is sub-1ms.
- Azure OpenAI embedding call to same-region Foundry endpoint: ~100-150ms.
- Total well within 500ms budget.
- LRU cache for repeated query embeddings reduces API calls.

### Risk 5: Scope Creep from 18 Requirements (HIGH)

**Risk:** Phase 5 has 18 requirements -- the most of any phase. Risk of scope creep and incomplete delivery.

**Mitigation:**
- Clear plan decomposition (see Section 13).
- Strict CONTEXT decisions (D-01 through D-19) reduce ambiguity.
- Desktop-only (D-04) eliminates mobile responsive work.
- APIM explicitly deferred.
- Teams bot explicitly limited to outbound card posting only.

### Risk 6: Two EventSource Connections vs. Single Connection (LOW)

**Risk:** D-07 mandates two separate EventSource connections, contradicting ARCHITECTURE.md's single-connection design. Browser limit of ~6 concurrent connections per domain.

**Mitigation:**
- Two connections is well within browser limits (6 per domain for HTTP/1.1, unlimited for HTTP/2).
- Container Apps supports HTTP/2 by default.
- If connection limits become an issue, multiplex onto a single connection (the ARCHITECTURE.md pattern) as a fallback.

---

## 12. Package & Version Matrix

### Python (api-gateway extensions)

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | existing | API framework |
| `azure-cosmos` | 4.x (existing) | Cosmos DB approval records |
| `azure-ai-projects` | 2.0.1 (existing) | Foundry thread management |
| `asyncpg` | 0.30.x | Async PostgreSQL for runbook search |
| `pgvector` | 0.3.x | pgvector support for asyncpg |
| `openai` | latest | Azure OpenAI embedding generation |
| `azure-storage-file-datalake` | 12.x | OneLake audit writes (AUDIT-002) |

### TypeScript (web-ui)

| Package | Version | Purpose |
|---------|---------|---------|
| `next` | 15.x | Framework |
| `react` / `react-dom` | 19.x | React (Next.js 15 default) |
| `@fluentui/react-components` | 9.73.4 | UI component library |
| `@azure/msal-browser` | 3.x | MSAL PKCE auth |
| `@azure/msal-react` | 2.x | React hooks for MSAL |
| `react-resizable-panels` | latest | Split-pane layout |
| `react-markdown` | latest | Markdown rendering in chat |
| `typescript` | 5.x | Type safety |

---

## 13. Work Decomposition Candidates

Based on research, the planner should consider the following plan structure:

### Plan 05-01: Web UI Foundation + MSAL Auth
- Next.js App Router project scaffolding (`services/web-ui/`)
- MSAL PKCE integration (login, token refresh, protected routes)
- Fluent UI v9 provider + Griffel SSR setup
- Split-pane layout with `react-resizable-panels`
- Tab navigation shell (Alerts, Topology, Resources, Audit Log)
- Dockerfile + GitHub Actions workflow for container image
- **Requirements:** UI-001, UI-002

### Plan 05-02: SSE Streaming + Chat Panel
- `/api/stream` Route Handler with ReadableStream
- Heartbeat timer (20s)
- Monotonic sequence numbers
- `Last-Event-ID` reconnect with ring buffer
- Foundry thread streaming integration (BFF proxy)
- Chat bubble components with streaming cursor
- Agent handoff "thinking" indicator
- Trace panel (expandable JSON tree)
- `POST /api/v1/chat` endpoint on api-gateway
- **Requirements:** TRIAGE-007, UI-003, UI-004, UI-008

### Plan 05-03: Runbook RAG
- PostgreSQL `runbooks` table migration (DDL + HNSW index)
- Embedding pipeline (Azure OpenAI `text-embedding-3-small`)
- Seed script with ~60 synthetic runbooks
- `GET /api/v1/runbooks/search` endpoint on api-gateway
- Domain agent integration (`retrieve_runbooks` tool)
- Agent spec updates for all 6 domain agents
- Unit tests: similarity threshold >0.75, latency <500ms
- **Requirements:** TRIAGE-005

### Plan 05-04: HITL Approval Gate + Remediation Flow
- Approval record schema + Cosmos DB writes (ETag concurrency)
- `POST /api/v1/approvals/{id}/approve` and `reject` endpoints
- Expiry enforcement (30-min default, 410 Gone for expired)
- Resource Identity Certainty (snapshot capture + re-verification)
- `stale_approval` abort path
- Foundry thread parking (write-then-return) and resume (message + run)
- Teams Adaptive Card posting (outbound only; minimal bot registration or Power Automate)
- Rate limiting per agent per subscription
- Protected tag guard
- Production scope confirmation
- Approval cards in Web UI chat panel (ProposalCard component)
- GitOps PR path for Arc K8s (Flux detection + GitHub API PR creation)
- `gitops_cluster_config` PostgreSQL table
- **Requirements:** REMEDI-002, REMEDI-003, REMEDI-004, REMEDI-005, REMEDI-006, REMEDI-008

### Plan 05-05: Alert Feed + Audit + Multi-Subscription
- Alert/incident feed (polling or change feed -> SSE)
- Subscription selector (multi-select, scopes all views)
- `GET /api/v1/incidents` list endpoint
- Audit Log tab (query Application Insights via KQL)
- `GET /api/v1/audit` endpoint
- Cosmos DB + OneLake dual write for approval records
- **Requirements:** UI-005, UI-006, UI-007, AUDIT-002, AUDIT-004

### Plan 05-06: Tests + CI
- Unit tests for all new api-gateway endpoints
- Unit tests for runbook retrieval and embedding
- Unit tests for approval lifecycle (pending -> approved/rejected/expired/aborted)
- Unit tests for Resource Identity Certainty (hash match, hash diverge -> abort)
- Unit tests for SSE reconnect (Last-Event-ID replay)
- Unit tests for rate limiting
- Integration test stubs for Foundry thread resume
- Web UI component tests (React Testing Library)
- Playwright tests for:
  - FMP <2s (SC-1)
  - SSE reconnect continuity (SC-2)
  - Runbook RAG similarity >0.75 (SC-3)
  - GitOps vs direct-apply path (SC-6)
- CI workflow updates

---

## Validation Architecture

This section maps each Phase 5 success criterion to a concrete, executable validation strategy. Every criterion must be covered by at least one test in Plan 05-06.

### SC-1 — Web UI Load + First Token Within 1s

**Criterion:** FMP <2s on cold load; `event:token` first token arrives within 1s of agent response start.

| Test Type | Tool | What It Asserts |
|-----------|------|-----------------|
| Playwright timing | `page.goto()` + `PerformanceObserver` | `LCP` entry's `startTime` < 2000ms in CI with cold container |
| Playwright SSE | Inject `window.performance.mark('token_start')` on SSE connect; mark `'first_token'` on first `event:token` | `first_token - token_start < 1000` |
| Unit | Mock Foundry stream | First `event:token` fires within 1s of `POST /api/v1/chat` response |

**CI gate:** Playwright test tagged `@sc1` fails the build if either timing assertion fails. Use `page.metrics()` in Playwright to capture DevTools timing in headless Chrome.

**Acceptance condition:** `performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd < 2000` AND time-to-first-token delta < 1000ms in Playwright assertions.

---

### SC-2 — Dual SSE Reconnect with Zero Duplication

**Criterion:** Two concurrent SSE streams with monotonic sequence numbers; after 10s connection drop, client reconnects via `Last-Event-ID` and receives all missed events in order, zero duplication.

| Test Type | Tool | What It Asserts |
|-----------|------|-----------------|
| Playwright SSE reconnect | `page.route()` to intercept and abort SSE connections at seq=N; verify reconnect sends `Last-Event-ID: N` | Header present on reconnect request |
| Playwright sequence check | Collect all `event:token` `seq` fields; assert strictly monotonically increasing | `seq[i+1] === seq[i] + 1` for all i |
| Playwright dedup check | After reconnect, collect full seq sequence; assert no value appears twice | `new Set(seqs).size === seqs.length` |
| Unit (ring buffer) | `test_ring_buffer.py`: insert events 1-100, query `since=50`, verify events 51-100 returned | Exact ID range, no gaps, no duplication |
| Unit (reconnect path) | POST `/api/stream?thread=X` with `Last-Event-ID: 42`; mock buffer returns events 43-50; assert all 8 events sent before live stream resumes | Sequence continuity check |

**CI gate:** Playwright test tagged `@sc2`; ring buffer unit tests in `pytest`. Both required for plan 05-06 acceptance.

**Acceptance condition:** Playwright asserts 0 sequence gaps AND 0 duplicate sequence numbers across a simulated 10-second drop-and-reconnect cycle.

---

### SC-3 — Runbook RAG Active: Top-3 Results >0.75 Similarity in <500ms

**Criterion:** Domain agent cites top-3 semantically relevant runbooks with name and version; known incident query returns cosine similarity >0.75 in <500ms.

| Test Type | Tool | What It Asserts |
|-----------|------|-----------------|
| Unit (retrieval latency) | `pytest` + `asyncio` timing around `GET /api/v1/runbooks/search` | `elapsed_ms < 500` |
| Unit (similarity threshold) | Query with known incident text; assert all 3 results have `similarity >= 0.75` | Each result's `similarity` field |
| Unit (citation format) | Mock agent triage response; assert response contains `runbook.title`, `runbook.version` | String presence check with regex |
| Integration | Run seed script; execute known-domain query (e.g., "VM CPU 100% for 15 minutes"); assert top result title matches expected runbook name | Exact title match |

**Fixture strategy:** Seed 3 canonical test runbooks with known embeddings (pre-computed, stored in fixtures). Tests do not call Azure OpenAI embedding API — they use stored embedding vectors. Only the similarity search path is exercised in unit tests.

**CI gate:** `pytest services/api-gateway/tests/test_runbook_rag.py -k similarity` must pass with pre-seeded vectors.

**Acceptance condition:** `test_known_incident_returns_relevant_runbooks` asserts `len(results) == 3` AND `all(r.similarity >= 0.75 for r in results)` AND elapsed < 500ms.

---

### SC-4 — HITL Gate: Card Posted, Thread Parked, Resume in <5s, Expiry Never Executes

**Criterion:** Adaptive Card posted to Teams on high-risk proposal; Foundry thread parks (no polling); resumes within 5s of webhook; expired (>30min) approval records `status: expired` and is never executed.

| Test Type | Tool | What It Asserts |
|-----------|------|-----------------|
| Unit (park) | Mock `create_run` not called after `RemediationProposal` with `risk_level: high` returned | `mock_create_run.call_count == 0` |
| Unit (Teams card) | Mock `TeamsNotifier.post_card()`; assert called with `approval_id`, `thread_id`, action buttons | Mock call args |
| Unit (resume latency) | Record `t0 = webhook_received`; record `t1 = create_run_called`; assert `t1 - t0 < 5000ms` | Timing assertion in integration test |
| Unit (expiry) | Create approval with `expires_at = now() - 1s`; call `POST /approvals/{id}/approve`; assert `410 Gone` and `status: expired` in Cosmos | HTTP status + Cosmos record |
| Unit (never execute after expiry) | Attempt execution with expired approval; assert `ExecutionGuard.check_approval()` raises `ApprovalExpiredError` | Exception type |
| Integration | Full flow: agent produces proposal → Cosmos write → webhook approve → thread resume → execution; assert full state machine transitions | Cosmos record transitions |

**CI gate:** `pytest tests/test_approval_lifecycle.py` must cover all 6 status transitions: `pending → approved → executed`, `pending → rejected`, `pending → expired`, `approved → aborted (stale)`.

**Acceptance condition:** State machine test asserts each transition produces the correct Cosmos record status AND the expiry guard prevents execution on any record where `now() > expires_at`.

---

### SC-5 — Resource Identity Certainty: `stale_approval` Abort

**Criterion:** 2+ independent signals verified before execution; resource state change after approval causes abort with `stale_approval`; Cosmos record shows `abort_reason: stale_approval`.

| Test Type | Tool | What It Asserts |
|-----------|------|-----------------|
| Unit (snapshot capture) | `test_capture_resource_snapshot()`; mock ARM reads; assert `snapshot_hash` is SHA-256 hex string with length 64 | Hash format and length |
| Unit (identity match) | Call `verify_resource_identity(snapshot, current)` with identical state; assert `True` | Return value |
| Unit (stale detection) | Modify one field in current state; assert `verify_resource_identity()` returns `False` | Return value |
| Unit (abort path) | Pre-approval state = A, post-approval state = B (diverged); assert `execute_remediation()` raises `StaleApprovalError`; assert Cosmos record `abort_reason == "stale_approval"` | Exception + Cosmos field |
| Unit (2-signal minimum) | Assert `capture_resource_snapshot()` always includes at least `resource_id` + `snapshot_hash` (2 independent signals) | Dataclass field presence |
| Playwright | Simulate resource change between approval and execution; assert `event:trace` contains `{"type":"error","reason":"stale_approval"}` in SSE stream | SSE event payload |

**CI gate:** `pytest tests/test_resource_identity.py` — 100% pass required; `stale_approval` Playwright test tagged `@sc5`.

**Acceptance condition:** `test_stale_approval_aborts_execution` asserts Cosmos record has `"abort_reason": "stale_approval"` AND execution function is not called past the identity check.

---

### SC-6 — GitOps vs Direct-Apply Path

**Criterion:** Arc K8s cluster with Flux → PR creation; without GitOps → direct-apply path. Both confirmed by separate Playwright tests.

| Test Type | Tool | What It Asserts |
|-----------|------|-----------------|
| Unit (Flux detection) | Mock `arc_k8s_gitops_status()` returning non-empty list; assert `is_gitops_managed() == True` | Return value |
| Unit (no-Flux detection) | Mock `arc_k8s_gitops_status()` returning empty list; assert `is_gitops_managed() == False` | Return value |
| Unit (PR creation) | Mock GitHub API `POST /repos/.../pulls`; assert called with correct branch name `aiops/fix-{incident_id}-*` and non-empty PR body | Mock call args + regex |
| Unit (direct-apply) | GitOps not detected; assert `kubectl_apply()` mock called; assert `github_create_pr()` mock NOT called | Call counts |
| Playwright (GitOps path) | Inject mock cluster config with `flux_detected: true`; trigger remediation; assert Web UI displays "PR created: aiops/fix-..." message in chat | Chat bubble text contains `aiops/fix-` |
| Playwright (direct-apply path) | Inject mock cluster config with `flux_detected: false`; trigger remediation; assert Web UI displays "Applied directly to cluster" message | Chat bubble text |

**CI gate:** `pytest tests/test_gitops_path.py` AND Playwright tests tagged `@sc6-gitops` and `@sc6-direct` must all pass.

**Acceptance condition:** The two Playwright tests assert mutually exclusive execution paths — one asserts PR creation, the other asserts direct apply — for the same remediation action on different cluster configurations.

---

### Validation Test File Map

| Plan | Test Files | Tags |
|------|-----------|------|
| 05-01 (Web UI Foundation) | `services/web-ui/__tests__/layout.test.tsx`, `services/web-ui/__tests__/auth.test.tsx` | `@unit` |
| 05-02 (SSE + Chat) | `services/api-gateway/tests/test_sse_stream.py`, `services/api-gateway/tests/test_ring_buffer.py`, `services/web-ui/__tests__/chat-panel.test.tsx`, `e2e/sc1.spec.ts`, `e2e/sc2.spec.ts` | `@sc1`, `@sc2` |
| 05-03 (Runbook RAG) | `services/api-gateway/tests/test_runbook_rag.py` | `@sc3` |
| 05-04 (HITL + Remediation) | `services/api-gateway/tests/test_approval_lifecycle.py`, `services/api-gateway/tests/test_resource_identity.py`, `services/api-gateway/tests/test_gitops_path.py`, `e2e/sc4.spec.ts`, `e2e/sc5.spec.ts`, `e2e/sc6.spec.ts` | `@sc4`, `@sc5`, `@sc6-gitops`, `@sc6-direct` |
| 05-05 (Alert Feed + Audit) | `services/api-gateway/tests/test_incidents.py`, `services/api-gateway/tests/test_audit.py`, `services/web-ui/__tests__/alert-feed.test.tsx` | `@unit` |
| 05-06 (Tests + CI) | All above + `services/api-gateway/tests/test_rate_limiting.py`, `services/api-gateway/tests/test_protected_tags.py` | All tags |

---

### Coverage Requirements

| Layer | Tool | Minimum |
|-------|------|---------|
| Python (api-gateway) | `pytest --cov=services/api-gateway --cov-report=xml` | 80% line coverage |
| TypeScript (web-ui) | `jest --coverage` | 80% branch coverage |
| E2E (Playwright) | All 6 SC tests pass | 100% (all 6 required) |

All SC tests (SC-1 through SC-6) are **blocking** — CI fails if any SC Playwright test fails.

## Research Sources

- [Scalable Server-Sent Events on Azure Container Apps](https://blog.nicholaschen.io/2025/04/15/scalable-server-sent-events-on-azure-container-apps/) -- Confirms 240s idle timeout, heartbeat pattern
- [MCP with SSE on Azure Container Apps: A Quick Guide](https://techcommunity.microsoft.com/blog/appsonazure/mcp-with-sse-on-azure-container-apps-a-quick-guide/4408635) -- Microsoft official guidance on SSE heartbeat for Container Apps
- [Scalable SSE with NestJS (Nick Hopman, Mar 2025)](https://dev.to/nickhopman/scalable-server-sent-events-sse-with-nestjs-from-basics-to-event-replay-with-redis-and-rxjs-a-production-grade-system-3gfm) -- Production-grade Last-Event-ID replay buffer pattern
- [Server-Sent Events: the alternative to WebSockets](https://germano.dev/sse-websockets/) -- Last-Event-ID reconnect architecture, event-driven store pattern
- [SSE Comprehensive Guide (ByteSizedAlex, 2025)](https://bytesizedalex.com/server-sent-events-sse/) -- SSE maturity in 2025, HTTP/3 support
- [Why SSE Are Making a Comeback (HackRead, 2025)](https://hackread.com/why-server-sent-events-sse-are-making-a-comeback/) -- SSE renaissance for AI streaming use cases
- [EventSource - MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/API/EventSource) -- Canonical EventSource API reference
- [pgvector GitHub](https://github.com/pgvector/pgvector) -- HNSW indexing, cosine similarity operators
- [react-resizable-panels GitHub](https://github.com/bvaughn/react-resizable-panels) -- SSR-safe split pane, autoSaveId
- `.planning/research/ARCHITECTURE.md` -- Dual SSE streaming design, HITL flow, Resource Identity Certainty protocol
- `.planning/research/SUMMARY.md` -- GBB research synthesis, pattern adoption decisions
- `CLAUDE.md` -- Technology stack, version matrix, "What NOT to Use" guidance

---

*Phase: 05-triage-remediation-web-ui*
*Research completed: 2026-03-27*
