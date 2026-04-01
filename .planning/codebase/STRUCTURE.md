# Directory Structure

> Last updated: 2026-04-01 (Phases 1–13 complete)

---

## Top-level layout

```
azure-agentic-platform/
├── agents/                  # Python domain agents (Foundry Hosted Agents / Container Apps)
├── services/                # Runtime services (API Gateway, Web UI, Teams Bot, MCP Servers, Detection Plane)
├── fabric/                  # Fabric Eventhouse KQL definitions and User Data Function
├── terraform/               # Infrastructure as Code (azurerm + azapi + azuread)
├── e2e/                     # Playwright end-to-end tests
├── docs/                    # Supplemental documentation (BOOTSTRAP.md, MANUAL-SETUP.md, agents/, superpowers/, verification/)
├── scripts/                 # Utility/maintenance scripts (provision, seed, simulate, wire agents)
├── tasks/                   # Planning artifacts (todo.md, lessons.md)
├── pyproject.toml           # Python project config: pytest settings, markers, pythonpath=["."]
├── conftest.py              # Root pytest conftest
└── _aap_bootstrap.py        # One-time platform bootstrap script
```

---

## services/ breakdown

```
services/
├── __init__.py
│
├── api-gateway/              # FastAPI — incident ingestion, chat, approvals, audit, runbook RAG
├── arc-mcp-server/           # Custom FastMCP server — Arc resource coverage gap filler
├── azure-mcp-server/         # @azure/mcp npm proxy wrapper (Node.js)
├── detection-plane/          # Detection plane logic library (domain classification, dedup, state)
├── teams-bot/                # TypeScript Teams bot (new Teams SDK)
└── web-ui/                   # Next.js 15 App Router web UI
```

### services/api-gateway/

FastAPI service. Single entry point for all external and inter-service communication. Thin routing layer — no business logic.

```
services/api-gateway/
├── main.py               # FastAPI app: all 13+ routes, CORS, lifespan startup migrations
├── models.py             # Pydantic models: IncidentPayload, ChatRequest, ApprovalRecord,
│                         #   ChatResponse, ChatResultResponse, AuditEntry, RunbookResult, etc.
├── auth.py               # verify_token FastAPI dependency (Entra ID Bearer)
├── dependencies.py       # get_cosmos_client, get_credential shared FastAPI dependencies
├── foundry.py            # create_foundry_thread() — Foundry thread/message/run via azure-ai-projects
├── chat.py               # create_chat_thread(), get_chat_result(), _approve_pending_subrun_mcp_calls()
├── approvals.py          # get_approval(), list_approvals_*, process_approval_decision()
├── audit.py              # query_audit_log() — Application Insights KQL queries
├── audit_export.py       # generate_remediation_report() — SOC 2 export
├── audit_trail.py        # Audit trail append helpers
├── incidents_list.py     # list_incidents() — Cosmos DB query with filters
├── dedup_integration.py  # check_dedup() — wires detection-plane dedup into gateway
├── runbook_rag.py        # generate_query_embedding(), search_runbooks() — pgvector cosine RAG
├── azure_tools.py        # AzureToolRequest/Response; call_azure_tool() — Azure MCP stdio bridge
├── teams_notifier.py     # notify_teams(), post_approval_card(), post_alert_card()
├── rate_limiter.py       # Per-client sliding-window rate limiter (Cosmos-backed)
├── http_rate_limiter.py  # Per-IP HTTP middleware rate limiter (chat + incidents endpoints)
├── remediation_logger.py # Remediation action logging to Cosmos DB
├── instrumentation.py    # foundry_span(), agent_span(), mcp_span() OTel context manager helpers
├── health.py             # /health router (HealthResponse, /health/ready)
├── patch_endpoints.py    # /api/v1/patch/* router (Phase 13 — patch compliance endpoints)
└── tests/                # 24 pytest test files (co-located with implementation)
    ├── conftest.py
    ├── test_approval_lifecycle.py
    ├── test_approvals_404.py
    ├── test_audit_export.py
    ├── test_audit_trail.py
    ├── test_auth_security.py
    ├── test_chat_endpoint.py
    ├── test_dependencies.py
    ├── test_gitops_path.py
    ├── test_health_ready.py
    ├── test_health.py
    ├── test_http_rate_limiter.py
    ├── test_incidents_list.py
    ├── test_incidents.py
    ├── test_patch_endpoints.py
    ├── test_rate_limiting.py
    ├── test_remediation_logger.py
    ├── test_resource_identity.py
    ├── test_runbook_rag.py
    ├── test_runbook_search_availability.py
    ├── test_sse_heartbeat.py
    ├── test_sse_stream.py
    └── test_teams_notifier.py
```

