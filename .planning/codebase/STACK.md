# Technology Stack — Azure Agentic Platform

> Generated: 2026-04-01. Source: requirements*.txt, package.json, Dockerfile*, terraform providers, CI workflows.

---

## Languages

| Language | Version | Where Used |
|---|---|---|
| **Python** | `>=3.10` (project minimum); `3.12` (agents, API gateway); `3.11` (Arc MCP server) | All backend services and agent containers |
| **TypeScript** | `^5.6` (teams-bot); `^5.0` (web-ui); `^6.0` (e2e) | Frontend, Teams bot, E2E tests |
| **JavaScript (Node.js)** | Node 20 | Azure MCP Server sidecar proxy (`proxy.js`) |
| **HCL (Terraform)** | `>= 1.9.0` | All infrastructure-as-code |
| **KQL** | n/a | Fabric Eventhouse queries, audit log queries via Log Analytics |
| **SQL** | n/a | PostgreSQL migrations (`services/api-gateway/migrations/*.sql`) |

---

## Python Backend Stack

### Core Agent Framework (`agents/requirements-base.txt`)

| Package | Version | Purpose |
|---|---|---|
| `agent-framework` | `==1.0.0b260107` | Microsoft Agent Framework — `ChatAgent`, `@ai_function` decorator. **Pinned**: rc5 API is incompatible with `agentserver b15` |
| `azure-ai-agentserver-core` | `==1.0.0b15` | Foundry Hosted Agent protocol adapter |
| `azure-ai-agentserver-agentframework` | `==1.0.0b15` | Agent Framework → Foundry adapter |
| `azure-ai-projects` | `==2.0.0b3` | Foundry SDK — `MCPTool`, `PromptAgentDefinitionText` |
| `azure-ai-agents` | `==1.2.0b5` | Foundry `AgentsClient` (threads, runs, messages); `SubmitToolApprovalAction` |
| `mcp[cli]` | `==1.26.0` (Arc MCP server); `>=1.26.0` (base) | FastMCP server framework (`mcp.server.fastmcp`) |

> **Version pin rationale**: `agentserver b16+` requires `agent-framework >= rc2` (rc5 API). `b15` is the last version compatible with the `b260107` beta API and uses starlette `lifespan` (not deprecated `on_event`). Do not upgrade these without a coordinated bump.

---

### API Gateway (`services/api-gateway/requirements.txt`)

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | `>=0.115.0` | ASGI web framework |
| `uvicorn[standard]` | `>=0.30.0` | ASGI server |
| `pydantic` | `>=2.8.0` | Request/response validation, typed models |
| `azure-identity` | `>=1.17.0` | `DefaultAzureCredential` |
| `fastapi-azure-auth` | `>=5.0.0` | Entra ID Bearer token validation (`SingleTenantAzureAuthorizationCodeBearer`) |
| `azure-ai-agents` | `==1.2.0b5` | Foundry `AgentsClient` — thread/run/message operations |
| `mcp[cli]` | `>=1.26.0` | MCP stdio client for `@azure/mcp` subprocess |
| `azure-cosmos` | `>=4.0.0` | Cosmos DB — incidents, approvals, sessions |
| `azure-monitor-opentelemetry` | `>=1.0.0` | OTel → Application Insights |
| `azure-storage-file-datalake` | `>=12.0.0` | OneLake / ADLS Gen2 — audit export |
| `openai` | `>=1.0.0` | Azure OpenAI embeddings (`text-embedding-3-small`) |
| `asyncpg` | `>=0.29.0` | Async PostgreSQL driver |
| `pgvector` | `>=0.3.0` | pgvector Python adapter |
| `azure-mgmt-resourcegraph` | `>=8.0.0` | Azure Resource Graph (patch endpoints, Phase 13) |

---

### Agent-Specific Additions

| Agent | Extra Packages | Version |
|---|---|---|
| **arc** | `azure-mgmt-hybridcompute` | `==9.0.0` |
| | `azure-mgmt-hybridkubernetes` (**NOT** `azure-mgmt-connectedk8s`) | `==1.1.0` |
| | `azure-mgmt-azurearcdata` (**NOT** `azure-mgmt-arcdata`) | `==1.0.0` |
| | `azure-mgmt-kubernetesconfiguration` | `==3.1.0` |
| | `httpx` | `>=0.27.0` |
| **network** | `azure-mgmt-network` | `>=27.0.0` |
| **patch** | `azure-mgmt-resourcegraph` | `>=8.0.1` |
| **eol** | `azure-mgmt-resourcegraph` | `>=8.0.1` |
| | `httpx` | `>=0.27.0` |

---

### Arc MCP Server (`services/arc-mcp-server/requirements.txt`)

