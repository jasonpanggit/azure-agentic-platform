# Technology Stack — Azure Agentic Platform

> Generated: 2026-03-30. Source: requirements*.txt, package.json, Dockerfile*, terraform providers, CI workflows.

---

## Languages

| Language | Version | Where Used |
|---|---|---|
| **Python** | `3.12` (agents, API gateway); `3.11` (Arc MCP server); `>=3.10` (project minimum) | All backend services and agent containers |
| **TypeScript** | `^5.6` (teams-bot); `^5.0` (web-ui); `^6.0` (e2e) | Frontend, Teams bot, E2E tests |
| **HCL (Terraform)** | `>= 1.9.0` | All infrastructure-as-code |
| **KQL** | n/a | Fabric Eventhouse queries, detection rules |

---

## Python Backend Stack

### Core Agent Framework

| Package | Version | Purpose |
|---|---|---|
| `agent-framework` | `==1.0.0rc5` | Microsoft Agent Framework — ChatAgent, HandoffOrchestrator, @ai_function decorator |
| `azure-ai-projects` | `>=2.0.1` | Azure AI Foundry SDK (GA) — project/resource management |
| `azure-ai-agents` | `>=1.0.0` | Foundry agent thread/run/message operations (split from azure-ai-projects 2.x) |
| `azure-ai-agentserver-core` | latest | Foundry Hosted Agent protocol adapter |
| `azure-ai-agentserver-agentframework` | latest | Microsoft Agent Framework → Foundry adapter |
| `mcp[cli]` | `>=1.26.0` (base); `==1.26.0` (Arc MCP server) | FastMCP server framework (official Python MCP SDK) |

### API Gateway (FastAPI)

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | `>=0.115.0` | ASGI web framework |
| `uvicorn[standard]` | `>=0.30.0` | ASGI server (workers=2 in prod) |
| `pydantic` | `>=2.8.0` | Request/response validation, typed models |
| `fastapi-azure-auth` | `>=5.0.0` | Entra ID Bearer token validation (`SingleTenantAzureAuthorizationCodeBearer`) |

### Azure Identity & Integration

| Package | Version | Purpose |
|---|---|---|
| `azure-identity` | `>=1.17.0` | `DefaultAzureCredential` — managed identity resolution via IMDS |
| `azure-cosmos` | `>=4.0.0` – `>=4.7.0` | Cosmos DB SDK — incidents, approvals, sessions containers |
| `azure-storage-file-datalake` | `>=12.0.0` | OneLake / ADLS Gen2 — audit log and alert history export |
| `azure-mgmt-alertsmanagement` | `>=0.2.0` | Detection plane alert state management |

### Arc SDK (Arc MCP Server + Arc Agent)

| Package | Version | Purpose |
|---|---|---|
| `azure-mgmt-hybridcompute` | `==9.0.0` | Arc-enabled servers (HybridCompute/machines) |
| `azure-mgmt-hybridkubernetes` | `==1.1.0` | Arc-enabled Kubernetes (ConnectedClusters) |
| `azure-mgmt-azurearcdata` | `==1.0.0` | Arc-enabled data services (SQL MI, PostgreSQL) |
| `azure-mgmt-kubernetesconfiguration` | `==3.1.0` | Arc extensions and GitOps configuration |

### Observability

| Package | Version | Purpose |
|---|---|---|
| `azure-monitor-opentelemetry` | `>=1.0.0` – `>=1.6.0` | Azure Monitor + Application Insights auto-instrumentation |
| `opentelemetry-sdk` | `>=1.25.0` | OTel SDK — custom spans, trace context |
| `opentelemetry-exporter-otlp` | `>=1.25.0` | OTLP exporter |

### Database / RAG

| Package | Version | Purpose |
|---|---|---|
| `asyncpg` | `>=0.29.0` | Async PostgreSQL driver for pgvector runbook search |
| `pgvector` | `>=0.3.0` | pgvector Python adapter (`register_vector` for asyncpg) |
| `openai` | `>=1.0.0` | Azure OpenAI client — `text-embedding-3-small` embeddings (1536-dim) |
| `psycopg[binary]` | `>=3.1.0` | Sync PostgreSQL driver (runbook seed scripts) |
| `pyyaml` | `>=6.0` | YAML parsing (runbook seed scripts) |