**Startup migrations** (lifespan): creates `runbooks` table (pgvector 1536-dim, ivfflat cosine index), `eol_cache` table (24h TTL, UNIQUE on product+version+source), and enables the `vector` extension.

### services/arc-mcp-server/

Custom Python FastMCP server filling the Azure MCP Server's Arc coverage gap.

```
services/arc-mcp-server/
├── server.py             # FastMCP("arc-mcp-server", stateless_http=True) — 9 @mcp.tool() registrations
├── __main__.py           # Entry point
├── auth.py               # DefaultAzureCredential helpers
├── models.py             # Pydantic response models (ArcServerDetail, ArcK8sSummary, etc.)
├── tools/
│   ├── arc_servers.py    # arc_servers_list_impl, arc_servers_get_impl, arc_extensions_list_impl
│   ├── arc_k8s.py        # arc_k8s_list_impl, arc_k8s_get_impl, arc_k8s_gitops_status_impl
│   └── arc_data.py       # arc_data_sql_mi_list_impl, arc_data_sql_mi_get_impl, arc_data_postgresql_list_impl
├── tests/
│   ├── conftest.py
│   ├── test_arc_servers.py
│   ├── test_arc_k8s.py
│   ├── test_arc_data.py
│   └── test_pagination.py
├── Dockerfile
└── requirements.txt
```

**Transport**: Streamable HTTP on port 8080. `stateless_http=True` — safe for multi-replica Container App deployment (no session affinity required).

### services/azure-mcp-server/

```
services/azure-mcp-server/
├── proxy.js              # Node.js stdio → HTTP proxy wrapping @azure/mcp
└── Dockerfile
```

### services/detection-plane/

Standalone Python library. No HTTP server — consumed by `fabric/user-data-function/` and imported by `services/api-gateway/dedup_integration.py`.

```
services/detection-plane/
├── models.py             # IncidentRecord, AlertStatus, StatusHistoryEntry (Cosmos DB schema)
├── classify_domain.py    # classify_domain(resource_type) — Python mirror of KQL function
├── dedup.py              # dedup_layer1() / dedup_layer2() — 2-layer alert dedup with ETag concurrency
├── alert_state.py        # Alert state machine: new → acknowledged → closed
├── payload_mapper.py     # DetectionResults row → IncidentPayload mapping
└── tests/
    ├── unit/
    │   ├── test_alert_state.py
    │   ├── test_classify_domain.py
    │   ├── test_dedup.py
    │   ├── test_kql_pipeline.py
    │   ├── test_payload_mapper.py
    │   └── test_user_data_function.py
    └── integration/
        ├── test_activity_log.py
        ├── test_dedup_load.py
        ├── test_pipeline_flow.py
        ├── test_round_trip.py
        ├── test_state_sync.py
        └── test_suppression.py
```

### services/teams-bot/

TypeScript, new Teams SDK (`@microsoft/teams.js`), Express server on port 3978.

```
services/teams-bot/
├── src/
│   ├── index.ts              # Express server entry point
│   ├── bot.ts                # AapTeamsBot — activity handler, Adaptive Card invoke
│   ├── config.ts             # Environment config (BOT_ID, API_GATEWAY_INTERNAL_URL, etc.)
│   ├── types.ts              # TypeScript type definitions
│   ├── instrumentation.ts    # OpenTelemetry setup
│   ├── cards/
│   │   ├── alert-card.ts     # New incident Adaptive Card
│   │   ├── approval-card.ts  # Remediation proposal approve/reject card
│   │   ├── outcome-card.ts   # Remediation execution outcome card
│   │   └── reminder-card.ts  # Approval expiry reminder
│   ├── routes/
│   │   ├── health.ts         # GET /health
│   │   └── notify.ts         # POST /teams/internal/notify — internal alert/approval dispatch
│   └── services/
│       ├── auth.ts               # Entra token validation for inbound requests
│       ├── conversation-state.ts # In-memory thread_id per Teams conversation
│       ├── escalation.ts         # Approval timeout escalation
│       ├── gateway-client.ts     # GatewayClient — typed API Gateway wrapper
│       └── proactive.ts          # ConversationReference store + sendProactiveMessage()
├── appPackage/
│   └── manifest.json         # Teams App manifest (bot registration)
├── Dockerfile
├── package.json
├── tsconfig.json
└── vitest.config.ts
```

