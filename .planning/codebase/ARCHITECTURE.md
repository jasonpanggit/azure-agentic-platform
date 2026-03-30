# Azure Agentic Platform — System Architecture

> Last updated: 2026-03-30

---

## 1. High-Level System Design

The Azure Agentic Platform (AAP) is an enterprise AIOps platform that monitors, triages, and remediates Azure infrastructure incidents through a **domain-specialist multi-agent architecture**. It exposes a hybrid interface: a browser-based split-pane web UI (conversational chat + live dashboards) and a Microsoft Teams bot for alerts and approvals.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DETECTION PLANE (Fabric)                            │
│  Azure Monitor Alerts → Event Hub → Fabric Eventstream → Eventhouse (KQL)  │
│              → Fabric Activator → User Data Function                        │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ POST /api/v1/incidents  (Bearer token)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         API GATEWAY  (FastAPI)                              │
│  /api/v1/incidents  /api/v1/chat  /api/v1/approvals  /api/v1/audit         │
│  /api/v1/runbooks/search  /api/v1/azure-tools  /health                     │
│                                                                             │
│  Auth: Entra ID Bearer (fastapi-azure-auth)                                 │
│  Dedup: 2-layer (time-window collapse + open-incident correlation)          │
│  Storage: Cosmos DB (incidents, approvals, sessions)                        │
│  RAG: PostgreSQL + pgvector (runbooks)                                      │
└────────────────────┬────────────────────────────────────────────────────────┘
                     │  azure-ai-agents (Foundry SDK)
                     │  creates thread → posts envelope → starts run
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   AZURE AI FOUNDRY (Hosted Agent Runtime)                   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                      Orchestrator Agent                             │  │
│   │  HandoffOrchestrator — classifies domain, routes to specialist      │  │
│   └──────────────────────────┬──────────────────────────────────────────┘  │
│         ┌────────┬───────┬───┴───┬─────────┬────────┬──────┐              │
│         ▼        ▼       ▼       ▼         ▼        ▼      ▼              │
│    Compute  Network  Storage  Security   SRE      Arc    (future)          │
│    Agent    Agent    Agent    Agent    Agent    Agent                      │
└────────────────────┬────────────────────────────────────────────────────────┘
                     │ MCP tools (Azure MCP Server + custom Arc MCP Server)
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AZURE CONTROL PLANE                                 │
│  Log Analytics · Resource Health · Monitor Metrics · Activity Log          │
│  Arc Servers · Arc Kubernetes · Arc Data Services (via custom Arc MCP)      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐       ┌─────────────────────────────────────────────────┐
│   WEB UI         │       │                TEAMS BOT                        │
│  (Next.js 15)   │       │  (TypeScript, botbuilder, new Teams SDK)        │
│                 │       │  Proactive alerts · Approval cards · Chat        │
│  Chat Panel     │       │  /investigate <id> command                       │
│  Dashboard:     │       │  Bot → API Gateway (internal Container App URL)  │
│  · Alerts       │       └─────────────────────────────────────────────────┘
│  · Audit Log    │
│  · Topology     │
│  · Resources    │
│  · Observability│
└─────────────────┘
```

---

## 2. Component Inventory

| Component | Runtime | Language | Purpose |
|-----------|---------|----------|---------|
| **API Gateway** | Container App (external ingress) | Python / FastAPI | Single entry point for incident ingestion, chat dispatch, approvals, audit, runbook RAG |
| **Orchestrator Agent** | Foundry Hosted Agent | Python / agent-framework | Classifies incident domain, routes via HandoffOrchestrator to domain specialist |
| **Compute Agent** | Foundry Hosted Agent | Python / agent-framework | VMs, VMSS, AKS, App Service triage and remediation proposals |
| **Network Agent** | Foundry Hosted Agent | Python / agent-framework | VNets, NSGs, load balancers, DNS, ExpressRoute triage |
| **Storage Agent** | Foundry Hosted Agent | Python / agent-framework | Blob, Files, ADLS Gen2, managed disks triage |
| **Security Agent** | Foundry Hosted Agent | Python / agent-framework | Defender, Key Vault, RBAC drift triage |
| **SRE Agent** | Foundry Hosted Agent | Python / agent-framework | Cross-domain generalist, SLA/SLO, fallback for unclassified incidents |
| **Arc Agent** | Foundry Hosted Agent | Python / agent-framework | Arc Servers, Arc K8s, Arc Data Services; mounts Arc MCP Server via MCPTool |
| **Arc MCP Server** | Container App (internal) | Python / FastMCP | Custom MCP server bridging Azure MCP Server's Arc coverage gap; 9 Arc-specific tools |
| **Web UI** | Container App (external ingress) | TypeScript / Next.js 15 | Hybrid chat + dashboard UI, SSE streaming, approval gate UI |
| **Teams Bot** | Container App (external ingress) | TypeScript / botbuilder | Proactive alert delivery, Adaptive Card approvals, `/investigate` command |
| **Detection Plane** | Fabric SaaS | Python (User Data Fn) + KQL | Azure Monitor → Event Hub → Fabric Eventhouse → Activator → incident dispatch |

---

## 3. Data Flow Between Components

### 3A. Automated Alert Flow (Detection → Resolution)

```
1. Azure Monitor fires alert
        │
        ▼
