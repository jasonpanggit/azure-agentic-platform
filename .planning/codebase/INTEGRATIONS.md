# External Integrations & APIs — Azure Agentic Platform

> Generated: 2026-04-01. Source: requirements*.txt, auth.py, foundry.py, audit_trail.py, azure_tools.py, Terraform modules, Dockerfiles.

---

## Azure Services

### Azure AI Foundry (Agent Service)

| Attribute | Detail |
|---|---|
| **SDK** | `azure-ai-agents==1.2.0b5` (API gateway + agents); `azure-ai-projects==2.0.0b3` (agent base image) |
| **Client class** | `AgentsClient(endpoint=AZURE_PROJECT_ENDPOINT, credential=DefaultAzureCredential())` |
| **Auth** | `DefaultAzureCredential` → system-assigned managed identity (Container Apps) or Azure CLI/env vars (local) |
| **Env vars** | `AZURE_PROJECT_ENDPOINT` (primary); `FOUNDRY_ACCOUNT_ENDPOINT` (fallback) |
| **Model** | GPT-4o (`gpt-4o`, version `2024-11-20`), Standard SKU, 100k TPM capacity in prod |
| **Terraform** | `azurerm_cognitive_account` (kind=`AIServices`), `azurerm_cognitive_account_project`, `azurerm_cognitive_deployment` |
| **Capability host** | `azapi_resource` (`Microsoft.CognitiveServices/accounts/capabilityHosts`) |

**Foundry operations used (API gateway → Foundry):**
1. `client.threads.create()` — new conversation thread per incident or chat session
2. `client.messages.create(thread_id, role="user", content=json_envelope)` — post typed incident/chat envelope
3. `client.runs.create(thread_id, agent_id=ORCHESTRATOR_AGENT_ID)` — dispatch to Orchestrator agent
4. `client.runs.get(thread_id, run_id)` — poll for completion; retrieve assistant reply

---

### Azure OpenAI (Embeddings)

| Attribute | Detail |
|---|---|
| **Client** | `openai.AzureOpenAI` (`openai>=1.0.0`) |
| **Model** | `text-embedding-3-small` (1536-dimensional vectors) |
| **Env vars** | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` (optional; omit or set to `DISABLED_LOCAL_AUTH_USE_MI` to use managed identity) |
| **Auth fallback** | `get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")` |
| **Purpose** | Runbook RAG — query embedding generation for pgvector cosine similarity search |
| **Deployment name env var** | `EMBEDDING_DEPLOYMENT_NAME` (default: `text-embedding-3-small`) |
| **API version** | `2024-06-01` |

---

### Azure MCP Server (`@azure/mcp`)

#### Sidecar HTTP Transport (`services/azure-mcp-server/`)

| Attribute | Detail |
|---|---|
| **Package** | `@azure/mcp@2.0.0-beta.34` (npm, pinned) |
| **Transport** | HTTP on port 5000 (`azmcp server start --transport http`) |
| **Proxy** | `proxy.js` (Node.js) — listens on `0.0.0.0:8080`, forwards to `localhost:5000`; returns 503 while `azmcp` warms up |
| **Auth** | `DefaultAzureCredential` from `@azure/identity` |
| **Purpose** | ARM/Monitor/Storage/Networking tool surfaces via MCP HTTP |

#### stdio Subprocess (API Gateway, `services/api-gateway/azure_tools.py`)

| Attribute | Detail |
|---|---|
| **Package** | `@azure/mcp@2.0.0-beta.34` installed globally in API gateway Dockerfile |
| **Transport** | stdio (launched as subprocess via `mcp[cli]` stdio client) |
| **Endpoint** | `POST /api/v1/azure-tools` — proxies tool calls as regular OpenAI function calls |
| **Reason** | Works around a protocol incompatibility between Foundry's HTTP MCP client and `@azure/mcp` streamable-HTTP |

---

### Custom Arc MCP Server (`services/arc-mcp-server/`)

| Attribute | Detail |
|---|---|
| **Framework** | `mcp[cli]==1.26.0` — FastMCP (`mcp.server.fastmcp`) |
| **Transport** | Streamable HTTP on port 8080 |
| **Auth** | `DefaultAzureCredential` → managed identity |
| **Container image** | `FROM python:3.11-slim` (standalone; does NOT extend `agents/Dockerfile.base`) |
| **Env var (Arc agent)** | `ARC_MCP_SERVER_URL` (injected by Terraform `modules/agent-apps`) |
| **Tools exposed** | `arc_servers_list`, `arc_k8s_list`, `arc_data_services_list`, `arc_k8s_gitops_status`, `arc_extensions_list` |
| **Azure SDKs** | `azure-mgmt-hybridcompute==9.0.0` (HybridCompute/machines), `azure-mgmt-hybridkubernetes==1.1.0` (ConnectedClusters), `azure-mgmt-azurearcdata==1.0.0` (data services), `azure-mgmt-kubernetesconfiguration==3.1.0` (Flux/GitOps) |

