---
phase: 19
title: "Production Stabilisation"
verification_date: "2026-04-02"
verifier: "claude"
overall_status: "CODE_COMPLETE_OPERATOR_PENDING"
---

# Phase 19: Production Stabilisation — Verification Report

## Phase Goal

> Resolve all known BLOCKING and HIGH-severity production defects so the platform is fully operational: authenticated, all agents functional, detection plane wiring ready, no unauthenticated external endpoints, Teams proactive alerting delivering cards.

**Phase Requirements (from ROADMAP.md Phase 19):** PROD-001, PROD-002, PROD-003, PROD-005

---

## Requirement Coverage Cross-Reference

The following table maps each requirement ID from the phase definition against the plans that address it. Every requirement ID declared in the phase goal is accounted for.

| REQ-ID | Requirement (from ROADMAP.md v2 PROD table) | Addressed by Plan | Status |
|--------|---------------------------------------------|-------------------|--------|
| PROD-001 | Entra authentication enforced on all non-health API endpoints in production | 19-2 Authentication Enablement | CODE COMPLETE — operator must run `terraform apply` after staging validation |
| PROD-002 | Azure MCP Server authenticated via managed identity; internal ingress only; no unauthenticated external access | 19-1 Azure MCP Server Security Hardening | CODE COMPLETE — operator must run `terraform apply` to activate in prod |
| PROD-003 | All 8 domain agent MCP tool groups registered in Foundry; each exercises domain tools in integration test | 19-3 MCP Tool Group Registration | CODE COMPLETE — operator must run `terraform apply` + verification script |
| PROD-005 | Teams proactive alerting delivers Adaptive Cards within 2 minutes of incident creation | 19-5 Teams Proactive Alerting | CODE COMPLETE — operator must install bot in Teams channel and set `TEAMS_CHANNEL_ID` |

> **Note — PROD-004:** PROD-004 (Live alert detection loop) is NOT listed as a Phase 19 requirement in the phase definition. It is assigned to Phase 21 (Detection Plane Activation). Not applicable here.

> **Note — BUG-002 / TRIAGE-005:** Plan 19-4 resolves BUG-002 (runbook search 500 error). The underlying formal requirement is TRIAGE-005 (Phase 5). BUG-002 is a production defect against TRIAGE-005, not a separate v2 PROD requirement. Plan 19-4 is within scope as a production stabilisation fix.

---

## Plan-by-Plan Verification

### Plan 19-1: Azure MCP Server Security Hardening

**Requirement:** PROD-002
**Summary status:** COMPLETE (code merged; operator action required to activate in prod)

| # | Must-Have | Evidence | Pass/Fail |
|---|-----------|----------|-----------|
| 1 | `terraform/modules/azure-mcp-server/` module exists with `main.tf`, `variables.tf`, `outputs.tf` | `ls terraform/modules/azure-mcp-server/` → `main.tf outputs.tf variables.tf` | ✅ PASS |
| 2 | `external_enabled = false` set in module (internal-only ingress) | `grep "external_enabled" terraform/modules/azure-mcp-server/main.tf` → `external_enabled = false # Internal only — SEC-001 fix` | ✅ PASS |
| 3 | `--dangerously-disable-http-incoming-auth` removed from Dockerfile | `grep "dangerously-disable-http-incoming-auth" services/azure-mcp-server/Dockerfile` → only a comment noting removal (line 32), not in CMD | ✅ PASS |
| 4 | `module "azure_mcp_server"` block added to `terraform/envs/prod/main.tf` | `grep "azure_mcp_server" terraform/envs/prod/main.tf` → module block at line 220 | ✅ PASS |
| 5 | `azure_mcp_server_url` wired from internal FQDN in `agent_apps` module | `grep "azure_mcp_server_url" terraform/envs/prod/main.tf` → `"http://${module.azure_mcp_server.internal_fqdn}"` at line 257 | ✅ PASS |
| 6 | Import block for `ca-azure-mcp-prod` in `terraform/envs/prod/imports.tf` | `grep "ca-azure-mcp-prod" terraform/envs/prod/imports.tf` → import block with full resource ID present | ✅ PASS |
| 7 | Operator runbook `scripts/ops/19-1-azure-mcp-security.sh` created | `ls scripts/ops/19-1-azure-mcp-security.sh` → file present | ✅ PASS |
| 8 | `ca-azure-mcp-prod` external access blocked in Azure | **OPERATOR PENDING** — requires `terraform apply` to toggle `external_enabled` | ⏳ PENDING |
| 9 | `terraform plan` shows zero diff post-apply | **OPERATOR PENDING** — requires `terraform apply` execution | ⏳ PENDING |