| Package | Version | Purpose |
|---|---|---|
| `mcp[cli]` | `==1.26.0` | FastMCP server (`mcp.server.fastmcp`) |
| `azure-identity` | `>=1.17.0` | Managed identity auth |
| `azure-mgmt-hybridcompute` | `==9.0.0` | Arc-enabled servers |
| `azure-mgmt-hybridkubernetes` | `==1.1.0` | Arc-enabled Kubernetes |
| `azure-mgmt-azurearcdata` | `==1.0.0` | Arc data services |
| `azure-mgmt-kubernetesconfiguration` | `==3.1.0` | Arc extensions, GitOps/Flux |
| `azure-monitor-opentelemetry` | `>=1.6.0` | Observability |
| `opentelemetry-sdk` | `>=1.25.0` | OTel SDK |
| `pydantic` | `>=2.8.0` | Schema validation |

---

### Detection Plane (`services/detection-plane/pyproject.toml`)

| Package | Version | Purpose |
|---|---|---|
| `azure-cosmos` | `>=4.7.0` | Alert state management |
| `azure-identity` | `>=1.17.0` | Auth |
| `azure-mgmt-alertsmanagement` | `>=0.2.0` | Azure Monitor alert management |
| `pydantic` | `>=2.0.0` | Data models |

---

### Fabric User Data Function (`fabric/user-data-function/requirements.txt`)

| Package | Version | Purpose |
|---|---|---|
| `msal` | `>=1.28.0` | Client credentials token acquisition (SP auth to API gateway) |
| `requests` | `>=2.31.0` | HTTP POST to API Gateway |

---

### Shared Observability (agent base)

| Package | Version | Purpose |
|---|---|---|
| `azure-monitor-opentelemetry` | `>=1.6.0` | `configure_azure_monitor()` — OTel → App Insights |
| `opentelemetry-sdk` | `>=1.25.0` | Custom spans (`aiops.*` attributes) |
| `opentelemetry-exporter-otlp` | `>=1.25.0` | OTLP export |

---

## TypeScript / Node.js Stack

### Web UI (`services/web-ui/package.json`)

| Package | Version | Purpose |
|---|---|---|
| `next` | `^15.0.0` | Next.js App Router — SSR, Route Handlers, SSE streaming |
| `react` / `react-dom` | `^19.0.0` | React runtime |
| `typescript` | `^5.0.0` | Type checking |
| `tailwindcss` | `^4.0.0` | Utility-first CSS |
| `@tailwindcss/typography` | `^0.5.0` | Markdown prose styling |
| `@tailwindcss/postcss` | `^4.2.2` | Tailwind v4 PostCSS integration |
| `tailwindcss-animate` | `^1.0.0` | CSS animations |
| `postcss` | `^8.0.0` | CSS processing |
| **Radix UI** (11 packages) | `^1.x` – `^2.x` | Headless UI primitives: checkbox, collapsible, dialog, dropdown-menu, icons, label, popover, scroll-area, select, separator, slot, tabs, tooltip |
| `lucide-react` | `^0.400.0` | Icon library |
| `class-variance-authority` | `^0.7.0` | Component variant management |
| `clsx` | `^2.1.0` | Conditional class merging |
| `tailwind-merge` | `^2.0.0` | Tailwind class deduplication |
| `cmdk` | `^1.1.1` | Command palette |
| `react-markdown` | `^9.0.0` | Markdown rendering in chat |
| `remark-gfm` | `^4.0.1` | GitHub Flavored Markdown |
| `react-resizable-panels` | `^2.0.0` | Resizable split-panel layouts |
| `@azure/cosmos` | `^4.0.0` | Cosmos DB SDK (Observability tab server-side queries) |
| `@azure/identity` | `^4.0.0` | `DefaultAzureCredential` (server-side Next.js routes) |
| `@azure/monitor-query` | `^1.3.0` | Log Analytics KQL queries (Observability tab) |
| `@azure/msal-browser` | `^3.0.0` | MSAL — browser SPA auth code flow |
| `@azure/msal-react` | `^2.0.0` | MSAL React hooks/context |

> **Note:** CLAUDE.md spec lists Fluent UI 2 (`@fluentui/react-components`) as the UI library target, but the actual codebase uses Radix UI + Tailwind CSS (shadcn/ui component pattern). `components.json` confirms the shadcn/ui setup.

**Web UI dev dependencies:**

| Package | Version | Purpose |
|---|---|---|
| `jest` + `jest-environment-jsdom` | `^29.0.0` | Unit test runner |
| `ts-jest` | `^29.0.0` | TypeScript Jest transformer |
| `@testing-library/react` | `^16.0.0` | React component testing |
| `@testing-library/jest-dom` | `^6.0.0` | DOM matchers |
| `@testing-library/user-event` | `^14.6.1` | User interaction simulation |
| `@testing-library/dom` | `^10.4.1` | DOM utilities |
| `@playwright/test` | `^1.58.2` | E2E tests |

