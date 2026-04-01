# Architecture

> Last updated: 2026-04-01 (Phases 1–13 complete)

---

## System Overview

The Azure Agentic Platform (AAP) is an enterprise AIOps platform that monitors, triages, and remediates Azure infrastructure incidents through a **domain-specialist multi-agent architecture** backed by Azure AI Foundry. Alerts flow from Azure Monitor into a Fabric Eventhouse detection plane, which classifies and deduplicates them before a Fabric Activator webhook triggers the Python API Gateway (FastAPI on Azure Container Apps). The gateway dispatches incidents to an Orchestrator agent running on Foundry Hosted Agents; the Orchestrator classifies the domain and routes via connected-agent tool handoffs to one of **eight** specialist domain agents (Compute, Network, Storage, Security, Arc, SRE, Patch, EOL). A custom Arc MCP Server (FastMCP/streamable-HTTP) fills the coverage gap left by the Azure MCP Server for Arc-enabled resources. Operators interact through a Next.js / Fluent UI v9 / Tailwind web dashboard (6 tabs including a dedicated Patch tab added in Phase 13) and through Microsoft Teams (new Teams SDK TypeScript bot). All remediation proposals require human-in-the-loop approval before any action is taken.

---

## Component Diagram (ASCII)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     DETECTION PLANE (Fabric — SaaS)                             │
│                                                                                 │
│  Azure Monitor ──► Event Hubs ──► Fabric Eventstreams ──► Eventhouse (KQL)      │
│                                                                                 │
│  KQL pipeline:  raw_alerts → enrich_alerts() → classify_domain() →             │
│                 DetectionResults (Sev0–Sev2 filtered)                          │
│                                                                                 │
│  Fabric Activator  ──► (threshold rule: AlertCount ≥ 1 per 5m)                 │
│       │                                                                         │
│       ▼                                                                         │
│  Fabric User Data Function (Python/MSAL)                                        │
│       │  DetectionResults row → IncidentPayload                                 │
│       │  Acquires Entra Bearer token (MSAL client-credentials)                  │
└───────┼─────────────────────────────────────────────────────────────────────────┘
        │  POST /api/v1/incidents (Bearer token)
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                   API GATEWAY  (FastAPI · Container App)                        │
│                                                                                 │
│  Middleware: CORS · correlation-ID injection · per-IP rate limiting             │
│  Auth: Entra ID Bearer token (verify_token dependency)                          │
│                                                                                 │
│  POST /api/v1/incidents      ──► dedup_integration → create_foundry_thread      │
│  POST /api/v1/chat           ──► create_chat_thread (operator-initiated)        │
│  GET  /api/v1/chat/{id}/result ──► get_chat_result (non-blocking poll)          │
│  POST /api/v1/approvals/{id}/approve|reject ──► process_approval_decision       │
│  GET  /api/v1/approvals      ──► list_approvals_by_status (Cosmos DB)           │
│  GET  /api/v1/incidents      ──► list_incidents (Cosmos DB, filterable)         │
│  GET  /api/v1/runbooks/search ──► pgvector RAG (PostgreSQL + pgvector)          │
│  GET  /api/v1/audit          ──► query_audit_log (Application Insights OTel)    │
│  GET  /api/v1/audit/export   ──► generate_remediation_report (SOC 2)            │
│  POST /api/v1/azure-tools    ──► call_azure_tool (Azure MCP stdio bridge)       │
│  /api/v1/patch/*             ──► patch_endpoints router                         │
│  GET  /health                ──► health check (unauthenticated)                 │
│                                                                                 │
│  Persistence: Cosmos DB (incidents, approvals) · PostgreSQL (runbooks, EOL)     │
│  OTel: azure-monitor-opentelemetry → Application Insights                       │
└──────────────────────────┬──────────────────────────────────────────────────────┘
                           │  azure-ai-projects SDK (Foundry Threads + Runs)
                           ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                  AZURE AI FOUNDRY  (Hosted Agent Service)                       │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │  ORCHESTRATOR AGENT  (ChatAgent + @ai_function)                         │   │
│  │  Tool: classify_incident_domain() — ARM resource type prefix voting     │   │
│  │  Connected-agent routing to 8 domain specialist agents                  │   │
│  │  Constraints: MUST NOT query Azure · MUST NOT execute remediation        │   │
│  └──────────────────────────┬──────────────────────────────────────────────┘   │
│                             │  connected-agent tool handoff                     │
│    ┌────────────────────────┼───────────────────────────────────────────────┐   │
│    │              DOMAIN AGENTS  (each a ChatAgent)                         │   │
│    │                                                                        │   │
│    │  compute-agent  ──► Azure MCP (VMs, VMSS, AKS, App Service)           │   │
│    │  network-agent  ──► Azure MCP (VNets, NSGs, LB, DNS, ExpressRoute)    │   │
│    │  storage-agent  ──► Azure MCP (Blob, Files, ADLS Gen2, StorageSync)   │   │
│    │  security-agent ──► Azure MCP (Defender, Key Vault, RBAC, Sentinel)   │   │
│    │  arc-agent      ──► Arc MCP Server (servers, K8s, data services)      │   │
│    │  patch-agent    ──► Azure MCP (Update Manager, patch compliance)      │   │
│    │  eol-agent      ──► EOL cache / endoflife.date API (PostgreSQL)       │   │
│    │  sre-agent      ──► Azure MCP (cross-domain, SLA, reliability)        │   │
│    └────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
         │                                           │
         │  Streamable HTTP MCP                      │  stdio bridge (via /api/v1/azure-tools)
         ▼                                           ▼
┌─────────────────────┐               ┌────────────────────────┐
│  ARC MCP SERVER     │               │  AZURE MCP SERVER      │
│  (FastMCP · CA)     │               │  (@azure/mcp npm pkg)  │
│  arc_servers_list   │               │  ARM, Compute, Monitor │
│  arc_servers_get    │               │  Storage, Security,    │
│  arc_extensions_list│               │  Foundry, Event Hubs,  │
│  arc_k8s_list/get   │               │  AKS, Key Vault, etc.  │
│  arc_k8s_gitops     │               └────────────────────────┘
│  arc_data_sql_mi_*  │
│  arc_data_postgres_*│
└─────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                    FRONTEND & TEAMS SURFACES                                    │
│                                                                                 │
│  WEB UI (Next.js 15 App Router · Fluent UI v9 · Tailwind · Container App)      │
│  Split-pane: Chat (35%) + Dashboard (65%)                                       │
│  Dashboard tabs: Alerts · Audit · Topology · Resources · Observability · Patch │
│  API routes: /api/proxy/* (gateway proxy) · /api/stream (SSE) · /api/resources │
│  Auth: Entra ID MSAL browser SPA flow                                           │
│                                                                                 │
│  TEAMS BOT (TypeScript · new Teams SDK · Container App · port 3978)            │
│  Proactive alert Adaptive Cards → Teams channel                                 │
│  Adaptive Card approve/reject → POST /api/v1/approvals/{id}/approve|reject      │
│  /ask command → API Gateway chat → reply in Teams                               │
└─────────────────────────────────────────────────────────────────────────────────┘

Persistence layer:
  Azure Cosmos DB ── incidents (hot path), approvals, agent session context
  PostgreSQL + pgvector ── runbooks RAG (ivfflat cosine), EOL cache (24h TTL)
  Fabric OneLake ── audit logs, alert history, resource inventory snapshots
  Foundry Agent Service ── conversation threads + run state (managed)
  Application Insights (OTel) ── agent spans, traces, audit log source
```

---

## Data Flow (Request Lifecycle)

### Detection-triggered incident

```
1.  Azure Monitor fires alert
2.  Event Hubs → Fabric Eventstreams → Eventhouse KQL table (raw_alerts)
3.  KQL pipeline: raw_alerts → enrich_alerts() → classify_domain() → DetectionResults
4.  Fabric Activator evaluates threshold rule (5-min window, Sev0–Sev2)
5.  Activator triggers Fabric User Data Function (Python)
        a. Acquires Entra Bearer token (MSAL client-credentials)
        b. Maps DetectionResults row → IncidentPayload
        c. POST /api/v1/incidents → API Gateway
6.  API Gateway:
        a. Verifies Entra Bearer token
        b. Runs 2-layer dedup check (Cosmos DB):
           Layer 1: same resource_id + detection_rule within 5m → collapse, incr duplicate_count
           Layer 2: open incident for same resource_id → append to correlated_alerts
        c. Creates Cosmos DB incident record (status: new)
        d. create_foundry_thread() → Foundry thread + message + run
        e. Returns 202 Accepted { thread_id, status: "dispatched" }
7.  Foundry runs Orchestrator Agent:
        a. Classifies domain (classify_incident_domain tool or domain_hint)
        b. Calls connected-agent tool for matching domain agent
8.  Domain Agent (e.g., compute-agent) mandatory triage workflow:
        a. query_activity_log (2h lookback — TRIAGE-003, mandatory first step)
        b. query_log_analytics (TRIAGE-002)
        c. query_resource_health (TRIAGE-002)
        d. query_monitor_metrics (MONITOR-001)
        e. Root-cause hypothesis: { hypothesis, evidence, confidence_score, needs_cross_domain }
        f. If remediation warranted: propose only — NEVER execute (REMEDI-001)
9.  If remediation proposed:
        a. Approval record written to Cosmos DB (status: pending, TTL: 30 min)
        b. API Gateway sends Adaptive Card to Teams Bot (teams_notifier)
        c. Agent RETURNS — thread goes idle (write-then-return pattern)
10. Web UI SSE polling (every 2s): GET /api/v1/chat/{thread_id}/result
        a. Background task auto-approves MCP tool_approval gates on sub-runs
        b. Returns reply when run_status == "completed"
11. Operator reviews ProposalCard (Web UI) or Adaptive Card (Teams):
        a. Approve → POST /api/v1/approvals/{id}/approve
        b. Reject  → POST /api/v1/approvals/{id}/reject
        c. Cosmos DB record updated; outcome card sent to Teams
```

### Operator-initiated chat

```
1.  Operator types in ChatDrawer (Web UI) or sends message in Teams
2.  POST /api/proxy/chat → POST /api/v1/chat (API Gateway)
3.  API Gateway builds operator_query envelope:
        - classify_query_text() assigns domain_hint
        - Thread created or continued (incident_id lookup from Cosmos DB)
        - Returns { thread_id, run_id }
4.  Web UI opens SSE: GET /api/stream?thread_id=...
        - Polls /api/proxy/chat/result every 2s
        - Emits token events + heartbeat (every 20s)
        - Supports reconnect via Last-Event-ID + ring buffer replay
5.  Orchestrator reads operator_query envelope:
        - domain_hint → calls matching domain agent connected-agent tool
        - Domain agent investigates and returns structured response
6.  SSE stream emits token events → ChatDrawer renders response
    If approval_gate event → ProposalCard rendered inline
```

---

## Agent Architecture

### Orchestrator Agent

- **Framework**: Microsoft Agent Framework `ChatAgent` + `@ai_function`
- **Hosting**: Foundry Hosted Agent (Container App + `azure-ai-agentserver-agentframework` adapter)
- **Entry point**: `agents/orchestrator/agent.py` → `from_agent_framework(create_orchestrator()).run()`
- **Local tool**: `classify_incident_domain` — ARM resource type prefix voting → domain
- **Routing**: 8 connected-agent tools registered on the Foundry agent definition at the Foundry level: `compute_agent`, `network_agent`, `storage_agent`, `security_agent`, `arc_agent`, `sre_agent`, `patch_agent`, `eol_agent`
- **Hard constraints** (in system prompt):
  - MUST NOT query Azure resources directly
  - MUST NOT propose or execute remediation
  - MUST preserve `correlation_id` through all messages (AUDIT-001)
  - MUST route — never answer from own knowledge

### Domain Agents (8 specialists)

Each domain agent pattern: `create_<domain>_agent()` → `ChatAgent` (system prompt + tool list) → `from_agent_framework(...).run()`

| Agent | Domain Coverage | Primary Tool Surface | Mandatory Triage Order |
|---|---|---|---|
| `compute-agent` | VMs, VMSS, AKS, App Service, Azure Functions | Azure MCP: activity log, log analytics, resource health, metrics | Activity Log → Log Analytics → Resource Health → Metrics |
| `network-agent` | VNets, NSGs, LBs, DNS, ExpressRoute, Firewall | Azure MCP: network, monitor, resourcehealth | Activity Log → Log Analytics → Resource Health → Metrics |
| `storage-agent` | Blob, Files, ADLS Gen2, StorageSync, managed disks | Azure MCP: storage, monitor, resourcehealth | Activity Log → Log Analytics → Resource Health → Metrics |
| `security-agent` | Defender, Key Vault, RBAC drift, Sentinel | Azure MCP: keyvault, security, role | Activity Log → Log Analytics → Resource Health → Metrics |
| `arc-agent` | Arc servers, Arc K8s (Flux GitOps), Arc data services | **Custom Arc MCP Server** (9 tools) + Azure MCP: monitor | Connectivity → Extension Health → GitOps Status → Metrics |
| `patch-agent` | Update Manager, patch compliance, missing patches | Azure MCP: maintenance, compute | Activity Log → Patch Compliance → Missing Patches → Metrics |
| `eol-agent` | Software lifecycle, EOL dates, upgrade planning | endoflife.date API + PostgreSQL cache (24h TTL) | Product lookup → EOL date → Impact assessment |
| `sre-agent` | Cross-domain, SLA/SLO, reliability, fallback | Azure MCP: monitor, resourcehealth, advisor, applicationinsights | Activity Log → Log Analytics → Resource Health → Metrics |

**Diagnosis structure** (all domain agents, TRIAGE-004):
```
{
  hypothesis: str,              # natural-language root cause
  evidence: list[str],          # supporting evidence items
  confidence_score: float,      # 0.0–1.0
  needs_cross_domain: bool,
  suspected_domain: str | None  # route target if cross-domain
}
```

**Safety constraints** (all domain agents, REMEDI-001):
- MUST NOT execute VM restart, scale, resize, or any mutation without human approval
- Propose only; execution requires approved Cosmos DB record

### Shared Agent Utilities (`agents/shared/`)

| Module | Purpose |
|---|---|
| `auth.py` | `get_foundry_client()` — `DefaultAzureCredential` + `azure-ai-projects` |
| `envelope.py` | `IncidentMessage` TypedDict; `validate_envelope()` — AGENT-002 typed inter-agent contract |
| `routing.py` | `classify_query_text()` — keyword-based domain classification for operator queries |
| `approval_manager.py` | `create_approval_record()` — write-then-return HITL pattern (Cosmos DB) |
| `budget.py` | `BudgetTracker` — per-session $5 cost ceiling + 10 iteration cap (ETag concurrency) |
| `gitops.py` | GitOps vs. direct-apply path detection (SC6 / MONITOR-006) |
| `otel.py` | `setup_telemetry()`, `record_tool_call_span()` — OTel tracing (AUDIT-001) |
| `resource_identity.py` | ARM resource ID parsing, resource certainty scoring (SC5) |
| `runbook_tool.py` | `retrieve_runbooks()` — `@ai_function` tool calling API Gateway runbook search |
| `triage.py` | Shared triage utilities |

### MCP Tool Surfaces

**Azure MCP Server** (`services/azure-mcp-server/`): `@azure/mcp` npm package wrapped in a Node.js proxy (`proxy.js`), deployed as Container App. Domain agents call it indirectly via the API Gateway's `/api/v1/azure-tools` endpoint (a stdio bridge that works around a Foundry protocol incompatibility with `@azure/mcp`'s HTTP MCP transport).

**Arc MCP Server** (`services/arc-mcp-server/`): Custom Python FastMCP server (official `mcp[cli]` 1.26.0), Streamable HTTP transport, `stateless_http=True` for multi-replica safety. Exposes 9 tools across three Azure SDK clients:

| Tool Group | Tools | Azure SDK Client |
|---|---|---|
| Arc Servers | `arc_servers_list`, `arc_servers_get`, `arc_extensions_list` | `HybridComputeManagementClient` |
| Arc Kubernetes | `arc_k8s_list`, `arc_k8s_get`, `arc_k8s_gitops_status` | `ConnectedKubernetesClient` |
| Arc Data Services | `arc_data_sql_mi_list`, `arc_data_sql_mi_get`, `arc_data_postgresql_list` | `AzureArcDataManagementClient` |

### Human-in-the-Loop (REMEDI-001)

```
Agent proposes remediation
       │
       ▼  (write-then-return — never blocks)
Cosmos DB: approval record { status: pending, TTL: 30 min }
       │
       ▼
teams_notifier → Adaptive Card in Teams channel
       │
       ▼  (Foundry thread goes idle — zero blocking)
Operator reviews in Teams or Web UI ProposalCard
       │
       ├── Approve → POST /api/v1/approvals/{id}/approve
       │              Cosmos DB status: approved
       │              Outcome card sent to Teams
       │
       └── Reject  → POST /api/v1/approvals/{id}/reject
                      Cosmos DB status: rejected
                      Outcome card sent to Teams
```

### Budget and Iteration Guard (AGENT-007)

Each agent session bounded by `BudgetTracker` (Cosmos DB, ETag optimistic concurrency):
- **Cost ceiling**: $5.00 USD (configurable via `BUDGET_THRESHOLD_USD`)
- **Iteration cap**: 10 iterations max (configurable via `MAX_ITERATIONS`)
- Session aborted and result returned if either limit is exceeded

---

## Deployment Model

All services deployed as **Azure Container Apps** in a VNet-integrated Container Apps Environment:

| Container App | Ingress | Port |
|---|---|---|
| `ca-api-gateway-{env}` | External | 8000 |
| `ca-web-ui-{env}` | External | 3000 |
| `ca-teams-bot-{env}` | External | 3978 |
| `ca-arc-mcp-server-{env}` | Internal | 8080 |
| `ca-azure-mcp-server-{env}` | Internal | varies |
| `ca-orchestrator-{env}` | Internal (Foundry Hosted Agent) | 8000 |
| `ca-compute-{env}` … `ca-eol-{env}` | Internal (Foundry Hosted Agent) | 8000 |

**Authentication**: All services use `DefaultAzureCredential` + system-assigned managed identity. No service accounts or stored secrets in code.

**Networking**: VNet-integrated Container Apps Environment; all Cosmos DB, ACR, Key Vault, and Foundry traffic routes through private endpoints. Known limitation: Foundry Hosted Agents do not support private networking in Preview — Container Apps fill this gap.

**Terraform**: Three environments (`dev`, `staging`, `prod`) using `azurerm ~> 4.65.0` + `azapi ~> 2.9.0`. State in Azure Storage with Entra auth. CI/CD: GitHub Actions — `terraform-plan.yml` on PR, `terraform-apply.yml` on merge to main.

**Observability**: `azure-monitor-opentelemetry` auto-instrumented in all Python services. OTel spans flow to Application Insights and are the source for `GET /api/v1/audit` queries. Standard span attributes: `aiops.agent_name`, `aiops.tool_name`, `aiops.correlation_id`, `aiops.thread_id`, `aiops.outcome`, `aiops.duration_ms`.

---

## Key Design Patterns

| Pattern | Where Applied | Rationale |
|---|---|---|
| **Thin gateway, smart agents** | API Gateway has no business logic | Agents own all reasoning; gateway is a routing layer |
| **Typed message envelopes** | All inter-agent messages (AGENT-002) | Prevents schema drift, enables audit correlation |
| **Connected-agent handoff** | Orchestrator → 8 domain agents | Explicit routing with agent specialization; no fan-out |
| **Write-then-return HITL** | Approval workflow (REMEDI-001) | Foundry thread idle during human review; non-blocking |
| **Optimistic concurrency (ETag)** | Cosmos DB dedup, budget tracker, approvals | Safe concurrent writes without distributed locking |
| **Mandatory triage workflow** | All 8 domain agents | Consistent evidence quality; enforced by system prompt |
| **Safety constraints in system prompt** | All agents | Never execute without approval; never skip triage steps |
| **Domain-scoped RBAC** | Per-agent managed identities | Least-privilege: compute agent cannot touch network resources |
| **SSE + polling hybrid** | Web UI streaming | SSE server-push; ring buffer for reconnect replay |
| **pgvector RAG** | Runbook search (TRIAGE-005) | Semantic similarity with domain filter; ivfflat cosine index |
| **2-layer dedup** | Detection plane + gateway | Prevents alert storms from creating O(n) incidents |
| **Correlation ID propagation** | Full request chain (AUDIT-001) | Single ID traces from Azure Monitor alert → Foundry span |
| **Python mirror of KQL** | `classify_domain.py` mirrors `classify_domain.kql` | Unit-testable logic; Fabric validation fallback |