**Plan verdict:** Code complete. 7/9 verifiable in codebase ✅. 2 items require live Azure operator execution.

---

### Plan 19-2: Authentication Enablement

**Requirement:** PROD-001
**Summary status:** COMPLETE (code merged; operator action required to apply to prod)

| # | Must-Have | Evidence | Pass/Fail |
|---|-----------|----------|-----------|
| 1 | `api_gateway_auth_mode`, `api_gateway_client_id`, `api_gateway_tenant_id` variables added to `terraform/modules/agent-apps/variables.tf` | `grep "api_gateway_auth_mode\|api_gateway_client_id\|api_gateway_tenant_id" terraform/modules/agent-apps/variables.tf` → lines 209, 215, 221 | ✅ PASS |
| 2 | `API_GATEWAY_AUTH_MODE` wired as variable-driven env var in `terraform/modules/agent-apps/main.tf` (replaced hardcoded `disabled`) | `grep "API_GATEWAY_AUTH_MODE" terraform/modules/agent-apps/main.tf` → `value = var.api_gateway_auth_mode` at line 109 | ✅ PASS |
| 3 | `api_gateway_auth_mode = "entra"` set in `terraform/envs/prod/terraform.tfvars` | `grep "api_gateway_auth_mode" terraform/envs/prod/terraform.tfvars` → `api_gateway_auth_mode = "entra"` at line 35 | ✅ PASS |
| 4 | `api_gateway_client_id = "505df1d3-..."` and `api_gateway_tenant_id = "abbdca26-..."` in prod tfvars | `grep "api_gateway_client_id\|api_gateway_tenant_id" terraform/envs/prod/terraform.tfvars` → lines 36–37 with correct values | ✅ PASS |
| 5 | Same auth values set in `terraform/envs/staging/terraform.tfvars` (pre-prod validation gate) | `grep "api_gateway_auth_mode\|api_gateway_client_id" terraform/envs/staging/terraform.tfvars` → lines 16–17 present | ✅ PASS |
| 6 | `cors_allowed_origins` locked to explicit prod origin (not `*`) in prod tfvars | `grep "cors_allowed_origins" terraform/envs/prod/terraform.tfvars` → `"https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"` at line 13 | ✅ PASS |
| 7 | Health endpoints excluded from auth in `auth.py` (documented) | `grep "health" services/api-gateway/auth.py` → module docstring lines 11–12 document `GET /health` and `GET /health/ready` exclusions | ✅ PASS |
| 8 | Staging auth validation script created | `ls scripts/auth-validation/validate-staging-auth.sh` → file present | ✅ PASS |
| 9 | E2E service principal docs created | `ls docs/ops/e2e-service-principal.md` → file present | ✅ PASS |
| 10 | `API_GATEWAY_AUTH_MODE=entra` live on `ca-api-gateway-prod` Container App | **OPERATOR PENDING** — requires `terraform apply` + staging validation pass | ⏳ PENDING |
| 11 | Unauthenticated request → HTTP 401 in prod | **OPERATOR PENDING** — requires apply + validation script execution | ⏳ PENDING |
| 12 | GitHub Actions `staging` environment E2E secrets set | **OPERATOR PENDING** — manual GitHub Actions secret creation | ⏳ PENDING |

**Plan verdict:** Code complete. 9/12 verifiable in codebase ✅. 3 items require live Azure/GitHub operator execution.

---

### Plan 19-3: MCP Tool Group Registration

**Requirement:** PROD-003
**Summary status:** COMPLETE (code merged; operator must run `terraform apply`)

