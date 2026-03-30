# Azure Agentic Platform — Codebase Structure

> Last updated: 2026-03-30

---

## 1. Top-Level Directory Layout

```
azure-agentic-platform/
├── agents/                  # Python domain agents (deployed to Foundry Hosted Agents / Container Apps)
├── services/                # Runtime services (API Gateway, Web UI, Teams Bot, Arc MCP Server, Detection Plane)
├── fabric/                  # Fabric Eventhouse KQL definitions and User Data Function
├── terraform/               # Infrastructure as Code (azurerm + azapi + azuread)
├── e2e/                     # Playwright end-to-end tests
├── docs/                    # Supplemental documentation
├── scripts/                 # Utility/maintenance scripts
├── tasks/                   # Planning artifacts (todo.md, lessons.md)
├── pyproject.toml           # Python project config: pytest settings, markers, pythonpath
├── conftest.py              # Root pytest conftest
└── _aap_bootstrap.py        # One-time platform bootstrap script
```

---

## 2. `agents/` — Domain Agent Layer

Each sub-directory is an independently deployable agent container. All agents share the `shared/` utilities package.

```
agents/
├── Dockerfile.base           # Base image shared by all agent Dockerfiles
├── requirements-base.txt     # Shared Python requirements (agent-framework, azure-ai-*)
│
├── orchestrator/             # Central incident dispatcher (HandoffOrchestrator)
│   ├── agent.py              # create_orchestrator() — HandoffOrchestrator with 6 AgentTargets
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── compute/                  # Azure compute specialist (VMs, VMSS, AKS, App Service)
│   ├── agent.py              # create_compute_agent() — ChatAgent with compute tools
│   ├── tools.py              # @ai_function tools: query_activity_log, query_log_analytics,
│   │                         #   query_resource_health, query_monitor_metrics
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── network/                  # Azure network specialist (VNets, NSGs, load balancers, DNS)
│   ├── agent.py
│   ├── tools.py              # Network-scoped monitoring tools
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── storage/                  # Azure storage specialist (Blob, Files, ADLS Gen2)
│   ├── agent.py
│   ├── tools.py              # Storage-scoped monitoring tools
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── security/                 # Azure security specialist (Defender, Key Vault, RBAC)
│   ├── agent.py
│   ├── tools.py              # Security-scoped monitoring tools
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── sre/                      # SRE generalist (cross-domain, SLA/SLO, fallback)
│   ├── agent.py              # create_sre_agent() — Reader + Monitoring Reader across all subs
│   ├── tools.py              # propose_remediation, query_availability_metrics,
│   │                         #   query_performance_baselines
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── arc/                      # Azure Arc specialist (Arc Servers, K8s, Data Services)
│   ├── agent.py              # create_arc_agent() — mounts Arc MCP Server via MCPTool
│   ├── tools.py              # Arc-scoped monitoring + ALLOWED_MCP_TOOLS list
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── shared/                   # Shared utilities imported by all agents
│   ├── __init__.py
│   ├── auth.py               # get_credential(), get_foundry_client() — DefaultAzureCredential
│   ├── envelope.py           # IncidentMessage TypedDict + validate_envelope()
│   ├── otel.py               # setup_telemetry(), record_tool_call_span(), instrument_tool_call()
│   ├── approval_manager.py   # create_approval_record() — write-then-return HITL pattern
│   ├── budget.py             # BudgetTracker — per-session token/cost/iteration guard (Cosmos DB)
│   ├── routing.py            # classify_query_text() — keyword-based domain classification
│   ├── triage.py             # Shared triage utilities
│   ├── runbook_tool.py       # retrieve_runbooks(), format_runbook_citations() (TRIAGE-005)
│   ├── resource_identity.py  # ARM resource ID parsing utilities
│   └── gitops.py             # GitOps path utilities
│
└── tests/
    ├── integration/          # Integration tests requiring live Foundry/Cosmos connections
    │   ├── test_arc_triage.py
    │   ├── test_budget.py
    │   ├── test_handoff.py
    │   ├── test_mcp_tools.py
    │   ├── test_remediation.py
    │   └── test_triage.py
    └── shared/               # Unit tests for shared utilities
        ├── test_budget.py
        └── test_envelope.py
```

### Agent Anatomy

Each domain agent follows the same pattern:

