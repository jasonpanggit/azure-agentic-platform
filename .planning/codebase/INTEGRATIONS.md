# External Integrations & APIs — Azure Agentic Platform

> Generated: 2026-03-30. Source: requirements*.txt, auth.py, foundry.py, Terraform modules, Dockerfiles, GitHub Actions workflows.

---

## Azure AI / Foundry

### Azure AI Foundry (Agent Service)

| Attribute | Detail |
|---|---|
| **SDK** | `azure-ai-agents` `>=1.0.0` (threads/runs/messages); `azure-ai-projects` `>=2.0.1` (project-level) |
| **Client class** | `AgentsClient(endpoint=AZURE_PROJECT_ENDPOINT, credential=DefaultAzureCredential())` |
| **Auth** | `DefaultAzureCredential` → system-assigned managed identity (Container Apps) or Azure CLI/env (local) |
| **Env vars** | `AZURE_PROJECT_ENDPOINT` (primary); `FOUNDRY_ACCOUNT_ENDPOINT` (fallback) |
| **Operations** | `client.threads.create()`, `client.messages.create()`, `client.runs.create(agent_id=ORCHESTRATOR_AGENT_ID)`, `client.runs.get()` |
| **Model** | GPT-4o (`azurerm_cognitive_deployment`), standard deployment, capacity configured per env |
| **Terraform** | `azurerm_cognitive_account` (kind=`AIServices`), `azurerm_cognitive_account_project`, `azurerm_cognitive_deployment` |
| **Capability host** | `azapi_resource` (`Microsoft.CognitiveServices/accounts/capabilityHosts`) |

**Usage pattern (API gateway → Foundry):**
1. `client.threads.create()` — new conversation thread per incident or chat session
2. `client.messages.create(thread_id, role="user", content=json_envelope)` — post typed envelope
3. `client.runs.create(thread_id, agent_id=orchestrator_id)` — dispatch to Orchestrator agent
4. `client.runs.get(thread_id, run_id)` / poll — check completion, retrieve assistant reply

---

### Azure OpenAI (Embeddings)

| Attribute | Detail |
|---|---|
| **Client** | `openai.AzureOpenAI` (`openai>=1.0.0`) |
| **Model** | `text-embedding-3-small` (1536-dimensional vectors) |
| **Env vars** | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` (optional; falls back to `DefaultAzureCredential` if absent or set to `DISABLED_LOCAL_AUTH_USE_MI`) |
| **Auth fallback** | `get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")` |
| **Purpose** | Runbook RAG — generating query embeddings for pgvector cosine similarity search |
| **Deployment name** | `EMBEDDING_DEPLOYMENT_NAME` env var (default: `text-embedding-3-small`) |
| **API version** | `2024-06-01` |

---

## Azure MCP Server (`@azure/mcp`)

### Azure MCP Server (Sidecar HTTP Transport)

| Attribute | Detail |
|---|---|
| **Package** | `@azure/mcp@2.0.0-beta.34` (npm, pinned) |
| **Transport** | HTTP on port 5000 (`azmcp server start --transport http`) |
| **Auth** | `DefaultAzureCredential` from `@azure/identity` (managed identity in Container Apps) |
| **Container** | `services/azure-mcp-server/Dockerfile` — `FROM node:20` |
| **Purpose** | Provides ARM/Monitor/Storage/Networking tool surfaces to Foundry agents via MCP |

### Azure MCP Server (stdio Subprocess — API Gateway)

| Attribute | Detail |
|---|---|
| **Package** | `@azure/mcp@2.0.0-beta.34` installed globally in API gateway container |
| **Transport** | stdio (launched as subprocess by `services/api-gateway/azure_tools.py`) |
| **Endpoint** | `POST /api/v1/azure-tools` — proxies tool calls as regular OpenAI function calls |
| **Reason** | Works around a protocol incompatibility between Foundry's HTTP MCP client and `@azure/mcp` streamable-HTTP |

---

## Custom Arc MCP Server