---

### Teams Bot (`services/teams-bot/package.json`)

| Package | Version | Purpose |
|---|---|---|
| `express` | `^4.21.0` | HTTP server (port 3978) |
| `botbuilder` | `^4.23.0` | Bot Framework SDK — Teams channel protocol |
| `@microsoft/teams-ai` | `^1.5.0` | Teams AI Library (built on Bot Framework) |
| `adaptivecards` | `^2.11.1` | Adaptive Card rendering (HITL approval cards) |
| `@azure/identity` | `^4.5.0` | Managed identity auth |
| `@azure/monitor-opentelemetry` | `^1.0.0` | Azure Monitor OTel integration |
| `@opentelemetry/auto-instrumentations-node` | `^0.50.0` | OTel auto-instrumentation |
| `typescript` | `^5.6.0` | Type checking |
| `vitest` | `^4.1.2` | Unit test runner |
| `@vitest/coverage-v8` | `^4.1.2` | Coverage reporting |
| `eslint` + `@typescript-eslint/*` | `^9.x` / `^8.x` | Linting |

> **Note:** Uses the legacy Bot Framework SDK + Teams AI Library v1.5 path. CLAUDE.md recommends migrating to the new `@microsoft/teams.js` SDK, but this has not been done yet.

---

### E2E Tests (`e2e/package.json`)

| Package | Version | Purpose |
|---|---|---|
| `@playwright/test` | `^1.58.2` | E2E browser automation |
| `typescript` | `^6.0.2` | Type checking |
| `@azure/cosmos` | `^4.9.2` | Test fixture setup/teardown |
| `@azure/identity` | `^4.13.1` | Auth for test fixture setup |
| `@azure/msal-node` | `^5.1.1` | Service principal auth in `global-setup.ts` |

---

## Build Tools & Package Managers

### Python

| Tool | Purpose |
|---|---|
| `pip` | Package installation (per-service `requirements.txt`) |
| `pytest` | Test runner (`pyproject.toml` root config); markers: `unit`, `integration`, `slow`, `e2e`, `sc1`–`sc6` |
| `pytest-asyncio` | Async test support |
| `bandit` | Static security analysis (CI: HIGH/MEDIUM findings fail build) |

### TypeScript / Node.js

| Tool | Purpose |
|---|---|
| `npm` (`npm ci`) | Package manager |
| `tsc` | TypeScript compiler (teams-bot build target) |
| `next build` | Next.js production build (web-ui) |
| `jest` + `ts-jest` + `jest-environment-jsdom` | Unit tests for web-ui |
| `vitest` + `@vitest/coverage-v8` | Unit tests for teams-bot |
| `eslint` + `@typescript-eslint/*` | Linting (teams-bot) |

---

## Container / Docker

### Base Images

| Image | Used By |
|---|---|
| `python:3.12-slim` | Agent base image (`agents/Dockerfile.base`), API gateway |
| `python:3.11-slim` | Arc MCP server (standalone — does NOT extend `agents/Dockerfile.base`) |
| `node:20-slim` | Web UI (multi-stage: builder + runner) |
| `node:20` | Azure MCP server sidecar |
| `node:20-alpine` | Teams bot (multi-stage: build + runtime) |

### Agent Container Pattern

- **Layered build**: `agents/Dockerfile.base` installs all shared deps; per-agent Dockerfiles `FROM` base and add only agent-specific code
- **Non-root users**: `agentuser` (agents), `gatewayuser` (API gateway), `nextjs` (web-ui), `mcp` (Arc MCP), `botuser` (teams-bot)
- **Port convention**: agents `8088` (Foundry adapter), API gateway `8000`, web-ui `3000`, teams-bot `3978`, Arc MCP `8080`, Azure MCP sidecar `5000`
- **`@azure/mcp` version**: `2.0.0-beta.34` pinned in API gateway Dockerfile (stdio subprocess) and Azure MCP sidecar

---

## Infrastructure Tooling

### Terraform

| Provider | Version | Purpose |
|---|---|---|
| `hashicorp/azurerm` | `~> 4.65.0` | Standard Azure resources (Container Apps, Cosmos, PostgreSQL, VNet, Event Hubs, ACR, Key Vault, App Insights, Log Analytics, Foundry account/project/model) |
| `azure/azapi` | `~> 2.9.0` | Preview/Fabric resources (Foundry capability hosts, Fabric Workspace/Eventhouse/KQL DB/Activator/Lakehouse, Entra Agent ID) |
| `hashicorp/azuread` | `~> 3.0` | Entra ID service principals, app registrations |
| `hashicorp/random` | `~> 3.6` | Random resource name suffixes |