1. **`agent.py`** — `create_<domain>_agent()` factory returning a `ChatAgent` or `HandoffOrchestrator`. Defines the system prompt with mandatory workflow, safety constraints, and allowed tool list. Entry point: `if __name__ == "__main__": agent.serve()`

2. **`tools.py`** — `@ai_function`-decorated tool functions callable by the LLM. Also defines `ALLOWED_MCP_TOOLS` list (explicit allowlist for Azure MCP Server tools).

3. **`Dockerfile`** — Extends `Dockerfile.base`, copies agent code, sets entry point.

---

## 3. `services/` — Runtime Services Layer

```
services/
├── __init__.py
│
├── api-gateway/              # FastAPI incident/chat/approval/audit gateway
│   ├── main.py               # FastAPI app — all route definitions, CORS, lifespan migrations
│   ├── models.py             # Pydantic models: IncidentPayload, ChatRequest, ApprovalRecord, etc.
│   ├── auth.py               # EntraTokenValidator — fastapi-azure-auth integration
│   ├── foundry.py            # create_foundry_thread() — Foundry thread + run creation
│   ├── chat.py               # create_chat_thread(), get_chat_result() — operator chat flow
│   ├── approvals.py          # get_approval(), list_approvals_*, process_approval_decision()
│   ├── audit.py              # query_audit_log() — Application Insights KQL
│   ├── audit_export.py       # generate_remediation_report() — SOC 2 export
│   ├── audit_trail.py        # Audit trail append helpers
│   ├── incidents_list.py     # list_incidents() — Cosmos DB query with filters
│   ├── dedup_integration.py  # check_dedup() — wires detection-plane dedup to gateway
│   ├── runbook_rag.py        # generate_query_embedding(), search_runbooks() — pgvector RAG
│   ├── azure_tools.py        # call_azure_tool() — Azure MCP Server stdio proxy
│   ├── teams_notifier.py     # notify_teams(), post_approval_card(), post_alert_card(), etc.
│   ├── rate_limiter.py       # Per-client rate limiting
│   ├── remediation_logger.py # Remediation action logging
│   ├── instrumentation.py    # foundry_span(), agent_span() OTel helpers
│   ├── migrations/
│   │   └── 002_seed_runbooks.py  # Seed initial runbooks in pgvector
│   └── tests/
│       ├── conftest.py
│       ├── test_approval_lifecycle.py
│       ├── test_audit_export.py
│       ├── test_audit_trail.py
│       ├── test_auth_security.py
│       ├── test_chat_endpoint.py
│       ├── test_gitops_path.py
│       ├── test_health.py
│       ├── test_incidents.py
│       ├── test_rate_limiting.py
│       ├── test_remediation_logger.py
│       ├── test_resource_identity.py
│       ├── test_runbook_rag.py
│       ├── test_runbook_search_availability.py
│       ├── test_sse_heartbeat.py
│       ├── test_sse_stream.py
│       └── test_teams_notifier.py
│
├── arc-mcp-server/           # Custom MCP server bridging Azure MCP Server's Arc coverage gap
│   ├── server.py             # FastMCP app — all 9 Arc tool registrations
│   ├── __main__.py           # Entry point: mcp.server.fastmcp serve
│   ├── auth.py               # DefaultAzureCredential helpers
│   ├── models.py             # Pydantic models for Arc resource responses
│   ├── tools/
│   │   ├── arc_servers.py    # arc_servers_list_impl, arc_servers_get_impl, arc_extensions_list_impl
│   │   ├── arc_k8s.py        # arc_k8s_list_impl, arc_k8s_get_impl, arc_k8s_gitops_status_impl
│   │   └── arc_data.py       # arc_data_sql_mi_list_impl, arc_data_sql_mi_get_impl,
│   │                         #   arc_data_postgresql_list_impl
│   └── tests/
│       ├── conftest.py
│       ├── test_arc_data.py
│       ├── test_arc_k8s.py
│       ├── test_arc_servers.py
│       └── test_pagination.py
│
├── detection-plane/          # Detection plane logic (runs as Fabric User Data Function)
│   ├── models.py             # IncidentRecord, AlertStatus, StatusHistoryEntry (Cosmos DB schema)
│   ├── classify_domain.py    # classify_domain() — ARM resource_type → agent domain mapping
│   ├── dedup.py              # dedup_layer1(), dedup_layer2(), collapse_duplicate(), correlate_alert()
│   ├── alert_state.py        # Alert state machine transitions
│   ├── payload_mapper.py     # DetectionResults row → IncidentPayload mapping
│   └── tests/
│       ├── unit/
│       │   ├── test_alert_state.py
│       │   ├── test_classify_domain.py
│       │   ├── test_dedup.py
│       │   ├── test_kql_pipeline.py
│       │   ├── test_payload_mapper.py
│       │   └── test_user_data_function.py
│       └── integration/
│           ├── test_activity_log.py
│           ├── test_dedup_load.py
│           ├── test_pipeline_flow.py
│           ├── test_round_trip.py
│           ├── test_state_sync.py
│           └── test_suppression.py
│
├── teams-bot/                # Microsoft Teams bot (TypeScript / botbuilder)
│   ├── src/
│   │   ├── index.ts          # Express server entry point (port 3978)
│   │   ├── bot.ts            # AapTeamsBot extends TeamsActivityHandler
│   │   ├── config.ts         # Environment configuration (BOT_ID, API_GATEWAY_INTERNAL_URL, etc.)
│   │   ├── types.ts          # TypeScript type definitions
│   │   ├── instrumentation.ts # OpenTelemetry setup
│   │   ├── cards/
│   │   │   ├── alert-card.ts     # New incident alert Adaptive Card
│   │   │   ├── approval-card.ts  # Remediation proposal approval/reject card
│   │   │   ├── outcome-card.ts   # Remediation execution outcome card
│   │   │   └── reminder-card.ts  # Approval expiry reminder card
│   │   ├── routes/
│   │   │   ├── health.ts     # GET /health
│   │   │   └── notify.ts     # POST /teams/internal/notify — internal alert/approval dispatch
│   │   └── services/
│   │       ├── auth.ts           # Entra token validation for inbound requests
│   │       ├── conversation-state.ts # In-memory thread_id per Teams conversation
│   │       ├── escalation.ts     # Approval timeout escalation
│   │       ├── gateway-client.ts # GatewayClient — typed wrapper for API Gateway calls
│   │       └── proactive.ts      # ConversationReference store + sendProactiveMessage()
│   ├── appPackage/
│   │   └── manifest.json     # Teams App manifest (bot registration)
│   ├── package.json
│   ├── tsconfig.json
│   └── vitest.config.ts
│
└── web-ui/                   # Next.js 15 App Router web UI
    ├── app/
    │   ├── layout.tsx            # Root layout — FluentUI provider, auth context
    │   ├── page.tsx              # Root page → <AuthenticatedApp />
    │   ├── providers.tsx         # React context providers
    │   ├── (auth)/
    │   │   ├── login/page.tsx    # MSAL login redirect
    │   │   └── callback/page.tsx # MSAL auth code callback
    │   └── api/
    │       ├── stream/route.ts           # GET /api/stream — SSE polling loop (token + trace events)
    │       ├── proxy/
    │       │   ├── chat/route.ts         # POST /api/proxy/chat → API Gateway
    │       │   ├── chat/result/route.ts  # GET /api/proxy/chat/result → API Gateway
    │       │   ├── incidents/route.ts    # GET /api/proxy/incidents → API Gateway
    │       │   └── approvals/
    │       │       ├── [approvalId]/approve/route.ts  # POST → API Gateway approve
    │       │       └── [approvalId]/reject/route.ts   # POST → API Gateway reject
    │       ├── resources/route.ts        # GET Azure ARM resource inventory
    │       ├── subscriptions/route.ts    # GET available Azure subscriptions
    │       ├── topology/route.ts         # GET resource topology/relationships
    │       └── observability/route.ts    # GET Log Analytics observability metrics
    ├── components/
    │   ├── AppLayout.tsx         # Root split-pane layout (PanelGroup: Chat 35% + Dashboard 65%)
    │   ├── AuthenticatedApp.tsx  # MSAL auth guard wrapper
    │   ├── ChatPanel.tsx         # Conversational chat panel with SSE streaming
    │   ├── ChatBubble.tsx        # Agent message bubble (supports streaming)
    │   ├── ChatInput.tsx         # Message input with send button
    │   ├── UserBubble.tsx        # Operator message bubble
    │   ├── ThinkingIndicator.tsx # Animated thinking/streaming indicator
    │   ├── ProposalCard.tsx      # Inline HITL approval/reject card
    │   ├── DashboardPanel.tsx    # Tabbed dashboard: Alerts / Audit / Topology / Resources / Observability
    │   ├── AlertFeed.tsx         # Live alert feed with polling
    │   ├── AlertFilters.tsx      # Severity/domain/status filter bar
    │   ├── AuditLogViewer.tsx    # Agent action audit log viewer
    │   ├── ObservabilityTab.tsx  # Platform health metrics (agent latency, pipeline lag)
    │   ├── ResourcesTab.tsx      # ARM resource inventory view
    │   ├── TopologyTab.tsx       # Resource topology graph
    │   ├── TraceTree.tsx         # Agent reasoning trace tree
    │   ├── SubscriptionSelector.tsx # Multi-subscription dropdown
    │   ├── MetricCard.tsx        # Reusable metric display card
    │   ├── ActiveErrorsCard.tsx  # Active error count metric
    │   ├── AgentLatencyCard.tsx  # Agent P50/P95 latency metric
    │   ├── PipelineLagCard.tsx   # Detection pipeline lag metric
    │   ├── ApprovalQueueCard.tsx # Pending approval count
    │   ├── DesktopOnlyGate.tsx   # Mobile viewport guard
    │   └── ui/                   # shadcn/ui primitive components
    │       ├── alert.tsx, badge.tsx, button.tsx, ...
    ├── lib/
    │   ├── use-sse.ts            # useSSE() React hook — SSE connection with reconnect logic
    │   └── sse-buffer.ts         # globalEventBuffer — in-memory ring buffer for SSE event replay
    ├── types/
    │   └── sse.ts                # SSEEvent, Message, ApprovalGateTracePayload types
    ├── __tests__/
    │   ├── auth.test.tsx
    │   └── layout.test.tsx
    ├── components.json           # shadcn/ui config
    ├── next.config.js
    ├── tailwind.config.ts
    └── tsconfig.json
```

