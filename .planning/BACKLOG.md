# AAP Backlog

> Backlog items logged from validation findings, deferred decisions, and phase closeout tasks.
> Items are sourced from VALIDATION-REPORT.md findings. Add new items at the top of each section.

---

## BLOCKING — Must Resolve Before Phase 8 Can Close

These items are Phase 8 BLOCKING findings. Phase 8 validation status is FAIL until resolved.

- [ ] **[Phase 8 F-01] Foundry / API Gateway: Grant Azure AI Developer RBAC to gateway MI**
  - Source: 08-VALIDATION-REPORT.md finding F-01
  - Severity: BLOCKING
  - Detail: MI `69e05934-1feb-44d4-8fd2-30373f83ccec` missing `Azure AI Developer` role on Foundry account `foundry-aap-prod`. Blocks Foundry API calls from gateway, E2E-002 triage polling, and SSE event generation.
  - Fix: `az role assignment create --assignee 69e05934-1feb-44d4-8fd2-30373f83ccec --role "Azure AI Developer" --scope /subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/foundry-aap-prod`

- [ ] **[Phase 8 F-02] API Gateway / Runbook RAG: Fix GET /api/v1/runbooks/search returning 500**
  - Source: 08-VALIDATION-REPORT.md finding F-02
  - Severity: BLOCKING
  - Detail: PostgreSQL pgvector search fails — either `PGVECTOR_CONNECTION_STRING` env var not set on `ca-api-gateway-prod`, or prod runbooks not seeded.
  - Fix: 1. Verify `PGVECTOR_CONNECTION_STRING` env var on `ca-api-gateway-prod`. 2. Run `scripts/seed-runbooks/seed.py` against prod PostgreSQL.

---

## DEGRADED — Platform Functional But Feature Broken

These items are Phase 8 DEGRADED findings. Platform operates; each item represents a broken feature or incomplete configuration.

- [ ] **[Phase 8 F-03] API Gateway: Lock CORS from wildcard to explicit prod origin**
  - Source: 08-VALIDATION-REPORT.md finding F-03
  - Severity: DEGRADED
  - Detail: `CORS_ALLOWED_ORIGINS=*` on prod. Security risk for credential-bearing cross-origin requests from web UI.
  - Fix: `az containerapp update --name ca-api-gateway-prod --resource-group rg-aap-prod --set-env-vars "CORS_ALLOWED_ORIGINS=https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"`

- [ ] **[Phase 8 F-04] Teams Bot: Register Azure Bot Service**
  - Source: 08-VALIDATION-REPORT.md finding F-04
  - Severity: DEGRADED
  - Detail: Bot Service not registered in Azure. Teams integration cannot receive proactive alerts or handle user messages. Web UI chat unaffected.
  - Fix: Complete MANUAL-SETUP.md section "Teams Bot Registration": create bot channel registration, set messaging endpoint, configure bot credentials.

- [ ] **[Phase 8 F-05] CI / E2E: Add GitHub secrets for Entra-authenticated E2E runs**
  - Source: 08-VALIDATION-REPORT.md finding F-05
  - Severity: DEGRADED
  - Detail: `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_API_AUDIENCE` not configured in GitHub Actions `staging` environment. E2E CI uses dev-mode auth only.
  - Fix: Add secrets to GitHub Actions environment `staging` via repository settings. Values from service principal in `configure-orchestrator.py`.

- [ ] **[Phase 8 F-06] Arc MCP Server / E2E: Update arc-mcp-server.spec.ts to use E2E_ARC_MCP_URL**
  - Source: 08-VALIDATION-REPORT.md finding F-06
  - Severity: DEGRADED
  - Detail: `arc-mcp-server.spec.ts` hardcodes `localhost:8080` — tests fail in prod.
  - Fix: Update `e2e/arc-mcp-server.spec.ts` to read `process.env.E2E_ARC_MCP_URL || 'http://localhost:8080'`. Add `E2E_ARC_MCP_URL` pointing to `ca-arc-mcp-server-prod` internal URL.

- [ ] **[Phase 8 F-07] API Gateway: Add 404 handler in approvals.py for missing approval records**
  - Source: 08-VALIDATION-REPORT.md finding F-07
  - Severity: DEGRADED
  - Detail: Non-existent `approval_id` in `GET /api/v1/approvals/{id}/approve` raises unhandled exception returning 500. Should return 404.
  - Fix: Add `try/except` or pre-check in `approvals.py`: `return JSONResponse({"detail": "Approval not found"}, status_code=404)`.

- [ ] **[Phase 8 F-08] SSE Reconnect E2E: Fix e2e-sse-reconnect.spec.ts sequence-ID test**
  - Source: 08-VALIDATION-REPORT.md finding F-08
  - Severity: DEGRADED
  - Detail: Test "SSE stream delivers events with sequence IDs" fails — `response.ok` evaluates false; dev-mode auth doesn't trigger real SSE events.
  - Fix: Depends on F-01 RBAC fix for real SSE events. Alternatively add local SSE mock for dev-mode path. Investigate if stream redirects or auth rejected at SSE level.

- [ ] **[Phase 8 F-09] Azure MCP / Network Agent: Add Microsoft.Network tool group to Foundry MCP connection**
  - Source: 08-VALIDATION-REPORT.md finding F-09
  - Severity: DEGRADED
  - Detail: Network agent replies "tool group was not found" for NSG queries. Azure MCP network tool group not configured as MCP connection on Foundry orchestrator.
  - Fix: Add `Microsoft.Network` tool group to Azure MCP Server MCP connection on Foundry project. Verify all required tool groups (compute, network, storage, security, monitor) are connected.

- [ ] **[Phase 8 F-10] Azure MCP / Security Agent: Add Microsoft.Security tool group to Foundry MCP connection**
  - Source: 08-VALIDATION-REPORT.md finding F-10
  - Severity: DEGRADED
  - Detail: Security agent replies "tool group was not found" for Defender alerts.
  - Fix: Add `Microsoft.Security` tool group to Azure MCP Server MCP connection on Foundry project.

- [ ] **[Phase 8 F-11] Arc MCP / SRE Agent: Register Arc MCP server + SRE tool groups on Foundry**
  - Source: 08-VALIDATION-REPORT.md finding F-11
  - Severity: DEGRADED
  - Detail: Arc and SRE agents fall back to compute tool surface — Arc MCP server not wired to Foundry orchestrator; SRE agent lacks dedicated tool group.
  - Fix: 1. Register `ca-arc-mcp-server-prod` as MCP connection on Foundry project. 2. Add SRE agent cross-domain tool access (monitor, Log Analytics) to Foundry project MCP connections.

---

## Operator Actions Pending

These items require manual operator execution (Azure Portal, CLI, or GitHub UI access).

- [ ] **[Phase 8 OTel] Complete 08-04-06 Container App rebuild to activate manual OTel spans**
  - Source: 08-04-PLAN.md task 08-04-06 (operator-only)
  - Detail: Rebuild `ca-api-gateway-prod` Container App with updated `instrumentation.py`, `foundry.py`, `chat.py`, `approvals.py` to activate manual OTel spans in App Insights.
  - After rebuild: verify 6 span types (`foundry.*`, `mcp.*`, `agent.orchestrator`) appear in App Insights Transaction Search.
  - Commands: See `.planning/phases/08-azure-validation-incident-simulation/08-01-USER-SETUP.md`

---

*Last updated: 2026-03-29 — Phase 8 closeout, 11 findings from 08-VALIDATION-REPORT.md*
