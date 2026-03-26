# Phase 2 Manual Verification Checklist

**Platform:** Azure Agentic Platform (AAP)
**Phase:** 2 — Agent Core
**Status:** Pending operator sign-off
**Date:** ____________
**Verified by:** ____________

---

## Overview

This checklist verifies all 6 Phase 2 success criteria (SC-1 through SC-6) before
the phase is marked complete. Each criterion maps to specific ROADMAP requirements.
Complete each section in order — later criteria build on earlier ones.

**Prerequisites:**
- AAP infrastructure deployed to target environment (dev/staging)
- All 7 Container Apps running and healthy
- Azure CLI authenticated with Reader access
- Application Insights connected and receiving traces

---

## SC-1 — MCP Tool Allowlist Enforcement (AGENT-009)

**Requirement:** Every domain agent uses an explicit MCP tool allowlist with no wildcards.

### Automated Test

```bash
cd /path/to/azure-agentic-platform
python -m pytest agents/tests/integration/test_mcp_tools.py::TestMcpToolAllowlists -v
```

Expected: All tests PASS, no `@pytest.mark.skip` markers present.

### Manual Verification

1. Review each agent's `ALLOWED_MCP_TOOLS` list:

| Agent | File | Wildcard-free? | Non-empty? |
|-------|------|---------------|-----------|
| Compute | `agents/compute/tools.py` | [ ] | [ ] |
| Network | `agents/network/tools.py` | [ ] | [ ] |
| Storage | `agents/storage/tools.py` | [ ] | [ ] |
| Security | `agents/security/tools.py` | [ ] | [ ] |
| SRE | `agents/sre/tools.py` | [ ] | [ ] |
| Arc | `agents/arc/agent.py` | [ ] | [ ] (empty intentional) |

2. Container image security scan — no HIGH/CRITICAL CVEs:

```bash
# Run trivy image scan against each agent image
trivy image aapacr<env>.azurecr.io/aap/compute-agent:latest \
  --exit-code 1 --severity HIGH,CRITICAL

trivy image aapacr<env>.azurecr.io/aap/network-agent:latest \
  --exit-code 1 --severity HIGH,CRITICAL

trivy image aapacr<env>.azurecr.io/aap/storage-agent:latest \
  --exit-code 1 --severity HIGH,CRITICAL

trivy image aapacr<env>.azurecr.io/aap/security-agent:latest \
  --exit-code 1 --severity HIGH,CRITICAL

trivy image aapacr<env>.azurecr.io/aap/sre-agent:latest \
  --exit-code 1 --severity HIGH,CRITICAL

trivy image aapacr<env>.azurecr.io/aap/arc-agent:latest \
  --exit-code 1 --severity HIGH,CRITICAL

trivy image aapacr<env>.azurecr.io/aap/orchestrator-agent:latest \
  --exit-code 1 --severity HIGH,CRITICAL
```

**SC-1 Result:** [ ] PASS  [ ] FAIL
**Notes:** ____________

---

## SC-2 — Handoff Routing (AGENT-001, TRIAGE-001, DETECT-004)

**Requirement:** POST /api/v1/incidents with a synthetic payload creates a Foundry thread,
dispatches to the Orchestrator, and the Orchestrator routes to the correct domain agent.

### Automated Test

```bash
python -m pytest agents/tests/integration/test_handoff.py -v
```

Expected: All tests PASS — domain classification returns correct domain for all 6 resource types.

### Synthetic Incident Test Payloads

#### Payload 1 — Compute (High CPU)

```bash
curl -X POST https://<api-gateway-fqdn>/api/v1/incidents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "incident_id": "inc-sc2-compute-001",
    "severity": "Sev2",
    "title": "High CPU on vm-prod-01",
    "affected_resources": [
      "/subscriptions/<sub-id>/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
    ],
    "detection_rule": "high-cpu-alert",
    "kql_evidence": "Perf | where CounterName == \"% Processor Time\" | where CounterValue > 95"
  }'
```