---

## 4. `fabric/` — Detection Plane Artifacts

```
fabric/
├── kql/
│   ├── schemas/
│   │   ├── raw_alerts.kql          # raw_alerts table schema (ingestion from Event Hub)
│   │   ├── enriched_alerts.kql     # enriched_alerts table schema
│   │   └── detection_results.kql   # DetectionResults table schema (Activator source)
│   ├── functions/
│   │   ├── classify_domain.kql     # classify_domain(resource_type: string) → string
│   │   ├── classify_alerts.kql     # classify_alerts() — Sev0–Sev2 filter + domain classification
│   │   └── enrich_alerts.kql       # enrich_alerts() — add resource name, subscription name
│   ├── policies/
│   │   └── update_policies.kql     # Table update policies (raw → enriched → detection)
│   └── retention/
│       └── retention_policies.kql  # Eventhouse retention configuration
│
└── user-data-function/
    ├── main.py              # handle_activator_trigger() — entry point called by Fabric Activator
    │                        # get_access_token() — MSAL client credentials
    │                        # map_detection_result_to_payload() — DetectionResults → IncidentPayload
    ├── requirements.txt     # msal, requests
    └── __init__.py
```

The `classify_domain.kql` function is the **canonical** domain classification implementation; `services/detection-plane/classify_domain.py` is a Python mirror that must produce identical results (used by unit tests and as a Fabric validation layer).