### HTTP / Utilities

| Package | Version | Purpose |
|---|---|---|
| `httpx` | `>=0.27.0` | HTTP client (Arc agent integration tests) |
| `requests` | `>=2.31.0` | HTTP client (Fabric user-data-function, incident simulation) |
| `msal` | `>=1.28.0` | Microsoft Authentication Library (Fabric user-data-function) |

---

## TypeScript / Node.js Stack

### Web UI (`services/web-ui`)

| Package | Version | Purpose |
|---|---|---|
| `next` | `^15.0.0` | Next.js App Router — SSR, Route Handlers, SSE streaming |
| `react` / `react-dom` | `^19.0.0` | React runtime |
| `typescript` | `^5.0.0` | Type checking |
| **Tailwind CSS** | `^3.4.19` | Utility-first CSS |
| `tailwindcss-animate` | `^1.0.0` | CSS animations |
| `@tailwindcss/typography` | `^0.5.0` | Markdown typography plugin |
| `postcss` | `^8.0.0` | CSS processing |
| **Radix UI** (11 packages) | `^1.x` – `^2.x` | Headless UI primitives (dialog, tabs, select, tooltip, etc.) |
| `lucide-react` | `^0.400.0` | Icon library |
| `class-variance-authority` | `^0.7.0` | Component variant management |
| `clsx` | `^2.1.0` | Conditional class merging |
| `tailwind-merge` | `^2.0.0` | Tailwind class deduplication |
| `cmdk` | `^1.1.1` | Command palette component |
| `react-markdown` | `^9.0.0` | Markdown rendering |
| `remark-gfm` | `^4.0.1` | GitHub Flavored Markdown |
| `react-resizable-panels` | `^2.0.0` | Resizable split-panel layouts |
| `@azure/cosmos` | `^4.0.0` | Cosmos DB SDK (client-side, dashboard use) |
| `@azure/identity` | `^4.0.0` | Azure identity (token acquisition) |
| `@azure/monitor-query` | `^1.3.0` | Log Analytics / metrics queries from UI |
| `@azure/msal-browser` | `^3.0.0` | MSAL — browser-side Entra auth |
| `@azure/msal-react` | `^2.0.0` | MSAL React hooks/context |

> **Note:** The CLAUDE.md spec lists Fluent UI 2 (`@fluentui/react-components`) as the intended UI library, but the actual codebase uses Radix UI + Tailwind CSS (shadcn/ui component pattern). The `components.json` file confirms this is a shadcn/ui setup.

### Teams Bot (`services/teams-bot`)

| Package | Version | Purpose |
|---|---|---|
| `botbuilder` | `^4.23.0` | Bot Framework SDK — Teams messaging protocol |
| `@microsoft/teams-ai` | `^1.5.0` | Teams AI Library (built on Bot Framework) |
| `express` | `^4.21.0` | HTTP server (listens on port 3978) |
| `@azure/identity` | `^4.5.0` | Azure identity |
| `adaptivecards` | `^3.0.0` | Adaptive Card rendering (HITL approval cards) |
| `@azure/monitor-opentelemetry` | `^1.0.0` | Azure Monitor integration |
| `@opentelemetry/auto-instrumentations-node` | `^0.50.0` | OTel auto-instrumentation |
| `typescript` | `^5.6.0` | Type checking |

> **Note:** Teams bot uses legacy Bot Framework SDK + Teams AI Library v1.5 path, not the new `@microsoft/teams.js` SDK listed in CLAUDE.md. Migration to new SDK is a pending improvement.

### E2E Tests (`e2e/`)

| Package | Version | Purpose |
|---|---|---|
| `@playwright/test` | `^1.58.2` | E2E browser automation (Chromium) |
| `typescript` | `^6.0.2` | Type checking |
| `@azure/cosmos` | `^4.9.2` | Test fixtures — direct Cosmos writes |
| `@azure/identity` | `^4.13.1` | Auth for test fixture setup |
| `@azure/msal-node` | `^5.1.1` | Service principal auth in E2E global setup |

