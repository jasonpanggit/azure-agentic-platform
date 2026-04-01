# Phase 14: Production Stabilisation

---
phase: 14
name: Production Stabilisation
goal: Wire agents correctly, fix MCP tool groups, fix runbook RAG, deploy Arc MCP, remove hardcoded IDs, and restore Teams proactive alerting
depends_on: [13]
status: not_started
---

## Goal

Make the production deployment fully functional by resolving all known BLOCKING and HIGH-severity production blockers. After this phase, an operator can send a query to any domain (compute, network, storage, security, arc, sre, patch, eol) and receive a complete triage response that includes MCP tool calls, runbook citations, and — where applicable — remediation proposals routed through Teams for HITL approval.

## Milestones

| # | Milestone | Tasks | Priority |
|---|-----------|-------|----------|
| M1 | Agent Wiring & MCP Tool Groups | 14-01 through 14-04 | CRITICAL |
| M2 | Hardcoded ID Removal & Code Fixes | 14-05, 14-06 | CRITICAL |
| M3 | Arc MCP Server Real Deployment | 14-07 | CRITICAL |
| M4 | Runbook RAG & Observability Restoration | 14-08, 14-09 | HIGH |
| M5 | Teams Proactive Alerting | 14-10 | MEDIUM |
| M6 | Dependency Pinning & Security Hardening | 14-11, 14-12 | LOW–MEDIUM |

---

## Tasks

### Milestone 1: Agent Wiring & MCP Tool Groups (CRITICAL)

These tasks fix the core chat pipeline: the orchestrator must route to MCP-enabled agents, and each domain agent must have its required MCP tool groups registered in Foundry.

---

<task id="14-01">
<title>Re-provision orchestrator with MCP-enabled agent IDs</title>
<priority>CRITICAL</priority>
<complexity>M</complexity>
<type>operator + code</type>

**Problem:** The orchestrator's `connected_agent` tools point to agent instances that have NO MCP tool groups. Newer agent instances with MCP groups exist but the orchestrator doesn't reference them. (CONCERNS: GAP-001, Backlog F-09/F-10/F-11)

**Action:**
1. Run `scripts/provision-domain-agents.py --dry-run` to list current Foundry agent IDs and identify which agents have MCP tool groups attached
2. For each domain agent (compute, network, storage, security, sre, arc, patch, eol): verify the Foundry agent ID has the correct MCP tool groups via the Foundry portal or SDK
3. If an agent lacks MCP tool groups, either:
   - a. Register MCP tool groups on the existing agent (preferred), OR
   - b. Create a new agent with MCP tool groups and update the orchestrator to reference the new ID
4. Re-run `scripts/provision-domain-agents.py` with `--resource-group rg-aap-prod --orchestrator-app ca-orchestrator-prod` to update all `*_AGENT_ID` env vars on the orchestrator Container App
5. Verify: `az containerapp show --name ca-orchestrator-prod` shows all 8 `*_AGENT_ID` env vars pointing to MCP-enabled agents

**Acceptance Criteria:**
- [ ] All 8 domain agent IDs on `ca-orchestrator-prod` reference agents with MCP tool groups
- [ ] `provision-domain-agents.py` output shows all 8 agents with correct IDs
- [ ] Orchestrator's `connected_agent` tools in Foundry match the env var IDs

**Files Modified:**
- `scripts/domain-agent-ids.json` (updated output)
- Container App env vars (operator action)
</task>

---

<task id="14-02">
<title>Register Microsoft.Network MCP tool group on Foundry project</title>
<priority>CRITICAL</priority>
<complexity>S</complexity>
<type>operator</type>

**Problem:** Network agent returns "tool group was not found" for NSG queries. The `Microsoft.Network` tool group is not registered as an MCP connection on the Foundry project. (Backlog F-09)