### services/web-ui/

Next.js 15 App Router, Fluent UI v9, Tailwind CSS, shadcn/ui primitives.

```
services/web-ui/
├── app/
│   ├── layout.tsx                # Root layout — FluentProvider, auth context, ThemeContext
│   ├── page.tsx                  # Root page → <AuthenticatedApp />
│   ├── providers.tsx             # React context providers (MSAL, theme)
│   ├── globals.css               # Tailwind base styles
│   ├── (auth)/
│   │   ├── login/page.tsx        # MSAL login redirect
│   │   └── callback/page.tsx     # MSAL auth code callback
│   └── api/
│       ├── stream/route.ts           # GET /api/stream — SSE polling loop (token/trace/done/heartbeat)
│       ├── proxy/
│       │   ├── chat/route.ts         # POST → /api/v1/chat
│       │   ├── chat/result/route.ts  # GET  → /api/v1/chat/{id}/result
│       │   ├── incidents/route.ts    # GET  → /api/v1/incidents
│       │   └── approvals/
│       │       ├── [approvalId]/approve/route.ts
│       │       └── [approvalId]/reject/route.ts
│       ├── resources/route.ts        # Azure ARM resource inventory (direct Azure SDK)
│       ├── subscriptions/route.ts    # Available Azure subscriptions
│       ├── topology/route.ts         # Resource topology / relationships
│       └── observability/route.ts   # Log Analytics observability metrics
├── components/
│   ├── AppLayout.tsx             # Root split-pane (Chat 35% + Dashboard 65%)
│   ├── AuthenticatedApp.tsx      # MSAL auth guard
│   ├── ChatDrawer.tsx            # Conversational chat panel with SSE streaming
│   ├── ChatBubble.tsx            # Agent message bubble
│   ├── ChatInput.tsx             # Message composer
│   ├── ChatFAB.tsx               # Floating action button for chat
│   ├── UserBubble.tsx            # Operator message bubble
│   ├── ThinkingIndicator.tsx     # Streaming/thinking animation
│   ├── ProposalCard.tsx          # Inline HITL approve/reject card
│   ├── DashboardPanel.tsx        # Tabbed dashboard container
│   ├── AlertFeed.tsx             # Live incident feed (polling)
│   ├── AlertFilters.tsx          # Severity/domain/status filter bar
│   ├── AuditLogViewer.tsx        # Agent action audit log (OTel spans)
│   ├── ObservabilityTab.tsx      # Platform health metrics (latency, pipeline lag, errors)
│   ├── ResourcesTab.tsx          # ARM resource inventory
│   ├── TopologyTab.tsx           # Resource topology graph
│   ├── PatchTab.tsx              # Patch compliance dashboard (Phase 13)
│   ├── TraceTree.tsx             # Agent reasoning trace tree
│   ├── SubscriptionSelector.tsx  # Multi-subscription dropdown
│   ├── NavSubscriptionPill.tsx   # Subscription pill in top nav
│   ├── TopNav.tsx                # Top navigation bar
│   ├── MetricCard.tsx            # Reusable metric display
│   ├── ActiveErrorsCard.tsx      # Active error count card
│   ├── AgentLatencyCard.tsx      # Agent P50/P95 latency card
│   ├── PipelineLagCard.tsx       # Detection pipeline lag card
│   ├── ApprovalQueueCard.tsx     # Pending approval count card
│   ├── DesktopOnlyGate.tsx       # Mobile viewport guard
│   └── ui/                       # shadcn/ui primitives (19 components)
│       ├── alert.tsx, badge.tsx, button.tsx, card.tsx, checkbox.tsx
│       ├── collapsible.tsx, command.tsx, dialog.tsx, dropdown-menu.tsx
│       ├── input.tsx, popover.tsx, scroll-area.tsx, select.tsx
│       ├── separator.tsx, skeleton.tsx, table.tsx, tabs.tsx
│       ├── textarea.tsx, tooltip.tsx
├── lib/
│   ├── api-gateway.ts            # Typed API Gateway client functions
│   ├── app-state-context.tsx     # Global app state context (subscription selection, etc.)
│   ├── format-relative-time.ts   # Time formatting utilities
│   ├── msal-config.ts            # MSAL configuration
│   ├── msal-instance.ts          # Singleton MSAL PublicClientApplication
│   ├── sse-buffer.ts             # globalEventBuffer — ring buffer for SSE reconnect replay
│   ├── theme-context.tsx         # Light/dark theme context
│   ├── use-auth.ts               # useAuth() hook — MSAL token acquisition
│   ├── use-resizable.ts          # useResizable() hook — panel resize
│   ├── use-sse.ts                # useSSE() hook — SSE connection with reconnect logic
│   └── utils.ts                  # Shared utilities (cn(), etc.)
├── types/                        # TypeScript type definitions
├── __tests__/                    # Jest unit tests (auth, layout)
├── __mocks__/                    # Jest mocks
├── components.json               # shadcn/ui configuration
├── next.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── jest.config.js
├── playwright.config.ts
└── Dockerfile
```