**Terraform version**: `>= 1.9.0`

**State backend**: Azure Blob Storage — Entra auth only (no shared access keys), separate state files per env (`dev.tfstate`, `staging.tfstate`, `prod.tfstate`).

### Terraform Module Structure

```
terraform/
├── envs/           dev | staging | prod (each has providers.tf + backend.tf)
└── modules/
    ├── activity-log      Azure Monitor activity log export to Log Analytics
    ├── agent-apps        Container Apps for all agents + services
    ├── arc-mcp-server    Arc MCP Server Container App
    ├── compute-env       Container Apps Environment + ACR
    ├── databases         Cosmos DB + PostgreSQL Flexible Server
    ├── entra-apps        App registrations, Fabric service principal
    ├── eventhub          Event Hub namespace, hub, consumer groups, Monitor Action Group
    ├── fabric            Fabric capacity, workspace, Eventhouse, KQL DB, Activator, Lakehouse (all azapi)
    ├── foundry           AI Services account, project, GPT-4o model deployment, diagnostic settings
    ├── keyvault          Key Vault (RBAC-mode, private, purge-protected)
    ├── monitoring        Log Analytics workspace + Application Insights
    ├── networking        VNet, subnets, private DNS zones
    ├── private-endpoints Centralized PE management (Cosmos, ACR, Key Vault, Foundry, Event Hub)
    ├── rbac              Role assignments (per-domain subscription scope)
    └── teams-bot         Azure Bot resource + bot app registration
```

### Key Infrastructure Resources

| Resource | Terraform Config |
|---|---|
| Azure Container Apps Environment | `modules/compute-env` — VNet-injected, hosts all containers |
| Container Apps (10 total) | `modules/agent-apps` — orchestrator, compute, network, storage, security, sre, arc, patch, eol, api-gateway, web-ui, teams-bot |
| Azure Container Registry (ACR) | Managed identity image pull (no admin credentials) |
| Foundry AI Services account | `azurerm_cognitive_account` (kind=`AIServices`, SKU=S0, `local_auth_enabled=false`) |
| Foundry Project | `azurerm_cognitive_account_project` |
| GPT-4o model deployment | `azurerm_cognitive_deployment` (model: `gpt-4o`, version: `2024-11-20`) |
| Cosmos DB | `GlobalDocumentDB`, private endpoint, `local_authentication_disabled=true`, autoscale in prod |
| PostgreSQL Flexible Server | v16, VNet-injected, private, pgvector extension (`VECTOR`) |
| Event Hub Namespace | Standard SKU, private endpoint |
| Fabric Capacity/Workspace/Eventhouse/Activator | All via `azapi_resource` |
| Key Vault | Standard SKU, RBAC-mode, private, 90-day soft-delete, purge protection |
| Log Analytics Workspace + App Insights | `modules/monitoring` |

---

## CI/CD (GitHub Actions)

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
| `terraform-plan.yml` | PR (terraform paths) | `terraform plan` for dev/staging/prod; posts plan as PR comment |
| `terraform-apply.yml` | Merge to main | `terraform apply -auto-approve` (gated by required reviewers) |
| `security-review.yml` | PR / push to main | bandit (Python), npm audit (TS), secrets scan |
| `detection-plane-ci.yml` | Detection plane paths | Detection plane unit tests |

**Auth pattern**: OIDC (`azure/login@v2`, `id-token: write`) for Terraform; client-secret fallback for image build workflows (auto-detected from `AZURE_CLIENT_SECRET` presence).

---

## Testing Summary

| Layer | Framework | Coverage Target |
|---|---|---|
| Python unit/integration | `pytest` + `pytest-asyncio` | 80% (enforced in CI) |
| Python security | `bandit` | No HIGH/MEDIUM findings |
| TypeScript unit (web-ui) | `jest` + `@testing-library/react` | — |
| TypeScript unit (teams-bot) | `vitest` + coverage-v8 | — |
| E2E browser | `@playwright/test` 1.58.2 (Chromium) | Critical flows (7 spec files + sc1–sc6) |
| TypeScript security | `npm audit` | No HIGH findings |

### Pytest Markers

```
unit          — Fast, no external dependencies
integration   — Require external services
slow          — >10 seconds
e2e           — Playwright tests
sc1           — FMP and first token latency
sc2           — SSE reconnect continuity
sc3           — Runbook RAG similarity and latency
sc4           — HITL gate lifecycle
sc5           — Resource Identity Certainty
sc6           — GitOps vs direct-apply path
```