---

### Azure Cosmos DB

| Attribute | Detail |
|---|---|
| **Python SDK** | `azure-cosmos>=4.0.0` (gateway), `>=4.7.0` (agents, detection plane) |
| **TypeScript SDK** | `@azure/cosmos ^4.0.0` (web-ui observability route), `^4.9.2` (e2e fixtures) |
| **Auth** | `local_authentication_disabled = true` — Entra-only (no keys); `DefaultAzureCredential` in Python; `@azure/identity` in TS |
| **Endpoint env var** | `COSMOS_ENDPOINT` |
| **Database** | `aap` (`COSMOS_DATABASE_NAME`) |
| **Containers** | `incidents` (partition: `/resource_id`), `approvals` (partition: `/thread_id`), `sessions` (partition: `/incident_id`) |
| **Consistency level** | Session |
| **Mode** | Serverless (dev/staging) or provisioned autoscale up to 4000 RU/s (prod) |
| **Multi-region** | Primary + `westus2` failover (prod only) |
| **Networking** | Private endpoint, `public_network_access_enabled = false` |

---

### PostgreSQL Flexible Server + pgvector

| Attribute | Detail |
|---|---|
| **Server version** | PostgreSQL 16 |
| **SKU** | `GP_Standard_D4s_v3` (prod), 128 GB storage |
| **Auth** | Entra (`active_directory_auth_enabled = true`) + password auth; production uses Entra exclusively |
| **Database** | `aap` |
| **Extension** | `pgvector` (`VECTOR`) — allowlisted via `azure.extensions` config parameter |
| **Python driver** | `asyncpg>=0.29.0` (async API gateway queries); seed scripts use `psycopg[binary]` |
| **pgvector adapter** | `pgvector>=0.3.0` (`register_vector` for asyncpg) |
| **Connection env vars** | `PGVECTOR_CONNECTION_STRING` (primary), `POSTGRES_DSN` (fallback), or individual `POSTGRES_HOST/PORT/DB/USER/PASSWORD` |
| **Tables** | `runbooks` (`id UUID`, `title`, `domain`, `content`, `embedding vector(1536)`, `version`, timestamps); `eol_cache` (24h TTL lifecycle cache) |
| **Index** | `ivfflat` cosine ops with `lists = 100` on `embedding` column |
| **Purpose** | Runbook RAG semantic search; EOL product version cache |
| **Networking** | VNet-injected, `public_network_access_enabled = false` |

---

### Azure Event Hubs

| Attribute | Detail |
|---|---|
| **Terraform** | `azurerm_eventhub_namespace` (Standard SKU, capacity=2 in prod), `azurerm_eventhub` (`raw-alerts`, 10 partitions in prod) |
| **Purpose** | Single ingest point for Azure Monitor alerts → Fabric detection plane |
| **Auth rules** | `action-group-send` (Monitor Action Group → EH, Send-only); `eventhouse-listen` (Fabric Eventstreams → EH, Listen-only) |
| **Consumer group** | `eventhouse-consumer` — used by Fabric Eventstreams |
| **Monitor integration** | `azurerm_monitor_action_group` forwards Azure Monitor alerts to `raw-alerts` hub using `use_common_alert_schema = true` |
| **Networking** | VNet subnet rule on Container Apps subnet; private endpoint |

---

### Microsoft Fabric

| Component | Status | Terraform Type | Purpose |
|---|---|---|---|
| **Fabric Capacity** | GA | `Microsoft.Fabric/capacities@2023-11-01` | Compute unit; SKU `F4` in prod |
| **Fabric Workspace** | GA | `Microsoft.Fabric/workspaces@2023-11-01` | Logical container |
| **Eventhouse** | GA | `Microsoft.Fabric/workspaces/eventhouses@2023-11-01` | KQL-native time-series store |
| **KQL Database** | GA | `Microsoft.Fabric/workspaces/eventhouses/databases@2023-11-01` | Holds `DetectionResults` table |
| **Activator** | GA | `Microsoft.Fabric/workspaces/reflex@2023-11-01` | Fires webhook on detection rule match |
| **OneLake Lakehouse** | GA | `Microsoft.Fabric/workspaces/lakehouses@2023-11-01` | Audit logs, alert history, snapshots |