**SSE protocol** (`/api/stream`):
- `event: token` — `{ delta, agent, seq }` — incremental text
- `event: done` — `{ seq }` — run completion
- `event: trace` — `{ type: "approval_gate", approval_id, proposal, expires_at }`
- `: heartbeat` — SSE comment every 20s (keeps proxies alive)
- Reconnect: `Last-Event-ID` / `last_seq` → ring buffer replays missed events

---

## Key files per service

| File | Role |
|---|---|
| `agents/orchestrator/agent.py` | `create_orchestrator()` — ChatAgent with `classify_incident_domain` tool; 8 connected-agent routing targets |
| `agents/shared/envelope.py` | `IncidentMessage` TypedDict; `validate_envelope()` — AGENT-002 inter-agent contract |
| `agents/shared/routing.py` | `classify_query_text()` — keyword-based domain detection for operator queries |
| `agents/shared/otel.py` | `setup_telemetry()`, `instrument_tool_call()` — OTel tracing (AUDIT-001) |
| `agents/shared/budget.py` | `BudgetTracker` — $5 cost ceiling + 10 iteration cap (Cosmos DB + ETag) |
| `agents/shared/approval_manager.py` | `create_approval_record()` — write-then-return HITL (Cosmos DB) |
| `agents/shared/runbook_tool.py` | `retrieve_runbooks()` — `@ai_function` calling API Gateway runbook search |
| `agents/arc/agent.py` | `create_arc_agent()` — mounts Arc MCP Server via `MCPTool` |
| `agents/patch/agent.py` | `create_patch_agent()` — Update Manager specialist (Phase 13) |
| `agents/eol/agent.py` | `create_eol_agent()` — software lifecycle specialist (Phase 12/13) |
| `services/api-gateway/main.py` | FastAPI app — all routes, CORS, lifespan startup migrations |
| `services/api-gateway/models.py` | All Pydantic request/response models |
| `services/api-gateway/auth.py` | `verify_token` FastAPI dependency (Entra ID) |
| `services/api-gateway/foundry.py` | `create_foundry_thread()` — Foundry thread/message/run via `azure-ai-projects` |
| `services/api-gateway/chat.py` | `create_chat_thread()`, `get_chat_result()`, `_approve_pending_subrun_mcp_calls()` |
| `services/api-gateway/patch_endpoints.py` | `/api/v1/patch/*` router (Phase 13) |
| `services/api-gateway/runbook_rag.py` | `generate_query_embedding()`, `search_runbooks()` — pgvector cosine RAG |
| `services/api-gateway/azure_tools.py` | `call_azure_tool()` — Azure MCP stdio proxy bridge |
| `services/arc-mcp-server/server.py` | FastMCP app — 9 Arc tool registrations (stateless_http=True) |
| `services/detection-plane/classify_domain.py` | `classify_domain()` — Python mirror of KQL `classify_domain()` function |
| `services/detection-plane/dedup.py` | `dedup_layer1()`, `dedup_layer2()` — 2-layer dedup with ETag concurrency |
| `fabric/user-data-function/main.py` | `handle_activator_trigger()` — Fabric entry point; maps + dispatches to API Gateway |
| `services/teams-bot/src/bot.ts` | `AapTeamsBot` — Teams activity handler, Adaptive Card invoke |
| `services/teams-bot/src/services/gateway-client.ts` | Typed API Gateway client (chat, approvals, incidents) |
| `services/web-ui/app/api/stream/route.ts` | SSE route — polls Foundry run status, emits token/done/heartbeat |
| `services/web-ui/components/AppLayout.tsx` | Root split-pane layout (Chat 35% + Dashboard 65%) |
| `services/web-ui/components/ChatDrawer.tsx` | Full chat UI with SSE streaming, ProposalCard rendering |
| `services/web-ui/components/PatchTab.tsx` | Patch compliance tab (Phase 13) |
| `services/web-ui/lib/use-sse.ts` | `useSSE()` hook — SSE reconnect + ring buffer |
| `services/web-ui/lib/sse-buffer.ts` | `globalEventBuffer` — in-memory ring buffer for reconnect replay |
| `terraform/modules/agent-apps/main.tf` | Container App definitions for all agents + services (`for_each`) |
| `pyproject.toml` | pytest config, test markers (unit/integration/sc1–sc6), `pythonpath=["."]` |