---

## 5. `terraform/` — Infrastructure as Code

```
terraform/
├── envs/
│   ├── dev/                 # Development environment
│   │   ├── main.tf          # Module wiring for dev (lower capacity, serverless Cosmos)
│   │   ├── providers.tf     # azurerm + azapi + azuread + random + null providers
│   │   ├── variables.tf     # Input variables
│   │   ├── terraform.tfvars # Dev-specific values
│   │   ├── outputs.tf       # Exported values
│   │   └── backend.tf       # Azure Storage state backend (dev.tfstate)
│   │
│   ├── staging/             # Staging environment (mirrors prod structure)
│   └── prod/                # Production environment
│       ├── main.tf          # Full module composition with prod-scale configs
│       ├── imports.tf       # azurerm_import blocks for existing resources
│       ├── credentials.tfvars # Sensitive values (gitignored)
│       └── ...              # Same structure as dev
│
└── modules/
    ├── networking/          # VNet, subnets, private DNS zones
    ├── compute-env/         # Container Apps Environment, ACR
    ├── agent-apps/          # All Container Apps (agents + services + teams-bot)
    │                        # Key: local.agents + local.services → for_each loop
    │                        # Injects agent IDs, Foundry endpoints, Cosmos URL via env vars
    ├── foundry/             # Azure AI Services account, project, GPT-4o deployment
    │   └── capability-host.tf # azapi_resource for Foundry Hosted Agent capability host
    ├── databases/
    │   ├── cosmos.tf        # Cosmos DB account, database, containers (incidents/approvals/sessions)
    │   └── postgres.tf      # PostgreSQL Flexible Server with pgvector extension
    ├── eventhub/            # Event Hub namespace + hub
    ├── fabric/              # Fabric capacity, workspace (azapi); data plane optional
    ├── monitoring/          # Log Analytics workspace, Application Insights
    ├── keyvault/            # Azure Key Vault
    ├── private-endpoints/   # Centralized private endpoint module (Cosmos, ACR, KV, Foundry, EH)
    ├── rbac/                # Role assignments — domain-scoped least privilege
    ├── entra-apps/          # Web UI MSAL app registration (Entra)
    ├── arc-mcp-server/      # Arc MCP Server Container App (optional, disabled in prod)
    └── activity-log/        # Diagnostic settings: Activity Log → Log Analytics (multi-sub)
```

