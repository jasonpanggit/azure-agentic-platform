# E2E Validation Report — 2026-04-01

> Validated: 2026-04-01 ~00:20 UTC
> Scope: Read-only. No changes made.

---

## Summary

| Component | Status | Notes |
|-----------|--------|-------|
| API Gateway — health | ✅ | `{"status":"ok","version":"1.0.0"}` |
| API Gateway — incidents | ⚠️ | Returns empty list `[]` (GET returns list, not paginated envelope; no active incidents is valid) |
| API Gateway — patch assessment | ✅ | 1 machine returned (Windows, last assessed 2026-03-27) |
| API Gateway — runbook search | ❌ | 500 Internal Server Error with valid Bearer token; auth token audience mismatch |
| API Gateway — audit | ⚠️ | Returns `[]` — empty but 200 OK |
| API Gateway — approvals | ⚠️ | Returns `[]` — empty but 200 OK |
| Chat — compute-agent | ✅ | Completed; listed VMs correctly |
| Chat — network-agent | ✅ | Completed; listed NSGs correctly |
| Chat — storage-agent | ✅ | Completed; listed storage accounts correctly |
| Chat — security-agent | ✅ | Completed; returned security recommendations |
| Chat — arc-agent | ❌ | Completed but returned auth error fetching Arc-enabled servers |
| Chat — patch-agent | ⚠️ | Completed but returned "issue fetching patch data" — no hard error, data thin |
| Foundry — orchestrator | ✅ | `AAP Orchestrator` (asst_NeBVjCA5isNrIERoGYzRpBTu) wired; 8 connected agents + 1 function |
| Foundry — domain agent MCP | ⚠️ | All 8 domain agents wired to `azure_mcp` only; arc-agent NOT wired to arc-mcp-server |
| Foundry — agent duplicates | ⚠️ | 19 total agents in project; duplicate names for all domains (stale old agents) |
| Container Apps — all apps | ✅ | All 14 apps Running (including ca-arc-mcp-server-prod) |
| Azure MCP server | ❌ | `ca-azure-mcp-prod` returns HTTP 404 on external health check — ingress issue |
| Arc MCP server | ⚠️ | `ca-arc-mcp-server-prod` — internal ingress only (expected); not wired into any agent |
| Web UI | ✅ | HTTP 200 |
| Teams bot — running | ✅ | Running (revision ca-teams-bot-prod--0000017) |
| Teams bot — BOT_PASSWORD | ❌ | `BOT_PASSWORD` is null — bot cannot authenticate |
| Teams bot — TEAMS_CHANNEL_ID | ✅ | Set: `19:VRkTF855s1bLp0XgVPTuxTbGJAYz9MqodJ6kgcoM7CU1@thread.tacv2` |
| Teams bot — APPLICATIONINSIGHTS | ⚠️ | `APPLICATIONINSIGHTS_CONNECTION_STRING` is empty |

---

## Detail

### API Gateway

**Health:**
```json
{"status":"ok","version":"1.0.0"}
```
HTTP 200. Healthy.

**`GET /api/v1/incidents?subscription=...`**
Returns `[]` (empty list). Note: response is a bare JSON array, not the `{"incidents":[...]}` envelope the validation script expected — causes a Python `AttributeError`. The route is a `POST` endpoint for ingesting incidents (`Ingest Incident` per OpenAPI); the `GET` variant returns an empty list. No active incidents is valid for a test environment.

**`GET /api/v1/patch/assessment?subscriptions=...`**
- Note: param is `subscriptions` (plural), not `subscription`
- Returns 1 Windows machine (`jumphost` in `AML-RG`), last assessed 2026-03-27
- `criticalCount`, `securityCount` are `null` (patch detail counts not populated — ARM assessment may need a fresh run)

**`GET /api/v1/runbooks/search?query=cpu&limit=3`**
- HTTP **500 Internal Server Error** even with valid `Authorization: Bearer <ai.azure.com token>`
- OpenAPI spec requires `query` param (not `q`) — confirmed correct in second attempt
- The 500 persists with correct param name and token — likely a backend DB/pgvector connection issue
- The endpoint requires auth (`HTTPBearer` in OpenAPI security); the token audience is `https://ai.azure.com/` which may not match the gateway's expected audience

**`GET /api/v1/audit` and `/api/v1/approvals`**
Both return `[]` with HTTP 200 — empty but operational.

---

### Chat Tests

All 6 runs **completed** within ~60–90 seconds. The polling script reported "timeout" because the result envelope uses `run_status` not `status` — the runs had already finished.

