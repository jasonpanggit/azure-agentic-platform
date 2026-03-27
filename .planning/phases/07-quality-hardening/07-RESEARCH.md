# Phase 7: Quality & Hardening — Research

> Research completed: 2026-03-27
> Objective: "What do I need to know to PLAN this phase well?"

---

## Table of Contents

1. [Phase Scope Summary](#1-phase-scope-summary)
2. [Requirement-by-Requirement Analysis](#2-requirement-by-requirement-analysis)
3. [E2E Test Infrastructure (E2E-001 through E2E-005)](#3-e2e-test-infrastructure)
4. [Remediation Audit Trail (REMEDI-007)](#4-remediation-audit-trail-remedi-007)
5. [Audit Report Export (AUDIT-006)](#5-audit-report-export-audit-006)
6. [Observability (D-05 through D-07)](#6-observability)
7. [Runbook Library Seed (D-08 through D-10)](#7-runbook-library-seed)
8. [Terraform Prod Apply (D-11 through D-14)](#8-terraform-prod-apply)
9. [Security Review (D-15)](#9-security-review)
10. [Existing Codebase Analysis](#10-existing-codebase-analysis)
11. [Risks and Mitigations](#11-risks-and-mitigations)
12. [Dependency Map](#12-dependency-map)
13. [Recommended Plan Breakdown](#13-recommended-plan-breakdown)
14. [Open Questions](#14-open-questions)

---

## 1. Phase Scope Summary

Phase 7 has **5 workstreams** that are largely independent:

| Workstream | Requirements | UI Changes | IaC Changes |
|---|---|---|---|
| E2E Test Suite | E2E-001, E2E-002, E2E-003, E2E-004, E2E-005 | No | No |
| Remediation Audit Trail | REMEDI-007 | No | No |
| Audit Report Export | AUDIT-006 | Yes (button on AuditLogViewer) | No |
| Observability | D-05, D-06, D-07 | Yes (Observability tab) | No |
| Runbook Library Seed | D-08, D-09, D-10 | No | No |
| Terraform Prod | D-11, D-12, D-13, D-14 | No | Yes |
| Security Review | D-15 | No | No |

**Key constraint:** E2E tests must run against **real deployed endpoints** (CONTEXT.md D-01). This is the hardest part of Phase 7 — every other workstream is either code, config, or content.

---

## 2. Requirement-by-Requirement Analysis

### E2E-001: Playwright Suite Against Live Container Apps

**What exists:**
- 5 existing E2E specs in `e2e/`: `sc1.spec.ts`, `sc2.spec.ts`, `sc5.spec.ts`, `sc6.spec.ts`, `arc-mcp-server.spec.ts`
- `sc1`, `sc2`, `sc5`, `sc6` all use `page.route()` mocks — they never hit real endpoints
- `arc-mcp-server.spec.ts` already hits real endpoints via `request.post()` — this is the correct pattern for Phase 7
- `playwright.config.ts` already supports `BASE_URL` env var; `webServer` is `undefined` in CI mode

**What needs to happen:**
1. Refactor `sc1`–`sc6` to remove `page.route()` mocks and use `BASE_URL` (real Container Apps FQDN)
2. Add 5 new E2E spec files: `e2e-incident-flow.spec.ts`, `e2e-hitl-approval.spec.ts`, `e2e-rbac.spec.ts`, `e2e-sse-reconnect.spec.ts`, `e2e-audit-export.spec.ts`
3. New CI workflow (`phase7-e2e.yml`) that deploys E2E environment, runs tests, tears down
4. CI gate: `required_status_checks` blocks merge if E2E fails
5. 15-minute timeout on the full suite

**Technical approach:**
- E2E environment is a **dedicated staging-like deployment** (not prod, not dev) per CONTEXT.md D-01
- Authentication: service principal client_credentials flow (D-02) — `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_TENANT_ID` from GitHub Secrets
- Token acquisition via MSAL `ConfidentialClientApplication` in a Playwright global setup fixture
- Test data isolation: dedicated Cosmos DB containers `incidents-e2e`, `approvals-e2e` (D-03) — created in `globalSetup`, wiped in `globalTeardown`

**Complexity:** HIGH — requires a deployed E2E environment with real Azure resources

### E2E-002: Full Incident Flow E2E

**What exists:**
- `POST /api/v1/incidents` endpoint in `api-gateway/main.py` — accepts incident payload, dispatches to Foundry
- Detection plane KQL pipeline (`services/detection-plane/`) — processes alerts through Eventhouse
- SSE stream at `/api/stream` — delivers `event:token` and `event:trace`

**What needs to happen:**
1. Inject synthetic alert into Event Hub (or directly into Eventhouse `RawAlerts`)
2. Wait for KQL enrichment → `DetectionResults` → Activator fires
3. Verify `POST /api/v1/incidents` was called (Cosmos DB incident record appears)
4. Verify Orchestrator dispatched to domain agent
5. Open SSE stream and verify `event:token` events arrive
6. Use Playwright to verify UI renders the triage response

**Technical approach:**
- Inject directly via Event Hub SDK (`azure-eventhub`) with a synthetic alert payload
- Poll Cosmos DB for the incident record (max 60s per Phase 4 SC-2)
- Open SSE stream via Playwright `page.goto()` or `request.fetch()` for the stream endpoint
- Assert DOM elements in the chat panel for rendered triage text

**Complexity:** HIGH — full pipeline end-to-end, multiple async hops, 60+ second timeout

### E2E-003: HITL Approval Flow E2E

**What exists:**
- Approval endpoints: `POST /api/v1/approvals/{id}/approve`, `POST /api/v1/approvals/{id}/reject`
- Teams notify: `POST /teams/internal/notify` on the teams-bot
- Graph API for message verification (per CONTEXT.md D-04)

**What needs to happen per D-04:**
1. Inject high-risk approval record into Cosmos DB (directly or via api-gateway)
2. Trigger `POST /teams/internal/notify` to simulate the card request
3. Verify card posted to Teams via Graph API `GET /v1.0/teams/{teamId}/channels/{channelId}/messages`
4. Approve via `POST /api/v1/approvals/{id}/approve` (webhook simulation)
5. Verify Cosmos DB record updated to `status: approved`
6. Verify outcome card posted to Teams via Graph API

**Technical approach:**
- Graph API requires `ChannelMessage.Read.All` application permission on the E2E service principal
- Teams channel `teamId` and `channelId` are injected as env vars (`E2E_TEAMS_TEAM_ID`, `E2E_TEAMS_CHANNEL_ID`)
- No full bot round-trip in CI (deferred per CONTEXT.md)
- Message verification: filter Graph API results by `attachments[].contentType == "application/vnd.microsoft.card.adaptive"`

**Complexity:** MEDIUM-HIGH — Graph API auth + async verification

### E2E-004: Cross-Subscription RBAC E2E

**What exists:**
- RBAC module in `terraform/modules/rbac/` — assigns per-domain roles
- `agent-apps` module creates SystemAssigned managed identities per agent
- Prod `main.tf` passes separate `compute_subscription_id`, `network_subscription_id`, `storage_subscription_id`

**What needs to happen:**
1. **Positive path:** Each domain agent calls its target subscription's ARM API and succeeds
2. **Negative path:** Compute Agent attempts a Storage API call on the storage subscription and receives `403 Forbidden`

**Technical approach:**
- Tests use `request.get()`/`request.post()` to the api-gateway, which internally delegates to agents
- Positive: inject a compute incident → agent calls compute subscription ARM API → triage succeeds
- Negative: need a test endpoint or agent tooling that attempts an out-of-scope call
- Alternative: directly call ARM API with each agent's managed identity token (obtained via the E2E environment's MI)
- The negative test may require a custom test endpoint on the api-gateway: `POST /api/v1/test/rbac` that attempts a cross-domain call and returns the result

**Complexity:** MEDIUM — straightforward ARM calls, but negative test needs careful design

### E2E-005: SSE Reconnect E2E

**What exists:**
- `sc2.spec.ts` tests SSE reconnect but with **mocked routes** — no real SSE server
- SSE endpoint at `/api/stream` with 20-second heartbeat (UI-008)
- Client reconnects with `Last-Event-ID` cursor (TRIAGE-007)

**What needs to happen:**
1. Open a real SSE connection to the deployed Container App
2. Receive some events with monotonic sequence IDs
3. Simulate a network drop (abort the connection)
4. Reconnect with `Last-Event-ID` header
5. Verify all missed events delivered in order, no duplicates, no gaps

**Technical approach:**
- Use Playwright CDP (Chrome DevTools Protocol) to emulate network offline/online
- `page.context().newCDPSession(page)` → `Network.emulateNetworkConditions({ offline: true })` → wait → restore
- Alternative: use `route.abort('connectionfailed')` on the first SSE request, let EventSource auto-reconnect
- For real deployed environment: better to use the SSE client directly (`fetch()` with `ReadableStream`) and manually set `Last-Event-ID` on reconnect request
- Assert sequence continuity: `seq[i+1] === seq[i] + 1` across the boundary
- Assert `new Set(allSeqs).size === allSeqs.length` (no duplicates)

**Complexity:** MEDIUM — SSE reconnect is well-understood; CDP approach is reliable

### REMEDI-007: OneLake Audit Trail

**What exists:**
- `AUDIT-001` already exports OpenTelemetry spans to Application Insights
- `AUDIT-002` stores approval records in Cosmos DB + OneLake
- OneLake lakehouse provisioned via Terraform `fabric` module
- No existing code writes directly to OneLake for remediation events

**What needs to happen:**
1. Every executed remediation action writes to OneLake with schema: `agentId`, `toolName`, `toolParameters`, `approvedBy`, `outcome`, `durationMs`
2. Every rejected proposal also writes to OneLake
3. Write path: `azure-storage-file-datalake` SDK → OneLake endpoint (`https://onelake.dfs.fabric.microsoft.com`)

**Technical approach:**
- Add a `remediation_logger.py` module in `services/api-gateway/` (or `agents/shared/`)
- After approval decision is processed (both approve and reject), call `log_remediation_event()` to write JSON to OneLake
- OneLake path: `<workspace>/<lakehouse>.Lakehouse/Files/remediation_audit/year=YYYY/month=MM/day=DD/{event_id}.json`
- Date-partitioned directory structure for query efficiency
- Authentication: `DefaultAzureCredential` (same as all other services)
- Schema matches the requirement exactly:
  ```json
  {
    "timestamp": "ISO8601",
    "agentId": "agent-compute",
    "toolName": "restart_vm",
    "toolParameters": { ... },
    "approvedBy": "user@contoso.com",
    "outcome": "success|failure|rejected|expired",
    "durationMs": 1234,
    "correlationId": "...",
    "threadId": "...",
    "approvalId": "..."
  }
  ```
- Dependencies: `azure-storage-file-datalake>=12.0.0`, `azure-identity` (already present)

**Complexity:** LOW — straightforward ADLS Gen2 write via OneLake endpoint

### AUDIT-006: Remediation Activity Report Export

**What exists:**
- `AuditLogViewer` component in `services/web-ui/components/AuditLogViewer.tsx` — DataGrid showing agent actions
- `GET /api/v1/audit` endpoint in api-gateway — queries Application Insights via KQL
- No export functionality exists yet

**What needs to happen:**
1. Add "Export Report" button to the AuditLogViewer
2. Export covers a configurable time period (30-day default)
3. Output: structured JSON or CSV document
4. Every `REMEDI-*` event includes `agentId`, `toolName`, `approvedBy`, `outcome`
5. Covers SOC 2 audit requirements

**Technical approach:**
- Add a new api-gateway endpoint: `GET /api/v1/audit/export?from_time=...&to_time=...&format=json`
- This endpoint queries both Application Insights (for agent tool calls) and OneLake (for REMEDI-007 records)
- Returns a downloadable JSON document with all remediation events
- Web UI: add an "Export" button to the AuditLogViewer toolbar that triggers a file download
- Format: JSON Lines (`.jsonl`) or structured JSON array — SOC 2 auditors prefer structured formats with clear field definitions

**Complexity:** LOW-MEDIUM — new endpoint + UI button + KQL query for remediation events

---

## 3. E2E Test Infrastructure

### CI Architecture for E2E Against Real Endpoints

```
GitHub Actions Workflow (phase7-e2e.yml)
│
├── Job 1: Deploy E2E Environment
│   ├── terraform apply terraform/envs/e2e (dedicated E2E tfvars)
│   ├── Build + push all container images to ACR
│   ├── Deploy Container Apps with E2E image tags
│   └── Output: E2E_BASE_URL, E2E_API_URL
│
├── Job 2: Seed Test Data
│   ├── Create incidents-e2e, approvals-e2e Cosmos containers
│   ├── Seed runbooks into PostgreSQL
│   └── Inject synthetic test data
│
├── Job 3: Run Playwright E2E Tests
│   ├── Acquire service principal token (MSAL)
│   ├── npx playwright test --project=chromium
│   └── Upload report artifacts
│
└── Job 4: Teardown (always)
    ├── Wipe Cosmos E2E containers
    └── (Optional: destroy E2E Terraform — or keep for faster re-runs)
```

**Decision: Dedicated E2E Environment vs. Ephemeral**
- Per CONTEXT.md D-01, E2E runs against a "real deployed environment"
- Ephemeral env (create/destroy per run) is safest for isolation but adds 10-15 min provisioning time
- Alternative: persistent staging-like E2E env with test data isolation via dedicated Cosmos containers
- Recommendation: **Use the existing staging environment** with E2E-specific Cosmos containers for speed. Full Terraform E2E env can be added later if staging contamination is a concern.

### Playwright Global Setup/Teardown Pattern

```typescript
// e2e/global-setup.ts
import { FullConfig } from '@playwright/test';
import { ConfidentialClientApplication } from '@azure/msal-node';
import { CosmosClient } from '@azure/cosmos';

async function globalSetup(config: FullConfig) {
  // 1. Acquire bearer token via MSAL client credentials
  const cca = new ConfidentialClientApplication({
    auth: {
      clientId: process.env.E2E_CLIENT_ID!,
      clientSecret: process.env.E2E_CLIENT_SECRET!,
      authority: `https://login.microsoftonline.com/${process.env.E2E_TENANT_ID}`,
    },
  });
  const token = await cca.acquireTokenByClientCredential({
    scopes: [`api://${process.env.E2E_API_AUDIENCE}/.default`],
  });
  process.env.E2E_BEARER_TOKEN = token!.accessToken;

  // 2. Create E2E Cosmos containers
  const cosmos = new CosmosClient({
    endpoint: process.env.E2E_COSMOS_ENDPOINT!,
    aadCredentials: { /* ... */ },
  });
  const db = cosmos.database(process.env.E2E_COSMOS_DB!);
  await db.containers.createIfNotExists({ id: 'incidents-e2e', partitionKey: '/domain' });
  await db.containers.createIfNotExists({ id: 'approvals-e2e', partitionKey: '/thread_id' });
}
```

### E2E Environment Variables (GitHub Secrets)

| Variable | Purpose |
|---|---|
| `E2E_CLIENT_ID` | Service principal for E2E auth |
| `E2E_CLIENT_SECRET` | Service principal secret |
| `E2E_TENANT_ID` | Entra tenant |
| `E2E_API_AUDIENCE` | API gateway app registration audience |
| `E2E_BASE_URL` | Web UI Container App FQDN |
| `E2E_API_URL` | API gateway Container App FQDN |
| `E2E_COSMOS_ENDPOINT` | Cosmos DB endpoint for E2E env |
| `E2E_COSMOS_DB` | Database name |
| `E2E_TEAMS_TEAM_ID` | Teams team ID for HITL E2E |
| `E2E_TEAMS_CHANNEL_ID` | Teams channel ID for HITL E2E |
| `E2E_GRAPH_CLIENT_ID` | Graph API service principal (for message verification) |
| `E2E_GRAPH_CLIENT_SECRET` | Graph API service principal secret |

---

## 4. Remediation Audit Trail (REMEDI-007)

### OneLake Write Pattern

```python
from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient
import json
from datetime import datetime, timezone

ONELAKE_ENDPOINT = "https://onelake.dfs.fabric.microsoft.com"

async def log_remediation_event(event: dict) -> None:
    """Write a remediation event to OneLake lakehouse."""
    credential = DefaultAzureCredential()
    service = DataLakeServiceClient(ONELAKE_ENDPOINT, credential)
    fs = service.get_file_system_client(WORKSPACE_NAME)

    now = datetime.now(timezone.utc)
    dir_path = f"{LAKEHOUSE_NAME}.Lakehouse/Files/remediation_audit/year={now.year}/month={now.month:02d}/day={now.day:02d}"
    dir_client = fs.get_directory_client(dir_path)
    dir_client.create_directory()

    file_name = f"{event['approvalId']}_{now.strftime('%H%M%S')}.json"
    file_client = dir_client.create_file(file_name)
    data = json.dumps(event, default=str).encode('utf-8')
    file_client.append_data(data, offset=0, length=len(data))
    file_client.flush_data(len(data))
```

### Integration Point

The write happens in `services/api-gateway/approvals.py` in the `process_approval_decision()` function — after the Cosmos DB record is updated and before the thread is resumed:

1. On **approve**: log with `outcome: "pending_execution"` (actual outcome updated after execution completes)
2. On **reject**: log with `outcome: "rejected"`
3. On **expire**: log with `outcome: "expired"`
4. After **execution completes**: update log entry or write a completion event with `outcome: "success"` or `outcome: "failure"` and `durationMs`

### Required Schema Fields

| Field | Type | Source |
|---|---|---|
| `timestamp` | ISO 8601 string | `datetime.now(timezone.utc)` |
| `agentId` | string | From approval record `proposal.agent_id` |
| `toolName` | string | From approval record `proposal.tool_name` |
| `toolParameters` | object | From approval record `proposal.tool_parameters` |
| `approvedBy` | string | From `decided_by` |
| `outcome` | enum | "success", "failure", "rejected", "expired" |
| `durationMs` | number | Execution duration (0 for rejected/expired) |
| `correlationId` | string | From request correlation ID |
| `threadId` | string | Foundry thread ID |
| `approvalId` | string | Cosmos approval record ID |

### New Dependencies

- `azure-storage-file-datalake>=12.0.0` — add to `services/api-gateway/requirements.txt`

---

## 5. Audit Report Export (AUDIT-006)

### New API Endpoint

```
GET /api/v1/audit/export
  ?from_time=2026-02-27T00:00:00Z
  &to_time=2026-03-27T23:59:59Z
  &format=json  (default: json)
```

**Response:** Streamed JSON file download with `Content-Disposition: attachment; filename="remediation-report-{from}-{to}.json"`

### Data Sources for the Report

1. **Application Insights** (via KQL): All agent tool calls with `REMEDI-*` event correlation
2. **OneLake** (via ADLS Gen2 read): All REMEDI-007 records in the time range
3. **Cosmos DB**: Approval records for approval chain data

The report combines these into a single document:

```json
{
  "report_metadata": {
    "generated_at": "2026-03-27T14:00:00Z",
    "period": { "from": "...", "to": "..." },
    "total_events": 42
  },
  "remediation_events": [
    {
      "timestamp": "...",
      "agentId": "agent-compute",
      "toolName": "restart_vm",
      "toolParameters": { "vm_name": "vm-prod-01" },
      "approvedBy": "ops@contoso.com",
      "outcome": "success",
      "durationMs": 12340,
      "approval_chain": {
        "proposed_at": "...",
        "decided_at": "...",
        "decided_by": "ops@contoso.com",
        "status": "approved"
      }
    }
  ]
}
```

### UI Changes

In `AuditLogViewer.tsx`:
- Add an "Export Report" `Button` to the toolbar (next to the agent filter dropdown)
- Add a date range picker (or use existing `from_time`/`to_time` if filter state exposes them)
- On click: `fetch('/api/proxy/audit/export?...')` → trigger browser download
- Button variant: `appearance="subtle"` with `DocumentTextRegular` icon

---

## 6. Observability

### 6.1 OpenTelemetry Auto-Instrumentation (D-05)

#### Python Services (api-gateway, agents, arc-mcp-server)

**Package:** `azure-monitor-opentelemetry`

```python
# At service startup (before FastAPI app creation)
from azure.monitor.opentelemetry import configure_azure_monitor

configure_azure_monitor(
    connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
)
```

This auto-instruments:
- FastAPI HTTP requests (inbound)
- `httpx`/`requests` outbound calls
- `azure-sdk` calls (Cosmos DB, Foundry, etc.)
- PostgreSQL queries (via `psycopg`/`asyncpg` instrumentation)

**New dependency:** `azure-monitor-opentelemetry>=1.0.0` in each Python service's requirements

#### TypeScript Services (teams-bot, web-ui API routes)

**Package:** `@azure/monitor-opentelemetry` + `@opentelemetry/auto-instrumentations-node`

```typescript
// instrumentation.ts (loaded via --require or NODE_OPTIONS)
import { useAzureMonitor } from "@azure/monitor-opentelemetry";

useAzureMonitor({
  azureMonitorExporterOptions: {
    connectionString: process.env.APPLICATIONINSIGHTS_CONNECTION_STRING,
  },
});
```

For Express (teams-bot): auto-instruments HTTP, Express middleware, outbound fetch.

**New dependency in teams-bot:** `@azure/monitor-opentelemetry`, `@opentelemetry/auto-instrumentations-node`

#### Correlation (D-07)

The api-gateway already injects `X-Correlation-ID` via middleware (`main.py` line 64-73). This header is propagated downstream. Application Insights uses W3C `traceparent` for cross-service correlation. The OTel auto-instrumentation picks up both headers automatically — no additional code needed.

### 6.2 Observability Tab (D-06) — Per UI-SPEC

The 07-UI-SPEC.md fully specifies the Observability tab:

- **New route:** `services/web-ui/app/observability/page.tsx` (or tab content in DashboardPanel)
- **New API route:** `services/web-ui/app/api/observability/route.ts`
- **Components:** `ObservabilityTab`, `MetricCard`, `AgentLatencyCard`, `PipelineLagCard`, `ApprovalQueueCard`, `ActiveErrorsCard`, `TimeRangeSelector`
- **Data source:** Azure Monitor Query API (Application Insights) + Cosmos DB (approval queue)
- **Polling:** 30-second interval
- **No new third-party packages** — DataGrid for tabular data, Text for scalar metrics

#### API Route Implementation

```typescript
// app/api/observability/route.ts
import { DefaultAzureCredential } from "@azure/identity";
import { LogsQueryClient } from "@azure/monitor-query";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const timeRange = searchParams.get("timeRange") || "1h";

  const credential = new DefaultAzureCredential();
  const logsClient = new LogsQueryClient(credential);

  // Query agent latency
  const latencyResult = await logsClient.queryWorkspace(
    WORKSPACE_ID,
    `AppDependencies | where ... | summarize P50=percentile(DurationMs, 50), P95=percentile(DurationMs, 95) by AppRoleName`,
    { duration: timeRange }
  );

  // ... similar for pipeline lag, errors
  // Query Cosmos for approval queue depth
}
```

**New dependencies for web-ui:**
- `@azure/identity` — already used by MSAL
- `@azure/monitor-query` — new, for Log Analytics KQL queries
- `@azure/cosmos` — new, for approval queue depth server-side query

### 6.3 DashboardPanel Tab Addition

Current tabs in `DashboardPanel.tsx` (line 82-87): `alerts`, `audit`, `topology`, `resources`

Phase 7 adds `observability` as the 5th tab:
- Import `ObservabilityTab` component
- Add to `DashboardTab` union type
- Add `<Tab value="observability">Observability</Tab>` after Resources
- Render `<ObservabilityTab subscriptions={subscriptions} />` in the tab content area

---

## 7. Runbook Library Seed

### 7.1 Runbook Content (D-08)

**~60 synthetic runbooks** (~10 per domain):

| Domain | Count | Example Titles |
|---|---|---|
| Compute | 10 | "VM High CPU Investigation", "VM Disk Full Remediation", "VMSS Scaling Failure Triage" |
| Network | 10 | "NSG Rule Conflict Resolution", "VPN Gateway Connectivity Loss", "Load Balancer Health Probe Failure" |
| Storage | 10 | "Blob Storage Throttling Investigation", "Storage Account Access Key Rotation", "Disk Snapshot Failure Recovery" |
| Security | 10 | "Unauthorized Access Alert Triage", "Key Vault Access Policy Audit", "Service Principal Credential Expiry" |
| Arc | 10 | "Arc Server Disconnected Investigation", "Arc Extension Install Failure", "Arc K8s Flux Reconciliation Failure" |
| SRE | 10 | "Multi-Region Failover Procedure", "Cost Anomaly Investigation", "Resource Tag Compliance Remediation" |

### 7.2 Runbook Markdown Schema

```yaml
---
title: "VM High CPU Investigation"
domain: compute
version: "1.0"
tags: ["cpu", "performance", "vm", "monitoring"]
---

## Symptoms
Sustained CPU utilization above 90% on an Azure Virtual Machine...

## Root Causes
1. Runaway process consuming excessive CPU...
2. Under-provisioned VM SKU for workload...

## Diagnostic Steps
1. Query Azure Monitor metrics for CPU percentage over the last hour
2. Check VM activity log for recent scaling events...
3. Query Log Analytics for top processes by CPU...

## Remediation Commands
```bash
# Restart the VM
az vm restart --resource-group {rg} --name {vm_name}
```

## Rollback Procedure
If restart causes service disruption, restore from the latest VM snapshot...
```

### 7.3 Seed Script (D-09)

**Location:** `scripts/seed-runbooks/seed.py`

**Dependencies:**
- `openai` (for Azure OpenAI embeddings)
- `psycopg[binary]` (PostgreSQL connection)
- `pgvector` (vector operations)
- `pyyaml` (frontmatter parsing)

**Behavior:**
1. Read all `.md` files from `scripts/seed-runbooks/runbooks/`
2. Parse YAML frontmatter for `title`, `domain`, `version`, `tags`
3. Call Azure OpenAI `text-embedding-3-small` to generate 1536-dim vector
4. `INSERT ... ON CONFLICT (title) DO UPDATE SET embedding = ..., version = ..., content = ...` (idempotent)
5. After insertion, validate: for each runbook, run a test query and assert cosine similarity > 0.75 (D-10)

**CI integration:**
- Runs in the staging Terraform apply workflow (after `CREATE EXTENSION IF NOT EXISTS vector`)
- Uses the temporary PostgreSQL firewall rule pattern already established in `terraform-apply.yml`
- **Never auto-runs against prod** — prod seed is a documented manual step

### 7.4 PostgreSQL Table Schema

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

CREATE INDEX IF NOT EXISTS idx_runbooks_embedding ON runbooks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
CREATE INDEX IF NOT EXISTS idx_runbooks_domain ON runbooks (domain);
```

This table is already assumed by `services/api-gateway/runbook_rag.py` — the seed script just populates it.

---

## 8. Terraform Prod Apply

### 8.1 Current State

`terraform/envs/prod/main.tf` already has:
- All Phase 1-4 modules: networking, monitoring, foundry, databases, compute-env, keyvault, private-endpoints, agent-apps, rbac, eventhub, fabric, activity-log
- Fabric service principal for detection plane

**Missing for Phase 7:**
1. Teams-bot Container App (D-14) — not in `agent-apps` module yet
2. Web-UI Container App — need to verify it's in `agent-apps` or separate
3. All prod tfvars values must be populated

### 8.2 Teams-Bot Container App Addition (D-14)

The `agent-apps` module (`terraform/modules/agent-apps/main.tf`) currently defines:
- 7 agent Container Apps (orchestrator, compute, network, storage, security, arc, sre)
- 1 api-gateway Container App

Need to add:
- `teams-bot` Container App: Express/Node.js, port 3978 (Bot Framework default), external ingress (for Bot Framework Connector webhook)
- `web-ui` Container App: Next.js, port 3000, external ingress

**Implementation:** Add to the `all_apps` local in `agent-apps/main.tf`:
```hcl
web-ui = { cpu = 0.5, memory = "1Gi", ingress_external = true, min_replicas = 1, max_replicas = 3, target_port = 3000 }
teams-bot = { cpu = 0.5, memory = "1Gi", ingress_external = true, min_replicas = 1, max_replicas = 3, target_port = 3978 }
```

Note: The current `agent-apps` module hardcodes `target_port = 8000`. Need to make this configurable per app.

### 8.3 Prod Terraform Apply Workflow (D-13)

The existing `terraform-apply.yml` already has an `apply-prod` job with `environment: prod` (which requires GitHub environment protection rules / required reviewers). The workflow:
1. Runs after staging apply succeeds (`needs: apply-staging`)
2. Uses OIDC authentication
3. Includes pgvector extension setup

**What needs to change:**
- Add `TF_VAR_compute_subscription_id`, `TF_VAR_network_subscription_id`, `TF_VAR_storage_subscription_id`, `TF_VAR_all_subscription_ids` from prod-specific GitHub Secrets
- Add `TF_VAR_fabric_admin_email` from secrets
- Verify `terraform plan` shows zero diff after successful apply (SC-7)

### 8.4 Prod Validation Checklist

After `terraform apply`:
1. `terraform plan` returns "No changes" — zero resource drift (SC-7)
2. All resources tagged with `environment: prod`, `managed-by: terraform`, `project: aap`
3. All data stores behind private endpoints (Cosmos, PostgreSQL, Key Vault, ACR, Foundry, Event Hub)
4. RBAC: each domain agent's managed identity has scoped role assignments (not Contributor on subscription)
5. No public access on any internal service (agents, arc-mcp-server)

---

## 9. Security Review

### 9.1 Automated Scanning (D-15)

**Python services:**
```bash
pip install bandit
bandit -r services/api-gateway/ services/arc-mcp-server/ services/detection-plane/ agents/ -f json -o bandit-report.json
```

**TypeScript services:**
```bash
cd services/web-ui && npm audit --audit-level=high
cd services/teams-bot && npm audit --audit-level=high
```

### 9.2 Manual Review Checklist

| Check | Services | How to Verify |
|---|---|---|
| No hardcoded secrets | All | `grep -rn "password\|secret\|api_key\|token" --include="*.py" --include="*.ts" --include="*.tsx"` |
| All endpoints require auth | api-gateway | Every route has `Depends(verify_token)` except `/health` |
| SQL injection prevention | api-gateway (runbook_rag.py) | Parameterized queries (`$1`, `$2`) — already correct |
| CORS configured | api-gateway | `allow_origins=["*"]` needs to be tightened for prod |
| Rate limiting | api-gateway | Needs verification — may need `slowapi` middleware |
| Input validation | api-gateway | Pydantic models validate all inputs |
| XSS prevention | web-ui | React escapes by default; verify no `dangerouslySetInnerHTML` |
| CSRF protection | web-ui, teams-bot | Stateless JWT auth (no CSRF needed for API-only) |

### 9.3 CORS Tightening for Prod

Currently `allow_origins=["*"]` in `main.py` line 57. For prod:
```python
ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, ...)
```

Set `CORS_ALLOWED_ORIGINS` to the prod web-ui FQDN in Terraform env vars.

---

## 10. Existing Codebase Analysis

### 10.1 Files to Modify

| File | Change | Workstream |
|---|---|---|
| `e2e/sc1.spec.ts` | Remove mocks, use real `BASE_URL` | E2E-001 |
| `e2e/sc2.spec.ts` | Remove mocks, test real SSE | E2E-001/005 |
| `e2e/sc5.spec.ts` | Remove mocks, use real approval endpoint | E2E-001 |
| `e2e/sc6.spec.ts` | Remove mocks, use real SSE/GitOps | E2E-001 |
| `services/api-gateway/approvals.py` | Add OneLake write call | REMEDI-007 |
| `services/api-gateway/main.py` | Add audit export endpoint | AUDIT-006 |
| `services/api-gateway/requirements.txt` | Add azure-monitor-opentelemetry, azure-storage-file-datalake | Observability, REMEDI-007 |
| `services/web-ui/components/DashboardPanel.tsx` | Add Observability tab | Observability |
| `services/web-ui/components/AuditLogViewer.tsx` | Add Export button | AUDIT-006 |
| `services/web-ui/package.json` | Add @azure/monitor-query, @azure/cosmos | Observability |
| `terraform/modules/agent-apps/main.tf` | Add teams-bot, web-ui; make target_port configurable | Terraform Prod |
| `terraform/envs/prod/main.tf` | Verify all modules present | Terraform Prod |
| `terraform/envs/prod/variables.tf` | May need teams-bot specific vars | Terraform Prod |
| `.github/workflows/phase5-ci.yml` | Rename/extend for Phase 7 | CI |

### 10.2 New Files to Create

| File | Purpose | Workstream |
|---|---|---|
| `e2e/e2e-incident-flow.spec.ts` | Full incident E2E test | E2E-002 |
| `e2e/e2e-hitl-approval.spec.ts` | HITL approval E2E test | E2E-003 |
| `e2e/e2e-rbac.spec.ts` | Cross-subscription RBAC E2E | E2E-004 |
| `e2e/e2e-sse-reconnect.spec.ts` | SSE reconnect E2E test | E2E-005 |
| `e2e/e2e-audit-export.spec.ts` | Audit export E2E test | AUDIT-006 |
| `e2e/global-setup.ts` | Playwright global setup (auth + Cosmos) | E2E-001 |
| `e2e/global-teardown.ts` | Playwright global teardown (cleanup) | E2E-001 |
| `e2e/fixtures/auth.ts` | Auth fixture for bearer token injection | E2E-001 |
| `.github/workflows/phase7-e2e.yml` | E2E CI workflow | E2E-001 |
| `services/api-gateway/remediation_logger.py` | OneLake write for REMEDI-007 | REMEDI-007 |
| `services/api-gateway/audit_export.py` | Report generation for AUDIT-006 | AUDIT-006 |
| `services/web-ui/components/ObservabilityTab.tsx` | Observability tab container | Observability |
| `services/web-ui/components/MetricCard.tsx` | Reusable metric card | Observability |
| `services/web-ui/components/AgentLatencyCard.tsx` | Agent latency display | Observability |
| `services/web-ui/components/PipelineLagCard.tsx` | Pipeline lag display | Observability |
| `services/web-ui/components/ApprovalQueueCard.tsx` | Approval queue display | Observability |
| `services/web-ui/components/ActiveErrorsCard.tsx` | Active errors display | Observability |
| `services/web-ui/components/TimeRangeSelector.tsx` | Time range dropdown | Observability |
| `services/web-ui/app/api/observability/route.ts` | Observability API route | Observability |
| `scripts/seed-runbooks/seed.py` | Runbook seed script | Runbook Seed |
| `scripts/seed-runbooks/runbooks/*.md` | ~60 runbook markdown files | Runbook Seed |
| `scripts/seed-runbooks/requirements.txt` | Seed script dependencies | Runbook Seed |
| `scripts/seed-runbooks/validate.py` | Similarity validation script | Runbook Seed |

### 10.3 Patterns to Follow

| Pattern | Source | Applies To |
|---|---|---|
| Cosmos DB client initialization | `approvals.py` `_get_approvals_container()` | REMEDI-007 Cosmos reads |
| `DefaultAzureCredential` auth | All services | OneLake write, Graph API, OTel |
| DataGrid + Toolbar layout | `AuditLogViewer.tsx` | Audit export button |
| Tab addition in DashboardPanel | `DashboardPanel.tsx` existing pattern | Observability tab |
| E2E spec with `request.post()` | `arc-mcp-server.spec.ts` | All new E2E specs |
| Terraform Container App for_each | `agent-apps/main.tf` | teams-bot, web-ui addition |
| CI workflow with Playwright | `phase5-ci.yml` | Phase 7 E2E workflow |
| Temporary PG firewall rule | `terraform-apply.yml` | Runbook seed in CI |

---

## 11. Risks and Mitigations

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | E2E env provisioning takes >15 min, blowing the CI time budget | E2E-001 SC: "full suite under 15 min" | MEDIUM | Use persistent staging env + test data isolation instead of ephemeral env |
| R2 | Foundry agent response times vary, causing flaky E2E-002 | Tests fail intermittently | HIGH | Use generous timeouts (90s for agent triage), `expect.poll()` with backoff, retry: 2 in CI |
| R3 | Teams Graph API permission `ChannelMessage.Read.All` requires admin consent | E2E-003 blocked | MEDIUM | Pre-configure admin consent as part of E2E service principal setup; document in ops runbook |
| R4 | OneLake write latency causes approval endpoint slowdown | REMEDI-007 degrades approval UX | LOW | Fire-and-forget pattern: write to OneLake async, don't block the approval response |
| R5 | prod `terraform apply` fails due to missing variable values | SC-7 blocked | LOW | Validate all `TF_VAR_*` secrets are configured before apply; `terraform plan` in PR catches this |
| R6 | SSE reconnect test is fragile with CDP network emulation | E2E-005 flaky | MEDIUM | Use `route.abort()` approach as primary, CDP as fallback; test the sequence assertion separately |
| R7 | Runbook embeddings drift if Azure OpenAI model changes | Similarity threshold (0.75) breaks | LOW | Pin model to `text-embedding-3-small`; version field enables re-embedding on model change |
| R8 | `azure-monitor-opentelemetry` conflicts with existing instrumentation | Services fail to start | LOW | Test in dev first; use `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS` to exclude conflicts |

---

## 12. Dependency Map

```
Independent (can run in parallel):
├── Observability (D-05, D-06, D-07) — no dependency on E2E or Terraform
├── Runbook Library Seed (D-08, D-09, D-10) — no dependency on E2E
├── REMEDI-007 (OneLake write) — no dependency on E2E
├── Security Review (D-15) — can run anytime
│
Sequential:
├── Terraform Prod (D-11–D-14) — must add teams-bot/web-ui BEFORE E2E deploys
├── E2E Infrastructure (E2E-001) — depends on deployed environment
│   ├── E2E-002 (incident flow) — depends on E2E infra
│   ├── E2E-003 (HITL approval) — depends on E2E infra
│   ├── E2E-004 (RBAC) — depends on E2E infra
│   └── E2E-005 (SSE reconnect) — depends on E2E infra
│
Late:
└── AUDIT-006 (export) — depends on REMEDI-007 being in place (to have data to export)
```

---

## 13. Recommended Plan Breakdown

Based on the dependency analysis and complexity, the phase should be split into **6 plans**:

### Plan 07-01: Observability — OTel + Observability Tab
**Scope:** D-05, D-06, D-07
**Complexity:** MEDIUM
**Dependencies:** None
**Deliverables:**
- `azure-monitor-opentelemetry` in Python services
- `@azure/monitor-opentelemetry` in TypeScript services
- Observability tab per 07-UI-SPEC.md (7 components + 1 API route)
- Verify traces appear in Application Insights

### Plan 07-02: Remediation Audit Trail + Export
**Scope:** REMEDI-007, AUDIT-006
**Complexity:** MEDIUM
**Dependencies:** None (but AUDIT-006 reads REMEDI-007 data)
**Deliverables:**
- `remediation_logger.py` writing to OneLake
- Hook into `approvals.py` process_approval_decision
- `audit_export.py` endpoint for report generation
- Export button in AuditLogViewer
- Unit tests for both modules

### Plan 07-03: Runbook Library Seed
**Scope:** D-08, D-09, D-10
**Complexity:** LOW-MEDIUM
**Dependencies:** None
**Deliverables:**
- ~60 runbook markdown files in `scripts/seed-runbooks/runbooks/`
- `seed.py` idempotent seed script
- `validate.py` similarity validation
- CI integration in staging deploy workflow
- Prod seed documented in ops runbook

### Plan 07-04: Terraform Prod + Security Review
**Scope:** D-11, D-12, D-13, D-14, D-15
**Complexity:** MEDIUM
**Dependencies:** None (but should run before E2E to have prod-like env)
**Deliverables:**
- teams-bot + web-ui in agent-apps Terraform module
- target_port made configurable per app
- Prod tfvars populated
- `terraform apply` on prod succeeds
- `terraform plan` shows zero changes
- Bandit + npm audit run
- CORS tightened
- Security checklist documented

### Plan 07-05: E2E Test Infrastructure + Real Endpoint Migration
**Scope:** E2E-001
**Complexity:** HIGH
**Dependencies:** Plan 07-04 (Terraform for E2E env)
**Deliverables:**
- Playwright global setup/teardown (auth + Cosmos containers)
- Auth fixture with service principal token injection
- Refactored sc1–sc6 specs (mocks removed, real endpoints)
- `phase7-e2e.yml` CI workflow
- E2E environment configuration (GitHub Secrets documentation)

### Plan 07-06: E2E Test Specs (E2E-002 through E2E-005)
**Scope:** E2E-002, E2E-003, E2E-004, E2E-005
**Complexity:** HIGH
**Dependencies:** Plan 07-05 (E2E infrastructure)
**Deliverables:**
- `e2e-incident-flow.spec.ts` (E2E-002)
- `e2e-hitl-approval.spec.ts` (E2E-003)
- `e2e-rbac.spec.ts` (E2E-004)
- `e2e-sse-reconnect.spec.ts` (E2E-005)
- All passing against deployed environment
- CI gate blocks merge on failure
- Suite completes in under 15 minutes

---

## 14. Open Questions

All questions below have **recommended answers** based on research. These are documented for planning review.

| # | Question | Recommended Answer | Rationale |
|---|---|---|---|
| Q1 | Should E2E tests use a dedicated E2E Terraform environment or the staging environment? | **Staging with E2E Cosmos containers** | Avoids 10-15 min provisioning; D-03 isolates test data via dedicated containers |
| Q2 | Should REMEDI-007 OneLake writes be synchronous or async? | **Async (fire-and-forget)** | Matches D-03 from Phase 4 ("fire-and-forget sync"); OneLake write must not block approval UX |
| Q3 | Should the audit export format be JSON or CSV? | **JSON** (with CSV as a future option) | SOC 2 auditors work with structured formats; JSON preserves nested `toolParameters`; CSV flattening loses fidelity |
| Q4 | How should the negative RBAC E2E test (E2E-004) be implemented? | **Direct ARM API call with agent MI token** | Calling ARM directly with the Compute Agent's MI attempting a Storage API gives a clean `403`; no agent code modification needed |
| Q5 | Should runbook generation be automated (LLM-generated) or hand-written? | **Claude-generated from domain knowledge** | Per D-08; faster to produce ~60 quality runbooks; validated by cosine similarity threshold |

---

*Phase: 07-quality-hardening*
*Research completed: 2026-03-27*