### Key Terraform Patterns

- **Provider split**: Standard resources via `azurerm`; Foundry capability hosts, Fabric, Entra Agent ID via `azapi`
- **agent-apps module**: Single `for_each` loop deploys all 9 agents + 2 services; dynamic env blocks inject agent IDs only to the relevant container
- **Identity**: All Container Apps use `SystemAssigned` managed identity; no stored credentials for Azure SDK access
- **State**: Per-environment state files in Azure Storage with Entra auth (no SAS keys)
- **lifecycle.ignore_changes**: Container image and env vars ignored after initial deploy (managed by CI/CD and manual az cli)

---

## 6. `e2e/` — End-to-End Tests

```
e2e/
├── global-setup.ts              # Playwright global setup (auth token acquisition)
├── global-teardown.ts           # Cleanup
├── fixtures/
│   └── auth.ts                  # Entra-authenticated browser fixture
│
├── e2e-incident-flow.spec.ts    # Full incident → triage → approval flow
├── e2e-hitl-approval.spec.ts    # Human-in-the-loop approval lifecycle
├── e2e-audit-export.spec.ts     # SOC 2 audit export
├── e2e-rbac.spec.ts             # Role-based access control
├── e2e-sse-reconnect.spec.ts    # SSE reconnect and event replay
├── e2e-teams-roundtrip.spec.ts  # Teams bot → API Gateway → Foundry roundtrip
└── arc-mcp-server.spec.ts       # Arc MCP Server tool coverage
```

---

## 7. Module Boundaries and Dependencies

### Python Package Boundaries

```
agents/shared/          ← imported by all agent packages
agents/{domain}/        ← standalone; imports only agents/shared/
services/api-gateway/   ← imports services/detection-plane/ (dedup_integration.py)
services/detection-plane/ ← standalone library (no service imports)
services/arc-mcp-server/  ← standalone server (no cross-service imports)
```

The `pythonpath = ["."]` in `pyproject.toml` makes top-level package imports work:
```python
from agents.shared.envelope import IncidentMessage
from services.api_gateway.models import IncidentPayload
```

### TypeScript Package Boundaries

Each TypeScript service has its own `package.json` and `node_modules`:
- `services/web-ui/` — Next.js app, independent
- `services/teams-bot/` — Express bot, independent
- `e2e/` — Playwright tests, independent

No shared TypeScript packages between services.

---

## 8. Key Files Reference