| Agent | Message | run_status | Reply Snippet |
|-------|---------|-----------|---------------|
| compute-agent | "list my virtual machines" | **completed** | "Here is the list of your Virtual Machines... testvm1 (eastus, Standard_D2s_v3, Windows)..." |
| network-agent | "show network security groups" | **completed** | "Here are the Network Security Groups... nsg-snet-foundry-prod (East US 2)..." |
| storage-agent | "check storage accounts" | **completed** | "Here are the storage accounts... agenticworkflowstore (southeastasia, Standard_LRS, HTTPS Only)..." |
| security-agent | "show security recommendations" | **completed** | "Retrieved security recommendations... Storage Accounts: restrict access with firewall/VNet..." |
| arc-agent | "show arc-enabled servers" | **completed** ⚠️ | "There was an issue retrieving Arc-enabled servers due to an **authentication error**..." |
| patch-agent | "show patch compliance" | **completed** ⚠️ | "Issue fetching patch compliance data. Could you provide more details?" |

**arc-agent observation:** Runs successfully and routes correctly, but the underlying MCP call to list Arc resources fails with an auth error. The arc-agent is wired to `azure_mcp` (Azure MCP server), but Arc resources (`Microsoft.HybridCompute/machines`) are not covered by the Azure MCP server — this is the known "Arc MCP gap". The `ca-arc-mcp-server-prod` custom Arc MCP server is running but **not wired into any Foundry agent**.

**patch-agent observation:** Routes correctly but returns a soft "I need more info" deflection rather than data. The `azure_mcp` server may not have a dedicated patch compliance tool (Update Manager / Azure Update Manager is not listed in confirmed Azure MCP tools).

---

### Foundry Agent Wiring

**Orchestrator** (`asst_NeBVjCA5isNrIERoGYzRpBTu` — `AAP Orchestrator`):
- Model: `gpt-4o`
- Tools: 1 function + 8 connected agents
- Connected agents: compute, network, storage, security, sre, arc, patch, eol ✅

**Domain agent MCP configuration** (all 8 agents wired to orchestrator):

| Agent | MCP server_label | MCP server_url | allowed_tools |
|-------|-----------------|----------------|---------------|
| compute-agent | `azure_mcp` | `https://ca-azure-mcp-prod...` | None (all) |
| network-agent | `azure_mcp` | `https://ca-azure-mcp-prod...` | None (all) |
| storage-agent | `azure_mcp` | `https://ca-azure-mcp-prod...` | None (all) |
| security-agent | `azure_mcp` | `https://ca-azure-mcp-prod...` | None (all) |
| arc-agent | `azure_mcp` | `https://ca-azure-mcp-prod...` | None (all) |
| patch-agent | `azure_mcp` | `https://ca-azure-mcp-prod...` | None (all) |
| eol-agent | `azure_mcp` | `https://ca-azure-mcp-prod...` | None (all) |
| sre-agent | `azure_mcp` | `https://ca-azure-mcp-prod...` | None (all) |

**Issue:** arc-agent should also be connected to `ca-arc-mcp-server-prod` (Arc MCP custom server) to handle `Microsoft.HybridCompute` and `Microsoft.Kubernetes/connectedClusters` resources. Currently `ca-arc-mcp-server-prod` is running but wired to nothing.

**Duplicate agents:** Foundry project contains 19 agents total — 11 are current (with MCP tools), 9 appear to be stale predecessors (no tools or legacy function tools). Not breaking, but creates namespace clutter.

---

### Container Apps

All 14 Container Apps are **Running**:

| App | Status | Revision |
|-----|--------|----------|
| ca-api-gateway-prod | Running | --0000060 |
| ca-web-ui-prod | Running | --0000050 |
| ca-orchestrator-prod | Running | --0000022 |
| ca-compute-prod | Running | --0000014 |
| ca-network-prod | Running | --0000014 |
| ca-storage-prod | Running | --0000014 |
| ca-security-prod | Running | --0000014 |
| ca-sre-prod | Running | --0000014 |
| ca-arc-prod | Running | --0000015 |
| ca-patch-prod | Running | --0000002 |
| ca-eol-prod | Running | --0000003 |
| ca-teams-bot-prod | Running | --0000017 |
| ca-azure-mcp-prod | Running | --0000037 |
| ca-arc-mcp-server-prod | Running | --kas7ou5 |

**Azure MCP server (ca-azure-mcp-prod):** Container App is Running but an external HTTP request to its FQDN returns **HTTP 404** from the Container Apps platform ("Container App is stopped or does not exist"). This means the app has **external ingress disabled or is misconfigured** — the Foundry agents call it by internal URL which may be correct if it's internal-only ingress, but the 404 response from the external FQDN is unexpected for a Running app. The Foundry Hosted Agent calling it externally likely hits the same 404.