**Action:**
1. In the Foundry portal or via `azapi`/SDK, add the `Microsoft.Network` tool group to the Azure MCP Server connection on the Foundry project
2. Verify: send a network query through the chat ("list NSGs in subscription X") and confirm the network agent invokes MCP tools without "tool group not found" errors

**Acceptance Criteria:**
- [ ] `Microsoft.Network` tool group visible in Foundry project MCP connections
- [ ] Network agent query returns NSG data (not "tool group was not found")
</task>

---

<task id="14-03">
<title>Register Microsoft.Security MCP tool group on Foundry project</title>
<priority>CRITICAL</priority>
<complexity>S</complexity>
<type>operator</type>

**Problem:** Security agent returns "tool group was not found" for Defender alerts. (Backlog F-10)

**Action:**
1. Add the `Microsoft.Security` tool group to the Azure MCP Server MCP connection on the Foundry project
2. Verify: send a security query ("show Defender alerts for subscription X") and confirm the security agent invokes MCP tools

**Acceptance Criteria:**
- [ ] `Microsoft.Security` tool group visible in Foundry project MCP connections
- [ ] Security agent query returns Defender data (not "tool group not found")
</task>

---

<task id="14-04">
<title>Register Arc MCP + SRE cross-domain tool groups on Foundry project</title>
<priority>CRITICAL</priority>
<complexity>S</complexity>
<type>operator</type>

**Problem:** Arc and SRE agents fall back to the compute tool surface because their dedicated MCP tool groups are not registered. (Backlog F-11)

**Action:**
1. Register the custom Arc MCP Server (`ca-arc-mcp-server-prod` internal URL) as an MCP connection on the Foundry project
2. Add SRE agent cross-domain tool access (monitor, Log Analytics, compute, network, storage) to the Foundry project MCP connections
3. Verify: arc query ("list Arc servers") uses Arc MCP tools; SRE query ("check SLA for resource X") uses cross-domain tools

**Acceptance Criteria:**
- [ ] Arc MCP Server registered as MCP connection on Foundry project
- [ ] SRE agent has access to monitor + Log Analytics MCP tool groups
- [ ] Arc agent query uses Arc MCP tools (not compute fallback)
- [ ] SRE agent query uses cross-domain tools

</task>

---

### Milestone 2: Hardcoded ID Removal & Code Fixes (CRITICAL)

---

<task id="14-05">
<title>Replace hardcoded Foundry agent IDs in chat.py with env vars</title>
<priority>CRITICAL</priority>
<complexity>M</complexity>
<type>code</type>

**Problem:** `services/api-gateway/chat.py:229-238` has 8 hardcoded Foundry agent IDs in `_approve_pending_subrun_mcp_calls()`. These break silently if agents are re-created. (DEBT-002)

**Action:**
1. Read the existing `*_AGENT_ID` env vars at module load time (same pattern used by the orchestrator routing in `chat.py`)
2. Build `domain_agent_ids` set from env vars:
   ```python
   domain_agent_ids = {
       v for v in (
           os.environ.get("COMPUTE_AGENT_ID"),
           os.environ.get("NETWORK_AGENT_ID"),
           os.environ.get("STORAGE_AGENT_ID"),
           os.environ.get("SECURITY_AGENT_ID"),
           os.environ.get("SRE_AGENT_ID"),
           os.environ.get("ARC_AGENT_ID"),
           os.environ.get("PATCH_AGENT_ID"),
           os.environ.get("EOL_AGENT_ID"),
       ) if v
   }
   ```
3. Add a warning log if `domain_agent_ids` is empty at startup
4. Remove all 8 hardcoded `asst_*` strings
5. Update unit tests in `services/api-gateway/tests/` to mock the env vars
6. Ensure the `*_AGENT_ID` env vars are set on `ca-api-gateway-prod` (not just on `ca-orchestrator-prod`) — update Terraform `agent-apps` module if needed