| Attribute | Detail |
|---|---|
| **Framework** | `mcp[cli]==1.26.0` (FastMCP — `mcp.server.fastmcp`) |
| **Transport** | Streamable HTTP on port 8080 |
| **Auth** | `DefaultAzureCredential` → managed identity |
| **Container** | `services/arc-mcp-server/Dockerfile` — `FROM python:3.11-slim` |
| **Azure SDKs** | `azure-mgmt-hybridcompute==9.0.0`, `azure-mgmt-hybridkubernetes==1.1.0`, `azure-mgmt-azurearcdata==1.0.0`, `azure-mgmt-kubernetesconfiguration==3.1.0` |
| **Tools exposed** | HybridCompute/machines, ConnectedK8s clusters, Arc-enabled data services, GitOps/extension config |
| **Env var** | `ARC_MCP_SERVER_URL` (injected into Arc agent container by Terraform) |
| **Health check** | `GET /mcp` or `POST /mcp` |

---

## Authentication

### Backend Services (Python)

| Mechanism | Where Used | Details |
|---|---|---|
| `DefaultAzureCredential` | All agent containers, API gateway, Arc MCP server | Resolves system-assigned managed identity (IMDS) in Container Apps; falls back to Azure CLI / VS Code / env vars locally |
| Entra ID Bearer token validation | API gateway (`/api/v1/*` endpoints) | `fastapi-azure-auth` `SingleTenantAzureAuthorizationCodeBearer`; reads `AZURE_CLIENT_ID` + `AZURE_TENANT_ID`; scope: `api://<client_id>/incidents.write` |
| Local bypass | API gateway only | `API_GATEWAY_AUTH_MODE=disabled` env var; fail-closed by default |

