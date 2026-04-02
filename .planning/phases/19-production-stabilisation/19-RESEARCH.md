# Phase 19: Production Stabilisation — Research

> Prepared: 2026-04-02
> Sources: STATE.md, ROADMAP.md, REQUIREMENTS.md, BACKLOG.md, CONCERNS.md, codebase inspection (chat.py, auth.py, Terraform modules, Dockerfiles, seed.py, teams-bot, requirements-base.txt, deploy scripts)

---

## Table of Contents

1. [Phase Scope & Requirements](#1-phase-scope--requirements)
2. [What's Already Fixed (Resolved Since Phase 14 Planning)](#2-whats-already-fixed)
3. [MCP Tool Group Registration](#3-mcp-tool-group-registration)
4. [Auth Enablement](#4-auth-enablement)
5. [Azure MCP Server Security](#5-azure-mcp-server-security)
6. [Arc MCP Server Real Image](#6-arc-mcp-server-real-image)
7. [Runbook RAG](#7-runbook-rag)
8. [Hardcoded Foundry Agent IDs](#8-hardcoded-foundry-agent-ids)
9. [Teams Bot Registration](#9-teams-bot-registration)
10. [Agent Framework Version Pin](#10-agent-framework-version-pin)
11. [Risk Register](#11-risk-register)
12. [Recommended Milestone Structure](#12-recommended-milestone-structure)

---

## 1. Phase Scope & Requirements

### Requirements

| ID | Requirement | Linked Concerns |
|----|-------------|-----------------|
| PROD-001 | Entra authentication enforced on all non-health API endpoints in production | SEC-003, SEC-004, BUG-004 |
| PROD-002 | Azure MCP Server authenticated via managed identity; internal ingress only; no unauthenticated external access | SEC-001, DEBT-006, DEBT-013 |
| PROD-003 | All 8 domain agent MCP tool groups registered in Foundry; each exercises domain tools in integration test | GAP-001, F-09, F-10, F-11 |
| PROD-005 | Teams proactive alerting delivers Adaptive Cards within 2 minutes of incident creation | GAP-004, F-04 |

### Full Backlog Items to Resolve

| Backlog ID | Description | Severity | PROD Req |
|------------|-------------|----------|----------|
| F-02 | Runbook RAG returns 500 (BUG-002) | BLOCKING | PROD-001 |
| F-03 | CORS wildcard `*` on prod (BUG-004) | HIGH | PROD-001 |
| F-04 | Azure Bot Service not in Terraform; TEAMS_CHANNEL_ID empty | HIGH | PROD-005 |
| F-05 | E2E GitHub Actions secrets not set | MEDIUM | PROD-001 |
| F-09 | Microsoft.Network MCP tool group missing | DEGRADED | PROD-003 |
| F-10 | Microsoft.Security MCP tool group missing | DEGRADED | PROD-003 |
| F-11 | Arc MCP + SRE tool groups not in Foundry | DEGRADED | PROD-003 |
| SEC-001 | Azure MCP Server externally exposed with no auth | CRITICAL | PROD-002 |
| SEC-003 | Dev-mode auth bypass active in prod | HIGH | PROD-001 |
| SEC-004 | Web UI proxy routes don't forward auth tokens correctly | HIGH | PROD-001 |
| DEBT-001 | Agent framework pinned to old beta | HIGH | — |
| DEBT-005 | In-memory Teams conversation/escalation state | HIGH | PROD-005 |
| DEBT-013 | Azure MCP Server not managed by Terraform | MEDIUM | PROD-002 |
| GAP-002 | OTel manual spans not deployed to prod | HIGH | — |
| GAP-009 | Arc MCP Server placeholder image | MEDIUM | PROD-003 |

### What Phase 14 Defined (12 tasks, 6 milestones)

Phase 14 was planned but never executed. Phase 19 inherits all 12 tasks, updated for current state. The original plan is at `.planning/phases/14-prod-stabilisation/PLAN.md`.

---

## 2. What's Already Fixed

Several items from the Phase 14 plan have been resolved by quick tasks since then. **Do NOT re-plan these:**

| Phase 14 Task | Description | Current State | Evidence |
|---------------|-------------|---------------|----------|
| 14-01 | Re-provision orchestrator with MCP-enabled agent IDs | **DONE** | Quick task 260331-ize: All 8 `connected_agent` tools registered on Foundry orchestrator. All 8 `*_AGENT_ID` env vars set on `ca-orchestrator-prod`. |
| 14-05 | Replace hardcoded Foundry agent IDs in chat.py | **DONE** | `chat.py:26-38` now uses `_DOMAIN_AGENT_IDS: frozenset[str]` built from env vars. Zero hardcoded `asst_*` strings remain. |
| 14-06 (BUG-001) | NameError `outputs` in chat.py | **DONE** | `chat.py:427` reads `tool_outputs=tool_outputs` (correct). Quick task 260401-bd1 fixed this. |
| 14-07 (partial) | Arc MCP Server placeholder flag | **DONE** | `terraform/envs/prod/main.tf:212` shows `use_placeholder_image = false`. `enable_arc_mcp_server = true`. |
| 14-09 (partial) | App Insights wiring | **DONE** | Quick task 260402-fvo wired all 12 containers to App Insights. Validation scripts created (260402-gcx). |
| F-01 | Foundry RBAC for gateway MI | **DONE** | Quick task 260331-k6y: `Azure AI Developer` role granted. |
| ORCHESTRATOR_AGENT_ID | Missing env var | **DONE** | Set to `asst_NeBVjCA5isNrIERoGYzRpBTu` on `ca-api-gateway-prod` (260331-k6y). |

### Remaining from Phase 14

The following Phase 14 tasks are **still open** and must be addressed in Phase 19:

1. **14-02** — Register `Microsoft.Network` MCP tool group (F-09)
2. **14-03** — Register `Microsoft.Security` MCP tool group (F-10)
3. **14-04** — Register Arc MCP + SRE cross-domain tool groups (F-11)
4. **14-08** — Fix runbook RAG: PGVECTOR_CONNECTION_STRING + seed prod (F-02)
5. **14-10** — Teams Bot Service + TEAMS_CHANNEL_ID wiring (F-04)
6. **14-11** — Verify agent framework dependency pins (DEBT-001)
7. **14-12** — Add Entra auth to Arc MCP Server (replaces `--dangerously-disable-http-incoming-auth`)

Plus **new scope** not in Phase 14:

8. **SEC-001** — Azure MCP Server security (switch to internal ingress + Terraform ownership)
9. **PROD-001** — Enable Entra auth on API gateway (SEC-003, SEC-004)
10. **F-03** — Lock CORS to explicit prod origin (BUG-004)
11. **F-05** — Set E2E GitHub Actions secrets for Entra-authenticated runs

---

## 3. MCP Tool Group Registration

### Problem

Network, Security, Arc, and SRE agents cannot invoke their domain-specific MCP tools in production. They return "tool group was not found" errors and fall back to the compute tool surface.

### Current State (verified from codebase)

- Azure MCP Server is deployed as `ca-azure-mcp-prod` (ad-hoc script `scripts/deploy-azure-mcp-server.sh`, NOT in Terraform — DEBT-013)
- Azure MCP Server has `Reader` role on the subscription
- The orchestrator's 8 `connected_agent` tools are registered (done 260331-ize)
- Missing: MCP tool group connections on the Foundry project for `Microsoft.Network`, `Microsoft.Security`, and Arc MCP Server

### How to Register MCP Tool Groups on Foundry

**Option A: Foundry Portal UI**
1. Navigate to Azure AI Foundry > project `aap-project-prod` > Connected resources > MCP Servers
2. Add MCP connection with the Azure MCP Server URL
3. Select tool groups: `Microsoft.Network`, `Microsoft.Security`, `Microsoft.Compute` (already working), `Microsoft.Storage`, `Microsoft.Monitor`, etc.
4. Separately add the custom Arc MCP Server as an MCP connection

**Option B: REST API / azapi (automatable)**

From `scripts/deploy-azure-mcp-server.sh:104-106`, the pattern is:
```bash
az rest --method PUT \
  --url 'https://management.azure.com/subscriptions/{sub}/resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod/connections/azure-mcp-connection?api-version=2026-01-01-preview' \
  --body '{"properties":{"category":"MCP","target":"https://{fqdn}","authType":"None"}}'
```

**Option C: Terraform azapi_resource**
```hcl
resource "azapi_resource" "mcp_connection" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2026-01-01-preview"
  name      = "azure-mcp-connection"
  parent_id = azurerm_cognitive_account_project.main.id
  body = jsonencode({
    properties = {
      category = "MCP"
      target   = "https://${azurerm_container_app.azure_mcp_server.ingress[0].fqdn}"
      authType = "None"  # Internal-only once SEC-001 is fixed
    }
  })
}
```

### Key Findings

1. **The tool group registration is at the Foundry project level**, not per-agent. Once `Microsoft.Network` is registered on the project, ALL agents in that project can invoke Network tools.
2. **The `configure-orchestrator.py` script** accepts `--mcp-connection` flag to wire MCP connections to the orchestrator agent specifically.
3. **Arc MCP Server** needs a separate MCP connection pointing to `ca-arc-mcp-server-prod` internal URL (not the Azure MCP Server URL).
4. **SRE agent cross-domain access** is satisfied by registering monitor + Log Analytics tool groups on the Foundry project — SRE doesn't need a separate connection, just the tool groups available in the project.

### Verification

For each domain:
```bash
# Send a domain-specific query via chat
POST /api/v1/chat {"message": "list NSGs in subscription X"}
# Check that the network agent invokes MCP tools (not "tool group not found")
```

---

## 4. Auth Enablement

### Problem

**PROD-001: Entra authentication is NOT enforced in production.**

Three layers of auth failure:
1. **API Gateway (SEC-003):** `API_GATEWAY_AUTH_MODE` defaults to `entra`, BUT `API_GATEWAY_CLIENT_ID` (or `AZURE_CLIENT_ID`) and `API_GATEWAY_TENANT_ID` (or `AZURE_TENANT_ID`) are not set on `ca-api-gateway-prod`. This causes a configuration error at init → 503 for all authenticated routes... BUT the current production workaround is `API_GATEWAY_AUTH_MODE=disabled` to bypass auth entirely.
2. **Web UI proxy routes (SEC-004):** The proxy code at `services/web-ui/lib/api-gateway.ts:25-37` correctly forwards the `Authorization` header from browser requests. However, the MSAL-acquired token must reach the API gateway with a valid audience claim.
3. **CORS (BUG-004):** `CORS_ALLOWED_ORIGINS=*` in prod. Must be locked to `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io`.

### How Auth Works (from `services/api-gateway/auth.py`)

The `EntraTokenValidator` class:
1. Reads `API_GATEWAY_AUTH_MODE` (default: `entra`; bypass: `disabled`)
2. Uses `API_GATEWAY_CLIENT_ID` or `AZURE_CLIENT_ID` for the app registration client ID
3. Uses `API_GATEWAY_TENANT_ID` or `AZURE_TENANT_ID` for the tenant
4. Instantiates `SingleTenantAzureAuthorizationCodeBearer` from `fastapi-azure-auth`
5. Validates JWT with scopes: `api://{client_id}/incidents.write`

### What's Needed

1. **Create/confirm API gateway Entra app registration**
   - An app registration for the API gateway already exists for the web-ui MSAL flow: client ID `505df1d3-3bd3-4151-ae87-6e5974b72a44`
   - May need a separate app registration for the API gateway with appropriate API scopes, or the existing one can expose scopes
   - Register API scope: `api://{client_id}/incidents.write`

2. **Set env vars on `ca-api-gateway-prod`:**
   ```bash
   az containerapp update --name ca-api-gateway-prod --resource-group rg-aap-prod \
     --set-env-vars \
       "API_GATEWAY_AUTH_MODE=entra" \
       "API_GATEWAY_CLIENT_ID=<api-app-client-id>" \
       "API_GATEWAY_TENANT_ID=abbdca26-d233-4a1e-9d8c-c4eebbc16e50"
   ```

3. **Configure Web UI MSAL to acquire the right token:**
   - `services/web-ui/` uses `@azure/msal-browser` for auth
   - Must configure `scopes: ['api://{api-gateway-client-id}/incidents.write']` in the MSAL config
   - Token is forwarded via `buildUpstreamHeaders()` in `lib/api-gateway.ts`

4. **Lock CORS:**
   - Already in `terraform.tfvars`: `cors_allowed_origins = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"`
   - Verify it's applied: `az containerapp show --name ca-api-gateway-prod --query "properties.template.containers[0].env" | grep CORS`

5. **E2E secrets (F-05):**
   - `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_API_AUDIENCE` in GitHub Actions `staging` environment
   - These come from a service principal with delegated access to the API gateway

### Dependency Chain

```
1. Create/confirm API gateway app registration with scopes
2. Set env vars on ca-api-gateway-prod (API_GATEWAY_AUTH_MODE=entra)
3. Configure MSAL in web-ui to request correct scope + forward token
4. Lock CORS to explicit origin
5. Test: web-ui can still access all proxy routes with real Entra tokens
6. Set E2E secrets in GitHub Actions for CI
```

### Risk

**Simultaneous breakage:** Enabling auth breaks ALL web UI functionality if MSAL isn't correctly configured. Must test in staging first. Plan for a rollback path (set `API_GATEWAY_AUTH_MODE=disabled` if auth breaks).

---

## 5. Azure MCP Server Security

### Problem

**SEC-001 (CRITICAL) + DEBT-006 + DEBT-013**

The Azure MCP Server (`ca-azure-mcp-prod`):
- Runs with `--dangerously-disable-http-incoming-auth` flag
- Has `ingress: external = true` (internet-accessible)
- Has `Reader` role on the subscription (can read ALL Azure resources)
- Is NOT managed by Terraform (deployed via ad-hoc script)

Any internet user can invoke it and read all Azure resource metadata.

### Current Architecture

From `services/azure-mcp-server/Dockerfile:32`:
```
CMD ["sh", "-c", "node /app/proxy.js & azmcp server start --transport http --dangerously-disable-http-incoming-auth 2>&1; ...]
```

From `services/azure-mcp-server/proxy.js`: A reverse proxy on `0.0.0.0:8080` forwarding to `azmcp` on `localhost:5000`.

### Fix Options (Ranked)

**Option 1: Switch to Internal Ingress (RECOMMENDED)**

The Azure MCP Server should be internal-only like the Arc MCP Server. Only Foundry agents within the Container Apps environment need access.

Steps:
1. Create a Terraform module `terraform/modules/azure-mcp-server/` (mirroring `arc-mcp-server/`)
2. Set `ingress.external_enabled = false`
3. Remove `--dangerously-disable-http-incoming-auth` from Dockerfile CMD
4. Assign `Reader` role via Terraform RBAC
5. Import the existing `ca-azure-mcp-prod` container app into Terraform state
6. Update the Foundry MCP connection URL to use the internal FQDN
7. `terraform apply` to enforce internal-only ingress

**Option 2: Add Entra Auth Header Validation to Proxy**

Add Entra JWT validation to `proxy.js` (the reverse proxy layer):
- Validate `Authorization: Bearer <token>` header
- Accept tokens from the Foundry project's managed identity
- Reject unauthenticated requests with 401

This is defense-in-depth but more complex than Option 1 and still leaves the server externally accessible.

**Recommendation: Option 1 + Option 2 for defense-in-depth.**

### Terraform Module Pattern

```hcl
# terraform/modules/azure-mcp-server/main.tf
resource "azurerm_container_app" "azure_mcp_server" {
  name                         = "ca-azure-mcp-${var.environment}"
  container_app_environment_id = var.container_apps_environment_id
  ...
  ingress {
    external_enabled = false  # INTERNAL ONLY
    target_port      = 8080
    transport        = "http"
  }
  ...
}
```

### Verification

```bash
# After Terraform apply:
# 1. External URL should be unreachable
curl https://ca-azure-mcp-prod.<domain>/mcp  # Should fail (no external ingress)

# 2. Internal URL from another Container App should work
# (test from api-gateway or orchestrator)
```

---

## 6. Arc MCP Server Real Image

### Problem

Phase 14 task 14-07 required deploying the real Arc MCP Server image. **This is now partially resolved.**

### Current State (verified)

1. `terraform/envs/prod/main.tf:212`: `use_placeholder_image = false` -- **DONE**
2. `enable_arc_mcp_server = true` -- **DONE**
3. Terraform module at `terraform/modules/arc-mcp-server/main.tf` is fully configured
4. Dockerfile at `services/arc-mcp-server/Dockerfile` is complete and production-ready
5. The Dockerfile already has `ARC_MCP_AUTH_DISABLED=false` (Entra JWT auth enabled by default)
6. Quick task 260331-chg created the Terraform infra code

### What's Still Needed

1. **Verify the image was built and pushed to ACR:**
   ```bash
   az acr repository show-tags --name aapcrprodjgmjti --repository services/arc-mcp-server
   ```

2. **Verify the Container App is running the real image (not placeholder):**
   ```bash
   az containerapp show --name ca-arc-mcp-server-prod --resource-group rg-aap-prod \
     --query "properties.template.containers[0].image"
   ```

3. **Verify health endpoint:**
   ```bash
   # Internal URL — test from another Container App
   curl http://ca-arc-mcp-server-prod.internal.{domain}/mcp
   ```

4. **Register as MCP connection on Foundry project** (see Section 3)

### If Image Not Yet Pushed

```bash
# Build from repo root (not from services/arc-mcp-server/)
docker build -t aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest \
  --platform linux/amd64 \
  -f services/arc-mcp-server/Dockerfile \
  services/arc-mcp-server/

az acr login --name aapcrprodjgmjti
docker push aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest

az containerapp update --name ca-arc-mcp-server-prod \
  --resource-group rg-aap-prod \
  --image aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest
```

---

## 7. Runbook RAG

### Problem

**BUG-002 / F-02:** `GET /api/v1/runbooks/search` returns 500 in production. Runbook-assisted triage is completely non-functional.

### Current State

1. **60 runbooks exist** in `scripts/seed-runbooks/runbooks/` (10 per domain x 6 domains: compute, network, storage, security, arc, sre)
2. **`seed.py`** is fully functional (verified from code):
   - Reads YAML frontmatter from markdown files
   - Generates 1536-dim embeddings via Azure OpenAI `text-embedding-3-small`
   - Upserts into PostgreSQL with `ON CONFLICT (title) DO UPDATE`
   - Creates table + indexes if not present
3. **`validate.py`** runs 12 domain queries with `SIMILARITY_THRESHOLD=0.75`
4. **Terraform already passes `pgvector_connection_string` to agent-apps module** (line 268 of `terraform/envs/prod/main.tf`)

### PostgreSQL Schema (from `seed.py:56-68`)

```sql
CREATE TABLE IF NOT EXISTS runbooks (
    id SERIAL PRIMARY KEY,
    title TEXT UNIQUE NOT NULL,
    domain TEXT NOT NULL,
    version TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_runbooks_embedding
  ON runbooks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
CREATE INDEX IF NOT EXISTS idx_runbooks_domain ON runbooks (domain);
```

### Connection String Formats

**With password (from `seed.py:build_dsn()`):**
```
postgresql://{user}:{password}@{host}:{port}/{db}
```
Example:
```
postgresql://aap_admin:{password}@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require
```

**With managed identity (for Container Apps):**
The Terraform module `databases` assigns the API gateway MI as Entra administrator on PostgreSQL. Connection with managed identity uses:
```
host=aap-postgres-prod.postgres.database.azure.com port=5432 dbname=aap user=69e05934-1feb-44d4-8fd2-30373f83ccec sslmode=require
```
But `psycopg` with Entra auth requires the `azure-identity` token provider pattern, not a simple DSN. The current `seed.py` uses password-based auth, which is simpler for the one-time seed operation.

### What's Needed

1. **Verify `PGVECTOR_CONNECTION_STRING` is set on `ca-api-gateway-prod`:**
   ```bash
   az containerapp show --name ca-api-gateway-prod --resource-group rg-aap-prod \
     --query "properties.template.containers[0].env[?name=='PGVECTOR_CONNECTION_STRING']"
   ```
   If not set:
   ```bash
   az containerapp update --name ca-api-gateway-prod --resource-group rg-aap-prod \
     --set-env-vars "PGVECTOR_CONNECTION_STRING=postgresql://aap_admin:{password}@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require"
   ```

2. **Seed prod runbooks (temporary firewall rule pattern):**
   ```bash
   # Get runner IP
   MY_IP=$(curl -s ifconfig.me)

   # Add temporary firewall rule
   az postgres flexible-server firewall-rule create \
     --resource-group rg-aap-prod \
     --name aap-postgres-prod \
     --rule-name temp-seed \
     --start-ip-address $MY_IP \
     --end-ip-address $MY_IP

   # Seed
   POSTGRES_DSN="postgresql://aap_admin:{password}@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require" \
   AZURE_OPENAI_ENDPOINT="https://aap-foundry-prod.openai.azure.com/" \
   python scripts/seed-runbooks/seed.py

   # Validate
   python scripts/seed-runbooks/validate.py

   # Remove firewall rule (ALWAYS, even on failure)
   az postgres flexible-server firewall-rule delete \
     --resource-group rg-aap-prod \
     --name aap-postgres-prod \
     --rule-name temp-seed --yes
   ```

3. **Verify:**
   ```bash
   curl -H "Authorization: Bearer $TOKEN" \
     "https://ca-api-gateway-prod.../api/v1/runbooks/search?q=vm+high+cpu&domain=compute"
   # Should return 200 with runbook results
   ```

---

## 8. Hardcoded Foundry Agent IDs

### Status: RESOLVED

**DEBT-002 is fully fixed.** The `_DOMAIN_AGENT_IDS` frozenset in `services/api-gateway/chat.py:26-38` is built from environment variables:

```python
_DOMAIN_AGENT_IDS: frozenset[str] = frozenset(
    v for v in (
        os.environ.get("COMPUTE_AGENT_ID"),
        os.environ.get("NETWORK_AGENT_ID"),
        os.environ.get("STORAGE_AGENT_ID"),
        os.environ.get("SECURITY_AGENT_ID"),
        os.environ.get("SRE_AGENT_ID"),
        os.environ.get("ARC_AGENT_ID"),
        os.environ.get("PATCH_AGENT_ID"),
        os.environ.get("EOL_AGENT_ID"),
    )
    if v
)
```

Zero hardcoded `asst_*` strings remain in `chat.py`. Warning logged if no agent IDs configured.

### Remaining Action

Verify that all 8 `*_AGENT_ID` env vars are set on `ca-api-gateway-prod` (not just `ca-orchestrator-prod`). The Terraform `agent-apps` module passes these vars via `terraform/envs/prod/terraform.tfvars`. Check:

```bash
az containerapp show --name ca-api-gateway-prod --resource-group rg-aap-prod \
  --query "properties.template.containers[0].env[?contains(name, 'AGENT_ID')]"
```

---

## 9. Teams Bot Registration

### Problem

**F-04 / GAP-004 / PROD-005:** Teams proactive alerting is non-functional.

### Current State (verified)

1. **Terraform module exists:** `terraform/modules/teams-bot/main.tf` — creates `azurerm_bot_service_azure_bot`, `azurerm_bot_channel_ms_teams`, Entra app + SP + password, Key Vault secrets
2. **`enable_teams_bot = true`** in `terraform/envs/prod/terraform.tfvars`
3. **Bot resource likely exists** — manually created as `aap-teams-bot-prod` (Resource ID in comments: `/subscriptions/4c727b88-.../providers/Microsoft.BotService/botServices/aap-teams-bot-prod`)
4. **Entra app registration exists:** object `670e3ba4-...`, client `d5b074fc-...`
5. **Container App `ca-teams-bot-prod` is deployed** (port 3978)
6. **Bot code is complete:** 100 tests at 92.34% coverage (Phase 6)

### What's NOT Done

1. **`TEAMS_CHANNEL_ID` is empty** on `ca-teams-bot-prod` — proactive posts are silently skipped
2. **Bot must be installed in a Teams channel** to capture `ConversationReference` (required for proactive messaging)
3. **Messaging endpoint must point to the Container App URL:** `https://ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/messages`

### How Proactive Messaging Works (from code)

From `services/teams-bot/src/services/proactive.ts`:
- `initializeProactive(adapter, appId)` — called at startup
- `setConversationReference(ref)` — called when bot is installed in a team/channel (`onInstallationUpdate` event)
- `sendProactiveCard(card)` — uses `adapter.continueConversationAsync()` with saved reference
- `hasConversationReference()` — returns false until bot is installed (503 pre-flight on notify route)

**The 30-second startup delay** in the escalation scheduler allows the bot install event to fire and capture the `ConversationReference` before attempting proactive posts.

### Steps

1. **Verify Terraform import blocks** for existing resources are uncommented in `terraform/envs/prod/imports.tf`
2. **`terraform apply`** to reconcile the bot module state
3. **Install the bot in a Teams channel:**
   - Upload Teams app manifest (at `services/teams-bot/manifest/`)
   - Install in the target team
   - Note the channel ID from the installation event or Teams admin center
4. **Set `TEAMS_CHANNEL_ID`:**
   ```bash
   az containerapp update --name ca-teams-bot-prod --resource-group rg-aap-prod \
     --set-env-vars "TEAMS_CHANNEL_ID=<channel_id>"
   ```
5. **Verify:** Trigger a synthetic alert via `POST /api/v1/incidents` and confirm an Adaptive Card appears in the Teams channel.

### Key Config (from `services/teams-bot/src/config.ts`)

Required env vars:
- `BOT_ID` (required — throws if missing)
- `BOT_PASSWORD`
- `API_GATEWAY_INTERNAL_URL` (required — internal URL to `ca-api-gateway-prod`)
- `WEB_UI_PUBLIC_URL` (required)
- `TEAMS_CHANNEL_ID` (optional but needed for proactive messaging)
- `ESCALATION_INTERVAL_MINUTES` (default 15)
- `PORT` (default 3978)

---

## 10. Agent Framework Version Pin

### Problem

**DEBT-001:** The codebase is pinned to `agent-framework==1.0.0b260107` (an old beta), not `1.0.0rc5` (latest RC).

### Current Pin Stack (from `agents/requirements-base.txt`)

```
agent-framework==1.0.0b260107
azure-ai-agentserver-core==1.0.0b15
azure-ai-agentserver-agentframework==1.0.0b15
azure-ai-projects==2.0.0b3
azure-ai-agents==1.2.0b5
```

### Why RC5 Was Avoided (from requirements-base.txt comments)

> rc5 introduced a breaking API overhaul (Agent/tool/WorkflowBuilder) that is incompatible with agentserver-agentframework b10-b15. agentserver b16+ requires agent-framework-core>=rc2 (rc5 API).

The b260107 beta is the **last version** that uses `ChatAgent` + `@ai_function` API AND is compatible with `agentserver-agentframework==1.0.0b15`.

### Breaking Changes in RC5

| Area | b260107 (current) | rc5 (target) |
|------|-------------------|--------------|
| Agent class | `ChatAgent` | `Agent` (new base class) |
| Tool decorator | `@ai_function` | `@tool` (new decorator) |
| Orchestration | Manual handoff | `WorkflowBuilder` pattern |
| Server adapter | `agentserver-agentframework b15` | `agentserver-agentframework b16+` |
| Project SDK | `azure-ai-projects 2.0.0b3` | `azure-ai-projects >=2.0.1` (GA) |

### Migration Impact

Upgrading requires changes in ALL 8+ agent files:
```
agents/orchestrator/agent.py   (ChatAgent -> Agent, @ai_function -> @tool)
agents/compute/agent.py
agents/network/agent.py
agents/storage/agent.py
agents/security/agent.py
agents/arc/agent.py
agents/sre/agent.py
agents/patch/agent.py
agents/eol/agent.py
conftest.py                     (mock module structure)
```

### Recommendation for Phase 19

**Do NOT upgrade to RC5 in Phase 19.** The scope is already large. Instead:

1. **Verify all pins are exact** (no floating versions) — **already verified, all pins are exact**
2. **Document the migration path** for a future phase
3. **Upgrade `azure-ai-projects` from `2.0.0b3` to `2.0.1` (GA)** if compatible with the b15 adapter stack — this is lower risk and gives stable Foundry SDK
4. **Pin `agentserver-agentframework` explicitly** — already pinned to `==1.0.0b15` (DEP-005 in CONCERNS.md says "no version pin" but the code shows it IS pinned)

### DEP-005 Status: RESOLVED

`agents/requirements-base.txt:19` shows `azure-ai-agentserver-agentframework==1.0.0b15` — exact pin present. The CONCERNS.md entry is stale.

---

## 11. Risk Register

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Enabling auth breaks all web UI functionality | HIGH | CRITICAL | Test in staging first; keep `API_GATEWAY_AUTH_MODE=disabled` as rollback |
| MCP tool group registration API changes (Foundry preview) | MEDIUM | HIGH | Document exact `api-version` and REST payloads; test each registration individually |
| Azure MCP Server internal ingress change breaks Foundry MCP connection | MEDIUM | HIGH | Update Foundry MCP connection URL to internal FQDN before applying ingress change |
| PostgreSQL firewall rule left open after seeding | LOW | CRITICAL | Wrap in try/finally; validate removal; use timeout |
| Teams bot ConversationReference not captured (bot not properly installed) | MEDIUM | MEDIUM | Test in staging Teams tenant; verify `hasConversationReference()` returns true |
| agent-framework b260107 beta PyPI package disappears | LOW | CRITICAL | Pre-download and cache in ACR-hosted Python package mirror or vendor locally |
| CORS lockdown breaks web UI in non-prod environments | LOW | MEDIUM | Verify `cors_allowed_origins` is set differently in dev/staging terraform.tfvars |

---

## 12. Recommended Milestone Structure

Based on the research, here's the recommended execution order:

### M1: Security Hardening (PROD-001, PROD-002) — CRITICAL

**Must do first — currently the platform has a CRITICAL external security exposure.**

| Task | Description | Type | Depends On |
|------|-------------|------|------------|
| 19-01 | Azure MCP Server: Create Terraform module, switch to internal ingress, remove `--dangerously-disable-http-incoming-auth` | Code + Operator | — |
| 19-02 | CORS lockdown: Verify `CORS_ALLOWED_ORIGINS` is applied from tfvars (not wildcard) | Operator | — |
| 19-03 | Enable Entra auth on API gateway: set `API_GATEWAY_CLIENT_ID`, `API_GATEWAY_TENANT_ID`, configure MSAL scopes in web-ui | Code + Operator | 19-01 |
| 19-04 | Web UI auth token forwarding: verify `buildUpstreamHeaders()` works with real Entra tokens | Code | 19-03 |

### M2: MCP Tool Groups (PROD-003) — CRITICAL

| Task | Description | Type | Depends On |
|------|-------------|------|------------|
| 19-05 | Register `Microsoft.Network` tool group on Foundry project | Operator | 19-01 (internal MCP URL) |
| 19-06 | Register `Microsoft.Security` tool group on Foundry project | Operator | 19-01 |
| 19-07 | Register Arc MCP Server as MCP connection on Foundry project | Operator | Arc MCP verified |
| 19-08 | Verify SRE agent cross-domain tool access (monitor + Log Analytics) | Operator | 19-05, 19-06 |
| 19-09 | Arc MCP Server: verify real image running, health endpoint 200 | Operator | — |

### M3: Runbook RAG (F-02) — HIGH

| Task | Description | Type | Depends On |
|------|-------------|------|------------|
| 19-10 | Set `PGVECTOR_CONNECTION_STRING` on `ca-api-gateway-prod` | Operator | — |
| 19-11 | Seed prod runbooks (temporary firewall rule, seed.py, validate.py) | Operator | 19-10 |

### M4: Teams Proactive Alerting (PROD-005) — HIGH

| Task | Description | Type | Depends On |
|------|-------------|------|------------|
| 19-12 | Verify Terraform teams-bot module reconciled; bot resource matches state | Operator | — |
| 19-13 | Install bot in Teams channel, capture channel ID | Operator | 19-12 |
| 19-14 | Set `TEAMS_CHANNEL_ID` on `ca-teams-bot-prod`; verify proactive card delivery | Operator | 19-13 |

### M5: CI Auth + Cleanup — MEDIUM

| Task | Description | Type | Depends On |
|------|-------------|------|------------|
| 19-15 | Set E2E GitHub Actions secrets (`E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_API_AUDIENCE`) | Operator | 19-03 |
| 19-16 | Verify agent framework dependency pins are stable (no floating versions) | Code | — |

### Parallelism

```
Week 1                              Week 2
├──────────────────────────┤├────────────────────────────┤

M1: Security (19-01..04)           M2: MCP Groups (19-05..09)
 ├─ 19-01 Azure MCP → internal     ├─ 19-05 Network MCP
 ├─ 19-02 CORS lockdown            ├─ 19-06 Security MCP
 ├─ 19-03 Enable Entra auth        ├─ 19-07 Arc MCP connection
 └─ 19-04 Web UI auth verify       ├─ 19-08 SRE verify
                                    └─ 19-09 Arc MCP verify
M3: Runbook RAG (19-10..11)
 ├─ 19-10 PGVECTOR env var         M4: Teams (19-12..14)
 └─ 19-11 Seed prod                 ├─ 19-12 TF reconcile
                                    ├─ 19-13 Install bot
M5: CI Auth (19-15..16)             └─ 19-14 Set TEAMS_CHANNEL_ID
 ├─ 19-15 E2E secrets
 └─ 19-16 Verify pins
```

- **M1 must go first** (CRITICAL security fix)
- **M2 depends on M1** (Azure MCP URL changes when switched to internal)
- **M3, M4, M5 are independent** of each other and can run in parallel with M2

### Estimated Effort

| Milestone | Code Changes | Operator Actions | Estimated Time |
|-----------|-------------|------------------|----------------|
| M1 | Terraform module (~100 LOC), Dockerfile edit, MSAL config | Apply TF, set env vars | 2-3 days |
| M2 | None | Foundry portal/REST registrations, verification queries | 1 day |
| M3 | None | Env var, firewall rule, seed, validate | 0.5 days |
| M4 | None | TF apply, Teams admin, env var | 1 day |
| M5 | None | GitHub settings, grep/verify | 0.5 days |
| **Total** | | | **5-6 days** |

---

## Summary: Key Planning Decisions Required

1. **Auth app registration strategy:** Create a dedicated API gateway app registration, or reuse the existing web-ui app registration (`505df1d3-...`) and expose API scopes on it?

2. **Azure MCP Server Terraform import:** The Container App `ca-azure-mcp-prod` was created ad-hoc. Import into Terraform state or destroy-and-recreate?

3. **Agent framework upgrade:** Defer RC5 migration to a separate phase, or attempt in Phase 19? (Recommendation: **defer**)

4. **Staging-first deployment:** Enforce staging validation of auth changes before touching prod? (Recommendation: **yes, mandatory**)

5. **MCP tool group registration automation:** Use REST API / Terraform azapi, or manual Foundry portal? (Recommendation: **REST API with scripts** for reproducibility; Terraform azapi for long-term)