**Acceptance Criteria:**
- [ ] Zero hardcoded `asst_*` strings in `chat.py`
- [ ] `domain_agent_ids` built from env vars at module level
- [ ] Warning logged if no agent IDs configured
- [ ] Existing unit tests updated and passing
- [ ] `ca-api-gateway-prod` has all 8 `*_AGENT_ID` env vars set

**Files Modified:**
- `services/api-gateway/chat.py`
- `services/api-gateway/tests/test_chat.py` (or relevant test file)
- `terraform/modules/agent-apps/main.tf` (if gateway env vars need adding)
</task>

---

<task id="14-06">
<title>Fix BUG-001: NameError `outputs` in chat.py tool submission</title>
<priority>CRITICAL</priority>
<complexity>S</complexity>
<type>code</type>

**Problem:** `services/api-gateway/chat.py:412` references `outputs` but the correct variable name is `tool_outputs`. The NameError is silently caught, causing the orchestrator's own function tool runs to stall until timeout. (BUG-001)

**Action:**
1. Verify the bug still exists at the specified line (the CONCERNS.md says "Not fixed" as of 2026-04-01)
2. Fix the variable name: `tool_outputs=outputs` -> `tool_outputs=tool_outputs`
3. Add a unit test that exercises the `submit_tool_outputs` code path and asserts no NameError

**Acceptance Criteria:**
- [ ] `tool_outputs=tool_outputs` on the `submit_tool_outputs` call
- [ ] Unit test covers the submit_tool_outputs path
- [ ] No NameError in logs when orchestrator hits `requires_action`

**Files Modified:**
- `services/api-gateway/chat.py`
- `services/api-gateway/tests/test_chat.py`

> **Note:** Per CONCERNS.md, this bug is at line 412. However, the code read at offset 409 shows `tool_outputs=tool_outputs` (correct). The bug may exist on a different code path for the orchestrator's own run (not the sub-run). Verify both code paths.
</task>

---

### Milestone 3: Arc MCP Server Real Deployment (CRITICAL)

---

<task id="14-07">
<title>Deploy real Arc MCP Server image and flip placeholder flag</title>
<priority>CRITICAL</priority>
<complexity>M</complexity>
<type>code + operator</type>

**Problem:** `terraform/modules/arc-mcp-server/` has `use_placeholder_image = true` in prod. The Container App runs the Microsoft hello-world placeholder, not the real arc-mcp-server. (DEP-003, GAP-009)

**Action:**
1. Build the arc-mcp-server Docker image:
   ```bash
   docker build -t <acr>.azurecr.io/services/arc-mcp-server:latest \
     --platform linux/amd64 -f services/arc-mcp-server/Dockerfile .
   ```
2. Push to ACR:
   ```bash
   az acr login --name <acr>
   docker push <acr>.azurecr.io/services/arc-mcp-server:latest
   ```
3. In `terraform/envs/prod/main.tf`, change `use_placeholder_image = true` to `use_placeholder_image = false` for the `arc_mcp_server` module
4. Run `terraform apply` for prod
5. Verify: `az containerapp show --name ca-arc-mcp-server-prod` shows the real image, health endpoint returns 200

**Acceptance Criteria:**
- [ ] `terraform/envs/prod/main.tf` arc_mcp_server module has `use_placeholder_image = false`
- [ ] ACR contains `services/arc-mcp-server:latest` image
- [ ] `ca-arc-mcp-server-prod` Container App running real image
- [ ] Health endpoint returns 200
- [ ] Arc agent queries route through Arc MCP Server (not compute fallback)

**Files Modified:**
- `terraform/envs/prod/main.tf`
</task>

---

### Milestone 4: Runbook RAG & Observability Restoration (HIGH)

---

<task id="14-08">
<title>Fix runbook RAG: set PGVECTOR_CONNECTION_STRING and seed prod</title>
<priority>HIGH</priority>
<complexity>M</complexity>
<type>operator + code</type>