**Agent identity**: Each Container App has a system-assigned managed identity. `AGENT_ENTRA_ID` env var (the identity's `principal_id`) is used for AUDIT-005 attribution in OTel spans.

### Frontend (TypeScript)

| Mechanism | Where Used | Details |
|---|---|---|
| MSAL Browser | Web UI | `@azure/msal-browser ^3.0.0` + `@azure/msal-react ^2.0.0`; SPA auth code flow |
| Env vars | Web UI build-time | `NEXT_PUBLIC_AZURE_CLIENT_ID`, `NEXT_PUBLIC_TENANT_ID`, `NEXT_PUBLIC_REDIRECT_URI` (baked into Next.js at build time via Docker `ARG`) |
| MSAL Node | E2E tests | `@azure/msal-node ^5.1.1` — service principal auth in `global-setup.ts`; bearer token injected as `E2E_BEARER_TOKEN` |

### Infrastructure (Terraform / CI)

| Mechanism | Where Used | Details |
|---|---|---|
| OIDC federated identity | Terraform workflows | `azure/login@v2` + `ARM_USE_OIDC: true`; `id-token: write` permission |
| Client secret fallback | Agent image build workflows | Auto-detected: if `AZURE_CLIENT_SECRET` is set, uses service principal login; otherwise falls back to OIDC |
| Env vars in workflows | All | `ARM_CLIENT_ID`, `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID` from GitHub secrets |
| ACR image pull | Container Apps | System-assigned managed identity (`identity = "system"` in registry block); no admin credentials |

---

## Cosmos DB

| Attribute | Detail |
|---|---|
| **SDK** | `azure-cosmos ^4.0.0` (Python), `@azure/cosmos ^4.0.0` (TypeScript) |
| **Auth** | `local_authentication_disabled = true` — Entra-only (no keys); `DefaultAzureCredential` in Python; `@azure/identity` in TS |
| **Endpoint env var** | `COSMOS_ENDPOINT` |
| **Database** | `aap` (`COSMOS_DATABASE_NAME`) |
| **Containers** | `incidents` (partition: `/resource_id`), `approvals` (partition: `/thread_id`), `sessions` (partition: `/incident_id`) |
| **Consistency** | Session |
| **Mode** | Serverless (dev/staging) or provisioned with autoscale (prod) |
| **Networking** | Private endpoint, `public_network_access_enabled = false` |

---

## PostgreSQL + pgvector

| Attribute | Detail |
|---|---|
| **Server** | Azure PostgreSQL Flexible Server v16, VNet-injected, private (no public access) |
| **Auth** | Both Entra (`active_directory_auth_enabled = true`) and password auth; production uses Entra |
| **Database** | `aap` |
| **Extension** | `pgvector` (`VECTOR`) — allowlisted via `azure.extensions` config |
| **Python driver** | `asyncpg>=0.29.0` (async API); `psycopg[binary]>=3.1.0` (seed scripts) |
| **pgvector adapter** | `pgvector>=0.3.0` (`register_vector` for asyncpg) |
| **Connection env vars** | `PGVECTOR_CONNECTION_STRING` (primary), `POSTGRES_DSN` (fallback), or `POSTGRES_HOST/PORT/DB/USER/PASSWORD` |
| **Schema** | `runbooks` table — `id UUID`, `title`, `domain`, `content`, `embedding vector(1536)`, `version`, timestamps |
| **Index** | `ivfflat` cosine ops with `lists = 100` |
| **Purpose** | Runbook RAG — semantic similarity search at query time |

---

## Azure Event Hubs

| Attribute | Detail |
|---|---|
| **Terraform** | `azurerm_eventhub_namespace` (Standard SKU), `azurerm_eventhub` (`raw-alerts`), consumer group, auth rules |
| **Purpose** | Ingest point for Azure Monitor alerts → Fabric detection plane |
| **Auth rules** | `action-group-send` (Monitor Action Group → EH, Send-only); `eventhouse-listen` (Fabric Eventstreams → EH, Listen-only) |
| **Networking** | VNet rule on Container Apps subnet; private endpoint provisioned separately |
| **Consumer group** | `eventhouse-consumer` — used by Fabric Eventstreams |
| **Monitor integration** | `azurerm_monitor_action_group` — forwards Azure Monitor alerts to `raw-alerts` hub using `use_common_alert_schema = true` |

---

## Microsoft Fabric

| Component | Status | Details |
|---|---|---|
| **Fabric Capacity** | GA | `Microsoft.Fabric/capacities@2023-11-01` via `azapi_resource`; SKU configurable |
| **Fabric Workspace** | GA | `Microsoft.Fabric/workspaces@2023-11-01`; linked to capacity |
| **Eventhouse** | GA | `Microsoft.Fabric/workspaces/eventhouses@2023-11-01`; KQL-native time-series store |
| **KQL Database** | GA | `Microsoft.Fabric/workspaces/eventhouses/databases@2023-11-01`; holds `DetectionResults` table |
| **Activator** | GA | `Microsoft.Fabric/workspaces/reflex@2023-11-01`; fires webhook triggers on detection rule matches |
| **OneLake Lakehouse** | GA | `Microsoft.Fabric/workspaces/lakehouses@2023-11-01`; audit logs, alert history snapshots |

**Data flow**: Azure Monitor → Event Hub (`raw-alerts`) → Fabric Eventstreams → Eventhouse KQL DB → Activator → webhook → API gateway `/api/v1/incidents`

**Manual steps required post-deploy**:
- Activator trigger configuration (Fabric portal — trigger condition on `DetectionResults` table)
- Activity Log OneLake mirror setup (≥2-year retention for AUDIT-003 compliance)

---

## Azure Key Vault

| Attribute | Detail |
|---|---|
| **Terraform** | `azurerm_key_vault` — standard SKU, RBAC-mode (`rbac_authorization_enabled = true`) |
| **Networking** | Private endpoint only (`public_network_access_enabled = false`) |
| **Settings** | 90-day soft-delete retention, purge protection enabled |
| **Usage** | Stores `APPLICATIONINSIGHTS_CONNECTION_STRING` as a Container App secret; Teams bot password |
| **Auth** | RBAC (Key Vault Secrets User/Officer roles via `azurerm_role_assignment`) |

---

## Azure Monitor / Application Insights

| Attribute | Detail |
|---|---|
| **Log Analytics** | `azurerm_log_analytics_workspace` — configurable SKU and retention |
| **Application Insights** | `azurerm_application_insights` (type=`other`), workspace-based, linked to Log Analytics |
| **Connection string env var** | `APPLICATIONINSIGHTS_CONNECTION_STRING` (injected as Container App secret) |
| **Python instrumentation** | `azure-monitor-opentelemetry` — `configure_azure_monitor(connection_string=...)` at startup |
| **Node.js instrumentation** | `@azure/monitor-opentelemetry ^1.0.0` + `@opentelemetry/auto-instrumentations-node ^0.50.0` |
| **Custom spans** | `aiops.*` attributes on all tool call spans: `agent_id`, `agent_name`, `tool_name`, `tool_parameters`, `outcome`, `duration_ms`, `correlation_id`, `thread_id` |
| **Audit log query** | `services/api-gateway/audit.py` — queries App Insights via Log Analytics REST API |
| **Web UI** | `@azure/monitor-query ^1.3.0` — direct Log Analytics queries from Observability tab (`LOG_ANALYTICS_WORKSPACE_ID` env var) |

---

## Microsoft Teams

| Attribute | Detail |
|---|---|
| **SDK** | `botbuilder ^4.23.0` + `@microsoft/teams-ai ^1.5.0` (legacy Bot Framework path) |
| **Server** | Express on port 3978 |
| **Auth** | Bot Framework channel authentication (`BOT_ID`, `BOT_PASSWORD` env vars) |
| **Env vars** | `BOT_ID`, `BOT_PASSWORD`, `API_GATEWAY_INTERNAL_URL`, `WEB_UI_PUBLIC_URL`, `TEAMS_CHANNEL_ID` |
| **Adaptive Cards** | `adaptivecards ^3.0.0` — HITL approval cards sent via Bot Framework proactive messaging |
| **Approval flow** | Bot receives `Action.Execute` from card → calls `POST /api/v1/approvals/{id}/approve` (or reject) on internal API gateway URL |

---

## Azure Container Registry (ACR)

| Attribute | Detail |
|---|---|
| **Image pull auth** | System-assigned managed identity on each Container App (`identity = "system"` in registry block) |
| **Role** | `Container Registry Repository Reader` on ACR scope |
| **ACR name** | From `vars.ACR_LOGIN_SERVER` GitHub variable |
| **Image naming** | `agents/<name>:<sha>` for agents, `services/<name>:<sha>` for services |
| **Base image resolution** | CI queries ACR for latest immutable tag (`az acr repository show-tags --orderby time_desc`) |

---

## GitHub Actions (CI/CD)

| Integration | Auth | Purpose |
|---|---|---|
| Azure login | OIDC (`azure/login@v2`) or client secret | Terraform plan/apply, image push, Container App deploy |
| ACR push | `az acr login` via authenticated service principal | `docker push` in `docker-push.yml` reusable workflow |
| Container App deploy | `az containerapp update --image ...` | Rolling revision update after image push |
| GitHub OIDC | `permissions: id-token: write` | Federates with Azure AD for passwordless auth |
| PR comments | `actions/github-script@v7` | Posts Terraform plan output as PR comment |
| Path filtering | `dorny/paths-filter@v3` | Triggers only changed agent/service builds |

---

## OneLake / ADLS Gen2

| Attribute | Detail |
|---|---|
| **SDK** | `azure-storage-file-datalake>=12.0.0` |
| **Auth** | `DefaultAzureCredential` |
| **Purpose** | Export audit logs, alert history, resource inventory snapshots to Fabric Lakehouse |
| **Env var** | `ONELAKE_ENDPOINT` |

---

## Integration Topology

```
Azure Monitor Alerts
    → Event Hub (raw-alerts)
        → Fabric Eventstreams
            → Eventhouse KQL DB
                → Activator (trigger on detection rule match)
                    → POST /api/v1/incidents (API Gateway)

API Gateway
    ├── POST /api/v1/incidents → Foundry (AgentsClient.threads + runs)
    │       ↓
    │   Orchestrator Agent (Foundry Hosted Agent)
    │       ↓ handoff
    │   Domain Agents (compute/network/storage/security/sre/arc)
    │       ├── Azure MCP tools (via azure_tools proxy or HTTP sidecar)
    │       └── Arc MCP tools (Arc MCP server HTTP endpoint)
    │
    ├── GET  /api/v1/runbooks/search → PostgreSQL + pgvector (cosine similarity)
    ├── POST /api/v1/chat → Foundry (chat thread dispatch)
    ├── GET  /api/v1/chat/{id}/result → Foundry (run poll)
    ├── POST /api/v1/approvals/{id}/approve|reject → Cosmos DB (approval record update)
    ├── GET  /api/v1/audit → Log Analytics (App Insights OTel spans)
    └── GET  /api/v1/audit/export → Log Analytics (remediation report)

Web UI (Next.js)
    ├── /app/api/stream → SSE — polls API gateway for agent replies
    ├── /app/api/proxy → reverse-proxy to API gateway (avoids CORS)
    ├── /app/api/observability → Log Analytics query (Azure Monitor SDK)
    └── MSAL auth → Entra ID (SPA auth code flow)

Teams Bot (Bot Framework)
    ├── Inbound: Teams channel → Bot Framework → Express /api/messages
    ├── Proactive: Agent platform → Teams channel (approval cards)
    └── Card actions → POST /api/v1/approvals (internal API gateway URL)
```