| File | Role |
|------|------|
| `agents/orchestrator/agent.py` | Central dispatcher; HandoffOrchestrator with 6 domain targets; `classify_incident_domain` @ai_function |
| `agents/shared/envelope.py` | `IncidentMessage` TypedDict; `validate_envelope()` — enforces AGENT-002 contract |
| `agents/shared/otel.py` | `setup_telemetry()`, `instrument_tool_call()` — OTel tracing for AUDIT-001 |
| `agents/shared/budget.py` | `BudgetTracker` — per-session $5 cost ceiling + 10 iteration cap |
| `agents/shared/approval_manager.py` | `create_approval_record()` — write-then-return HITL pattern |
| `agents/shared/runbook_tool.py` | `retrieve_runbooks()` — calls API Gateway runbook search from domain agents |
| `agents/arc/agent.py` | Arc Agent; mounts Arc MCP Server via `MCPTool(server_url=ARC_MCP_SERVER_URL)` |
| `services/api-gateway/main.py` | FastAPI app; all 13 route handlers; startup migrations |
| `services/api-gateway/models.py` | Pydantic models for all API contracts (IncidentPayload, ChatRequest, ApprovalRecord, etc.) |
| `services/api-gateway/auth.py` | `EntraTokenValidator`; `verify_token` FastAPI dependency |
| `services/api-gateway/foundry.py` | `create_foundry_thread()` — Foundry thread/message/run creation via `azure-ai-agents` |
| `services/api-gateway/chat.py` | `create_chat_thread()`, `get_chat_result()` — operator chat dispatch and polling |
| `services/api-gateway/runbook_rag.py` | `generate_query_embedding()`, `search_runbooks()` — pgvector cosine search |
| `services/arc-mcp-server/server.py` | `FastMCP` app with 9 Arc tool registrations |
| `services/detection-plane/models.py` | `IncidentRecord`, `AlertStatus`, state machine constants |
| `services/detection-plane/dedup.py` | `dedup_layer1()`, `dedup_layer2()` — 2-layer alert deduplication with ETag concurrency |
| `services/detection-plane/classify_domain.py` | `classify_domain()` — Python mirror of KQL classify_domain function |
| `fabric/user-data-function/main.py` | `handle_activator_trigger()` — Fabric entry point; maps + dispatches to API Gateway |
| `services/teams-bot/src/bot.ts` | `AapTeamsBot` — message handler, Adaptive Card invoke handler |
| `services/teams-bot/src/services/gateway-client.ts` | Typed API Gateway client (chat, approvals, incident lookup) |
| `services/web-ui/app/api/stream/route.ts` | SSE route handler — polls Foundry run status, emits token/done/heartbeat events |
| `services/web-ui/components/AppLayout.tsx` | Root split-pane layout (Chat 35% + Dashboard 65%) |
| `services/web-ui/components/ChatPanel.tsx` | Full chat UI with SSE streaming, approval gate rendering |
| `services/web-ui/lib/use-sse.ts` | `useSSE()` hook — reconnect logic, event routing |
| `services/web-ui/lib/sse-buffer.ts` | `globalEventBuffer` — ring buffer for SSE reconnect replay |
| `terraform/envs/prod/main.tf` | Full module composition for production environment |
| `terraform/modules/agent-apps/main.tf` | Container App definitions for all agents + services (for_each) |
| `pyproject.toml` | pytest config, test markers, pythonpath |

---

## 9. Service Boundaries

### What Each Service Owns

| Service | Owns | Does NOT Own |
|---------|------|-------------|
| `api-gateway` | Incident ingestion, dedup, Foundry dispatch, chat orchestration, approval CRUD, audit queries, runbook RAG, Teams notification proxy | Agent reasoning, resource queries, execution of remediation |
| `arc-mcp-server` | Arc resource data retrieval (HybridCompute, ConnectedK8s, ArcData) | Alert classification, triage logic, remediation |
| `detection-plane` | Alert schema, domain classification, deduplication logic, state machine models | HTTP transport, Foundry integration (handled by User Data Function in fabric/) |
| `teams-bot` | Teams activity handling, Adaptive Card rendering, proactive messaging, conversation state | Direct Azure resource access, incident storage |
| `web-ui` | UI rendering, SSE streaming, browser auth (MSAL), API proxying | Direct Azure SDK calls (all go through API Gateway) |

### Agent Specialization