**Problem:** `GET /api/v1/runbooks/search` returns 500 in prod. `PGVECTOR_CONNECTION_STRING` is not set on `ca-api-gateway-prod`, and prod runbooks have never been seeded. (BUG-002, Backlog F-02, GAP-003)

**Action:**
1. Retrieve the PostgreSQL Flexible Server connection string from the Terraform output or Azure Portal
2. Set `PGVECTOR_CONNECTION_STRING` on `ca-api-gateway-prod`:
   ```bash
   az containerapp update --name ca-api-gateway-prod --resource-group rg-aap-prod \
     --set-env-vars "PGVECTOR_CONNECTION_STRING=<connection_string>"
   ```
3. Add temporary firewall rule for runner IP on PostgreSQL (same pattern as Phase 1 CI):
   ```bash
   az postgres flexible-server firewall-rule create ...
   ```
4. Run `scripts/seed-runbooks/seed.py` against prod PostgreSQL
5. Run `scripts/seed-runbooks/validate.py` to confirm SIMILARITY_THRESHOLD=0.75 met for all 12 domain queries
6. Remove temporary firewall rule
7. Verify: `GET /api/v1/runbooks/search?q=vm+high+cpu&domain=compute` returns 200 with results

**Acceptance Criteria:**
- [ ] `PGVECTOR_CONNECTION_STRING` set on `ca-api-gateway-prod`
- [ ] 60 runbooks seeded in prod PostgreSQL (10 per domain x 6 domains)
- [ ] `validate.py` passes with >= 0.75 cosine similarity for all 12 queries
- [ ] `GET /api/v1/runbooks/search` returns 200 with relevant results
- [ ] Agent triage responses cite runbooks

**Files Modified:**
- Container App env vars (operator action)
- No code changes — seeding uses existing `scripts/seed-runbooks/seed.py`
</task>

---

<task id="14-09">
<title>Validate observability: App Insights connection string + OTel spans</title>
<priority>HIGH</priority>
<complexity>S</complexity>
<type>operator</type>

**Problem:** Observability tab may show no data. `APPLICATIONINSIGHTS_CONNECTION_STRING` may not be set on all Container Apps. Manual OTel spans from Phase 8 have never been deployed. (GAP-002, Backlog OTel)

**Action:**
1. Verify `APPLICATIONINSIGHTS_CONNECTION_STRING` is set on all 3 frontend/gateway Container Apps:
   - `ca-api-gateway-prod`
   - `ca-web-ui-prod`
   - `ca-teams-bot-prod`
2. Verify `LOG_ANALYTICS_WORKSPACE_ID` is set on `ca-web-ui-prod` (Backlog Step 3)
3. Rebuild and redeploy `ca-api-gateway-prod` with the latest code (includes `instrumentation.py` manual OTel spans from Phase 8):
   ```bash
   docker build -t <acr>.azurecr.io/services/api-gateway:latest ...
   docker push ...
   az containerapp update --name ca-api-gateway-prod --image <acr>.azurecr.io/services/api-gateway:latest
   ```
4. Verify: App Insights Transaction Search shows `foundry.*`, `mcp.*`, `agent.*` spans within 5 minutes of a chat query

**Acceptance Criteria:**
- [ ] `APPLICATIONINSIGHTS_CONNECTION_STRING` set on all 3 Container Apps
- [ ] `LOG_ANALYTICS_WORKSPACE_ID` set on `ca-web-ui-prod`
- [ ] OTel spans visible in App Insights after a test chat query
- [ ] Observability tab in web UI shows metric data

**Files Modified:**
- Container App env vars and image updates (operator action)
</task>

---

### Milestone 5: Teams Proactive Alerting (MEDIUM)

---

<task id="14-10">
<title>Provision Azure Bot Service in Terraform and wire TEAMS_CHANNEL_ID</title>
<priority>MEDIUM</priority>
<complexity>L</complexity>
<type>code + operator</type>