---

## Configuration files

| File | Purpose |
|---|---|
| `pyproject.toml` | Python project: pytest testpaths, markers, pythonpath |
| `conftest.py` | Root pytest conftest (shared fixtures) |
| `agents/requirements-base.txt` | Shared Python deps: `agent-framework 1.0.0rc5`, `azure-ai-projects>=2.0.1`, `mcp[cli]>=1.26.0` |
| `services/api-gateway/Dockerfile` | FastAPI container (port 8000) |
| `services/arc-mcp-server/Dockerfile` | FastMCP container (port 8080) |
| `services/arc-mcp-server/requirements.txt` | `mcp[cli]`, `azure-mgmt-hybridcompute`, `azure-mgmt-hybridkubernetes`, `azure-mgmt-azurearcdata` |
| `services/web-ui/next.config.ts` | Next.js config (Node.js runtime for API routes) |
| `services/web-ui/tailwind.config.ts` | Tailwind configuration |
| `services/web-ui/components.json` | shadcn/ui configuration |
| `services/web-ui/jest.config.js` | Jest config for web-ui unit tests |
| `services/web-ui/playwright.config.ts` | Playwright config for web-ui E2E |
| `services/teams-bot/vitest.config.ts` | Vitest config for teams-bot unit tests |
| `e2e/playwright.config.ts` | Root Playwright config for full E2E suite |
| `.github/workflows/` | 20 CI/CD workflows (see below) |

**GitHub Actions workflows** (`.github/workflows/`):

| Workflow | Trigger | Purpose |
|---|---|---|
| `terraform-plan.yml` | PR | `terraform plan` output as PR comment |
| `terraform-apply.yml` | merge to main | `terraform apply -auto-approve` |
| `api-gateway-build.yml` | push | Build + push `api-gateway` image to ACR |
| `web-ui-build.yml` | push | Build + push `web-ui` image to ACR |
| `teams-bot-build.yml` | push | Build + push `teams-bot` image to ACR |
| `arc-mcp-server-build.yml` | push | Build + push `arc-mcp-server` image to ACR |
| `azure-mcp-server-build.yml` | push | Build + push `azure-mcp-server` image to ACR |
| `agent-images.yml` | push | Build + push all 9 domain agent images to ACR |
| `base-image.yml` | push | Build shared `Dockerfile.base` agent base image |
| `deploy-all-images.yml` | manual | Deploy all images in one shot |
| `container-app-deploy.yml` | merge | Update Container App revisions |
| `api-gateway-web-ui-ci.yml` | push | Combined pytest + Jest CI |
| `teams-bot-api-gateway-ci.yml` | push | Teams bot + API gateway integration CI |
| `detection-plane-ci.yml` | push | Detection plane pytest CI |
| `staging-e2e-simulation.yml` | schedule | Playwright E2E on staging |
| `agent-spec-lint.yml` | push | Agent system prompt linting |
| `security-review.yml` | push | bandit + dependency audit |
| `terraform-detection.yml` | push | Detection plane Terraform plan |
| `prod-db-setup.yml` | manual | Production PostgreSQL + pgvector setup |
| `docker-push.yml` | manual | Manual image push override |

