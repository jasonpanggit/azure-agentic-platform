# Phase 3: Arc MCP Server — Verification Checklist

> **Date:** Filled in at verification time
> **Verifier:** _____________
> **Environment:** dev / staging / prod

This checklist maps directly to the 6 Phase 3 Success Criteria in ROADMAP.md.
Each item must be checked before Phase 3 is declared complete.

---

## Pre-Conditions

- [ ] Arc MCP Server image is built and pushed to ACR (`arc-mcp-server:latest`)
- [ ] `terraform apply` completed without errors for `module.arc_mcp_server` in dev env
- [ ] `ca-arc-mcp-server-dev` Container App is in Running state
- [ ] Arc Agent Container App (`ca-arc-dev`) has been redeployed with `ARC_MCP_SERVER_URL` env var set

---

## SC-1: Internal Deployment (AGENT-005)

> **Criteria:** Arc MCP Server Container App is deployed as internal (no public ingress);
> Arc Agent calls `arc_servers_list` without public internet egress.

- [ ] Verify Container App `ca-arc-mcp-server-dev` has `external_enabled = false` in Azure portal
- [ ] Verify `ARC_MCP_SERVER_URL` on Arc Agent Container App points to internal FQDN
  (e.g., `http://ca-arc-mcp-server-dev.{env-domain}/mcp` — NOT a public hostname)
- [ ] Run `./scripts/verify-arc-connectivity.sh` from within the Container Apps environment
  ```bash
  export ARC_MCP_SERVER_URL="http://ca-arc-mcp-server-dev.{env-domain}/mcp"
  ./scripts/verify-arc-connectivity.sh
  ```
  Expected: `PASS: MCP initialize handshake successful`

**SC-1 Status:** [ ] PASS / [ ] FAIL

---

## SC-2: Pagination Exhaustion (AGENT-006)

> **Criteria:** `arc_servers_list` and `arc_k8s_list` exhaust all nextLink pages;
> `total_count` matches ARM count.

- [ ] Run pagination unit tests (must pass with 0 failures):
  ```bash
  pytest services/arc-mcp-server/tests/test_pagination.py -m unit -v
  ```
  Expected: All tests pass, including `test_arc_servers_list_120_total_count`
  and `test_arc_k8s_list_105_total_count`

- [ ] Verify `total_count` invariant check passes:
  ```bash
  pytest services/arc-mcp-server/tests/test_pagination.py -k "total_count_equals_len" -v
  ```

- [ ] Against real Azure subscription (if available): call `arc_servers_list` and compare
  `total_count` to `az connectedmachine list --subscription {sub_id} --query 'length(@)' -o tsv`

**SC-2 Status:** [ ] PASS / [ ] FAIL

---

## SC-3: All Three Arc Resource Types Covered (AGENT-005)

> **Criteria:** Tools cover HybridComputeManagementClient, ConnectedKubernetesClient,
> and AzureArcDataManagementClient; each has list + get; all Pydantic-validated.

- [ ] Run tool discovery via verify script:
  ```bash
  ./scripts/verify-arc-connectivity.sh
  ```
  Expected: `PASS: All 9 required tools registered`

- [ ] Verify all tools are defined in `server.py`:
  ```bash
  grep -c "@mcp.tool()" services/arc-mcp-server/server.py
  ```
  Expected: Output >= 9

- [ ] Verify Pydantic models exist for all resource types:
  ```bash
  grep -c "class Arc.*BaseModel" services/arc-mcp-server/models.py
  ```
  Expected: >= 8 model classes

- [ ] Run Arc Servers unit tests:
  ```bash
  pytest services/arc-mcp-server/tests/test_arc_servers.py -m unit -v
  ```
  Expected: All tests pass

- [ ] Run Arc K8s unit tests:
  ```bash
  pytest services/arc-mcp-server/tests/test_arc_k8s.py -m unit -v
  ```
  Expected: All tests pass

- [ ] Run Arc Data tests:
  ```bash
  pytest services/arc-mcp-server/tests/test_arc_data.py -m unit -v
  ```
  Expected: All tests pass

**SC-3 Status:** [ ] PASS / [ ] FAIL

---

## SC-4: Arc Agent TRIAGE-006 Workflow (TRIAGE-006)

> **Criteria:** Arc Agent performs complete pre-triage: connectivity → extension health
> → GitOps → structured triage summary before any remediation proposal.

- [ ] Verify Arc Agent system prompt contains all 5 workflow steps:
  ```bash
  grep -c "### Step" agents/arc/agent.py
  ```
  Expected: >= 5