**Fabric data flow**: Azure Monitor → Event Hub (`raw-alerts`) → Fabric Eventstreams → Eventhouse KQL DB → Activator → webhook → `POST /api/v1/incidents`

**Manual steps required post-deploy**: Activator trigger configuration (Fabric portal); Activity Log OneLake mirror setup.

---

### Azure Key Vault

| Attribute | Detail |
|---|---|
| **Terraform** | `azurerm_key_vault` — Standard SKU, RBAC-mode (`rbac_authorization_enabled = true`) |
| **Auth** | RBAC (Key Vault Secrets User/Officer via `azurerm_role_assignment`) |
| **Settings** | 90-day soft-delete retention, purge protection enabled |
| **Networking** | Private endpoint only (`public_network_access_enabled = false`) |
| **Stored secrets** | `APPLICATIONINSIGHTS_CONNECTION_STRING` (injected as Container App secret), Teams bot password, Fabric SP client ID/secret |

---

### Azure Monitor / Application Insights

| Attribute | Detail |
|---|---|
| **Log Analytics Workspace** | `azurerm_log_analytics_workspace` — workspace-based App Insights |
| **Application Insights** | `azurerm_application_insights` (type=`other`) |
| **Connection string env var** | `APPLICATIONINSIGHTS_CONNECTION_STRING` |
| **Python instrumentation** | `azure-monitor-opentelemetry` — `configure_azure_monitor()` at startup in all agents and API gateway |
| **Node.js instrumentation** | `@azure/monitor-opentelemetry ^1.0.0` + `@opentelemetry/auto-instrumentations-node ^0.50.0` (teams-bot) |
| **Custom span attributes** | `aiops.agent_id`, `aiops.agent_name`, `aiops.tool_name`, `aiops.tool_parameters`, `aiops.outcome`, `aiops.duration_ms`, `aiops.correlation_id`, `aiops.thread_id` |
| **Audit log queries** | `services/api-gateway/audit.py` — queries App Insights OTel spans via Log Analytics REST API (`LOG_ANALYTICS_WORKSPACE_ID`) |
| **Web UI queries** | `@azure/monitor-query ^1.3.0` — direct Log Analytics queries from Observability tab |

---

### Azure Resource Graph

| Attribute | Detail |
|---|---|
| **SDK** | `azure-mgmt-resourcegraph>=8.0.0` (API gateway patch endpoints); `>=8.0.1` (patch agent, eol agent) |
| **Client** | `ResourceGraphClient(credential)` |
| **Purpose** | Patch assessment queries (`PatchAssessmentResources`, `PatchInstallationResources`); EOL inventory queries |
| **Queries** | KQL against `patchassessmentresources`, `patchinstallationresources` tables |

---

### Azure Container Registry (ACR)

| Attribute | Detail |
|---|---|
| **Auth** | System-assigned managed identity on each Container App (`identity = "system"` in registry block) |
| **Role** | `Container Registry Repository Reader` on ACR scope |
| **Image naming** | `agents/<name>:<sha>` for agents; `services/<name>:<sha>` for services |
| **Base image resolution** | CI queries ACR for latest immutable tag (`az acr repository show-tags --orderby time_desc`) |

---

## APIs & Endpoints

### API Gateway (`services/api-gateway/`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | None | Health check |
| `POST` | `/api/v1/incidents` | Entra Bearer | Ingest incident; deduplicate; dispatch to Foundry |
| `GET` | `/api/v1/incidents` | Entra Bearer | List incidents (rate-limited; Cosmos DB query) |
| `GET` | `/api/v1/runbooks/search` | Entra Bearer | Semantic runbook search via pgvector |
| `POST` | `/api/v1/chat` | Entra Bearer | Start operator chat thread in Foundry |
| `GET` | `/api/v1/chat/{thread_id}/result` | Entra Bearer | Poll Foundry run status; approve pending MCP sub-run tool calls |
| `POST` | `/api/v1/approvals/{id}/approve` | Entra Bearer | Approve HITL remediation proposal |
| `POST` | `/api/v1/approvals/{id}/reject` | Entra Bearer | Reject HITL remediation proposal |
| `GET` | `/api/v1/approvals` | Entra Bearer | List approvals by status |
| `GET` | `/api/v1/approvals/{id}` | Entra Bearer | Get approval record |
| `GET` | `/api/v1/audit` | Entra Bearer | Query agent action history (OTel spans in Log Analytics) |
| `GET` | `/api/v1/audit/export` | Entra Bearer | Export remediation report (SOC 2 format) |
| `POST` | `/api/v1/azure-tools` | Entra Bearer | Call Azure MCP tool via stdio subprocess |
| `GET` | `/api/v1/patch/assessments` | Entra Bearer | Patch assessment data from Azure Resource Graph |
| `GET` | `/api/v1/patch/installations` | Entra Bearer | Patch installation data from Azure Resource Graph |