2. Azure Event Hub receives alert event
        │
        ▼
3. Fabric Eventstream ingests → writes to Eventhouse (raw_alerts table)
        │
        ▼
4. Fabric Activator evaluates KQL rules:
   classify_domain(resource_type) → domain
   Fires trigger when: domain IS NOT NULL AND severity IN (Sev0–Sev2)
        │
        ▼
5. Fabric User Data Function (Python):
   - Acquires Entra Bearer token via MSAL (client credentials)
   - Maps DetectionResults row → IncidentPayload
   - POST /api/v1/incidents → API Gateway
        │
        ▼
6. API Gateway:
   a. Validates Bearer token (Entra ID / fastapi-azure-auth)
   b. Dedup Layer 1: check same resource_id + detection_rule within 5m
   c. Dedup Layer 2: check any open incident for resource_id
   d. If new: create Cosmos DB incident record (status: new)
   e. create_foundry_thread() → thread + envelope message + run
   │
   └─→ Response: 202 Accepted { thread_id, status: "dispatched" }
        │
        ▼
7. Foundry Orchestrator Agent run:
   - Reads incident envelope (AGENT-002 typed message)
   - Calls classify_incident_domain() if domain ambiguous
   - HandoffOrchestrator.handoff() to target domain agent
        │
        ▼
8. Domain Agent (e.g., Compute Agent) run:
   a. query_activity_log (TRIAGE-003 — mandatory first step)
   b. query_log_analytics (TRIAGE-002)
   c. query_resource_health (TRIAGE-002)
   d. query_monitor_metrics (MONITOR-001)
   e. Arc Agent additionally calls Arc MCP Server tools
   f. Produce structured diagnosis with confidence_score (TRIAGE-004)
   g. If remediation warranted: propose_remediation()
        │
        ▼
9. If remediation proposed:
   a. Agent writes approval record to Cosmos DB (status: pending)
   b. API Gateway posts Adaptive Card to Teams Bot via teams_notifier
   c. Teams Bot sends card to Teams channel (proactive message)
   d. Agent RETURNS (thread is idle — write-then-return pattern)
        │
        ▼
10. Operator reviews in Teams or Web UI
    - Clicks Approve/Reject on Adaptive Card
    - Teams Bot → POST /api/v1/approvals/{id}/approve (or reject)
    - API Gateway updates Cosmos DB record (status: approved/rejected)
    - Sends outcome card to Teams
```

### 3B. Operator Chat Flow

```
1. Operator types message in Web UI (ChatPanel)
        │
        ▼
2. POST /api/proxy/chat (Next.js API route — proxy)
        │
        ▼
3. POST /api/v1/chat → API Gateway
   - create_chat_thread(): create Foundry thread, post operator_query envelope, start run
   - Returns { thread_id, run_id }
        │
        ▼
4. Web UI opens SSE connection: GET /api/stream?thread_id=...&type=token
   - SSE Route Handler polls /api/proxy/chat/result every 2s
   - Emits token events as Foundry run completes
   - Heartbeat every 20s to keep connection alive through proxies
        │
        ▼
5. Orchestrator Agent processes operator query:
   - Detects conversational vs. structured input
   - Routes to domain agent via HandoffOrchestrator
   - Domain agent calls Azure MCP tools and returns diagnosis
        │
        ▼
6. SSE stream emits token events → ChatPanel renders streaming response
   If approval_gate event: ProposalCard rendered inline for human decision
```

---

## 4. Multi-Agent Orchestration Patterns

### 4A. Handoff Pattern (Primary)

The platform uses the **HandoffOrchestrator** pattern from the Microsoft Agent Framework exclusively. The Orchestrator is a `HandoffOrchestrator` instance with 6 registered `AgentTarget` entries pointing to Foundry agent IDs.

```
Incident arrives at Orchestrator
        │
        ▼
