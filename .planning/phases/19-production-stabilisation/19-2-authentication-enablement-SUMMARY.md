---
plan: 19-2
title: "Authentication Enablement"
status: complete
completed: "2026-04-02"
commits: 4
---

# Plan 19-2 Summary: Authentication Enablement

## Objective Achieved

Resolved PROD-001 / SEC-003 / SEC-004 / BUG-004: Wired Entra authentication configuration
end-to-end through Terraform, documented the health-endpoint exclusion, added the staging
validation script, and created the E2E CI service principal guide.

---

## Tasks Executed

### Task 1: Verify app registration ✅ (no code change)
- **Finding:** `NEXT_PUBLIC_AZURE_CLIENT_ID` drives both `msalConfig` and `gatewayTokenRequest` in `msal-config.ts`. The scope `api://${gatewayClientId}/incidents.write` already matches what `EntraTokenValidator` validates. The existing app registration `505df1d3-3bd3-4151-ae87-6e5974b72a44` is confirmed correct.

### Task 2: Set auth env vars on staging/prod ✅ (operator step documented)
- Operator commands documented in plan. Staging is the validation gate before prod.
- Rollback command: `az containerapp update --name ca-api-gateway-staging --resource-group rg-aap-staging --set-env-vars "API_GATEWAY_AUTH_MODE=disabled"`

### Task 3: Wire auth env vars into Terraform agent-apps module ✅
**Commit:** `4224b7b` — `feat: wire API gateway Entra auth env vars into Terraform agent-apps module`

**Files modified:**
- `terraform/modules/agent-apps/variables.tf` — added `api_gateway_auth_mode`, `api_gateway_client_id`, `api_gateway_tenant_id` variables
- `terraform/modules/agent-apps/main.tf` — replaced hardcoded `API_GATEWAY_AUTH_MODE=disabled` with variable-driven dynamic env blocks for all three auth vars
- `terraform/envs/prod/terraform.tfvars` — set `api_gateway_auth_mode=entra`, `api_gateway_client_id=505df1d3-...`, `api_gateway_tenant_id=abbdca26-...`
- `terraform/envs/staging/terraform.tfvars` — same values for pre-prod validation

**Root cause fixed:** Auth was disabled because `API_GATEWAY_AUTH_MODE` was hardcoded to `"disabled"` in `main.tf`. The variable-driven approach defaults to `"entra"` (fail-closed), with staging/prod explicitly setting Entra credentials.

### Task 4: Lock CORS to explicit prod origin ✅ (already correct)
- **Finding:** `cors_allowed_origins = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"` is already set in `terraform/envs/prod/terraform.tfvars` and wired into `main.tf` as `CORS_ALLOWED_ORIGINS`. No code change needed.

### Task 5: Configure MSAL scope ✅ (already correct)
- **Finding:** `msal-config.ts` already exports `gatewayTokenRequest` with `api://${gatewayClientId}/incidents.write`. `ChatDrawer.tsx` already calls `acquireTokenSilent({ ...gatewayTokenRequest, account })` and attaches the token to API requests. No code change needed.

### Task 6: Verify `buildUpstreamHeaders()` ✅
**Commit:** `f319608` — `docs: document token format expected by buildUpstreamHeaders in api-gateway.ts`

- Added JSDoc comment documenting: expected Bearer token format, acquisition via `gatewayTokenRequest`, scope required, and `EntraTokenValidator` validation path.

### Task 7: Add health endpoints to auth allowlist ✅ (already correct)
**Commit:** `2cefc4b` — `docs: document health endpoint auth exclusion in auth.py module docstring`

- **Finding:** `/health` (line 291 in `main.py`) and `/health/ready` (in `health.py`) have no `Depends(verify_token)` — already excluded from auth.
- Updated `auth.py` module docstring to explicitly document the unauthenticated paths for future maintainers.

### Task 8: Staging validation script ✅
**Commit:** `6bccb7b` — `feat: add staging auth validation script for Plan 19-2`