**Problem:** Azure Bot Service is not in Terraform. `TEAMS_CHANNEL_ID` is empty on `ca-teams-bot-prod`. Proactive detection-plane alerts to Teams channels are silently skipped. (Backlog F-04, GAP-004)

**Action:**
1. Add `azurerm_bot_service_azure_bot` resource to Terraform (new module `terraform/modules/bot-service/` or extend `agent-apps`):
   - Bot handle: `aap-bot-prod`
   - Messaging endpoint: `https://ca-teams-bot-prod.<env>.azurecontainerapps.io/api/messages`
   - Microsoft App ID: from existing Entra app registration
   - SKU: F0 (free for dev/staging, S1 for prod if needed)
   - Teams channel enabled
2. Register the bot in the target Teams channel (operator action via Teams admin center)
3. Set `TEAMS_CHANNEL_ID` on `ca-teams-bot-prod`:
   ```bash
   az containerapp update --name ca-teams-bot-prod --resource-group rg-aap-prod \
     --set-env-vars "TEAMS_CHANNEL_ID=<channel_id>"
   ```
4. Verify: trigger a synthetic alert via `POST /api/v1/incidents` and confirm an Adaptive Card appears in the Teams channel within 10 seconds

**Acceptance Criteria:**
- [ ] `azurerm_bot_service_azure_bot` in Terraform, `terraform plan` clean
- [ ] Bot registered and installed in target Teams channel
- [ ] `TEAMS_CHANNEL_ID` set on `ca-teams-bot-prod`
- [ ] Synthetic alert produces Adaptive Card in Teams channel
- [ ] Reactive chat (user message -> bot reply) also works

**Files Modified:**
- `terraform/modules/bot-service/` (new module) or `terraform/modules/agent-apps/main.tf`
- `terraform/envs/prod/main.tf`
- Container App env vars (operator action)
</task>

---

### Milestone 6: Dependency Pinning & Security Hardening (LOW-MEDIUM)

---

<task id="14-11">
<title>Pin azure-ai-agentserver-agentframework version</title>
<priority>LOW</priority>
<complexity>S</complexity>
<type>code</type>

**Problem:** `agents/requirements-base.txt` line 19 has `azure-ai-agentserver-agentframework==1.0.0b15` but the CONCERNS.md and original brief flag it as unpinned. Verify current state; if already pinned to `1.0.0b15`, this is a no-op. If any agent Dockerfile or requirements file overrides without a pin, fix it. (DEP-005)

**Action:**
1. Grep all `requirements*.txt` and `Dockerfile` files for `azure-ai-agentserver-agentframework`
2. Verify every occurrence has `==1.0.0b15` (or equivalent exact pin)
3. If any file lacks a version specifier, add `==1.0.0b15`
4. Run `pip install --dry-run` to verify resolution

**Acceptance Criteria:**
- [ ] Every `requirements*.txt` referencing `azure-ai-agentserver-agentframework` has an exact version pin
- [ ] No `Dockerfile` installs this package without a version constraint
- [ ] `pip install --dry-run` resolves to `1.0.0b15` consistently

**Files Modified:**
- `agents/requirements-base.txt` (verify/update)
- Any agent-specific `requirements.txt` that overrides
</task>

---

<task id="14-12">
<title>Add Entra auth to Arc MCP Server (replace --dangerously-disable-http-incoming-auth)</title>
<priority>MEDIUM</priority>
<complexity>L</complexity>
<type>code</type>

**Problem:** The custom Arc MCP Server has no authentication. The `--dangerously-disable-http-incoming-auth` flag is for dev only. Since the Arc MCP Server is internal-only (no public ingress), the risk is lower, but defense-in-depth requires auth. (SEC-001 is for the Azure MCP Server, but the same principle applies to Arc MCP.)