### Web UI Next.js Route Handlers (`services/web-ui/app/api/`)

| Path | Transport | Purpose |
|---|---|---|
| `/api/stream` | SSE (`ReadableStream`) | Polls Foundry run status every 2s; emits `token` and `done` events |
| `/api/proxy/*` | HTTP reverse-proxy | Proxies chat, incidents, approvals, patch endpoints to API gateway (avoids CORS) |
| `/api/observability` | HTTP | Queries Log Analytics (KQL) + Cosmos DB for Observability tab metrics |
| `/api/resources` | HTTP | Azure resource queries |
| `/api/subscriptions` | HTTP | Azure subscription listing |
| `/api/topology` | HTTP | Resource topology queries |

---

## Authentication

### Backend Services

| Mechanism | Where Used | Details |
|---|---|---|
| `DefaultAzureCredential` | All agent containers, API gateway, Arc MCP server | Resolves system-assigned managed identity (IMDS) in Container Apps; falls back to Azure CLI / VS Code / env vars locally |
| Entra ID Bearer token validation | API gateway (`/api/v1/*`) | `fastapi-azure-auth` `SingleTenantAzureAuthorizationCodeBearer`; env vars: `API_GATEWAY_CLIENT_ID` + `API_GATEWAY_TENANT_ID`; scope: `api://<client_id>/incidents.write` |
| Local bypass | API gateway only | `API_GATEWAY_AUTH_MODE=disabled`; fail-closed by default (defaults to `entra`) |
| MSAL client credentials | Fabric User Data Function | `msal.ConfidentialClientApplication` with `FABRIC_SP_CLIENT_ID` + `FABRIC_SP_CLIENT_SECRET` → Bearer token for API gateway audience |