---

## Build Tools & Package Managers

### Python

| Tool | Purpose |
|---|---|
| `pip` | Package installation (per-service `requirements.txt`) |
| `pytest` | Test runner (`pyproject.toml` root config) |
| `pytest-cov` | Coverage reporting (80% minimum enforced in CI) |
| `pytest-asyncio` | Async test support |
| `bandit` | Static security analysis (CI: high/medium issues fail build) |

### TypeScript / Node.js

| Tool | Purpose |
|---|---|
| `npm` | Package manager (`npm ci` in all CI steps) |
| `tsc` | TypeScript compiler (teams-bot build target) |
| `next build` | Next.js production build (web-ui) |
| `jest` + `ts-jest` + `jest-environment-jsdom` | Unit tests for web-ui |
| `vitest` + `@vitest/coverage-v8` | Unit tests for teams-bot |
| `eslint` + `@typescript-eslint/*` | Linting (teams-bot) |
| `@testing-library/react` + `@testing-library/jest-dom` | React component testing |

---

## Container / Docker

### Base Images

| Image | Used By |
|---|---|
| `python:3.12-slim` | Agent base image (`agents/Dockerfile.base`), API gateway |
| `python:3.11-slim` | Arc MCP server (standalone, does not extend base) |
| `node:20-slim` | Web UI (multi-stage: builder + runner) |
| `node:20` | Azure MCP server sidecar container |
| `node:20-alpine` | Teams bot (multi-stage: build + runtime) |

### Agent Container Pattern

- **Layered build**: `agents/Dockerfile.base` installs all shared deps; per-agent Dockerfiles `FROM` the base and add only agent-specific code
- **Non-root users**: All containers run as non-root (`agentuser`, `gatewayuser`, `nextjs`, `mcp`, `botuser`, `appuser`)
- **Port convention**: agents on `8088` (Foundry adapter), API gateway `8000`, web-ui `3000`, teams-bot `3978`, Arc MCP `8080`, Azure MCP sidecar `5000`
- **Azure MCP version**: `@azure/mcp@2.0.0-beta.34` pinned in both API gateway Dockerfile (stdio subprocess) and Azure MCP server sidecar

### Azure MCP Server Sidecar

The API gateway embeds `@azure/mcp@2.0.0-beta.34` as a Node.js subprocess (stdio transport) to work around a protocol incompatibility between the Foundry HTTP MCP client and `@azure/mcp`'s streamable-HTTP transport. A separate sidecar container (`services/azure-mcp-server/`) exists for direct HTTP transport usage.

---

## Infrastructure Tooling

### Terraform

| Provider | Version | Purpose |
|---|---|---|
| `hashicorp/azurerm` | `~> 4.65.0` | Standard Azure resources (Container Apps, Cosmos, PostgreSQL, VNet, Event Hubs, ACR, Key Vault, App Insights, Log Analytics, Foundry account/project/model) |
| `azure/azapi` | `~> 2.9.0` | Preview/Fabric resources (Foundry capability hosts, Fabric Workspace/Eventhouse/KQL DB/Activator/Lakehouse, Entra Agent ID) |
| `hashicorp/azuread` | `~> 3.0` | Entra ID service principals, app registrations |
| `hashicorp/random` | `~> 3.6` | Random resource name suffixes |

**Terraform version**: `>= 1.9.0` (CI uses `1.9.8`)

**State backend**: Azure Blob Storage (`rg-aap-tfstate-prod` / `staaptfstateprod`), Entra auth only (no shared access keys), separate state files per env (`dev.tfstate`, `staging.tfstate`, `prod.tfstate`).

### Module Structure

```
terraform/
├── envs/           dev | staging | prod (each has providers.tf + backend.tf)
└── modules/
    ├── agent-apps        Container Apps for all agents + services
    ├── activity-log      Azure Monitor activity log routing
    ├── compute-env       Container Apps Environment
    ├── databases         Cosmos DB + PostgreSQL Flexible Server
    ├── entra-apps        App registrations, service principals
    ├── eventhub          Event Hub namespace + hub + consumer groups + Action Group
    ├── fabric            Fabric capacity, workspace, Eventhouse, KQL DB, Activator, Lakehouse (all azapi)
    ├── foundry           AI Services account, project, model deployment, diagnostic settings
    ├── keyvault          Key Vault (RBAC-mode, private, purge-protected)
    ├── monitoring        Log Analytics workspace + Application Insights
    ├── networking        VNet, subnets, private DNS zones
    └── rbac              Role assignments
```