Expected response: `{"thread_id": "<foundry-thread-id>", "routed_to": "compute-agent", ...}`

#### Payload 2 — Network (NSG Block)

```bash
curl -X POST https://<api-gateway-fqdn>/api/v1/incidents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "incident_id": "inc-sc2-network-001",
    "severity": "Sev2",
    "title": "NSG blocking inbound traffic",
    "affected_resources": [
      "/subscriptions/<sub-id>/resourceGroups/rg-prod/providers/Microsoft.Network/networkSecurityGroups/nsg-prod-01"
    ],
    "detection_rule": "nsg-block-alert"
  }'
```

Expected response: `{"routed_to": "network-agent", ...}`

#### Payload 3 — Arc (Connectivity Lost)

```bash
curl -X POST https://<api-gateway-fqdn>/api/v1/incidents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "incident_id": "inc-sc2-arc-001",
    "severity": "Sev3",
    "title": "Arc server connectivity lost",
    "affected_resources": [
      "/subscriptions/<sub-id>/resourceGroups/rg-arc/providers/Microsoft.HybridCompute/machines/arc-srv-01"
    ],
    "detection_rule": "arc-disconnect"
  }'
```

Expected response: `{"routed_to": "arc-agent", "stub_response": {"phase_available": 3}, ...}`

### Verification Steps

- [ ] Compute incident routes to `compute-agent` (verified in Foundry thread)
- [ ] Network incident routes to `network-agent`
- [ ] Storage incident routes to `storage-agent`
- [ ] Security incident routes to `security-agent`
- [ ] SRE incident (unknown resource type) routes to `sre-agent`
- [ ] Arc incident routes to `arc-agent` with stub response `phase_available: 3`
- [ ] All responses include `correlation_id` matching the `incident_id` submitted
- [ ] Foundry thread created and accessible in Azure AI Foundry portal

**SC-2 Result:** [ ] PASS  [ ] FAIL
**Notes:** ____________

---

## SC-3 — OTel Span Recording (AUDIT-001, AGENT-004)

**Requirement:** A domain agent calls at least one Azure MCP Server tool, returns a
structured response, and the tool call is logged as an OpenTelemetry span with
`agentId`, `toolName`, `toolParameters`, `outcome`, and `durationMs`.

### Automated Test

```bash
python -m pytest agents/tests/integration/test_mcp_tools.py::TestOtelSpanRecording -v
```

Expected: All tests PASS.

### Manual Verification — Application Insights

After submitting the SC-2 compute incident, run the following KQL query in
Application Insights to verify spans are present:

```kql
dependencies
| where timestamp > ago(30m)
| where customDimensions["aiops.tool_name"] != ""
| project
    timestamp,
    agent_id = tostring(customDimensions["aiops.agent_id"]),
    agent_name = tostring(customDimensions["aiops.agent_name"]),
    tool_name = tostring(customDimensions["aiops.tool_name"]),
    tool_parameters = tostring(customDimensions["aiops.tool_parameters"]),
    outcome = tostring(customDimensions["aiops.outcome"]),
    duration_ms = toint(customDimensions["aiops.duration_ms"]),
    correlation_id = tostring(customDimensions["aiops.correlation_id"]),
    thread_id = tostring(customDimensions["aiops.thread_id"])
| order by timestamp desc
| limit 20
```

### Required Span Attribute Checklist

For each tool call span, verify all 8 AUDIT-001 fields are present:

| Attribute | Present? | Non-empty? | agentId != "system"? |
|-----------|---------|-----------|---------------------|
| `aiops.agent_id` | [ ] | [ ] | [ ] |
| `aiops.agent_name` | [ ] | [ ] | N/A |
| `aiops.tool_name` | [ ] | [ ] | N/A |
| `aiops.tool_parameters` | [ ] | [ ] | N/A |
| `aiops.outcome` | [ ] | [ ] | N/A |
| `aiops.duration_ms` | [ ] | [ ] | N/A |
| `aiops.correlation_id` | [ ] | [ ] | N/A |
| `aiops.thread_id` | [ ] | [ ] | N/A |

