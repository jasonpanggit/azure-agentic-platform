# AAP Backlog

> Backlog items logged from validation findings, deferred decisions, and phase closeout tasks.
> Items are sourced from VALIDATION-REPORT.md findings. Add new items at the top of each section.
>
> **Last reviewed: 2026-04-11** — validated against Phases 9–28 codebase. All Phase 8 code-level
> findings are resolved. Remaining items are operator-only (terraform apply, GitHub secrets, manual
> Azure Portal steps).

---

## OPERATOR ACTIONS PENDING

These items require manual operator execution. All code changes are complete — no further dev work needed.

- [ ] **[Phase 19] Run `terraform apply` on prod to activate MCP connections + RBAC**
  - Source: Phase 19-3 VERIFICATION.md item 7 (PENDING)
  - Detail: Terraform code is complete but `terraform apply` has not been confirmed run on prod. This single apply will activate:
    - **F-01 fix**: `Azure AI Developer` RBAC grant to gateway MI on Foundry account (`terraform/modules/rbac/main.tf:130–138`)
    - **F-09 fix**: Azure MCP Server connection registered on Foundry project (`mcp-connections.tf:35–57`)
    - **F-10 fix**: Microsoft.Security exposed via the same Azure MCP Server connection
    - **F-11 fix**: Arc MCP Server connection registered on Foundry project (`mcp-connections.tf:63–87`)
  - Confirm: `enable_arc_mcp_server = true` in `terraform/envs/prod/terraform.tfvars` before apply (for Arc MCP / F-11)
  - Verify after apply: `bash scripts/ops/19-3-register-mcp-connections.sh`

- [ ] **[Phase 19] Seed production runbooks (pgvector)**
  - Source: Phase 19-4 (F-02 fix complete; seed not yet confirmed run)
  - Detail: `PGVECTOR_CONNECTION_STRING` is wired in Terraform and the endpoint returns 503 (not 500) when unavailable. Run the seed script to populate the database.
  - Command: `bash scripts/ops/19-4-seed-runbooks.sh`

- [ ] **[Phase 19] Add GitHub Actions staging environment secrets for E2E**
  - Source: Phase 19-2 Task 10 (F-05 fix complete; secrets not yet created in GitHub UI)
  - Detail: Workflow references `${{ secrets.E2E_CLIENT_ID }}`, `${{ secrets.E2E_CLIENT_SECRET }}`, `${{ secrets.E2E_API_AUDIENCE }}` correctly. Values must be added to the GitHub repo `staging` environment.
  - Guide: `docs/ops/e2e-service-principal.md`

- [ ] **[Phase 19] Complete Teams Bot channel install**
  - Source: Phase 19-5 (F-04 fix complete; Teams install not yet confirmed)
  - Detail: Azure Bot Service is in Terraform (`terraform/modules/teams-bot/main.tf:39–62`). Steps remaining: package manifest → install bot in Teams channel → capture `TEAMS_CHANNEL_ID` → run `terraform apply`.
  - Guide: `scripts/ops/19-5-package-manifest.sh` + `MANUAL-SETUP.md` Teams section

- [ ] **[Phase 8 OTel] Rebuild `ca-api-gateway-prod` to activate manual OTel spans**
  - Source: 08-04-PLAN.md task 08-04-06 (operator-only)
  - Detail: `instrumentation.py` (foundry/mcp/agent spans), `approvals.py` (span wiring) are complete in the codebase. Rebuild the Container App to activate spans in App Insights.
  - After rebuild: verify `foundry.*`, `mcp.*`, `agent.orchestrator` span types appear in App Insights Transaction Search.
  - Commands: See `.planning/phases/08-azure-validation-incident-simulation/08-01-USER-SETUP.md`

---

## RESOLVED — Fixed in Phases 9–28

These items were open after Phase 8. All are confirmed resolved in the codebase.

- [x] **[F-01] Grant Azure AI Developer RBAC to gateway MI on Foundry account** — Fixed Phase 19-2. `terraform/modules/rbac/main.tf:130–138`. Pending `terraform apply` to activate in prod.
- [x] **[F-02] Fix GET /api/v1/runbooks/search returning 500** — Fixed Phase 19-4. `services/api-gateway/runbook_rag.py:130–136` catches all pgvector errors; endpoint returns 503 (not 500) when unavailable. `PGVECTOR_CONNECTION_STRING` wired in Terraform.
- [x] **[F-03] Lock CORS from wildcard to explicit prod origin** — Fixed Phase 19-2. `terraform/envs/prod/terraform.tfvars:22` has explicit prod origin. No code change needed.
- [x] **[F-04] Register Azure Bot Service** — Fixed Phase 19-5. `terraform/modules/teams-bot/main.tf:39–62` has full Bot Service + Teams channel resources with import blocks.
- [x] **[F-05] Add GitHub secrets for E2E runs** — Fixed Phase 19-2. `staging-e2e-simulation.yml:32–35` references all 3 secrets. Operator must add secret values in GitHub UI.
- [x] **[F-06] Update arc-mcp-server.spec.ts to remove hardcoded localhost:8080** — Fixed (pre-Phase 19). `e2e/arc-mcp-server.spec.ts:27` reads `process.env.ARC_MCP_SERVER_URL || 'http://localhost:8080'`. No hardcoded URLs in call sites. Note: env var is `ARC_MCP_SERVER_URL` (documented in file JSDoc at line 13), not `E2E_ARC_MCP_URL` as originally specified — naming is intentional and self-consistent.
- [x] **[F-07] Add 404 handler in approvals.py for missing records** — Fixed (pre-Phase 19). `services/api-gateway/approvals.py:109–110` and `161–162` both catch `CosmosResourceNotFoundError` and raise `HTTPException(status_code=404)`.
- [x] **[F-08] Fix e2e-sse-reconnect.spec.ts sequence-ID test** — Fixed Phase 19-2. Assertions are guarded; auth fixture wired via `fixtures/auth`. Remaining: GitHub CI secrets (see F-05 operator action).
- [x] **[F-09] Add Microsoft.Network tool group to Foundry MCP connection** — Fixed Phase 19-3. `terraform/envs/prod/mcp-connections.tf:35–57` registers Azure MCP Server (covers all tool groups). Pending `terraform apply`.
- [x] **[F-10] Add Microsoft.Security tool group to Foundry MCP connection** — Fixed Phase 19-3. Same MCP connection as F-09. Pending `terraform apply`.
- [x] **[F-11] Register Arc MCP server + SRE tool groups on Foundry** — Fixed Phase 19-3. `terraform/envs/prod/mcp-connections.tf:63–87` registers Arc MCP connection (count-gated on `enable_arc_mcp_server`). Pending `terraform apply` + tfvars check.

---

*Last updated: 2026-04-11 — Phase 8 findings fully validated; all code-level issues resolved in Phases 19–28. 5 operator-only actions remain.*