**Arc MCP server (ca-arc-mcp-server-prod):** Confirmed **internal ingress only** (FQDN: `ca-arc-mcp-server-prod.internal.wittypebble-0144adc3.eastus2.azurecontainerapps.io`). This is correct for a sidecar-style MCP server, but Foundry agents reference it by external URL — it needs to be wired via an **internal** URL or the Foundry connection must use internal FQDN.

---

### Web UI

`GET https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` → **HTTP 200** ✅

---

### Teams Bot

| Env Var | Value | Status |
|---------|-------|--------|
| `BOT_ID` | `d5b074fc-7ca6-4354-8938-046e034d80da` | ✅ Set |
| `BOT_TENANT_ID` | `abbdca26-d233-4a1e-9d8c-c4eebbc16e50` | ✅ Set |
| `BOT_PASSWORD` | *(null/empty)* | ❌ Missing — bot cannot authenticate to Teams |
| `TEAMS_CHANNEL_ID` | `19:VRkTF855s1bLp0XgVPTuxTbGJAYz9MqodJ6kgcoM7CU1@thread.tacv2` | ✅ Set |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | *(empty)* | ⚠️ No telemetry |

---

## Issues Found

1. **[CRITICAL] Teams bot `BOT_PASSWORD` is null** — The Teams bot container is Running but `BOT_PASSWORD` is not set. The bot cannot authenticate with Microsoft Teams (OAuth client credentials flow will fail). Any Teams alert delivery or approval workflow will be broken.

2. **[HIGH] arc-agent wired only to azure_mcp, not arc-mcp-server** — `ca-arc-mcp-server-prod` is running but no Foundry agent has it configured as an MCP tool. The arc-agent returns an authentication error when asked about Arc-enabled servers because Azure MCP does not cover `Microsoft.HybridCompute` resources. The Arc MCP server needs to be added as a second MCP tool on `arc-agent` in Foundry.

3. **[HIGH] Azure MCP server (ca-azure-mcp-prod) returns HTTP 404 externally** — The Container App is Running but external HTTP requests receive a 404 "stopped or does not exist" response from the platform. This suggests ingress is misconfigured (possibly disabled or the wrong revision is receiving traffic). Foundry agents using the external URL `https://ca-azure-mcp-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` may be failing silently — yet chat tests 1-4 completed, suggesting the Foundry Hosted Agent runtime may use an internal channel. Needs investigation.

4. **[HIGH] `/api/v1/runbooks/search` returns 500** — The endpoint crashes with a 500 on valid authenticated requests. Likely a pgvector/PostgreSQL connection failure or missing embedding dimension in the DB. The endpoint is auth-gated (`HTTPBearer`) and the `ai.azure.com` audience token may not match the gateway's expected audience — but the 500 suggests it got past auth and failed on the DB call.

5. **[MEDIUM] patch-agent cannot retrieve patch compliance data** — Chat completes but returns a soft deflection. Azure MCP does not have a dedicated Update Manager / patch compliance tool. The patch-agent's tool coverage needs review — it may need a custom function or the Arc MCP server to query Update Manager data.

6. **[MEDIUM] Patch assessment `criticalCount` / `securityCount` are null** — The single machine returned (`jumphost`) has null patch counts. The ARM Update Manager assessment may need to be triggered manually or the data hasn't been refreshed since 2026-03-27.

7. **[LOW] 19 Foundry agents with duplicate names** — The project has 9 stale/predecessor agents (no tools or old function-based tools). While not breaking, this pollutes the agent list and could cause confusion if an old agent ID is referenced somewhere. Recommend cleanup.

8. **[LOW] Chat polling key mismatch** — The `/api/v1/chat/{thread_id}/result` endpoint returns `run_status` (not `status`) and `reply` (not `messages[]`). Any client code that polls for `status` key will always see `None` and never detect completion. The Web UI chat panel should be verified to use the correct field name.

9. **[LOW] Teams bot has no Application Insights telemetry** — `APPLICATIONINSIGHTS_CONNECTION_STRING` is empty. Bot errors and latency will not be observable.

10. **[INFO] Incidents endpoint is POST-only for ingestion; GET returns bare array** — The `GET /api/v1/incidents` route returns an empty list (not an error), but the API shape (`[]` vs `{"incidents":[]}`) differs from what the validation script expected. This is a documentation/client alignment issue, not a bug.
