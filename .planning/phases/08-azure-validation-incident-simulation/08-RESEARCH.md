# Phase 8: Azure Validation & Incident Simulation - Research

**Date:** 2026-03-29
**Phase:** 08-azure-validation-incident-simulation
**Purpose:** Everything a planner needs to know to break this phase into implementable plans

---

## Table of Contents

1. [Current Provisioning State](#1-current-provisioning-state)
2. [Sub-Goal 1: Fix Provisioning Gaps](#2-sub-goal-1-fix-provisioning-gaps)
3. [Sub-Goal 2: Critical-Path Validation](#3-sub-goal-2-critical-path-validation)
4. [Sub-Goal 3: Incident Simulation](#4-sub-goal-3-incident-simulation)
5. [Sub-Goal 4: Deferred Phase 7 Work](#5-sub-goal-4-deferred-phase-7-work)
6. [Requirement Traceability](#6-requirement-traceability)
7. [Risk Assessment](#7-risk-assessment)
8. [Dependency Graph](#8-dependency-graph)

---

## 1. Current Provisioning State

### What's Working (DONE)

| Resource | Evidence |
|----------|----------|
| Cosmos DB (`incidents`, `sessions`, `approvals`) | All 3 containers exist, 10 RBAC role assignments confirmed |
| Log Analytics on Web UI | `LOG_ANALYTICS_WORKSPACE_ID` set on `ca-web-ui-prod` |
| Entra Redirect URIs | Both localhost + prod callback URIs configured |
| Container Apps | All 3 exist: `ca-api-gateway-prod`, `ca-web-ui-prod`, `ca-teams-bot-prod` |
| ACR | `aapcrprodjgmjti.azurecr.io` — all images push successfully |
| API Gateway env vars (partial) | `FOUNDRY_ACCOUNT_ENDPOINT`, `COSMOS_ENDPOINT`, `APPLICATIONINSIGHTS_CONNECTION_STRING` set |
| GitHub Actions core secrets | `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_LOGIN_SERVER` present |

### What's Broken (BLOCKING)

| Gap | Impact | Fix Required |
|-----|--------|--------------|
| **No Foundry Orchestrator Agent** | Chat returns 503 ("ORCHESTRATOR_AGENT_ID env var required"). All incident dispatch fails. | Create agent via Python SDK or Portal, get `asst_xxx` ID |
| **`ORCHESTRATOR_AGENT_ID` env var missing** | Even if agent existed, gateway can't reference it | `az containerapp update --set-env-vars` |
| **`Azure AI Developer` role missing** | Gateway MI `69e05934-...` has `Cognitive Services User` but NOT `Azure AI Developer` | `az role assignment create` on Foundry account scope |
| **`CORS_ALLOWED_ORIGINS=*`** | Security concern for prod (any origin can call API) | Lock to `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` |

### What's Incomplete (PARTIAL)

| Gap | Impact | Fix Required |
|-----|--------|--------------|
| **Azure Bot Service resource missing** | Teams bot Container App exists but no Bot Framework registration | Create Azure Bot resource (Steps 5a-5f in MANUAL-SETUP.md) |
| **Missing GitHub secrets** | `POSTGRES_ADMIN_PASSWORD`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` | Add to GitHub repo secrets |
| **Runbook seeding unverified** | Can't confirm 60 runbooks are in prod PostgreSQL (VNet-isolated) | Run seed script via temporary firewall rule or Jump Box |
| **Secret rotation unverified** | Can't confirm `credentials.tfvars` was never committed | Check git history, rotate secrets if needed |

### Cannot Verify

| Item | Reason |
|------|--------|
| Prod runbook seeding | PostgreSQL is VNet-isolated; no CI/local access without firewall rule |
| Secret rotation status | Requires checking Entra credential expiry dates |

---

## 2. Sub-Goal 1: Fix Provisioning Gaps

### 2.1 Creating the Foundry Orchestrator Agent via Python SDK

**Decision D-01 (from 08-CONTEXT.md):** Fix provisioning gaps within Phase 8, not just document them.

#### SDK: `azure-ai-agents` (AgentsClient)

The project already uses `AgentsClient` in two places:
- `services/api-gateway/foundry.py` (creates threads, messages, runs)
- `scripts/configure-orchestrator.py` (updates existing agent instructions)

**Current `configure-orchestrator.py` assumes the agent already exists** (takes `ORCHESTRATOR_AGENT_ID` as input). Phase 8 needs a **create** script.

#### Agent Creation Pattern

```python
from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential

client = AgentsClient(
    endpoint="https://aap-foundry-prod.cognitiveservices.azure.com/",
    credential=DefaultAzureCredential(),
)

# Create the agent (returns agent object with .id)
agent = client.create_agent(
    model="gpt-4o",                    # matches FOUNDRY_MODEL_DEPLOYMENT env var
    name="AAP Orchestrator",
    instructions=ORCHESTRATOR_INSTRUCTIONS,  # from configure-orchestrator.py
    description="Azure Agentic Platform central orchestrator",
)

print(f"Agent ID: {agent.id}")  # asst_xxx
```

**Key `create_agent()` parameters:**
- `model` (str, required): Model deployment name (e.g., `"gpt-4o"`)
- `name` (str, optional): Display name
- `instructions` (str, optional): System prompt
- `description` (str, optional): Agent description
- `tools` (list, optional): Tool definitions (code interpreter, file search, function, MCP)

**MCP tool attachment** requires direct REST API call (not yet in SDK `azure-ai-agents` 1.1.0). The existing `configure-orchestrator.py:add_mcp_tools()` already has this REST pattern.

#### Implementation Approach

Extend `scripts/configure-orchestrator.py` with a `--create` flag:
1. If `--create` passed: call `client.create_agent()` and print the `asst_xxx` ID
2. Then run existing `update_assistant_instructions()` to set system prompt
3. Then optionally add MCP tools if `--mcp-connection` provided

**Or** create a separate `scripts/create-orchestrator.py` that:
1. Creates agent
2. Prints the agent ID
3. Calls `configure-orchestrator.py --agent-id <id>` to set instructions

**Recommendation:** Extend existing script (less code duplication, same auth pattern).

#### Post-Creation Steps (sequencing matters per D-01)

1. Create agent -> get `asst_xxx` ID
2. Update Container App env var:
   ```bash
   az containerapp update --name ca-api-gateway-prod --resource-group rg-aap-prod \
     --set-env-vars "ORCHESTRATOR_AGENT_ID=<asst_xxx>"
   ```
3. Grant `Azure AI Developer` role:
   ```bash
   az role assignment create \
     --assignee "69e05934-1feb-44d4-8fd2-30373f83ccec" \
     --role "Azure AI Developer" \
     --scope "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod"
   ```
4. Lock CORS:
   ```bash
   az containerapp update --name ca-api-gateway-prod --resource-group rg-aap-prod \
     --set-env-vars "CORS_ALLOWED_ORIGINS=https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
   ```

### 2.2 Teams Bot Registration

**Current state:** Container App `ca-teams-bot-prod` exists. Azure Bot Service resource does NOT exist.

**Steps required (from MANUAL-SETUP.md Steps 5a-5f):**

1. **Create Azure Bot resource** via Azure Portal or CLI:
   ```bash
   az bot create --resource-group rg-aap-prod \
     --name aap-teams-bot-prod \
     --kind registration \
     --endpoint "https://ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/messages" \
     --app-type MultiTenant \
     --appid "<app-client-id>"
   ```
2. **Enable Teams channel** on the Bot resource
3. **Set Bot credentials** (`MicrosoftAppId`, `MicrosoftAppPassword`) as env vars on the Container App
4. **Register messaging endpoint** (the Container App URL + `/api/messages`)
5. **Install bot in Teams** (sideload the app manifest or publish to org store)

**Note:** The Teams bot uses Bot Framework SDK (`botbuilder`), not the new Teams SDK. The bot is `AapTeamsBot extends TeamsActivityHandler`. This is an architectural decision from Phase 6 — the bot works with Bot Framework REST API for CI testing.

### 2.3 Missing GitHub Secrets

| Secret | Purpose | Action |
|--------|---------|--------|
| `POSTGRES_ADMIN_PASSWORD` | Runbook seed script in staging CI | Add from Key Vault or Terraform output |
| `AZURE_OPENAI_ENDPOINT` | Embedding generation for seed script | Set to `https://aap-foundry-prod.cognitiveservices.azure.com/` |
| `AZURE_OPENAI_API_KEY` | OpenAI API auth for seed script | Generate key from Foundry account |

---

## 3. Sub-Goal 2: Critical-Path Validation

### 3.1 Critical Path Definition

Per D-02, the critical path is: **chat -> detection -> triage -> HITL approval -> Teams alert**

This maps to a chain of requirements:
```
Operator message (UI-003)
  -> POST /api/v1/chat (DETECT-004 pattern)
    -> Foundry thread creation (foundry.py)
      -> Orchestrator agent run (AGENT-001)
        -> Domain agent handoff (TRIAGE-001)
          -> Runbook RAG retrieval (TRIAGE-005)
          -> Root cause analysis (TRIAGE-004)
            -> Remediation proposal (REMEDI-001)
              -> HITL approval gate (REMEDI-002)
                -> Teams Adaptive Card (TEAMS-003)
                  -> Approve/Reject callback (REMEDI-005)
                    -> Thread resume (REMEDI-003)
```

### 3.2 Validation Test Plan

**Phase 7 E2E tests to run against prod (D-03):**

| Test | File | What it validates |
|------|------|-------------------|
| E2E-002 | `e2e/e2e-incident-flow.spec.ts` | POST /api/v1/incidents -> thread creation -> agent dispatch |
| E2E-003 | `e2e/e2e-hitl-approval.spec.ts` | Approval list -> approve/reject endpoints -> Cosmos update |
| E2E-004 | `e2e/e2e-rbac.spec.ts` | Cross-subscription RBAC via managed identity |
| E2E-005 | `e2e/e2e-sse-reconnect.spec.ts` | SSE stream with Last-Event-ID reconnect |
| AUDIT-006 | `e2e/e2e-audit-export.spec.ts` | Audit export endpoint returns valid report |

**Critical change from Phase 7:** Remove `test.skip()` behavior when infra unavailable. In Phase 8, these tests MUST pass — skipping = failure.

**Existing skip patterns to override:**
- `e2e-incident-flow.spec.ts` line 124: `test.skip(true, 'Foundry not available in E2E environment')`
- `e2e-hitl-approval.spec.ts` line 45: `test.skip(true, 'No pending approvals available')`
- All `if (response.status() !== 202) { test.skip(...) }` patterns

**Phase 8 approach:** Replace `test.skip()` with `expect(response.status()).toBe(202)` — hard failures when infra is broken.

### 3.3 Smoke Tests (Non-Critical Path)

| Service | Test | Expected |
|---------|------|----------|
| Web UI | `GET /` (load homepage) | 200, renders Fluent UI shell |
| Web UI | Observability tab loads | 200, shows metric cards |
| Arc MCP | `POST /tools/list` | Returns tool list |
| Runbook search | `GET /api/v1/runbooks/search?query=high%20cpu` | Returns 1-3 results |
| Audit log | `GET /api/v1/audit` | Returns array |
| Health check | `GET /health` | `{"status":"ok"}` |
| Incidents list | `GET /api/v1/incidents` | Returns array |

### 3.4 Environment Variables for E2E Against Prod

```bash
E2E_BASE_URL=https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io
E2E_API_URL=https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io
E2E_CLIENT_ID=<service principal client ID>
E2E_CLIENT_SECRET=<service principal client secret>
E2E_TENANT_ID=abbdca26-d233-4a1e-9d8c-c4eebbc16e50
E2E_COSMOS_ENDPOINT=https://aap-cosmos-prod.documents.azure.com:443/
E2E_COSMOS_DB=aap
```

---

## 4. Sub-Goal 3: Incident Simulation

### 4.1 Simulation Architecture (D-04, D-05, D-06, D-07)

**Injection point:** `POST /api/v1/incidents` (same endpoint used by the detection plane)

**NOT real Azure Monitor alerts** — synthetic payloads with realistic field values.

**Location:** `scripts/simulate-incidents/` (follows project convention: scripts in `scripts/` directory)

**Structure per scenario:**
```
scripts/simulate-incidents/
  run-all.sh              # Orchestrator: runs all 7 in sequence
  common.py               # Shared utilities (API client, auth, cleanup, assertions)
  scenario_compute.py     # 1/7: VM high CPU
  scenario_network.py     # 2/7: NSG rule blocking 443
  scenario_storage.py     # 3/7: Storage quota approaching
  scenario_security.py    # 4/7: Defender suspicious login
  scenario_arc.py         # 5/7: Arc server disconnected
  scenario_sre.py         # 6/7: Multi-signal SLA breach
  scenario_cross.py       # 7/7: Disk-full (compute + storage)
  requirements.txt        # azure-identity, azure-cosmos, requests
```

### 4.2 Incident Payload Schema (from `models.py:IncidentPayload`)

All simulation payloads must conform to this validated schema:

```python
{
    "incident_id": str,        # required, min_length=1
    "severity": str,           # required, pattern: ^Sev[0-3]$
    "domain": str,             # required, pattern: ^(compute|network|storage|security|arc|sre)$
    "affected_resources": [    # required, min_length=1
        {
            "resource_id": str,       # Full ARM resource ID
            "subscription_id": str,   # Azure subscription ID
            "resource_type": str,     # ARM resource type
        }
    ],
    "detection_rule": str,     # required
    "kql_evidence": str,       # optional
    "title": str,              # optional
    "description": str,        # optional
}
```

**Important constraints:**
- `severity` must match regex `^Sev[0-3]$` (e.g., "Sev0", "Sev1", "Sev2", "Sev3")
- `domain` must be one of: `compute`, `network`, `storage`, `security`, `arc`, `sre`
- `affected_resources` must have at least one entry
- For the cross-domain scenario (7/7), the API only accepts ONE domain per payload. The cross-domain test should inject two separate incidents (one compute, one storage) with the same resource group context.

### 4.3 Seven Simulation Scenarios

#### Scenario 1: Compute - VM High CPU on vm-prod-01

```python
{
    "incident_id": "sim-compute-001",
    "severity": "Sev2",
    "domain": "compute",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-.../resourceGroups/rg-aap-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Compute/virtualMachines",
    }],
    "detection_rule": "HighCPUThreshold",
    "kql_evidence": "Perf | where ObjectName == 'Processor' | where CounterName == '% Processor Time' | where CounterValue > 95 | summarize avg(CounterValue) by bin(TimeGenerated, 5m), Computer",
    "title": "VM High CPU: vm-prod-01 sustained >95% for 15 minutes",
    "description": "Sustained CPU utilization above 95% threshold for 15 consecutive minutes.",
}
```

**Expected agent behavior:** Orchestrator routes to Compute Agent -> queries Activity Log + Resource Health -> retrieves `compute-01-vm-high-cpu.md` runbook -> proposes investigation steps.

#### Scenario 2: Network - NSG Rule Blocking Port 443

```python
{
    "incident_id": "sim-network-001",
    "severity": "Sev1",
    "domain": "network",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-.../resourceGroups/rg-aap-prod/providers/Microsoft.Network/networkSecurityGroups/nsg-app-tier",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Network/networkSecurityGroups",
    }],
    "detection_rule": "NSGBlockedTraffic",
    "kql_evidence": "AzureNetworkAnalytics_CL | where FlowStatus_s == 'D' | where DestPort_d == 443",
    "title": "NSG Deny Rule blocking HTTPS to app tier",
    "description": "NSG effective rule denying inbound TCP/443 traffic to application tier subnet.",
}
```

#### Scenario 3: Storage - Account Quota Approaching Limit

```python
{
    "incident_id": "sim-storage-001",
    "severity": "Sev2",
    "domain": "storage",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-.../resourceGroups/rg-aap-prod/providers/Microsoft.Storage/storageAccounts/aapstorageprod",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Storage/storageAccounts",
    }],
    "detection_rule": "StorageQuotaThreshold",
    "kql_evidence": "StorageBlobLogs | summarize TotalBytes=sum(RequestBodySize) | where TotalBytes > 4000000000000",
    "title": "Storage account approaching 5TB quota limit (80% utilization)",
    "description": "Blob storage usage at 4.1TB of 5TB limit. Approaching quota boundary.",
}
```

#### Scenario 4: Security - Defender Suspicious Login

```python
{
    "incident_id": "sim-security-001",
    "severity": "Sev1",
    "domain": "security",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-.../resourceGroups/rg-aap-prod/providers/Microsoft.Security/alerts/suspicious-login-001",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Security/alerts",
    }],
    "detection_rule": "DefenderSuspiciousLogin",
    "kql_evidence": "SecurityAlert | where AlertType == 'SIMULATED_BRUTE_FORCE' | where TimeGenerated > ago(1h)",
    "title": "Defender alert: suspicious login pattern from unusual geography",
    "description": "Multiple failed login attempts from IP 203.0.113.42 (unrecognized geography) followed by successful authentication.",
}
```

#### Scenario 5: Arc - Server Connectivity Loss

```python
{
    "incident_id": "sim-arc-001",
    "severity": "Sev2",
    "domain": "arc",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-.../resourceGroups/rg-arc-servers/providers/Microsoft.HybridCompute/machines/arc-server-prod-01",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.HybridCompute/machines",
    }],
    "detection_rule": "ArcDisconnectedThreshold",
    "kql_evidence": "Heartbeat | where Computer == 'arc-server-prod-01' | summarize LastHeartbeat=max(TimeGenerated) | where LastHeartbeat < ago(30m)",
    "title": "Arc server disconnected: arc-server-prod-01 offline >30 minutes",
    "description": "Arc-enabled server has not sent heartbeat in over 30 minutes. Status: Disconnected.",
}
```

#### Scenario 6: SRE - Multi-Signal SLA Breach

```python
{
    "incident_id": "sim-sre-001",
    "severity": "Sev0",
    "domain": "sre",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-.../resourceGroups/rg-aap-prod",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Resources/resourceGroups",
    }],
    "detection_rule": "SLABreachMultiSignal",
    "kql_evidence": "union AzureMetrics, AzureDiagnostics | where TimeGenerated > ago(1h) | summarize ErrorCount=countif(ResultType == 'Failed') | where ErrorCount > 50",
    "title": "Multi-service SLA breach: >50 failures across rg-aap-prod in 1h",
    "description": "Correlated failure pattern across API gateway, Cosmos DB, and Foundry services exceeding SLA error budget.",
}
```

#### Scenario 7: Cross-Domain - Disk Full (Compute + Storage)

This requires TWO incidents (API only accepts one domain per payload):

```python
# Incident A: Compute perspective
{
    "incident_id": "sim-cross-001a",
    "severity": "Sev1",
    "domain": "compute",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-.../resourceGroups/rg-aap-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-02",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Compute/virtualMachines",
    }],
    "detection_rule": "VMDiskFullCritical",
    "title": "VM disk full: vm-prod-02 OS disk at 98% capacity",
}

# Incident B: Storage perspective
{
    "incident_id": "sim-cross-001b",
    "severity": "Sev1",
    "domain": "storage",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-.../resourceGroups/rg-aap-prod/providers/Microsoft.Compute/disks/vm-prod-02-osdisk",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Compute/disks",
    }],
    "detection_rule": "ManagedDiskCapacityCritical",
    "title": "Managed disk critical: vm-prod-02-osdisk at 98% capacity",
}
```

### 4.4 Simulation Script Pattern

Each scenario follows a consistent 4-step pattern (matching `seed.py` idiom):

```python
#!/usr/bin/env python3
"""Scenario: Compute - VM High CPU."""
from common import SimulationClient, cleanup_incident

def run():
    client = SimulationClient()

    # 1. SETUP - Prepare scenario
    payload = { ... }  # IncidentPayload

    # 2. INJECT - POST to /api/v1/incidents
    result = client.inject_incident(payload)
    assert result["status"] in ("dispatched", "deduplicated"), f"Unexpected: {result}"
    thread_id = result["thread_id"]

    # 3. ASSERT - Verify expected behavior
    # Wait for Foundry run to complete (poll chat result endpoint)
    final = client.poll_thread_completion(thread_id, timeout_seconds=120)
    assert final["run_status"] == "completed", f"Run failed: {final}"
    assert final.get("reply"), "Agent produced no reply"

    # 4. CLEANUP - Delete Cosmos records
    cleanup_incident(client, payload["incident_id"])

if __name__ == "__main__":
    run()
```

### 4.5 Cleanup Pattern (D-06)

Cleanup must delete from TWO Cosmos containers:
1. **`incidents` container** - keyed by `resource_id` (partition key), filtered by `incident_id`
2. **`approvals` container** - keyed by `thread_id` (partition key)

```python
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

def cleanup_incident(client, incident_id: str):
    """Delete all Cosmos records created by a simulation."""
    cosmos = CosmosClient(url=COSMOS_ENDPOINT, credential=DefaultAzureCredential())
    db = cosmos.get_database_client("aap")

    # Delete from incidents (cross-partition query to find the record)
    incidents = db.get_container_client("incidents")
    query = "SELECT * FROM c WHERE c.incident_id = @id"
    for item in incidents.query_items(query, parameters=[{"name": "@id", "value": incident_id}], enable_cross_partition_query=True):
        incidents.delete_item(item=item["id"], partition_key=item["resource_id"])

    # Delete from approvals (need thread_id from the incident)
    # ... similar pattern with approvals container
```

**Note:** The existing `e2e/global-teardown.ts` deletes ENTIRE containers (`incidents-e2e`, `approvals-e2e`). Simulation cleanup is more surgical — it deletes specific records from the REAL `incidents` and `approvals` containers by incident_id.

### 4.6 Common Utilities Module (`common.py`)

```python
class SimulationClient:
    """HTTP client for simulation scripts with auth."""

    def __init__(self):
        self.base_url = os.environ.get("API_GATEWAY_URL", "https://ca-api-gateway-prod...")
        self.token = self._acquire_token()

    def _acquire_token(self) -> str:
        """Acquire bearer token via DefaultAzureCredential."""
        credential = DefaultAzureCredential()
        token = credential.get_token("https://management.azure.com/.default")
        return token.token

    def inject_incident(self, payload: dict) -> dict:
        """POST /api/v1/incidents and return response."""
        resp = requests.post(
            f"{self.base_url}/api/v1/incidents",
            json=payload,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        resp.raise_for_status()
        return resp.json()

    def poll_thread_completion(self, thread_id: str, timeout_seconds: int = 120) -> dict:
        """Poll GET /api/v1/chat/{thread_id}/result until terminal."""
        ...
```

**Auth consideration:** The API gateway uses `verify_token` middleware. In dev-mode (no `AZURE_CLIENT_ID` on gateway), any token is accepted. In prod, the token must be a valid Entra bearer token. The simulation scripts should use `DefaultAzureCredential` to get a token scoped appropriately.

---

## 5. Sub-Goal 4: Deferred Phase 7 Work

### 5.1 Teams Bot Round-Trip E2E (D-11, D-12)

**What was deferred from Phase 7:** "Full bot round-trip (sending messages via Teams Bot Connector API) deferred to Phase 8."

#### Bot Connector REST API

The Bot Framework REST API allows sending activities to a conversation programmatically — this is how CI can simulate a user message to the bot.

**Endpoint:**
```
POST {serviceUrl}/v3/conversations/{conversationId}/activities
```

**Authentication flow:**
1. Request token from Bot Framework token endpoint:
   ```
   POST https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token

   grant_type=client_credentials
   &client_id={MicrosoftAppId}
   &client_secret={MicrosoftAppPassword}
   &scope=https://api.botframework.com/.default
   ```
2. Use the token as `Authorization: Bearer {token}`

**Activity payload (simulate user message):**
```json
{
  "type": "message",
  "from": {
    "id": "e2e-test-user",
    "name": "E2E Test User"
  },
  "recipient": {
    "id": "{bot-app-id}",
    "name": "AAP Teams Bot"
  },
  "text": "investigate the CPU alert on vm-prod-01",
  "channelId": "msteams",
  "serviceUrl": "https://smba.trafficmanager.net/teams/"
}
```

#### E2E Test Structure

New file: `e2e/e2e-teams-roundtrip.spec.ts` (D-12)

```typescript
test.describe('E2E: Teams Bot Round-Trip', () => {
  test('Message to bot gets agent response within 60s', async ({ }) => {
    // 1. Acquire Bot Connector token
    // 2. POST activity to bot's service URL
    // 3. Poll for bot's response in the conversation (via Graph API or Bot Connector)
    // 4. Assert response contains triage content within 60s
  });
});
```

**Prerequisites:**
- Azure Bot resource must exist (Step 5 from MANUAL-SETUP.md)
- `MicrosoftAppId` and `MicrosoftAppPassword` available in CI secrets
- Bot must be installed in a Teams channel (for serviceUrl)
- `E2E_TEAMS_TEAM_ID` and `E2E_TEAMS_CHANNEL_ID` must be set

**Alternative approach (simpler, if Bot Connector auth is complex):**
1. POST directly to the bot's messaging endpoint (`/api/messages`) with a synthetic activity
2. This bypasses Bot Framework auth entirely but tests the same code path
3. The bot's Express server at `ca-teams-bot-prod` accepts POST `/api/messages`

**Recommended:** Start with the direct POST to `/api/messages` approach (tests the handler code), add full Bot Connector round-trip as a stretch goal.

### 5.2 Manual OTel Spans (D-13, D-14)

**What was deferred from Phase 7:** "Manual agent-level spans (per-Foundry-call, per-tool-call latency) are a Phase 8 observability improvement."

#### Current OTel Setup

In `services/api-gateway/main.py` (lines 52-59):
```python
from azure.monitor.opentelemetry import configure_azure_monitor
configure_azure_monitor(connection_string=_appinsights_conn)
```

This provides **auto-instrumentation** (HTTP requests, database calls, etc.) but NOT domain-specific spans.

#### Three Instrumentation Points (D-13)

**1. Foundry API Calls** (`services/api-gateway/foundry.py` + `chat.py`)

Wrap `client.threads.create()`, `client.messages.create()`, `client.runs.create()`, `client.runs.list()`, and `client.messages.list()` with manual spans:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def create_foundry_thread(payload: IncidentPayload) -> dict[str, str]:
    client = _get_foundry_client()
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")

    # Span 1: Thread creation
    with tracer.start_as_current_span("foundry.create_thread") as span:
        thread = client.threads.create()
        span.set_attribute("foundry.thread_id", thread.id)

    # Span 2: Message posting
    with tracer.start_as_current_span("foundry.post_message") as span:
        span.set_attribute("foundry.thread_id", thread.id)
        span.set_attribute("foundry.model", os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", ""))
        client.messages.create(thread_id=thread.id, role="user", content=...)

    # Span 3: Run dispatch
    with tracer.start_as_current_span("foundry.create_run") as span:
        span.set_attribute("foundry.thread_id", thread.id)
        span.set_attribute("foundry.agent_id", orchestrator_agent_id)
        run = client.runs.create(thread_id=thread.id, agent_id=orchestrator_agent_id)
        span.set_attribute("foundry.run_id", run.id)
```

**Attributes per D-13:**
- `foundry.thread_id`
- `foundry.model`
- `foundry.duration_ms` (computed from span start/end)
- `foundry.tokens_used` (if available from run result)

**2. MCP Tool Calls** (not directly in api-gateway today; agents use MCP tools)

The MCP tool spans should be added where MCP tools are invoked. In the current architecture, MCP tools are invoked by the Foundry agent runtime (not by the api-gateway directly). This means MCP spans need to be in the **agent container code**, not the gateway.

However, the gateway's `get_chat_result()` in `chat.py` processes `requires_action` / `submit_tool_approval` responses — we can add spans around the tool approval flow:

```python
with tracer.start_as_current_span("mcp.tool_approval") as span:
    span.set_attribute("mcp.tool_calls_count", len(approval_ids))
    span.set_attribute("mcp.thread_id", thread_id)
    client.runs.submit_tool_approval(...)
    span.set_attribute("mcp.outcome", "approved")
```

**Attributes per D-13:**
- `mcp.tool_name`
- `mcp.server`
- `mcp.duration_ms`
- `mcp.outcome` (success/error)

**3. Agent Invocations** (domain agent activation)

Span around each `client.runs.create()` call:

```python
with tracer.start_as_current_span("agent.invoke") as span:
    span.set_attribute("agent.name", "orchestrator")
    span.set_attribute("agent.domain", payload.domain)
    span.set_attribute("agent.correlation_id", payload.incident_id)
    run = client.runs.create(thread_id=thread.id, agent_id=orchestrator_agent_id)
```

**Attributes per D-13:**
- `agent.name`
- `agent.domain`
- `agent.correlation_id`
- `agent.duration_ms`

#### Implementation Approach

Create a thin instrumentation helper module:

```python
# services/api-gateway/instrumentation.py

from opentelemetry import trace
from contextlib import contextmanager
from time import time

tracer = trace.get_tracer("aap.api-gateway")

@contextmanager
def foundry_span(operation: str, **attributes):
    """Context manager for Foundry API call spans."""
    with tracer.start_as_current_span(f"foundry.{operation}") as span:
        start = time()
        for key, value in attributes.items():
            span.set_attribute(f"foundry.{key}", str(value))
        try:
            yield span
        finally:
            span.set_attribute("foundry.duration_ms", int((time() - start) * 1000))

@contextmanager
def mcp_span(tool_name: str, server: str = "azure_mcp", **attributes):
    """Context manager for MCP tool call spans."""
    with tracer.start_as_current_span(f"mcp.{tool_name}") as span:
        start = time()
        span.set_attribute("mcp.tool_name", tool_name)
        span.set_attribute("mcp.server", server)
        for key, value in attributes.items():
            span.set_attribute(f"mcp.{key}", str(value))
        try:
            yield span
            span.set_attribute("mcp.outcome", "success")
        except Exception:
            span.set_attribute("mcp.outcome", "error")
            raise
        finally:
            span.set_attribute("mcp.duration_ms", int((time() - start) * 1000))

@contextmanager
def agent_span(agent_name: str, domain: str = "", correlation_id: str = ""):
    """Context manager for agent invocation spans."""
    with tracer.start_as_current_span(f"agent.{agent_name}") as span:
        start = time()
        span.set_attribute("agent.name", agent_name)
        span.set_attribute("agent.domain", domain)
        span.set_attribute("agent.correlation_id", correlation_id)
        try:
            yield span
        finally:
            span.set_attribute("agent.duration_ms", int((time() - start) * 1000))
```

**Files to modify:**
- `services/api-gateway/foundry.py` — wrap `create_foundry_thread()` internals
- `services/api-gateway/chat.py` — wrap `create_chat_thread()` and `get_chat_result()`
- `services/api-gateway/approvals.py` — wrap `_resume_foundry_thread()`
- New: `services/api-gateway/instrumentation.py` — shared span helpers

**No new dependencies needed.** `opentelemetry` is already transitively installed via `azure-monitor-opentelemetry`.

#### Verification

Spans should appear in:
1. **Application Insights** (Transaction Search > Custom events/traces)
2. **Web UI Observability Tab** (via the existing Azure Monitor Query API route)

---

## 6. Requirement Traceability

### Requirements Directly Validated by Phase 8

Phase 8 doesn't ADD new requirements — it VALIDATES existing ones:

| REQ-ID | Requirement | Validation Method |
|--------|------------|-------------------|
| DETECT-004 | POST /api/v1/incidents endpoint | Simulation scripts (7 scenarios) |
| AGENT-001 | Orchestrator routes by domain | Simulation asserts correct domain routing |
| TRIAGE-001 | Domain classification | Each scenario targets one domain |
| TRIAGE-004 | Root cause with evidence | Assert agent reply contains hypothesis |
| TRIAGE-005 | Runbook RAG retrieval | Assert runbook domain match in simulation |
| REMEDI-001 | No action without approval | Simulation verifies HITL gate |
| REMEDI-002 | High-risk triggers Teams card | E2E-003 against prod |
| REMEDI-003 | Approval records in Cosmos | Simulation cleanup verifies records exist |
| UI-003 | Chat streaming | E2E SSE test against prod |
| TEAMS-001 | Two-way Teams conversation | Teams round-trip E2E |
| TEAMS-003 | Approval cards in Teams | E2E-003 against prod |
| E2E-001 | CI gate blocks on failure | Run E2E suite with no skips |
| E2E-002 | Full incident flow | E2E against prod |
| E2E-003 | HITL approval flow | E2E against prod |
| E2E-004 | Cross-subscription RBAC | E2E against prod |
| E2E-005 | SSE reconnect | E2E against prod |
| MONITOR-007 | OTel spans to App Insights | Manual spans added (D-13) |
| AUDIT-001 | Agent tool calls as OTel spans | Manual spans added (D-13) |

### Requirements Phase 8 Fixes (Provisioning)

| REQ-ID | Gap | Fix |
|--------|-----|-----|
| AGENT-001 | No orchestrator agent exists | Create via Python SDK |
| AGENT-008 | Missing Azure AI Developer role | Grant RBAC |
| TEAMS-001 | No Azure Bot resource | Create Bot registration |

---

## 7. Risk Assessment

### High Risk

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Foundry agent creation fails (SDK compatibility) | Medium | BLOCKING | Fallback: create via Azure Portal UI, use SDK only for configuration |
| `Cognitive Services User` role insufficient for thread/run operations | Medium | BLOCKING | Validate with minimal test after RBAC; escalate to `Cognitive Services Contributor` if needed |
| Simulation scripts hit rate limits on Foundry | Low | Delays | Add backoff between scenarios in `run-all.sh`; run sequentially (not parallel) |
| Teams Bot registration requires admin consent | Medium | Teams E2E blocked | Document as known gap if admin consent unavailable; mark Teams round-trip E2E as conditional |

### Medium Risk

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Simulation cleanup fails (Cosmos cross-partition delete) | Low | Orphaned test data | Cleanup function is idempotent; add manual cleanup script as fallback |
| MCP tool spans require agent-container changes | Medium | D-13 partially satisfied | Gateway-side spans cover Foundry and approval flows; defer agent-internal MCP spans to v2 |
| Bot Connector auth requires app registration changes | Medium | Teams E2E harder | Fall back to direct POST to `/api/messages` (simpler, same code path) |

### Low Risk

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| E2E test timeout (120s) too short for real Foundry | Low | Flaky tests | Already 120s per test; add retry logic (2 retries in CI config already) |
| Missing GitHub secrets block CI | Low | CI broken | Phase 8 adds secrets as part of fix tasks |

---

## 8. Dependency Graph

### Execution Order (Critical Path)

```
[Plan 1] Fix Provisioning Gaps
    |
    |-- 1a. Create Foundry Orchestrator Agent (Python SDK script)
    |-- 1b. Set ORCHESTRATOR_AGENT_ID env var on Container App
    |-- 1c. Grant Azure AI Developer RBAC
    |-- 1d. Lock CORS_ALLOWED_ORIGINS
    |-- 1e. Register Azure Bot resource (for Teams)
    |-- 1f. Add missing GitHub secrets
    |
    v
[Plan 2] Critical-Path Validation
    |
    |-- 2a. Remove test.skip() from Phase 7 E2E tests (hard failures)
    |-- 2b. Run E2E suite against prod (E2E-002 through E2E-005)
    |-- 2c. Smoke tests on all services
    |-- 2d. Write VALIDATION-REPORT.md with findings
    |
    v
[Plan 3] Incident Simulation
    |
    |-- 3a. Create common.py (SimulationClient, cleanup, auth)
    |-- 3b. Implement 7 scenario scripts
    |-- 3c. Create run-all.sh orchestrator
    |-- 3d. Run all scenarios against prod
    |-- 3e. Update VALIDATION-REPORT.md
    |
    v (parallel with Plan 3)
[Plan 4] Deferred Phase 7 Work
    |
    |-- 4a. Manual OTel spans (instrumentation.py + modify foundry.py/chat.py/approvals.py)
    |-- 4b. Teams bot round-trip E2E (e2e-teams-roundtrip.spec.ts)
    |
    v
[Plan 5] Validation Report & Closeout
    |
    |-- 5a. Final VALIDATION-REPORT.md (all findings, severity, status)
    |-- 5b. Log DEGRADED/COSMETIC findings as backlog items
    |-- 5c. Confirm all BLOCKING findings resolved
```

### Parallelization Opportunities

- **Plan 3 and Plan 4a** can run in parallel (simulation scripts are independent of OTel instrumentation)
- **Plan 4a and Plan 4b** can run in parallel (OTel spans and Teams E2E touch different files)
- **Plan 1e (Teams Bot)** and **Plan 4b (Teams E2E)** are sequential (can't test what isn't registered)

### External Dependencies

| Dependency | Required By | Status |
|------------|------------|--------|
| Azure Portal or CLI access | Plan 1 (all steps) | Available |
| Foundry project (`aap-project-prod`) | Plan 1a | Exists |
| Entra admin consent for Bot | Plan 1e | Requires tenant admin |
| `MicrosoftAppId` / `MicrosoftAppPassword` | Plan 1e, 4b | Generated during Bot creation |
| Active Teams channel + team | Plan 4b | Requires Teams setup |

---

## Appendix A: File Inventory (Files to Create/Modify)

### New Files

| File | Purpose |
|------|---------|
| `scripts/simulate-incidents/common.py` | Shared simulation utilities |
| `scripts/simulate-incidents/scenario_compute.py` | VM high CPU scenario |
| `scripts/simulate-incidents/scenario_network.py` | NSG blocking scenario |
| `scripts/simulate-incidents/scenario_storage.py` | Storage quota scenario |
| `scripts/simulate-incidents/scenario_security.py` | Defender alert scenario |
| `scripts/simulate-incidents/scenario_arc.py` | Arc disconnected scenario |
| `scripts/simulate-incidents/scenario_sre.py` | SLA breach scenario |
| `scripts/simulate-incidents/scenario_cross.py` | Cross-domain scenario |
| `scripts/simulate-incidents/run-all.sh` | Orchestrator script |
| `scripts/simulate-incidents/requirements.txt` | Python dependencies |
| `services/api-gateway/instrumentation.py` | Manual OTel span helpers |
| `e2e/e2e-teams-roundtrip.spec.ts` | Teams round-trip E2E test |
| `.planning/phases/08-azure-validation-incident-simulation/08-VALIDATION-REPORT.md` | Validation findings |

### Modified Files

| File | Change |
|------|--------|
| `scripts/configure-orchestrator.py` | Add `--create` flag for agent creation |
| `services/api-gateway/foundry.py` | Add manual OTel spans around Foundry calls |
| `services/api-gateway/chat.py` | Add manual OTel spans around chat + tool approval |
| `services/api-gateway/approvals.py` | Add manual OTel spans around thread resume |
| `e2e/e2e-incident-flow.spec.ts` | Remove `test.skip()` graceful skips |
| `e2e/e2e-hitl-approval.spec.ts` | Remove `test.skip()` graceful skips |
| `e2e/e2e-sse-reconnect.spec.ts` | Remove `test.skip()` if present |
| `.github/workflows/staging-e2e-simulation.yml` | Update to Phase 8 CI (or create new workflow) |

---

## Appendix B: SDK Reference Summary

### Agent Creation (azure-ai-agents)

```python
from azure.ai.agents import AgentsClient
client = AgentsClient(endpoint=..., credential=DefaultAzureCredential())
agent = client.create_agent(model="gpt-4o", name="...", instructions="...")
# agent.id -> "asst_xxx"
```

### Manual OTel Spans (opentelemetry)

```python
from opentelemetry import trace
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("my.operation") as span:
    span.set_attribute("key", "value")
    span.add_event("checkpoint")
    span.set_status(trace.StatusCode.OK)
```

### Bot Connector API (REST)

```
# Token
POST https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token
  grant_type=client_credentials&client_id={AppId}&client_secret={Password}&scope=https://api.botframework.com/.default

# Send activity
POST {serviceUrl}/v3/conversations/{conversationId}/activities
  Authorization: Bearer {token}
  Content-Type: application/json
  {"type":"message","text":"...","from":{"id":"bot-id"},"recipient":{"id":"user-id"}}
```

### Cosmos DB Item Delete (azure-cosmos)

```python
container.delete_item(item=item_id, partition_key=partition_value)
# Cross-partition query to find records:
items = container.query_items(query, parameters=[...], enable_cross_partition_query=True)
```

---

## Validation Architecture

> This section defines the test strategy for Phase 8 and is consumed by Nyquist validation.

### Validation Layers

Phase 8 uses four validation layers, executed in dependency order:

| Layer | Type | Tooling | Target |
|-------|------|---------|--------|
| **L1: Provisioning checks** | CLI smoke tests | `az cli` + Python | Azure resources exist and are configured correctly |
| **L2: E2E critical path** | Playwright E2E | `@playwright/test` against prod | Full operator flow: chat → detection → triage → HITL → Teams |
| **L3: Incident simulation** | Python scripts | `scripts/simulate-incidents/` | 7 synthetic scenarios through full agent pipeline |
| **L4: Observability** | Manual inspection + App Insights | Azure Portal / App Insights | OTel spans appear correctly |

### Test Inventory

| Test ID | File | Layer | What It Proves |
|---------|------|-------|----------------|
| E2E-002 | `e2e/e2e-incident-flow.spec.ts` | L2 | Full incident flow end-to-end |
| E2E-003 | `e2e/e2e-hitl-approval.spec.ts` | L2 | HITL approval via Teams/webhook |
| E2E-004 | `e2e/e2e-rbac.spec.ts` | L2 | Cross-subscription RBAC |
| E2E-005 | `e2e/e2e-sse-reconnect.spec.ts` | L2 | SSE reconnect with Last-Event-ID |
| E2E-006 | `e2e/e2e-teams-roundtrip.spec.ts` | L2 | Teams bot round-trip (new) |
| SIM-001 | `scripts/simulate-incidents/scenario_compute.py` | L3 | VM high CPU agent routing |
| SIM-002 | `scripts/simulate-incidents/scenario_network.py` | L3 | NSG block network agent routing |
| SIM-003 | `scripts/simulate-incidents/scenario_storage.py` | L3 | Storage quota storage agent routing |
| SIM-004 | `scripts/simulate-incidents/scenario_security.py` | L3 | Defender alert security agent routing |
| SIM-005 | `scripts/simulate-incidents/scenario_arc.py` | L3 | Arc disconnect arc agent routing |
| SIM-006 | `scripts/simulate-incidents/scenario_sre.py` | L3 | Multi-signal SLA breach sre agent routing |
| SIM-007 | `scripts/simulate-incidents/scenario_cross.py` | L3 | Cross-domain disk-full (compute + storage) |

### Pass/Fail Criteria

| Layer | Pass Condition | Fail Condition |
|-------|---------------|----------------|
| L1 | All `az` commands return expected values | Any BLOCKING gap remains after fix tasks |
| L2 | All E2E tests exit 0, no `test.skip()` remaining | Any E2E test fails or is still skipped |
| L3 | All 7 scenarios: `run_status == "completed"`, agent reply non-empty, cleanup exits 0 | Any scenario fails assertion or cleanup leaves orphaned records |
| L4 | `foundry.*`, `mcp.*`, `agent.*` spans visible in App Insights Transaction Search | No custom spans appear after code change deployed |

### CI Integration

```yaml
# Phase 8 validation pipeline (extend .github/workflows/staging-e2e-simulation.yml)
jobs:
  e2e-prod:
    # Run existing E2E suite against prod (no test.skip())
    env:
      PLAYWRIGHT_BASE_URL: ${{ vars.PROD_WEB_UI_URL }}
      API_GATEWAY_URL: ${{ vars.PROD_API_GATEWAY_URL }}

  simulation:
    # Run all 7 simulation scenarios
    run: |
      cd scripts/simulate-incidents
      pip install -r requirements.txt
      bash run-all.sh
    env:
      API_GATEWAY_URL: ${{ vars.PROD_API_GATEWAY_URL }}
```

### Validation Report

All findings are written to `.planning/phases/08-azure-validation-incident-simulation/08-VALIDATION-REPORT.md` using the schema:

```
| ID | Service | Description | Severity | Fix | Status |
```

- **BLOCKING** — Phase 8 cannot close until resolved
- **DEGRADED** — Feature broken; logged as backlog todo
- **COSMETIC** — Minor; logged as backlog todo