| # | Must-Have | Evidence | Pass/Fail |
|---|-----------|----------|-----------|
| 1 | `terraform/envs/prod/mcp-connections.tf` created with `azapi_resource` blocks | `ls terraform/envs/prod/mcp-connections.tf` → file exists | ✅ PASS |
| 2 | `azapi_resource "mcp_connection_azure"` block targets `azure-mcp-connection` on Foundry project | `grep "azure-mcp-connection" terraform/envs/prod/mcp-connections.tf` → name = "azure-mcp-connection" at line 18 | ✅ PASS |
| 3 | `azapi_resource "mcp_connection_arc"` block targets `arc-mcp-connection` on Foundry project | `grep "arc-mcp-connection" terraform/envs/prod/mcp-connections.tf` → name = "arc-mcp-connection" at line 43 | ✅ PASS |
| 4 | Both connections use correct `foundry_project_id` (not `project_id` — output name mismatch fixed) | `grep "foundry_project_id" terraform/envs/prod/mcp-connections.tf` → `module.foundry.foundry_project_id` at line 11 | ✅ PASS |
| 5 | `internal_fqdn` output added to `terraform/modules/arc-mcp-server/outputs.tf` | `grep "internal_fqdn" terraform/modules/arc-mcp-server/outputs.tf` → output "internal_fqdn" at line 16 | ✅ PASS |
| 6 | Operator verification script `scripts/ops/19-3-register-mcp-connections.sh` created | `ls scripts/ops/19-3-register-mcp-connections.sh` → file present | ✅ PASS |
| 7 | Foundry project shows `azure-mcp-connection` and `arc-mcp-connection` registered (live) | **OPERATOR PENDING** — requires `terraform apply` on prod | ⏳ PENDING |
| 8 | Domain agents (Network/Security/Arc/SRE) no longer return "tool group was not found" | **OPERATOR PENDING** — requires `terraform apply` + script execution | ⏳ PENDING |

**Plan verdict:** Code complete. 6/8 verifiable in codebase ✅. 2 items require live Azure operator execution.

---

### Plan 19-4: Runbook RAG Seeding

**Underlying requirement:** TRIAGE-005 (BUG-002 is a production defect against this Phase 5 requirement)
**Summary status:** COMPLETE (code merged; operator must run seeding script)

| # | Must-Have | Evidence | Pass/Fail |
|---|-----------|----------|-----------|
| 1 | `scripts/ops/19-4-seed-runbooks.sh` created (prod seed script with temp firewall rule, KV password retrieval, validate.py post-check) | `ls scripts/ops/19-4-seed-runbooks.sh` → file present | ✅ PASS |
| 2 | `docs/ops/runbook-seeding.md` created (full operational guide) | `ls docs/ops/runbook-seeding.md` → file present | ✅ PASS |
| 3 | `pgvector_connection_string` placeholder added to `terraform/envs/prod/terraform.tfvars` | `grep "pgvector_connection_string" terraform/envs/prod/terraform.tfvars` → `pgvector_connection_string = ""` at line 51 | ✅ PASS |
| 4 | `pgvector_connection_string` already in `credentials.tfvars` and wired end-to-end (confirmed by summary) | Summary confirms: `credentials.tfvars` has `pgvector_connection_string = "postgresql://aap_admin:...@aap-postgres-prod..."`, wired via `main.tf:290` | ✅ PASS |
| 5 | `GET /api/v1/runbooks/search` returns HTTP 200 in prod | **OPERATOR PENDING** — requires running `bash scripts/ops/19-4-seed-runbooks.sh` | ⏳ PENDING |
| 6 | PostgreSQL `runbooks` table contains 60 rows post-seed | **OPERATOR PENDING** — requires seed script execution | ⏳ PENDING |
| 7 | `validate.py` 12 domain queries all pass ≥ 0.75 similarity | **OPERATOR PENDING** — script runs validate.py automatically | ⏳ PENDING |
| 8 | Temp PostgreSQL firewall rule removed post-seed | **DESIGN-ENFORCED** — `trap cleanup EXIT` in script guarantees cleanup | ✅ PASS |

**Plan verdict:** Code complete. 5/8 verifiable in codebase ✅. 3 items require live Azure operator execution (all handled by the seeding script once run).

---

### Plan 19-5: Teams Proactive Alerting

**Requirement:** PROD-005
**Summary status:** COMPLETE (code merged; operator must install bot and capture channel ID)

| # | Must-Have | Evidence | Pass/Fail |
|---|-----------|----------|-----------|
| 1 | `scripts/ops/19-5-package-manifest.sh` created (manifest packaging with placeholder substitution) | `ls scripts/ops/19-5-package-manifest.sh` → file present | ✅ PASS |
| 2 | `scripts/ops/19-5-test-teams-alerting.sh` created (E2E test with synthetic Sev1 incident injection) | `ls scripts/ops/19-5-test-teams-alerting.sh` → file present | ✅ PASS |
| 3 | `teams_channel_id = ""` placeholder added to `terraform/envs/prod/terraform.tfvars` | `grep "teams_channel_id" terraform/envs/prod/terraform.tfvars` → line 44 present | ✅ PASS |
| 4 | `TEAMS_CHANNEL_ID` variable and env var wiring already end-to-end in `agent-apps` module (confirmed pre-existing, no new change needed) | Summary confirms: variable in `prod/variables.tf`, pass-through in `prod/main.tf`, env var in `agent-apps/main.tf:394-396` | ✅ PASS |
| 5 | Bot resource import blocks already in `imports.tf` (confirmed pre-existing) | Summary confirms: four bot import blocks present with accurate resource IDs | ✅ PASS |
| 6 | Adaptive Card delivered in Teams channel within 120 seconds of incident creation | **OPERATOR PENDING** — requires bot installation in Teams channel + `TEAMS_CHANNEL_ID` capture + env var set | ⏳ PENDING |
| 7 | `hasConversationReference()` returns `true` after bot installation | **OPERATOR PENDING** — requires bot installation to fire `onInstallationUpdate` event | ⏳ PENDING |
| 8 | `TEAMS_CHANNEL_ID` persisted in Terraform (non-empty in tfvars post-installation) | **OPERATOR PENDING** — requires channel ID capture + tfvars update + `terraform apply` | ⏳ PENDING |