---

## Infrastructure layout (terraform/)

```
terraform/
├── envs/
│   ├── dev/
│   │   ├── main.tf           # Module wiring: networking, compute-env, agent-apps, foundry,
│   │   │                     #   databases, eventhub, monitoring, keyvault, rbac, entra-apps
│   │   ├── providers.tf      # azurerm ~4.65.0, azapi ~2.9.0, azuread ~3.x, random, null
│   │   ├── variables.tf      # Input variables
│   │   ├── terraform.tfvars  # Dev-specific values (lower capacity, serverless Cosmos)
│   │   ├── outputs.tf        # Exported values (endpoints, IDs)
│   │   └── backend.tf        # Azure Storage state backend (dev.tfstate, Entra auth)
│   ├── staging/              # Mirrors dev structure, staging-scale configs
│   └── prod/
│       ├── main.tf           # Full module composition (prod-scale, multi-region Cosmos)
│       ├── imports.tf        # azurerm_import blocks for pre-existing resources
│       └── ...               # Same structure as dev + credentials.tfvars (gitignored)
│
└── modules/
    ├── networking/           # VNet (10.0.0.0/16), 4 subnets, private DNS zones
    │                         #   (Cosmos, ACR, Key Vault, Cognitive Services, Service Bus)
    ├── compute-env/          # Container Apps Environment (VNet-integrated), ACR
    ├── agent-apps/           # All Container Apps — single for_each loop over agents + services
    │                         #   Dynamic env blocks inject agent IDs, Foundry endpoints, Cosmos URL
    │                         #   lifecycle.ignore_changes on image + env (managed by CI/CD)
    ├── foundry/
    │   ├── main.tf           # AI Services account (kind=AIServices), AI Project, GPT-4o deployment
    │   ├── capability-host.tf # azapi_resource: Foundry capability host (enables Hosted Agents)
    │   ├── providers.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── databases/
    │   ├── cosmos.tf         # Cosmos DB: account, database, 3 containers
    │   │                     #   (incidents/resource_id, approvals/incident_id, sessions/user_id)
    │   │                     #   Prod: Autoscale 4000 RU, multi-region eastus2+westus2
    │   └── postgres.tf       # PostgreSQL Flexible Server + pgvector extension
    │                         #   Prod: GP_Standard_D4s_v3, 128 GB
    ├── eventhub/             # Event Hub namespace + hub (10 partitions prod)
    ├── fabric/               # Fabric capacity (F4 prod), workspace (azapi)
    ├── monitoring/           # Log Analytics workspace, Application Insights
    ├── keyvault/             # Azure Key Vault (bot password, app insights conn, SP creds)
    ├── private-endpoints/    # Centralised private endpoints (Cosmos, ACR, KV, Foundry, EH)
    ├── rbac/                 # Domain-scoped role assignments (least privilege per agent)
    ├── entra-apps/           # Web UI MSAL SPA app registration
    ├── arc-mcp-server/       # Arc MCP Server Container App (optional; disabled in prod)
    ├── teams-bot/            # Teams bot Container App
    └── activity-log/         # Diagnostic settings: Activity Log → Log Analytics (multi-sub)
```

**Key Terraform patterns**:
- **Provider split**: Standard resources via `azurerm`; Foundry capability hosts, Fabric, Entra Agent ID via `azapi`
- **agent-apps module**: Single `for_each` loop deploys all 9 agents + services; dynamic `env` blocks inject agent IDs only to relevant containers
- **Identity**: All Container Apps use `SystemAssigned` managed identity; no stored credentials for Azure SDK access
- **State**: Per-environment state files in Azure Storage with Entra auth (no SAS keys)

---