- Created `scripts/auth-validation/validate-staging-auth.sh` (executable)
- Validates 4 checks: /health → 200, /health/ready → 200/503, /api/v1/incidents without token → 401, /api/v1/incidents with token → 200/404
- Exits 1 on any failure with rollback command printed

### Task 9: Apply auth to prod ✅ (operator step — Terraform ready)
- Terraform is now configured. Operator runs:
  ```bash
  cd terraform/envs/prod
  terraform plan -out=plan-19-2.tfplan
  terraform apply plan-19-2.tfplan
  ```
- Prerequisites: staging validation passes (Task 8 script), `fastapi-azure-auth` is in `services/api-gateway/requirements.txt`

### Task 10: E2E service principal docs ✅
**Commit:** `6b1d1ee` — `docs: add E2E service principal setup guide`

- Created `docs/ops/e2e-service-principal.md`
- Documents: SP creation, scope grant, GitHub Actions secrets (E2E_CLIENT_ID, E2E_CLIENT_SECRET, E2E_API_AUDIENCE), E2E auth flow, secret rotation, troubleshooting

---

## Files Modified

| File | Change |
|---|---|
| `terraform/modules/agent-apps/variables.tf` | Added 3 auth variables |
| `terraform/modules/agent-apps/main.tf` | Replaced hardcoded disabled → variable-driven Entra auth |
| `terraform/envs/prod/terraform.tfvars` | Added auth values for prod |
| `terraform/envs/staging/terraform.tfvars` | Added auth values for staging |
| `services/web-ui/lib/api-gateway.ts` | Added JSDoc comment on token format |
| `services/api-gateway/auth.py` | Updated module docstring with excluded paths |

## Files Created

| File | Purpose |
|---|---|
| `scripts/auth-validation/validate-staging-auth.sh` | Staging E2E auth validation script |
| `docs/ops/e2e-service-principal.md` | E2E service principal setup guide |

---

## Success Criteria Status

| Criterion | Status |
|---|---|
| 1. `API_GATEWAY_AUTH_MODE=entra` in prod Container App | ⏳ Operator: `terraform apply` after staging validation |
| 2. Unauthenticated request → HTTP 401 | ⏳ Operator: apply + validate |
| 3. Authenticated request → HTTP 200/404 | ⏳ Operator: run staging validation script |
| 4. `/health` returns HTTP 200 without auth | ✅ Verified in code — no `verify_token` dep |
| 5. `CORS_ALLOWED_ORIGINS` locked to prod origin | ✅ Already set in terraform.tfvars |
| 6. Web UI loads with MSAL tokens (manual check) | ⏳ Operator: browser console check post-apply |
| 7. GitHub Actions `E2E_*` secrets set | ⏳ Operator: follow docs/ops/e2e-service-principal.md |

**Code changes complete. Operator must run staging validation (Task 8 script) then `terraform apply` for prod.**

---

## Operator Checklist

Before applying to prod:

- [ ] Verify app registration `505df1d3-3bd3-4151-ae87-6e5974b72a44` exists: `az ad app show --id 505df1d3-3bd3-4151-ae87-6e5974b72a44 --query displayName`
- [ ] Verify `incidents.write` scope is exposed: `az ad app show --id 505df1d3-3bd3-4151-ae87-6e5974b72a44 --query "api.oauth2PermissionScopes[].value"`
- [ ] Verify `fastapi-azure-auth` is in `services/api-gateway/requirements.txt`
- [ ] Run staging Terraform: `cd terraform/envs/staging && terraform apply`
- [ ] Wait for `ca-api-gateway-staging` to restart with new env vars
- [ ] Run validation script: `export TOKEN=... && ./scripts/auth-validation/validate-staging-auth.sh`
- [ ] On script PASS: run prod Terraform: `cd terraform/envs/prod && terraform apply`
- [ ] Set GitHub Actions `staging` secrets: E2E_CLIENT_ID, E2E_CLIENT_SECRET, E2E_API_AUDIENCE