classify_incident_domain() — resource type prefix voting:
  "microsoft.compute" → compute
  "microsoft.network" → network
  "microsoft.storage" → storage
  "microsoft.keyvault" / "microsoft.security" → security
  "microsoft.hybridcompute" / "microsoft.kubernetes" → arc
  fallback → sre
        │
        ▼
HandoffOrchestrator.handoff(target=DOMAIN_AGENT_MAP[domain])
  → Transfers conversation to domain agent with typed envelope
```

**Domain → Agent map:**
| Domain | Agent Name | Foundry Agent ID Source |
|--------|------------|------------------------|
| `compute` | `compute-agent` | `COMPUTE_AGENT_ID` env var |
| `network` | `network-agent` | `NETWORK_AGENT_ID` env var |
| `storage` | `storage-agent` | `STORAGE_AGENT_ID` env var |
| `security` | `security-agent` | `SECURITY_AGENT_ID` env var |
| `sre` | `sre-agent` | `SRE_AGENT_ID` env var |
| `arc` | `arc-agent` | `ARC_AGENT_ID` env var |

### 4B. Typed Message Envelope (AGENT-002)

All inter-agent messages use the `IncidentMessage` TypedDict:

```python
{
  "correlation_id": str,    # incident_id — preserved through all hops (AUDIT-001)
  "thread_id": str,         # Foundry thread ID
  "source_agent": str,      # e.g., "api-gateway", "orchestrator"
  "target_agent": str,      # e.g., "compute-agent"
  "message_type": Literal[  # incident_handoff | diagnosis_complete |
                            #   remediation_proposal | cross_domain_request |
                            #   status_update | approval_request | approval_response
  "payload": dict,
  "timestamp": str          # ISO 8601
}
```

Raw string messages between agents are prohibited.

### 4C. Mandatory Triage Workflow (Domain Agents)

Every domain agent follows this ordered workflow:

1. **Activity Log first** (TRIAGE-003): Mandatory 2-hour look-back for config changes, deployments, scaling events
2. **Log Analytics** (TRIAGE-002): Cross-workspace KQL for errors, OOM kills, crashes
3. **Resource Health** (TRIAGE-002): Platform vs. configuration issue disambiguation
4. **Monitor Metrics** (MONITOR-001): CPU, memory, disk I/O, network metrics
5. **Arc-specific steps** (Arc Agent only): connectivity check → extension health → GitOps status
6. **Structured diagnosis** (TRIAGE-004): hypothesis + evidence + confidence_score (0.0–1.0)
7. **Remediation proposal** (REMEDI-001): description + risk_level + reversible — NEVER auto-executed

### 4D. Human-in-the-Loop (REMEDI-001)

No remediation action is ever executed without explicit human approval. The pattern:
1. Agent writes approval record to Cosmos DB (status: `pending`, TTL: 30 min)
2. Agent posts Adaptive Card to Teams (non-blocking call)
3. Agent **returns immediately** — Foundry thread goes idle
4. Operator approves/rejects via Teams card or Web UI ProposalCard
5. API Gateway updates Cosmos DB record; sends outcome card
6. (Optional) New Foundry run on the same thread to execute approved action

### 4E. Budget and Iteration Guard (AGENT-007)

Each agent session is bounded by:
- **Cost ceiling**: $5.00 USD (configurable via `BUDGET_THRESHOLD_USD`)
- **Iteration cap**: 10 iterations max (configurable via `MAX_ITERATIONS`)

`BudgetTracker` stores per-session state in Cosmos DB with ETag optimistic concurrency, aborting the session if either limit is exceeded.

---

## 5. API Gateway Design

**Technology:** FastAPI (Python), deployed as a Container App with external ingress.

### Endpoint Summary

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/incidents` | Ingest incident from detection plane; dedup + Foundry dispatch |
| `POST` | `/api/v1/chat` | Start operator chat thread in Foundry |
| `GET` | `/api/v1/chat/{thread_id}/result` | Poll Foundry run completion status |
| `POST` | `/api/v1/approvals/{id}/approve` | Approve remediation proposal |
| `POST` | `/api/v1/approvals/{id}/reject` | Reject remediation proposal |
| `GET` | `/api/v1/approvals` | List approvals by status |
| `GET` | `/api/v1/approvals/{id}` | Get single approval record |
| `GET` | `/api/v1/incidents` | List incidents for alert feed (with filters) |
| `GET` | `/api/v1/runbooks/search` | Semantic runbook search (pgvector cosine similarity) |
| `GET` | `/api/v1/audit` | Query audit log from Application Insights |
| `GET` | `/api/v1/audit/export` | Export SOC 2 remediation activity report |
| `POST` | `/api/v1/azure-tools` | Proxy Azure MCP Server stdio calls |
| `GET` | `/health` | Health check (unauthenticated) |

### Authentication

- **Production**: Entra ID Bearer tokens via `fastapi-azure-auth` (`SingleTenantAzureAuthorizationCodeBearer`)
- **Local dev**: `API_GATEWAY_AUTH_MODE=disabled` bypasses validation
- **Fabric User Data Function**: Uses MSAL client credentials (Service Principal) to acquire tokens

### Correlation ID Propagation

Every request/response receives a `X-Correlation-ID` header (generated or forwarded from caller). This ID flows as `correlation_id` through all Foundry messages for end-to-end trace correlation.

---

## 6. Detection Plane Architecture

### Pipeline Stages

```
Azure Monitor Alerts
    │
    ▼  (Azure Monitor Diagnostic Settings)
Azure Event Hub  ←── Activity Log Exports (multi-subscription)
    │
    ▼  (Fabric Eventstream connector)
Eventhouse / KQL Database
    ├── raw_alerts      — raw Azure Monitor alert schema
    ├── enriched_alerts — enriched with resource metadata
    └── DetectionResults — classified + filtered (Sev0–Sev2 only)
    │
    ▼  (KQL functions)
    classify_domain(resource_type) → domain
    classify_alerts(severity)      → Sev0–Sev2 filter
    enrich_alerts()                → resource name, subscription name
    │
    ▼  (Fabric Activator rule)
    Evaluates: WHERE domain IS NOT NULL AND AlertCount >= 1 per 5m window
    Fires trigger on new qualifying rows
    │
    ▼  (Fabric User Data Function — Python)
    Maps DetectionResults row → IncidentPayload
    Acquires Entra token (MSAL client credentials)
    POST /api/v1/incidents → API Gateway
```

### Deduplication (Detection Plane + Gateway)

**Layer 1 (time-window collapse, D-11):** Multiple alerts for the same `resource_id + detection_rule` within 5 minutes collapse into one Cosmos DB record; `duplicate_count` incremented.

**Layer 2 (open-incident correlation, D-12):** A new distinct alert for a `resource_id` that already has an `new` or `acknowledged` incident is appended to `correlated_alerts` array rather than creating a new incident.

Both layers use ETag optimistic concurrency for safe concurrent updates (retry on 412 Precondition Failed).

### Incident State Machine

```
new → acknowledged → closed
new → closed
acknowledged: terminal for new alerts from same resource (Layer 2 correlation)
closed: terminal state
```

---

## 7. Arc MCP Server Architecture

The Azure MCP Server (`@azure/mcp`) has a confirmed gap: it does not cover Arc resources. The custom Arc MCP Server fills this gap.

**Transport:** Streamable HTTP on port 8080, `stateless_http=True` (multi-replica safe)
**Auth:** `DefaultAzureCredential` → managed identity in Container App
**Framework:** `mcp.server.fastmcp.FastMCP` (official Python MCP SDK)

### Tool Surface

| Tool Group | Tools | Azure SDK Client |
|------------|-------|-----------------|
| Arc Servers | `arc_servers_list`, `arc_servers_get`, `arc_extensions_list` | `HybridComputeManagementClient` |
| Arc Kubernetes | `arc_k8s_list`, `arc_k8s_get`, `arc_k8s_gitops_status` | `ConnectedKubernetesClient` |
| Arc Data Services | `arc_data_sql_mi_list`, `arc_data_sql_mi_get`, `arc_data_postgresql_list` | `AzureArcDataManagementClient` |

The Arc Agent mounts these tools via `MCPTool(server_label="arc-mcp", server_url=ARC_MCP_SERVER_URL)`.

---

## 8. Frontend Architecture

### Web UI (Next.js 15 App Router)

**Split-pane layout:** `react-resizable-panels` — Chat (35%) + Dashboard (65%)

**Chat Panel:**
- Sends messages via `POST /api/proxy/chat` (Next.js API route → API Gateway proxy)
- Streams responses via SSE: `GET /api/stream?thread_id=...&type=token`
- Renders `ProposalCard` inline when `approval_gate` trace event arrives
- Supports SSE reconnect with event replay from in-memory ring buffer

**Dashboard Panel tabs:**
- **Alerts** — `AlertFeed` polling `GET /api/proxy/incidents` (filterable by severity/domain/status)
- **Audit** — `AuditLogViewer` querying `GET /api/v1/audit` (Application Insights OTel data)
- **Topology** — Resource relationship map
- **Resources** — Multi-subscription ARM resource inventory
- **Observability** — Agent latency, pipeline lag, active errors (Log Analytics queries)

**SSE Protocol:**
- `event: token` — `{delta, agent, seq}` — incremental text tokens
- `event: done` — `{seq}` — signals completion
- `event: trace` — `{type: "approval_gate", approval_id, proposal, expires_at}`
- SSE comments (`: heartbeat`) every 20s to keep proxies alive
- Reconnect supported via `Last-Event-ID` / `last_seq` — ring buffer replays missed events

**Auth:** Entra ID MSAL browser SPA flow; callback at `/callback`

### Teams Bot

**Runtime:** TypeScript, `botbuilder` + `TeamsActivityHandler`

**Message flows:**
1. **Operator messages** → `gateway.chat()` → polling for response → reply in Teams
2. **`/investigate <id>` command** → look up existing thread_id → join conversation context
3. **Adaptive Card Action.Execute** → `onAdaptiveCardInvoke()` → `gateway.approveProposal()` / `rejectProposal()` → in-place card update

**Proactive alerts:** `setConversationReference()` captured on bot installation; `sendProactiveMessage()` pushes alert/approval/outcome cards without user-initiated turn.

**Adaptive Card types:** `alert-card`, `approval-card`, `outcome-card`, `reminder-card`

---

## 9. Deployment Architecture

### Azure Infrastructure

All resources deployed via Terraform (azurerm ~4.65.0, azapi ~2.9.0, azuread ~3.x).

```
Azure Subscription (platform)
└── Resource Group: rg-aap-{env}
    │
    ├── Networking
    │   ├── VNet: vnet-aap-{env} (10.0.0.0/16)
    │   │   ├── subnet-container-apps  (10.0.1.0/24)
    │   │   ├── subnet-postgres        (10.0.2.0/24)
    │   │   ├── subnet-private-endpoints (10.0.3.0/24)
    │   │   └── subnet-reserved-1      (10.0.4.0/24)
    │   └── Private DNS zones (Cosmos, ACR, Key Vault, Cognitive, Service Bus)
    │
    ├── Compute Environment
    │   ├── Container Apps Environment (VNet-integrated)
    │   │   ├── ca-api-gateway-{env}   [external ingress, port 8000]
    │   │   ├── ca-web-ui-{env}        [external ingress, port 3000]
    │   │   ├── ca-teams-bot-{env}     [external ingress, port 3978]
    │   │   ├── ca-orchestrator-{env}  [internal, port 8000]
    │   │   ├── ca-compute-{env}       [internal, port 8000]
    │   │   ├── ca-network-{env}       [internal, port 8000]
    │   │   ├── ca-storage-{env}       [internal, port 8000]
    │   │   ├── ca-security-{env}      [internal, port 8000]
    │   │   ├── ca-sre-{env}           [internal, port 8000]
    │   │   ├── ca-arc-{env}           [internal, port 8000]
    │   │   └── ca-arc-mcp-server-{env} [internal, port 8080] (optional)
    │   └── Azure Container Registry (ACR) — managed identity pull
    │
    ├── AI / Foundry
    │   ├── Azure AI Services account (kind: AIServices)
    │   ├── Azure AI Project
    │   ├── Foundry Model Deployment (gpt-4o, 100 TPM prod)
    │   └── Capability Host (azapi) — enables Hosted Agents
    │
    ├── Databases
    │   ├── Cosmos DB (NoSQL) — incidents, approvals, sessions
    │   │   ├── Partition key: resource_id (incidents) / incident_id (sessions)
    │   │   └── Prod: Provisioned Autoscale, 4000 RU, multi-region (eastus2 + westus2)
    │   └── PostgreSQL Flexible Server + pgvector — runbooks RAG
    │       └── Prod: GP_Standard_D4s_v3, 128 GB
    │
    ├── Monitoring
    │   ├── Log Analytics Workspace
    │   └── Application Insights — OTel traces (AUDIT-001 agent spans)
    │
    ├── Event Hub
    │   └── eventhub-aap-{env} (10 partitions prod)
    │
    ├── Key Vault — secrets (bot password, app insights conn string, SP credentials)
    ├── Entra App Registration — Web UI MSAL (SPA flow)
    └── RBAC Assignments — domain-scoped least privilege
        ├── Compute Agent: Virtual Machine Contributor + Monitoring Reader (compute sub)
        ├── Network Agent: Network Contributor + Monitoring Reader (network sub)
        ├── Storage Agent: Storage Account Contributor + Monitoring Reader (storage sub)
        ├── Security Agent: Security Reader + Key Vault Reader (security sub)
        ├── Arc Agent: Reader on Arc subscriptions
        └── SRE Agent: Reader + Monitoring Reader (all subscriptions)

External: Fabric (SaaS)
    ├── Fabric Capacity: fcaap{env} (F4 prod)
    ├── Fabric Workspace
    ├── Fabric Eventhouse (KQL database: raw_alerts, enriched_alerts, DetectionResults)
    ├── Fabric Activator (trigger rules → User Data Function)
    └── OneLake Lakehouse (audit logs, alert history, snapshots)
```

### Container Image Strategy

Images are built from `agents/` and `services/` directories and pushed to ACR:
- `agents/{agent-name}` → `{acr}/agents/{agent-name}:latest`
- `services/{service-name}` → `{acr}/services/{service-name}:latest`

All Container Apps use **system-assigned managed identity** for ACR pull and Azure SDK authentication (`DefaultAzureCredential`). No admin credentials or stored secrets for resource access.

### Private Networking

- All Cosmos DB, ACR, Key Vault, and Foundry traffic flows through **private endpoints** in `subnet-private-endpoints`
- Private DNS zones ensure resolution within the VNet
- Container Apps environment is VNet-integrated (`subnet-container-apps`)
- **Known limitation:** Foundry Hosted Agents do not support private networking in Preview; the Container App agents fill this gap

---

## 10. Observability Architecture

### OpenTelemetry (AUDIT-001, MONITOR-007)

All agent containers and the API Gateway are instrumented with `azure-monitor-opentelemetry`. Every tool call produces an OTel span with:

```
aiops.agent_id         — Entra Agent ID (AUDIT-005)
aiops.agent_name       — e.g., "compute-agent"
aiops.tool_name        — MCP tool or @ai_function name
aiops.tool_parameters  — serialized input args
aiops.outcome          — "success" | "failure" | "timeout"
aiops.duration_ms      — wall-clock duration
aiops.correlation_id   — incident_id (end-to-end trace linkage)
aiops.thread_id        — Foundry thread ID
```

Spans flow to **Application Insights** → queryable via `GET /api/v1/audit`.

### Audit Export (AUDIT-006)

`GET /api/v1/audit/export?from_time=...&to_time=...` generates a structured SOC 2 remediation activity report including full approval chains.

### Operational Metrics

The `ObservabilityTab` in the Web UI queries Log Analytics directly for:
- Agent response latency (P50/P95)
- Pipeline lag (Event Hub → Foundry dispatch)
- Active error counts by agent
- Approval queue depth

---

## 11. Key Design Patterns

| Pattern | Where Applied | Rationale |
|---------|--------------|-----------|
| **Thin gateway, smart agents** | API Gateway never contains business logic | Agents own all reasoning; gateway is a routing layer |
| **Typed message envelopes** | All inter-agent messages (AGENT-002) | Prevents schema drift, enables audit correlation |
| **Handoff orchestration** | Orchestrator → domain agents | Explicit routing with agent specialization; no fan-out |
| **Write-then-return HITL** | Approval workflow (REMEDI-002) | Thread never blocks; Foundry idle during human review |
| **Optimistic concurrency (ETag)** | Cosmos DB dedup, budget tracker, approvals | Safe concurrent writes without locking |
| **Mandatory triage workflow** | All domain agents | Consistent evidence quality; enforced by system prompt |
| **Safety constraints in prompts** | All agents | Hard constraints: never execute without approval; never skip steps |
| **Domain-scoped RBAC** | Per-agent managed identities | Least-privilege: compute agent cannot touch network resources |
| **SSE + polling hybrid** | Web UI streaming | SSE for server-push; polling fallback on Foundry's eventual consistency |
| **pvector RAG** | Runbook search (TRIAGE-005) | Semantic similarity with domain filtering; ivfflat cosine index |
| **2-layer dedup** | Detection plane + gateway | Prevents alert storm from creating O(n) incidents |
| **Correlation ID propagation** | Full request chain | Single ID traces from Azure Monitor alert → Foundry span |