## Module boundaries and dependencies

### Python import boundaries

```
agents/shared/          ← imported by all agent packages (auth, envelope, otel, routing, etc.)
agents/{domain}/        ← standalone; imports only agents/shared/ and agent_framework
services/api-gateway/   ← imports services/detection-plane/ (dedup_integration.py)
                          imports agents/shared/routing (classify_query_text)
services/detection-plane/ ← standalone library (no service imports)
services/arc-mcp-server/  ← standalone server (no cross-service imports)
fabric/user-data-function/ ← standalone (self-contained payload mapping; no detection-plane import)
```

`pythonpath = ["."]` in `pyproject.toml` enables top-level absolute imports:
```python
from agents.shared.envelope import IncidentMessage
from services.api_gateway.models import IncidentPayload
from services.detection_plane.classify_domain import classify_domain
```

### TypeScript package boundaries

Each TypeScript service has its own `package.json` and `node_modules` — no shared packages:
- `services/web-ui/` — Next.js app (independent)
- `services/teams-bot/` — Express bot (independent)
- `e2e/` — Playwright tests (independent)

---

## agents/ breakdown

Each domain agent is an independently deployable container sharing a common base image and `agents/shared/` utilities.

```
agents/
├── requirements-base.txt    # Shared deps for all agent images
│
├── orchestrator/            # Central dispatcher (routes to 8 domain agents)
│   ├── agent.py             # create_orchestrator() — ChatAgent + classify_incident_domain @ai_function
│   ├── Dockerfile
│   └── requirements.txt
│
├── compute/                 # Azure compute specialist
│   ├── agent.py             # create_compute_agent()
│   ├── tools.py             # query_activity_log, query_log_analytics, query_resource_health,
│   │                        #   query_monitor_metrics; ALLOWED_MCP_TOOLS list
│   ├── Dockerfile
│   └── requirements.txt
│
├── network/                 # Azure network specialist
│   ├── agent.py             # create_network_agent()
│   ├── tools.py             # Network-scoped monitoring tools
│   └── ...
│
├── storage/                 # Azure storage specialist
│   ├── agent.py             # create_storage_agent()
│   ├── tools.py
│   └── ...
│
├── security/                # Azure security specialist
│   ├── agent.py             # create_security_agent()
│   ├── tools.py
│   └── ...
│
├── arc/                     # Azure Arc specialist
│   ├── agent.py             # create_arc_agent() — mounts Arc MCP Server via MCPTool
│   ├── tools.py             # ALLOWED_MCP_TOOLS + Arc-specific monitoring
│   └── ...
│
├── patch/                   # Update Manager / patch compliance specialist (Phase 13)
│   ├── agent.py             # create_patch_agent()
│   ├── tools.py             # Patch compliance tools
│   └── ...
│
├── eol/                     # Software end-of-life lifecycle specialist (Phase 12/13)
│   ├── agent.py             # create_eol_agent()
│   ├── tools.py             # EOL lookup tools (endoflife.date API + PostgreSQL cache)
│   └── ...
│
├── sre/                     # SRE generalist / cross-domain fallback
│   ├── agent.py             # create_sre_agent()
│   ├── tools.py             # propose_remediation, query_availability_metrics,
│   │                        #   query_performance_baselines
│   └── ...
│
├── shared/                  # Shared utilities (imported by all agents)
│   ├── auth.py
│   ├── envelope.py
│   ├── otel.py
│   ├── approval_manager.py
│   ├── budget.py
│   ├── routing.py
│   ├── triage.py
│   ├── runbook_tool.py
│   ├── resource_identity.py
│   └── gitops.py
│
└── tests/
    ├── integration/         # Integration tests (require live Foundry/Cosmos)
    └── shared/              # Unit tests for shared utilities
```

**Agent anatomy** (all domain agents follow this pattern):
1. **`agent.py`** — `create_<domain>_agent()` factory → `ChatAgent(instructions=..., tools=[...])`. Entry point: `from_agent_framework(create_<domain>_agent()).run()`
2. **`tools.py`** — `@ai_function`-decorated tool functions callable by the LLM + `ALLOWED_MCP_TOOLS` allowlist
3. **`Dockerfile`** — Extends base image, copies agent code, sets entry point