### Key Infrastructure Resources

| Resource | Terraform Config |
|---|---|
| Azure Container Apps Environment | `modules/compute-env` — hosts all agent/service containers |
| Container Apps (9 agent + 3 service) | `modules/agent-apps` — orchestrator, compute, network, storage, security, sre, arc, api-gateway, web-ui, teams-bot |
| Azure Container Registry (ACR) | Managed identity image pull (no admin credentials) |
| Foundry AI Services account | `azurerm_cognitive_account` (kind=`AIServices`, SKU=S0) |
| Foundry Project | `azurerm_cognitive_account_project` |
| GPT-4o model deployment | `azurerm_cognitive_deployment` |
| Cosmos DB | GlobalDocumentDB, serverless-capable, private endpoint, Entra-only auth |
| PostgreSQL Flexible Server | v16, VNet-injected, private, pgvector extension (`VECTOR`) |
| Event Hub Namespace | Standard SKU, VNet-locked, private endpoint |
| Fabric Capacity/Workspace/Eventhouse/Activator | All via `azapi_resource` |
| Key Vault | Standard SKU, RBAC-mode, private, 90-day soft-delete, purge protection |
| Log Analytics Workspace + App Insights | `modules/monitoring` |

---

## Dev Tooling

### CI/CD (GitHub Actions)

| Workflow | Trigger | Purpose |
|---|---|---|
| `api-gateway-web-ui-ci.yml` | PR / push to main | Python unit tests (80% coverage), Playwright E2E |
| `agent-images.yml` | Push to main (agent paths) | Detect changed agents, build + push to ACR, deploy to Container Apps |
| `base-image.yml` | Push to main (base paths) | Build + push `agents/base` image |
| `arc-mcp-server-build.yml` | Push to main | Build + push Arc MCP server |
| `azure-mcp-server-build.yml` | Push to main | Build + push Azure MCP sidecar |
| `teams-bot-build.yml` | Push to main | Build + push teams-bot |
| `web-ui-build.yml` | Push to main | Build + push web-ui |
| `api-gateway-build.yml` | Push to main | Build + push api-gateway |
| `terraform-plan.yml` | PR (terraform paths) | `terraform plan` for dev/staging/prod; tag lint check; post plan as PR comment |
| `terraform-apply.yml` | Merge to main | `terraform apply -auto-approve` (gated by reviewers) |
| `security-review.yml` | PR / push to main | bandit (Python), npm audit (TS), secrets scan |
| `staging-e2e-simulation.yml` | Scheduled / manual | E2E against staging environment |
| `detection-plane-ci.yml` | Detection plane paths | Detection plane unit tests |

**Authentication pattern**: OIDC (`azure/login@v2`) for Terraform workflows; supports both OIDC and client-secret fallback for image build workflows (auto-detected from `AZURE_CLIENT_SECRET` presence).

### Testing Frameworks Summary

| Layer | Framework | Coverage Target |
|---|---|---|
| Python unit/integration | `pytest` + `pytest-asyncio` | 80% (enforced in CI) |
| Python security | `bandit` | No HIGH/MEDIUM findings |
| TypeScript unit (web-ui) | `jest` + `@testing-library/react` | — |
| TypeScript unit (teams-bot) | `vitest` + coverage-v8 | — |
| E2E browser | `@playwright/test` 1.58.2 (Chromium) | Critical flows (7 spec files) |
| TypeScript security | `npm audit` | No HIGH findings |

### Test Markers (Python)

```
unit          — Fast, no external dependencies
integration   — Require external services
slow          — >10 seconds
e2e           — Playwright tests
sc1–sc6       — Success Criteria tests (FMP latency, SSE reconnect, runbook RAG, HITL gate, resource identity, GitOps path)
```