**SC-3 Result:** [ ] PASS  [ ] FAIL
**Notes:** ____________

---

## SC-4 — Remediation Safety — No ARM Writes Without Approval (REMEDI-001)

**Requirement:** A synthetic remediation proposal is generated by the SRE agent and
confirmed NOT executed without explicit approval.

### Automated Test

```bash
python -m pytest agents/tests/integration/test_remediation.py -v
python -m pytest agents/tests/integration/test_triage.py::TestRemediationProposal -v
```

Expected: All tests PASS. `requires_approval: True` on all proposals regardless of risk level.

### Manual Verification — Activity Log Check

After submitting a remediation-triggering incident via SC-2, verify no ARM write
operations were made by any agent managed identity:

```bash
# Get managed identity principal IDs
COMPUTE_PRINCIPAL=$(az containerapp show \
  --name ca-compute-<env> \
  --resource-group <resource-group> \
  --query "identity.principalId" --output tsv)

SRE_PRINCIPAL=$(az containerapp show \
  --name ca-sre-<env> \
  --resource-group <resource-group> \
  --query "identity.principalId" --output tsv)

# Check activity log for ARM write operations (should return 0 entries)
az monitor activity-log list \
  --caller "${COMPUTE_PRINCIPAL}" \
  --start-time "$(date -u -v-1H '+%Y-%m-%dT%H:%M:%SZ')" \
  --query "[?httpRequest.method != 'GET' && httpRequest.method != 'HEAD']" \
  --output table

az monitor activity-log list \
  --caller "${SRE_PRINCIPAL}" \
  --start-time "$(date -u -v-1H '+%Y-%m-%dT%H:%M:%SZ')" \
  --query "[?httpRequest.method != 'GET' && httpRequest.method != 'HEAD']" \
  --output table
```

Expected: Zero entries returned (no PUT/POST/DELETE/PATCH operations from any agent identity).

### Remediation Proposal Verification

- [ ] SRE agent returns proposal dict (not execution result)
- [ ] Proposal contains all fields: `description`, `target_resources`, `estimated_impact`, `risk_level`, `reversibility`, `action_type`
- [ ] `requires_approval: True` on every proposal
- [ ] No `execute()` method exists on `RemediationProposal` class
- [ ] Zero ARM write operations recorded in Activity Log for agent identities

**SC-4 Result:** [ ] PASS  [ ] FAIL
**Notes:** ____________

---

## SC-5 — Session Budget Enforcement (AGENT-007)

**Requirement:** A session budget threshold of $5 is enforced. Sessions exceeding
the limit are aborted with a `budget_exceeded` status in Cosmos DB.

### Automated Test

```bash
python -m pytest agents/tests/integration/test_budget.py -v
```

Expected: All tests PASS. Budget exception raised at $5.05 when threshold is $5.00.
Max iterations (10) enforcement also verified.

### Manual Verification — Cosmos DB Record

After submitting an incident, verify the session record is created in Cosmos DB:

```bash
# Query session record via Azure CLI
az cosmosdb sql query \
  --account-name <cosmos-account-name> \
  --database-name <database-name> \
  --container-name sessions \
  --query-text "SELECT * FROM c WHERE c.incident_id = 'inc-sc2-compute-001'" \
  --resource-group <resource-group>
```

Expected fields in active session:

```json
{
  "id": "<session-id>",
  "incident_id": "inc-sc2-compute-001",
  "status": "active",
  "threshold_usd": 5.0,
  "max_iterations": 10,
  "total_cost_usd": <number>,
  "iteration_count": <number>,
  "abort_reason": null
}
```

### Budget Limit Test (Optional — requires test environment)

To verify budget enforcement in a live environment, set a low threshold via env var:

```bash
# Temporarily set a $0.01 threshold to trigger abort quickly
# (only do this in dev/test, never in staging/prod)
az containerapp update \
  --name ca-compute-dev \
  --resource-group <resource-group> \
  --set-env-vars BUDGET_THRESHOLD_USD=0.01

# Submit an incident and observe Cosmos DB record transitions to status: aborted
```