**Agent identity**: Each Container App has a system-assigned managed identity. `AGENT_ENTRA_ID` env var (the identity's `principal_id`) is used for AUDIT-005 attribution in OTel spans.

### Frontend

| Mechanism | Where Used | Details |
|---|---|---|
| MSAL Browser | Web UI | `@azure/msal-browser ^3.0.0` + `@azure/msal-react ^2.0.0`; SPA auth code flow; scopes: `openid`, `profile`, `email` |
| MSAL config env vars | Web UI build-time | `NEXT_PUBLIC_AZURE_CLIENT_ID`, `NEXT_PUBLIC_TENANT_ID`, `NEXT_PUBLIC_REDIRECT_URI` (baked into Next.js at Docker build via `ARG`) |
| MSAL Node | E2E tests | `@azure/msal-node ^5.1.1` — service principal auth in `global-setup.ts`; bearer token injected as `E2E_BEARER_TOKEN` |

### Infrastructure (Terraform / CI)

| Mechanism | Where Used | Details |
|---|---|---|
| OIDC federated identity | Terraform workflows | `azure/login@v2` + `ARM_USE_OIDC: true`; `id-token: write` permission |
| Client secret fallback | Agent image build workflows | Auto-detected: if `AZURE_CLIENT_SECRET` is set, uses SP login; else OIDC |
| ACR image pull | Container Apps | System-assigned managed identity (`identity = "system"` in registry block); no admin credentials |

---

## Data Stores

| Store | SDK | Auth | Purpose |
|---|---|---|---|
| **Azure Cosmos DB** | `azure-cosmos` (Python), `@azure/cosmos` (TS) | Entra-only (`DefaultAzureCredential`) | Hot-path: incidents, approvals, agent sessions |
| **PostgreSQL Flexible Server v16** | `asyncpg` (async), `psycopg[binary]` (seed scripts) | Entra or password | Runbook library (RAG), gitops_config table, EOL cache |
| **pgvector** | `pgvector>=0.3.0` | n/a (extension) | 1536-dim cosine similarity on `runbooks.embedding` column |
| **Fabric OneLake (ADLS Gen2)** | `azure-storage-file-datalake>=12.0.0` | `DefaultAzureCredential` | Long-term audit logs, alert history, resource snapshots (≥2 years) |
| **Fabric Eventhouse (KQL)** | Fabric Eventstreams (no-code) | Fabric capacity | Alert ingestion and detection via KQL rules |

---

## Messaging / Events

### Azure Event Hubs → Fabric Pipeline

```
Azure Monitor alert fires
  → azurerm_monitor_action_group (use_common_alert_schema = true)
      → Event Hub namespace: raw-alerts (Standard SKU, 10 partitions in prod)
          → Fabric Eventstreams (eventhouse-listen auth rule, eventhouse-consumer group)
              → Eventhouse KQL Database (DetectionResults table)
                  → Fabric Activator (trigger on domain IS NOT NULL)
                      → POST /api/v1/incidents (API Gateway)
                          → Foundry AgentsClient (thread + run)
                              → Orchestrator → Domain Agents
```

### Teams Integration

| Attribute | Detail |
|---|---|
| **SDK** | `botbuilder ^4.23.0` + `@microsoft/teams-ai ^1.5.0` |
| **Server** | Express on port 3978 |
| **Bot auth** | `BOT_ID`, `BOT_PASSWORD` env vars (Bot Framework channel auth) |
| **Inbound** | Teams channel → Bot Framework → Express `/api/messages` handler |
| **Proactive outbound** | Agent platform → `services/api-gateway/teams_notifier.py` → `POST TEAMS_BOT_INTERNAL_URL/notify` → Teams channel |
| **Card types** | `alert`, `approval`, `outcome`, `reminder` |
| **Approval flow** | Adaptive Card `Action.Execute` → `POST /api/v1/approvals/{id}/approve` or `/reject` on internal API gateway URL |
| **Internal URL pattern** | `https://ca-api-gateway-{env}.internal.{container_apps_env_domain}` |
| **Key env vars** | `TEAMS_BOT_INTERNAL_URL`, `TEAMS_CHANNEL_ID` |

### Internal Service-to-Service (HTTP)

| Caller | Target | Transport | Purpose |
|---|---|---|---|
| Web UI SSE route | API gateway `/api/v1/chat/{id}/result` | HTTP poll every 2s | Stream agent replies to browser via SSE |
| API gateway | Teams bot `/notify` | httpx (async) | Forward alert/approval card notifications |
| Arc agent | Arc MCP Server | HTTP (`ARC_MCP_SERVER_URL`) | Arc resource tool calls |
| API gateway | Azure MCP `azmcp` binary | stdio subprocess | Azure resource tool calls (workaround for Foundry HTTP MCP incompatibility) |
| Fabric User Data Function | API gateway `/api/v1/incidents` | MSAL + HTTP | Push detected alerts from Fabric to platform |

---

## Integration Topology

```
Azure Monitor Alerts
    → Event Hub (raw-alerts)
        → Fabric Eventstreams
            → Eventhouse KQL DB
                → Activator (trigger on detection rule match)
                    → POST /api/v1/incidents  ←── Authenticated with MSAL SP token

API Gateway (FastAPI, port 8000)
    ├── POST /api/v1/incidents → Foundry AgentsClient (thread + run)
    │       ↓
    │   Orchestrator Agent (Foundry Hosted Agent Container App)
    │       ↓ handoff
    │   Domain Agents: compute / network / storage / security / sre / arc / patch / eol
    │       ├── Azure MCP tools  → /api/v1/azure-tools → azmcp stdio subprocess
    │       └── Arc MCP tools    → Arc MCP Server HTTP (ARC_MCP_SERVER_URL)
    │
    ├── GET  /api/v1/runbooks/search → PostgreSQL + pgvector
    ├── POST /api/v1/chat           → Foundry (chat thread dispatch)
    ├── GET  /api/v1/chat/{id}/result → Foundry (run poll + background MCP approval)
    ├── POST /api/v1/approvals/{id}/approve|reject → Cosmos DB + OneLake audit
    ├── GET  /api/v1/audit          → Log Analytics (OTel spans KQL)
    ├── GET  /api/v1/audit/export   → Log Analytics (remediation report)
    ├── POST /api/v1/azure-tools    → @azure/mcp stdio subprocess
    └── GET  /api/v1/patch/*        → Azure Resource Graph

Web UI (Next.js, port 3000)
    ├── /api/stream      → SSE — polls API gateway for agent replies
    ├── /api/proxy/*     → HTTP reverse-proxy to API gateway
    ├── /api/observability → Log Analytics (Azure Monitor SDK) + Cosmos DB
    └── MSAL SPA auth   → Entra ID (auth code flow)

Teams Bot (Bot Framework, port 3978)
    ├── Inbound: Teams channel → /api/messages → Express → teams-ai handler
    ├── Proactive: API gateway teams_notifier → /notify → Bot Framework proactive
    └── Card actions → POST /api/v1/approvals (internal gateway URL)
```