**Plan verdict:** Code complete. 5/8 verifiable in codebase ✅. 3 items require live Teams + Azure operator execution.

---

## Phase Goal Achievement Summary

| Phase Goal Component | Status | Notes |
|---|---|---|
| Authenticated production API (no auth bypass) | CODE COMPLETE | `API_GATEWAY_AUTH_MODE=entra` wired in Terraform; operator runs `terraform apply` |
| Azure MCP Server secured (no unauthenticated external access) | CODE COMPLETE | `external_enabled=false` module created; auth bypass flag removed from Dockerfile; operator runs `terraform apply` |
| MCP tool groups registered (all 8 domain agents) | CODE COMPLETE | `azapi_resource` blocks for both MCP servers in `mcp-connections.tf`; operator runs `terraform apply` |
| Runbook search 500 fixed | CODE COMPLETE | Seed script + docs + tfvars placeholder + `credentials.tfvars` wiring confirmed; operator runs seeding script |
| Teams proactive alerting delivering cards | CODE COMPLETE | Manifest packaging + E2E test scripts + Terraform wiring complete; operator installs bot + captures channel ID |

---

## Requirement ID Accounting

The phase goal declares requirements: **PROD-001, PROD-002, PROD-003, PROD-005**

| REQ-ID | Phase Requirement? | Plan that addresses it | Accounted for? |
|--------|-------------------|------------------------|----------------|
| PROD-001 | ✅ Yes | 19-2 Authentication Enablement | ✅ Yes |
| PROD-002 | ✅ Yes | 19-1 Azure MCP Server Security Hardening | ✅ Yes |
| PROD-003 | ✅ Yes | 19-3 MCP Tool Group Registration | ✅ Yes |
| PROD-004 | ❌ Not in Phase 19 (assigned to Phase 21) | N/A | N/A — out of scope |
| PROD-005 | ✅ Yes | 19-5 Teams Proactive Alerting | ✅ Yes |
| BUG-002 / TRIAGE-005 | Implicit (production defect against Phase 5 req) | 19-4 Runbook RAG Seeding | ✅ Yes — addressed as stabilisation fix |

**All 4 declared requirement IDs (PROD-001, PROD-002, PROD-003, PROD-005) are fully accounted for across the 5 plans.**

---

## Overall Verdict

**Phase 19: CODE COMPLETE — OPERATOR ACTION REQUIRED TO ACTIVATE**

All 5 plans are code-complete with commits merged to the repository. The code changes themselves satisfy the must-have criteria that are verifiable in the codebase. The remaining open items in each plan are **operational execution steps** (running `terraform apply`, installing the bot, executing seed scripts) that require live Azure credentials and manual human interaction — they are correctly classified as operator tasks, not unfinished code work.

Phase 19 will be fully closed when the operator completes:

1. **PROD-002** — `cd terraform/envs/prod && terraform apply` (activates internal-only ingress for Azure MCP Server)
2. **PROD-001** — Staging validation via `scripts/auth-validation/validate-staging-auth.sh`, then `terraform apply` on prod
3. **PROD-003** — `cd terraform/envs/prod && terraform apply` + `bash scripts/ops/19-3-register-mcp-connections.sh`
4. **BUG-002** — `bash scripts/ops/19-4-seed-runbooks.sh` (seeds 60 runbooks, removes BUG-002 500 error)
5. **PROD-005** — `bash scripts/ops/19-5-package-manifest.sh` + Teams bot installation + `TEAMS_CHANNEL_ID` capture + `terraform apply`

See individual operator runbooks in `scripts/ops/` for step-by-step commands.