- [ ] Session record created in Cosmos DB on incident start
- [ ] `threshold_usd: 5.00` set correctly on all sessions
- [ ] `max_iterations: 10` set correctly on all sessions
- [ ] Session transitions to `status: aborted` when threshold exceeded
- [ ] `abort_reason` field populated with cost details on abort
- [ ] ETag-based optimistic concurrency used for all Cosmos DB writes

**SC-5 Result:** [ ] PASS  [ ] FAIL
**Notes:** ____________

---

## SC-6 — RBAC Least Privilege (INFRA-006, AUDIT-005, AGENT-008)

**Requirement:** All 7 agent managed identities have only the minimum required RBAC roles.
No agent has Owner, User Access Administrator, or any role beyond what D-14 specifies.

### Automated Verification Script

```bash
./scripts/verify-managed-identity.sh <resource-group> <environment>
```

Expected: `=== All RBAC checks PASSED ===`

The script (references INFRA-006, AUDIT-005, D-14) checks:
- Each Container App has a system-assigned managed identity
- Each identity has exactly the expected roles (no more, no less)
- No identity has `Owner` or `User Access Administrator`

### Expected Role Assignments (from D-14)

| Agent Container App | Expected Roles | Scope |
|---------------------|---------------|-------|
| `ca-orchestrator-<env>` | Reader | Platform subscription |
| `ca-compute-<env>` | Virtual Machine Contributor, Monitoring Reader | Compute subscription |
| `ca-network-<env>` | Network Contributor, Reader | Network subscription |
| `ca-storage-<env>` | Storage Blob Data Reader | All subscriptions |
| `ca-security-<env>` | Security Reader | All subscriptions |
| `ca-sre-<env>` | Reader, Monitoring Reader | All subscriptions |
| `ca-arc-<env>` | Contributor | Arc resource groups only |

### Manual Spot Check

```bash
# Verify orchestrator does NOT have Contributor or higher
ORCH_PRINCIPAL=$(az containerapp show \
  --name ca-orchestrator-<env> \
  --resource-group <resource-group> \
  --query "identity.principalId" --output tsv)

az role assignment list \
  --assignee "${ORCH_PRINCIPAL}" \
  --query "[].{role:roleDefinitionName, scope:scope}" \
  --output table
```

Expected: Only `Reader` and `Cosmos DB Built-in Data Contributor` assignments visible.

- [ ] `./scripts/verify-managed-identity.sh` exits with code 0
- [ ] No agent has `Owner` role
- [ ] No agent has `User Access Administrator` role
- [ ] Orchestrator has Reader only (no direct Azure resource write access)
- [ ] Arc agent scoped to Arc resource groups only (not full subscription)
- [ ] All agents have `Cosmos DB Built-in Data Contributor` for session tracking

**SC-6 Result:** [ ] PASS  [ ] FAIL
**Notes:** ____________

---

## Final Sign-off

| Criterion | Requirement | Result | Notes |
|-----------|-------------|--------|-------|
| SC-1 | MCP Tool Allowlist (AGENT-009) | [ ] PASS / [ ] FAIL | |
| SC-2 | Handoff Routing (DETECT-004) | [ ] PASS / [ ] FAIL | |
| SC-3 | OTel Span Recording (AUDIT-001) | [ ] PASS / [ ] FAIL | |
| SC-4 | Remediation Safety (REMEDI-001) | [ ] PASS / [ ] FAIL | |
| SC-5 | Budget Enforcement (AGENT-007) | [ ] PASS / [ ] FAIL | |
| SC-6 | RBAC Least Privilege (AGENT-008) | [ ] PASS / [ ] FAIL | |

**Overall Phase 2 Result:** [ ] PASS — All 6 criteria met  [ ] FAIL — See notes above

**Verified by:** ____________
**Date:** ____________
**Environment:** ____________
**Git SHA:** ____________