- [ ] Verify Arc Agent system prompt references all TRIAGE-006 tools:
  ```bash
  grep -q "arc_servers_list" agents/arc/agent.py && echo PASS
  grep -q "arc_extensions_list" agents/arc/agent.py && echo PASS
  grep -q "arc_k8s_gitops_status" agents/arc/agent.py && echo PASS
  ```
  Expected: All 3 PASS

- [ ] Run Arc triage integration tests:
  ```bash
  pytest agents/tests/integration/test_arc_triage.py -m integration -v
  ```
  Expected: All tests pass, including `test_arc_triage_workflow_produces_diagnosis`

- [ ] Verify `ALLOWED_MCP_TOOLS` is non-empty:
  ```bash
  python3 -c "
  import sys; sys.path.insert(0, '.')
  from agents.arc.tools import ALLOWED_MCP_TOOLS
  assert len(ALLOWED_MCP_TOOLS) >= 9, f'Expected >= 9 tools, got {len(ALLOWED_MCP_TOOLS)}'
  print(f'PASS: {len(ALLOWED_MCP_TOOLS)} MCP tools configured')
  "
  ```

**SC-4 Status:** [ ] PASS / [ ] FAIL

---

## SC-5: Playwright E2E Pagination Test (E2E-006)

> **Criteria:** Playwright E2E test with >100 seeded servers confirms total_count
> matches, all pages exhausted; runs in CI and blocks merge on failure.

- [ ] E2E test file exists:
  ```bash
  test -f e2e/arc-mcp-server.spec.ts && echo PASS
  ```

- [ ] CI workflow includes arc-mcp-server build and unit tests:
  ```bash
  test -f .github/workflows/arc-mcp-server-build.yml && echo PASS
  grep -q "cov-fail-under=80" .github/workflows/arc-mcp-server-build.yml && echo PASS
  ```

- [ ] Run E2E test (requires ARC_MCP_SERVER_URL pointing to a seeded environment):
  ```bash
  export ARC_MCP_SERVER_URL="http://ca-arc-mcp-server-dev.{env-domain}/mcp"
  export ARC_SEEDED_COUNT=120
  npx playwright test e2e/arc-mcp-server.spec.ts --reporter=list
  ```
  Expected: `arc_servers_list exhausts pagination and returns total_count >= 100` PASSES

**SC-5 Status:** [ ] PASS / [ ] FAIL

---

## SC-6: Prolonged Disconnection Alert (MONITOR-004)

> **Criteria:** Prolonged Arc server disconnection triggers alert via POST /api/v1/incidents;
> Arc Agent receives it, opens triage thread, cites last heartbeat and connectivity duration.

- [ ] Verify disconnection detection logic:
  ```bash
  pytest services/arc-mcp-server/tests/test_arc_servers.py -k "disconnect" -m unit -v
  ```
  Expected: `test_prolonged_disconnect_flagged` and `test_recent_disconnect_not_flagged` PASS

- [ ] Verify alert payload structure in integration test:
  ```bash
  pytest agents/tests/integration/test_arc_triage.py -k "alert" -m integration -v
  ```
  Expected: `test_prolonged_disconnection_triggers_alert` PASS

- [ ] Verify `ARC_DISCONNECT_ALERT_HOURS` env var is configurable (default=1):
  ```bash
  grep -q "ARC_DISCONNECT_ALERT_HOURS" services/arc-mcp-server/tools/arc_servers.py && echo PASS
  grep -q "ARC_DISCONNECT_ALERT_HOURS" terraform/modules/arc-mcp-server/main.tf && echo PASS
  ```

**SC-6 Status:** [ ] PASS / [ ] FAIL

---

## Final Sign-off

| SC | Criteria | Status |
|----|----------|--------|
| SC-1 | Internal deployment, no public egress | [ ] PASS / [ ] FAIL |
| SC-2 | Pagination exhaustion, total_count matches | [ ] PASS / [ ] FAIL |
| SC-3 | All 3 Arc resource types, list+get, Pydantic | [ ] PASS / [ ] FAIL |
| SC-4 | TRIAGE-006 workflow, 5 steps, structured summary | [ ] PASS / [ ] FAIL |
| SC-5 | Playwright E2E, >100 servers, CI blocks on failure | [ ] PASS / [ ] FAIL |
| SC-6 | Prolonged disconnection alert, last heartbeat cited | [ ] PASS / [ ] FAIL |

**Phase 3 Complete:** [ ] YES — All 6 SC items PASS
**Phase 3 Blocked:** [ ] NO — See failing items above

---

*Generated by: 03-04-PLAN.md — Phase 3 Arc MCP Server*
*Requirements: AGENT-005, AGENT-006, MONITOR-004, MONITOR-005, MONITOR-006, TRIAGE-006, E2E-006*