**Action:**
1. Create an Entra app registration for the Arc MCP Server (or reuse the Foundry project's managed identity)
2. Add middleware to the FastMCP server that validates Entra JWT tokens:
   - Validate `iss`, `aud`, `exp` claims
   - Accept tokens from the agent Container Apps' managed identities
3. Update the Arc agent's MCP client to acquire a token before calling the Arc MCP Server
4. Remove `--dangerously-disable-http-incoming-auth` from the Arc MCP Server Dockerfile (if present)
5. Add unit tests for the auth middleware

**Acceptance Criteria:**
- [ ] Arc MCP Server rejects unauthenticated requests with 401
- [ ] Arc agent acquires token and successfully calls Arc MCP tools
- [ ] No `--dangerously-disable-http-incoming-auth` flag in any production Dockerfile
- [ ] Unit tests for auth middleware pass

**Files Modified:**
- `services/arc-mcp-server/` (auth middleware)
- `agents/arc/` (MCP client token acquisition)
- `services/arc-mcp-server/Dockerfile`
- `services/arc-mcp-server/tests/`
</task>

---

## Execution Order

```
Week 1                          Week 2                          Week 3
├───────────────────────┤├───────────────────────┤├───────────────────────┤

M1: Agent Wiring (14-01..04)    M4: Runbook RAG (14-08)         M5: Teams Bot (14-10)
 ├─ 14-01 re-provision orch.    ├─ 14-08 pgvector + seed        ├─ 14-10 Bot Service TF
 ├─ 14-02 network MCP           └─ 14-09 observability          └─ verify proactive alerts
 ├─ 14-03 security MCP
 └─ 14-04 arc/sre MCP          M6: Pins & Auth (14-11..12)
                                 ├─ 14-11 pin agentserver
M2: Code Fixes (14-05..06)      └─ 14-12 arc MCP auth
 ├─ 14-05 env var agent IDs
 └─ 14-06 fix NameError

M3: Arc MCP Deploy (14-07)
 └─ 14-07 flip placeholder
```

**Parallelism:**
- M1 tasks 14-02, 14-03, 14-04 can run in parallel (all are Foundry MCP connection registrations)
- M2 tasks 14-05 and 14-06 are independent code changes, can run in parallel
- M3 depends on M1/14-04 (Arc MCP tools must be registered after the server is deployed)
- M4 and M6 are independent of each other and of M1/M2/M3 once code is deployed

## Success Criteria (Phase-Level)

1. **All domain agents respond with MCP tool calls:** A chat query to each of the 8 domains (compute, network, storage, security, arc, sre, patch, eol) produces a triage response that includes at least one MCP tool call — no "tool group not found" errors.
2. **Runbook RAG functional:** `GET /api/v1/runbooks/search` returns 200 with relevant results; agent triage responses cite runbooks.
3. **Arc MCP Server live:** `ca-arc-mcp-server-prod` runs the real image; Arc agent queries route through Arc MCP tools.
4. **No hardcoded agent IDs:** Zero `asst_*` strings in `chat.py`; all agent IDs driven by env vars.
5. **BUG-001 fixed:** Orchestrator function tool submissions succeed without NameError.
6. **Teams proactive alerts work:** A synthetic alert produces an Adaptive Card in the configured Teams channel.
7. **Observability data flowing:** OTel spans visible in App Insights; Observability tab shows metrics.

## Risk Register

| Risk | Mitigation |
|------|------------|
| Re-provisioning orchestrator breaks existing threads | New threads only; existing threads will fail gracefully (already broken) |
| MCP tool group registration API changes (Foundry preview) | Pin to current API version; document exact registration steps |
| Arc MCP Server image build fails on ARM64 dev machines | Build with `--platform linux/amd64` explicitly |
| PostgreSQL firewall rule left open after seeding | Wrap in try/finally; validate removal |
| Bot Service Terraform conflicts with manual registration | Import existing resource if already created manually |