| Agent | Scope | MCP Tool Surface | RBAC Scope |
|-------|-------|-----------------|------------|
| Orchestrator | Routing only — no resource queries | `classify_incident_domain` @ai_function only | None (read Foundry threads) |
| Compute | VMs, VMSS, AKS nodes, App Service | Azure MCP: compute, monitor, resourcehealth | VM Contributor + Monitoring Reader (compute sub) |
| Network | VNets, NSGs, LBs, DNS, ExpressRoute | Azure MCP: network, monitor, resourcehealth | Network Contributor + Monitoring Reader (network sub) |
| Storage | Blob, Files, ADLS Gen2, managed disks | Azure MCP: storage, monitor, resourcehealth | Storage Account Contributor + Monitoring Reader (storage sub) |
| Security | Defender, Key Vault, RBAC drift | Azure MCP: keyvault, security, role | Security Reader + Key Vault Reader |
| SRE | Cross-domain, SLA/SLO, fallback | Azure MCP: monitor, resourcehealth, advisor, applicationinsights | Reader + Monitoring Reader (all subs) |
| Arc | Arc Servers, Arc K8s, Arc Data | **Custom Arc MCP Server** (9 tools) + Azure MCP: monitor | Reader on Arc subscriptions |

---

## 10. Configuration and Environment Variables

### Critical Environment Variables (Container Apps)

| Variable | Used By | Source |
|----------|---------|--------|
| `AZURE_PROJECT_ENDPOINT` | All agents, API Gateway | Foundry module output |
| `FOUNDRY_ACCOUNT_ENDPOINT` | All (fallback for above) | Foundry module output |
| `ORCHESTRATOR_AGENT_ID` | API Gateway, Orchestrator | Manual: Foundry console |
| `COMPUTE_AGENT_ID` | Orchestrator | Manual: Foundry console |
| `NETWORK_AGENT_ID` | Orchestrator | Manual: Foundry console |
| `STORAGE_AGENT_ID` | Orchestrator | Manual: Foundry console |
| `SECURITY_AGENT_ID` | Orchestrator | Manual: Foundry console |
| `SRE_AGENT_ID` | Orchestrator | Manual: Foundry console |
| `ARC_AGENT_ID` | Orchestrator | Manual: Foundry console |
| `ARC_MCP_SERVER_URL` | Arc Agent | Arc MCP Server module output |
| `COSMOS_ENDPOINT` | API Gateway, agents (budget/approvals) | Databases module output |
| `COSMOS_DATABASE_NAME` | API Gateway, agents | terraform.tfvars |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | All (OTel) | Key Vault secret |
| `CORS_ALLOWED_ORIGINS` | API Gateway | terraform.tfvars / env-specific |
| `API_GATEWAY_AUTH_MODE` | API Gateway | `entra` (default) or `disabled` (dev) |
| `AZURE_CLIENT_ID` | API Gateway (Entra auth) | Entra app registration |
| `AZURE_TENANT_ID` | API Gateway (Entra auth) | Terraform variables |

---

## 11. Test Organization

Test files are co-located with the code they test, following the `pytest` `testpaths = ["agents", "services"]` configuration.

### Test Markers

```
unit         — Fast tests, no external dependencies
integration  — Require live Foundry/Cosmos connections
slow         — >10 seconds
e2e          — Playwright browser tests
sc1–sc6      — Success criteria gates (FMP latency, SSE reconnect, RAG, HITL, etc.)
```

### Coverage Areas

| Area | Test Files |
|------|-----------|
| API Gateway routing | `test_chat_endpoint.py`, `test_incidents.py`, `test_health.py` |
| Auth security | `test_auth_security.py` |
| Approval lifecycle | `test_approval_lifecycle.py` |
| Audit trail | `test_audit_trail.py`, `test_audit_export.py` |
| Runbook RAG | `test_runbook_rag.py`, `test_runbook_search_availability.py` |
| SSE streaming | `test_sse_stream.py`, `test_sse_heartbeat.py` |
| Teams notifier | `test_teams_notifier.py` |
| Rate limiting | `test_rate_limiting.py` |
| Domain classification | `test_classify_domain.py` (unit) |
| Alert dedup | `test_dedup.py` (unit), `test_dedup_load.py` (integration) |
| Agent handoff | `test_handoff.py` (integration) |
| Budget guard | `test_budget.py` (shared + integration) |
| Envelope validation | `test_envelope.py` (unit) |
| Arc MCP Server | `test_arc_servers.py`, `test_arc_k8s.py`, `test_arc_data.py` |
| E2E flows | `e2e-incident-flow`, `e2e-hitl-approval`, `e2e-sse-reconnect`, etc. |
