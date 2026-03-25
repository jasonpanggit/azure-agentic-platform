<!-- GSD:project-start source:PROJECT.md -->
## Project

**Azure Agentic Platform (AAP)**

An enterprise-grade AI operations platform that uses a domain-specialist multi-agent architecture to perform continuous monitoring, auditing, alerting, triage, troubleshooting, and automated remediation across all Azure subscriptions and Arc-enabled resources (servers, Kubernetes, data services). The platform exposes a hybrid web UI (Fluent UI 2 + Next.js) with co-equal conversational chat and live operational dashboards, and integrates with Microsoft Teams for two-way agent interaction, alert delivery, and human-in-the-loop remediation approvals.

**Core Value:** Operators can understand, investigate, and resolve any Azure infrastructure issue — across all subscriptions and Arc-connected resources — through a single intelligent platform that shows its reasoning transparently and never acts without human approval.

### Constraints

- **Framework**: Microsoft Agent Framework (Python) — may still have breaking changes as it matures
- **Arc MCP gap**: Azure MCP Server does not cover Arc; requires custom MCP server development
- **Foundry Hosted Agents**: Still Preview; no private networking yet — Container Apps fill this gap
- **SK AzureAIAgent**: Experimental — avoid this path; use direct Foundry SDK (`azure-ai-projects`)
- **Fabric IQ**: Preview — Operations Agent and IQ workloads not GA; architect with graceful degradation
- **Entra Agent ID**: Preview — governance layer may change before GA
- **Timeline**: Phased delivery; MVP (core monitoring + chat + Teams alerts) in 3-6 months
- **Single tenant**: Multi-subscription within one Entra tenant; cross-tenant support deferred
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Core Agent Framework
### Microsoft Agent Framework (Python)
| Attribute | Value |
|---|---|
| **Package** | `agent-framework` |
| **Install** | `pip install agent-framework --pre` |
| **Latest version** | `1.0.0rc5` (released 2026-03-20) |
| **Status** | ⚠️ **Pre-release (RC)** — high-velocity, breaking changes likely before GA |
| **Python requirement** | ≥ 3.10 |
| **License** | MIT |
#### Key APIs
# Tool declaration
# Agent instantiation
- `ChatAgent` — the primary agent class for conversational agents; wraps `AzureAIAgentClient`
- `Agent` — lower-level base class; use `ChatAgent` for this platform
- `@ai_function` — decorator that exposes a Python function as an LLM-callable tool; replaces manual JSON schema definition
- `AzureAIAgentClient` — Azure AI Foundry backend client; uses `project_endpoint` + `DefaultAzureCredential`
- `OpenAIChatClient` / `AzureOpenAIChatClient` — non-Foundry backends; **not recommended here**
#### Supported Orchestration Patterns
| Pattern | Use in this Platform |
|---|---|
| **Sequential** | Orchestrator → Domain Agent → result chain |
| **Handoff** | Orchestrator delegates to Compute/Network/Storage/Security/Arc/SRE agents |
| **Group Chat** | Multi-specialist collaboration on complex incidents |
| **Concurrent** | Parallel agent fan-out for multi-domain investigations |
| **Magentic** | Agentic planning with self-directed subtask decomposition |
#### Deployment as Foundry Hosted Agents
# Packages required per agent container
# Entry point
- Protocol translation between Foundry Responses API and agent framework native format
- Auto-instrumentation (OpenTelemetry traces, metrics, logs)
- Conversation state management
- Local testability before containerization (test via `POST localhost:8088/responses`)
- Build with `--platform linux/amd64` (Hosted Agents run on Linux AMD64 only)
- Push to Azure Container Registry (ACR)
- Grant project managed identity `Container Registry Repository Reader` role on ACR
- `azure-ai-agentserver-core` — core adapter (all agents)
- `azure-ai-agentserver-agentframework` — Microsoft Agent Framework adapter
- `azure-ai-agentserver-langgraph` — LangGraph adapter (not needed here)
#### Rationale
#### Confidence: **MEDIUM** — RC quality, high-velocity; pin versions tightly
## Azure Integration Layer
### Foundry Agent Service SDK — `azure-ai-projects`
| Attribute | Value |
|---|---|
| **Package** | `azure-ai-projects` |
| **Install** | `pip install "azure-ai-projects>=2.0.1"` |
| **Latest stable version** | `2.0.1` (released 2026-03-12) |
| **Status** | ✅ **GA (Stable)** — production/stable, v1 Foundry REST APIs |
| **Python requirement** | ≥ 3.9 |
#### Key Classes for this Platform
# Streaming
#### Companion package — `azure-ai-agents`
| Attribute | Value |
|---|---|
| **Package** | `azure-ai-agents` |
| **Latest stable** | `1.1.0` (2025-08-05); pre-release `1.2.0b6` |
| **Status** | ⚠️ Stable but superseded by `azure-ai-projects` 2.x for most use cases |
#### Rationale
#### Confidence: **HIGH** — GA, production-stable
## MCP Tool Surfaces
### Azure MCP Server (GA)
| Attribute | Value |
|---|---|
| **Package** | `@azure/mcp` (npm, run as sidecar) OR invoke via `npx @azure/mcp@latest start` |
| **Distribution** | npm package `@azure/mcp`; also `azmcp` binary |
| **Status** | ✅ **GA** |
| **Authentication** | Entra ID via `DefaultAzureCredential` / managed identity |
#### Covered Services (confirmed in docs, March 2026)
| Domain | Tools Available |
|---|---|
| ARM / Resource management | `group`, `subscription`, `role`, `quota`, `policy`, `advisor`, `resourcehealth` |
| Compute | `compute` (VMs, VMSS, disks), `aks` (list), `appservice`, `functionapp`, `servicefabric` |
| Storage | `storage`, `fileshares`, `storagesync`, `managedlustre` |
| Databases | `cosmos`, `postgres`, `mysql`, `sql`, `redis` |
| Networking | (via `appservice`, `signalr`; no dedicated VNet/NSG tools confirmed) |
| Monitoring | `monitor` (Log Analytics queries + metrics), `applicationinsights`, `applens`, `workbooks` |
| Security | `keyvault`, `role` |
| AI/ML | `foundry`, `search`, `speech` |
| Messaging/Events | `eventhubs`, `servicebus`, `eventgrid` |
| DevOps | `deploy`, `bicepschema`, `grafana`, `loadtesting` |
| Identity | `role` (RBAC assignments) |
| Containers | `acr` (list) |
#### Arc Coverage Gap (CONFIRMED)
- Arc-enabled servers (`Microsoft.HybridCompute/machines`)
- Arc-enabled Kubernetes (`Microsoft.Kubernetes/connectedClusters`)
- Arc-enabled data services (SQL Managed Instance, PostgreSQL)
- Azure Arc extensions management
- Arc guest configuration / policy compliance
#### Mounting in a Foundry Hosted Agent
#### Confidence: **HIGH** — GA, tool list verified from docs
### Custom Arc MCP Server
| Attribute | Value |
|---|---|
| **Framework** | `mcp` Python package (FastMCP high-level API) |
| **Package** | `mcp[cli]` |
| **Install** | `pip install "mcp[cli]>=1.26.0"` |
| **Latest version** | `1.26.0` (released 2026-01-24) |
| **Python requirement** | ≥ 3.10 |
| **Transport** | Streamable HTTP (recommended for production) |
| **Status** | ✅ **Stable** |
#### Recommended Approach: FastMCP + Azure SDK
#### Azure SDK packages for Arc tools
#### Why FastMCP (not alternatives)
| Option | Verdict |
|---|---|
| **FastMCP (in `mcp` package)** | ✅ **Use this.** Official Python MCP SDK. Decorator-based, Pydantic validation, production Streamable HTTP transport, actively maintained by Anthropic/MCP community. Ships as `mcp.server.fastmcp`. |
| `mcp-python` (third-party) | ❌ Unofficial fork; do not use |
| `fastmcp` (separate PyPI package) | ⚠️ Was a community project; FastMCP is now absorbed into the official `mcp` package. Use `mcp[cli]` directly. |
| Bare REST API sidecar | ❌ Loses MCP protocol compliance, tool discovery, schema generation |
#### Confidence: **HIGH** — mcp 1.26.0 is stable; FastMCP is the idiomatic Python path
## Real-Time Detection Plane (Fabric)
### Fabric Eventhouse + Activator
| Component | Status | Notes |
|---|---|---|
| **Fabric Eventhouse** | ✅ GA | KQL-native time-series store; auto-mirrors to OneLake |
| **Fabric Activator** | ✅ GA | Event detection engine with webhook/pipeline trigger |
| **Fabric Eventstreams** | ✅ GA | No-code ingestion pipeline; Azure Event Hubs connector included |
| **Fabric IQ / Operations Agent** | ⚠️ Preview | Do NOT place on critical path; graceful degradation required |
#### Pipeline: Azure Monitor → Eventhouse → Activator → API
- Source: Azure Event Hubs (using Event Hub connection string or managed identity)
- Destination: Eventhouse KQL Database table
| where TimeGenerated > ago(5m)
| where AlertSeverity in ("Sev0", "Sev1", "Sev2")
| where AlertState == "New"
| where ResourceType == "microsoft.compute/virtualmachines"
| summarize AlertCount = count(),
| where AlertCount >= 1
- Fabric Pipelines, Notebooks, Spark Jobs, Functions
- Power Automate flows
- Teams notifications
- Email
# Fabric User Data Function triggered by Activator
#### Terraform provisioning of Fabric
#### Confidence: **HIGH** for Eventhouse + Activator (both GA). **LOW** for Fabric IQ/Operations Agent (Preview — exclude from critical path)
## Frontend (Next.js + Fluent UI 2)
### Next.js App Router
| Attribute | Value |
|---|---|
| **Package** | `next` |
| **Latest version** | `15.x` (Next.js 15; docs reference 16.2.1 route handler docs in March 2026) |
| **Install** | `npx create-next-app@latest --typescript --app` |
| **Runtime** | Node.js (not Edge Runtime — needed for Azure SDK calls in API routes) |
| **Status** | ✅ GA |
#### Token Streaming: SSE vs WebSocket
| Approach | Verdict |
|---|---|
| **SSE (ReadableStream in Route Handler)** | ✅ **Recommended.** Native Web API, no extra infra, works through Azure Container Apps, half-duplex (server → client) which is all that's needed for token streaming. |
| **WebSocket** | ⚠️ More complex; requires separate WebSocket server or Azure Web PubSub; Container Apps support WebSockets but adds operational overhead. Use only if bidirectional push is needed. |
| **Vercel AI SDK (`ai` package)** | ⚠️ Useful abstraction but adds a dependency and may conflict with Foundry's streaming format. Acceptable for prototyping. |
#### Confidence: **HIGH** — SSE + App Router Route Handlers is the established pattern
### Fluent UI 2
| Attribute | Value |
|---|---|
| **Package** | `@fluentui/react-components` |
| **Latest version** | `9.73.4` (released 2026-03-17) |
| **Install** | `npm install @fluentui/react-components` |
| **Styling engine** | Griffel (CSS-in-JS, SSR-compatible) |
| **Status** | ✅ GA (v9 is current stable) |
#### Next.js App Router SSR Considerations
#### What NOT to use
- `@fluentui/react` v8 — the legacy Fabric/Office UI Fabric package; heavy, Office-branded, not the right baseline for a modern Azure ops UI
- `@fluentui/web-components` — web components variant; does not compose well with React state
#### Confidence: **HIGH** — v9 is current and well-maintained; SSR pattern is settled
## Teams Integration
### Teams SDK (New, 2026)
| Attribute | Value |
|---|---|
| **TypeScript package** | `@microsoft/teams.js` + `@microsoft/teams.ai` (new Teams SDK) |
| **Python package** | `microsoft-teams-ai` (`teams-ai` on PyPI, v1.8.1 — **old SDK**) |
| **Python Teams SDK new** | `microsoft.teams` + `microsoft.teams.ai` (new SDK, Python preview) |
| **CLI bootstrap** | `npx @microsoft/teams.cli@latest new typescript my-agent --template echo` |
| **Status** | New Teams SDK: ✅ GA for TypeScript; ⚠️ Preview for Python |
#### Recommendation: TypeScript Teams Bot (New Teams SDK)
#### Adaptive Card Approval Flow
#### Legacy Bot Framework SDK — avoid for new development
| SDK | Verdict |
|---|---|
| `botbuilder` (Python, npm `botbuilder`) | ❌ **Avoid for new work.** Legacy Bot Framework SDK. Heavy, complex, not designed for AI-native bots. Still works but the new Teams SDK is the Microsoft-recommended path. |
| `teams-ai` (PyPI, v1.8.1) | ⚠️ Transitional — older Teams AI Library built on Bot Framework. Works but will not receive new features from the new SDK path. |
| New Teams SDK (`@microsoft/teams.js`) | ✅ **Use this.** Rebuilt from ground up, clean DX, active development. |
#### Confidence: **HIGH** for new Teams SDK TypeScript; **MEDIUM** for Python (behind TypeScript)
## Data Persistence
### Polyglot Persistence Summary
| Store | Package | Version | Use Case | Status |
|---|---|---|---|---|
| **Foundry Agent Service** | `azure-ai-projects` | 2.0.1 | Agent conversation threads + state | ✅ GA (managed) |
| **Azure Cosmos DB** | `azure-cosmos` (Python) | `4.x` | Hot-path alerts, agent session context, pending approvals | ✅ GA |
| **PostgreSQL Flexible Server** | `asyncpg` or `psycopg[binary]` | asyncpg `0.30.x`; psycopg3 `3.2.x` | Runbook library, RBAC config, platform settings | ✅ GA |
| **pgvector** | `pgvector` (Python) | `0.3.x` | Runbook RAG / semantic search | ✅ GA |
| **Fabric OneLake** | `azure-storage-file-datalake` | `12.x` | Audit logs, alert history, resource inventory snapshots | ✅ GA |
#### Cosmos DB Recommendations
#### PostgreSQL + pgvector for Runbook RAG
#### Confidence: **HIGH** across all persistence layers
## Infrastructure as Code (Terraform)
### Provider Strategy
| Provider | Version | When to Use |
|---|---|---|
| `azurerm` (HashiCorp) | `~> 4.65.0` (latest: 4.65.0, 2026-03-19) | Standard Azure resources: Container Apps, Cosmos DB, PostgreSQL, VNet, Storage, Key Vault, Event Hubs, ACR, App Insights |
| `azapi` (Azure) | `~> 2.9.0` (latest: 2.9.0, 2026-03-23) | Foundry resources, Fabric, Entra Agent ID, capability hosts, preview API features |
| `azuread` (HashiCorp) | `~> 3.x` | Entra ID service principals, app registrations, group membership |
#### Provider Configuration
#### Resource Mapping: azurerm vs azapi
| Resource | Provider | Terraform Resource |
|---|---|---|
| Resource Groups | `azurerm` | `azurerm_resource_group` |
| VNet + Subnets | `azurerm` | `azurerm_virtual_network`, `azurerm_subnet` |
| Container Apps Environment | `azurerm` | `azurerm_container_app_environment` |
| Container Apps | `azurerm` | `azurerm_container_app` |
| Cosmos DB Account | `azurerm` | `azurerm_cosmosdb_account` |
| PostgreSQL Flexible Server | `azurerm` | `azurerm_postgresql_flexible_server` |
| Azure Event Hubs | `azurerm` | `azurerm_eventhub_namespace`, `azurerm_eventhub` |
| Azure Container Registry | `azurerm` | `azurerm_container_registry` |
| Key Vault | `azurerm` | `azurerm_key_vault` |
| Application Insights | `azurerm` | `azurerm_application_insights` |
| Storage Account (Terraform state) | `azurerm` | `azurerm_storage_account` |
| **Foundry Account** | **`azurerm`** | **`azurerm_cognitive_account` (kind = "AIServices")** |
| **Foundry Project** | **`azurerm`** | **`azurerm_cognitive_account_project`** |
| **Foundry Model Deployment** | **`azurerm`** | **`azurerm_cognitive_deployment`** |
| **Foundry Capability Host** | **`azapi`** | `azapi_resource` (type: `Microsoft.CognitiveServices/accounts/capabilityHosts`) |
| **Foundry MCP Connection** | **`azapi`** | `azapi_resource` (type: `Microsoft.CognitiveServices/accounts/projects/connections`) |
| **Fabric Workspace** | **`azapi`** | `azapi_resource` (type: `Microsoft.Fabric/workspaces`) |
| **Fabric Eventhouse** | **`azapi`** | `azapi_resource` (type: `Microsoft.Fabric/workspaces/eventhouses`) |
| **Fabric Activator** | **`azapi`** | `azapi_resource` (type: `Microsoft.Fabric/workspaces/activators`) |
| **Entra Agent ID** | **`azapi`** | `azapi_data_plane_resource` (type: `Microsoft.Foundry/agents`) |
| Private Endpoints | `azurerm` | `azurerm_private_endpoint` |
| RBAC Assignments | `azurerm` | `azurerm_role_assignment` |
#### Key Foundry Terraform Pattern
# Foundry account (azurerm is sufficient for core provisioning)
# Foundry project
# Capability host (azapi required — not in azurerm)
#### State Management
# Backend: Azure Storage with Entra auth (no shared access keys)
- **PR**: `terraform plan` (output as PR comment via GitHub Actions)
- **Merge to main**: `terraform apply -auto-approve` (gated by required reviewers)
- Use separate state files per environment: `dev.tfstate`, `staging.tfstate`, `prod.tfstate`
#### Confidence: **HIGH** for azurerm 4.65.0; **HIGH** for azapi 2.9.0; azapi required for Foundry capability hosts, Fabric, and Entra Agent ID
## E2E Testing
### Playwright
| Attribute | Value |
|---|---|
| **Package** | `@playwright/test` |
| **Latest version** | `1.58.2` (released 2026-02-06) |
| **Install** | `npm install -D @playwright/test@1.58.2` |
| **Status** | ✅ GA, stable |
#### E2E Pattern for Entra-Protected Azure Container Apps
# .github/workflows/e2e.yml
- name: Run Playwright Tests
#### Confidence: **HIGH** — Playwright 1.58.2 is current stable; auth pattern is well-established
## What NOT to Use (and Why)
| Technology | Verdict | Reason |
|---|---|---|
| **AutoGen / AG2 (`pyautogen`)** | ❌ Do not use | AutoGen is in maintenance mode per Microsoft's own positioning; AG2 (community fork) has no enterprise support. Microsoft Agent Framework is the stated successor. |
| **Semantic Kernel `AzureAIAgent` wrapper** | ❌ Do not use | Explicitly marked **Experimental** in the Semantic Kernel SDK. Not a stable API; Microsoft's own docs flag this. Use `azure-ai-projects` directly. |
| **Semantic Kernel (core orchestration)** | ⚠️ Avoid for agent orchestration | SK is GA for plugins/planners but its agent orchestration primitives trail Microsoft Agent Framework. Would introduce framework fragmentation. SK remains useful for embedding/memory patterns. |
| **Copilot Studio / Power Platform agents** | ❌ Out of scope | Low-code, not developer-first. Insufficient programmatic control for AIOps. Confirmed out of scope in PROJECT.md. |
| **LangGraph** | ⚠️ Not recommended | LangGraph is supported by Foundry Hosted Agents (has an adapter), but it's a third-party framework with no Microsoft enterprise support. Introduces an external dependency for no benefit when Microsoft Agent Framework provides equivalent orchestration natively. |
| **AKS (Azure Kubernetes Service)** | ⚠️ Deferred | Container Apps is sufficient for this platform. Add AKS only if scale demands it. Confirmed deferred in PROJECT.md. |
| **Azure Container Instances (ACI)** | ❌ Do not use | No scaling, no managed networking, no revision management. Container Apps is strictly superior. |
| **@fluentui/react v8 ("Fabric")** | ❌ Do not use | Legacy Office UI Fabric; not actively developed for new features. v9 (`@fluentui/react-components`) is the correct package. |
| **Bot Framework SDK (`botbuilder`)** | ❌ Avoid for new bots | Legacy SDK. New Teams SDK (`@microsoft/teams.js`) is the Microsoft-recommended replacement with cleaner developer experience. |
| **`teams-ai` v1.8.1 (old Teams AI Library)** | ⚠️ Legacy path | Built on Bot Framework; will not receive new features. Migrate to new Teams SDK for fresh development. |
| **Vercel AI SDK (`ai` package)** | ⚠️ Use sparingly | Useful helper but opinionated about streaming format. May conflict with Foundry's SSE format. Use raw `ReadableStream` for direct Foundry integration; `ai` package only as a thin convenience wrapper if needed. |
| **`fastmcp` (separate PyPI package)** | ❌ Obsolete | FastMCP was a community project. It is now absorbed into the official `mcp` package as `mcp.server.fastmcp`. Use `pip install mcp[cli]`. |
| **Fabric IQ / Operations Agent** | ⚠️ Preview — keep off critical path | Not GA; no developer SDK. Use Eventhouse + Activator (both GA) for the detection plane. Add Fabric IQ semantic layer only as enrichment once GA. |
| **Entra Agent ID** | ⚠️ Preview — provision but plan for changes | Important for agent identity governance but the API may change before GA. Provision with `azapi` and be prepared for breaking changes in `2025-10-01-preview` API version. |
| **Foundry Hosted Agents** | ⚠️ Preview — no private networking | Critical architectural note: Hosted Agents do not support private networking during Preview. Container Apps fill this gap for VNet-isolated services. Do not put Hosted Agents behind a private endpoint until GA. |
| **Azure SignalR Service** | ⚠️ Overkill | Would add cost and complexity for WebSocket management. SSE via Container Apps is sufficient for token streaming and agent trace events. |
| **pgvector on Cosmos DB** | ⚠️ Not recommended | Cosmos DB for NoSQL vector search exists but pgvector on PostgreSQL is more mature for runbook RAG with hybrid keyword+vector search. Keep PostgreSQL as the runbook store. |
## Summary: Versions At a Glance
| Component | Package | Version | Status |
|---|---|---|---|
| Agent Framework | `agent-framework` | `1.0.0rc5` | ⚠️ Pre-release RC |
| Hosting Adapter | `azure-ai-agentserver-agentframework` | latest | ⚠️ Preview |
| Foundry SDK | `azure-ai-projects` | `2.0.1` | ✅ GA |
| Azure MCP Server | `@azure/mcp` (npm) | GA | ✅ GA |
| Arc MCP Framework | `mcp[cli]` | `1.26.0` | ✅ Stable |
| Fabric Eventhouse | (Fabric SaaS) | GA | ✅ GA |
| Fabric Activator | (Fabric SaaS) | GA | ✅ GA |
| Next.js | `next` | `15.x` | ✅ GA |
| Fluent UI v9 | `@fluentui/react-components` | `9.73.4` | ✅ GA |
| Teams SDK (TS) | `@microsoft/teams.js` | latest | ✅ GA (TS) |
| Cosmos DB SDK | `azure-cosmos` | `4.x` | ✅ GA |
| pgvector | `pgvector` | `0.3.x` | ✅ GA |
| Terraform azurerm | hashicorp/azurerm | `~> 4.65.0` | ✅ GA |
| Terraform azapi | azure/azapi | `~> 2.9.0` | ✅ GA |
| Playwright | `@playwright/test` | `1.58.2` | ✅ GA |
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
