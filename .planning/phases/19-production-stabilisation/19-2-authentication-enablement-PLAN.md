---
phase: 19
plan: 2
title: "Authentication Enablement"
objective: "Enable Entra authentication on the API gateway in production, lock CORS to the explicit prod origin, configure MSAL in the web UI to acquire the correct token scope, and set E2E CI secrets."
wave: 1
estimated_tasks: 10
gap_closure: false
---

# Plan 19-2: Authentication Enablement

## Objective

Resolve **PROD-001 / SEC-003 / SEC-004 / BUG-004**: Entra authentication is disabled in production via `API_GATEWAY_AUTH_MODE=disabled`. This plan enables it end-to-end: API gateway Entra app registration confirmed, `API_GATEWAY_AUTH_MODE=entra` set, MSAL configured in the web UI to acquire the correct scope, CORS locked to the explicit prod origin, and E2E CI secrets set so automated tests can authenticate.

## Context

**Current state (verified from research):**

Three layers of auth are broken:

1. **API Gateway (SEC-003):** `API_GATEWAY_AUTH_MODE=disabled` is set as a workaround because `API_GATEWAY_CLIENT_ID` and `API_GATEWAY_TENANT_ID` were never set on `ca-api-gateway-prod`. The `EntraTokenValidator` class in `services/api-gateway/auth.py` is correctly implemented — it just needs the env vars and mode switched to `entra`.

2. **CORS (BUG-004):** `CORS_ALLOWED_ORIGINS=*` in prod — set as wildcard, accepting requests from any origin. Must be locked to `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io`.

3. **Web UI (SEC-004):** `services/web-ui/lib/api-gateway.ts` correctly forwards `Authorization` headers via `buildUpstreamHeaders()`. However, the MSAL config must request the right scope (`api://{client_id}/incidents.write`) so the acquired token has the correct audience for the API gateway validator.

4. **E2E CI (F-05):** `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_API_AUDIENCE` are not set in GitHub Actions `staging` environment secrets, so authenticated E2E runs fail immediately.

**Key constraint:** Enabling auth breaks ALL web UI functionality if MSAL isn't correctly configured. Must test in staging first. The plan includes an explicit staging validation step before prod.

**PROD requirement:** PROD-001 — Entra authentication enforced on all non-health API endpoints in production.

---

## Tasks

### Task 1: Verify / confirm API gateway Entra app registration

The research confirms an existing web-UI app registration exists: client ID `505df1d3-3bd3-4151-ae87-6e5974b72a44`. Determine whether to reuse this or create a dedicated API gateway registration.

**Decision: Reuse the existing web-UI app registration** and expose an API scope on it. This avoids creating a second app registration, which would require both MSAL config and the gateway to know about two different client IDs.

Run:
```bash
# Verify the app registration exists
az ad app show --id 505df1d3-3bd3-4151-ae87-6e5974b72a44 \
  --query "{displayName: displayName, appId: appId, id: id}"

# Check if the API scope already exists
az ad app show --id 505df1d3-3bd3-4151-ae87-6e5974b72a44 \
  --query "api.oauth2PermissionScopes[].value"
```

If the scope `incidents.write` does not exist, add it:
```bash
# Get the current api block
az ad app show --id 505df1d3-3bd3-4151-ae87-6e5974b72a44 --query api > /tmp/api-block.json

# Add the scope via patch (GUI alternative: Azure Portal > App registrations > Expose an API > Add scope)
# Scope: incidents.write, type: User, admin consent display name: "Write incidents"
```

Document the confirmed client ID and tenant ID for use in subsequent tasks.

### Task 2: Set auth env vars on `ca-api-gateway-prod`

Switch the gateway from auth-bypass mode to Entra auth:

```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars \
    "API_GATEWAY_AUTH_MODE=entra" \
    "API_GATEWAY_CLIENT_ID=505df1d3-3bd3-4151-ae87-6e5974b72a44" \
    "API_GATEWAY_TENANT_ID=abbdca26-d233-4a1e-9d8c-c4eebbc16e50"
```

**IMPORTANT:** Do this in **staging** first:
```bash
az containerapp update \
  --name ca-api-gateway-staging \
  --resource-group rg-aap-staging \
  --set-env-vars \
    "API_GATEWAY_AUTH_MODE=entra" \
    "API_GATEWAY_CLIENT_ID=505df1d3-3bd3-4151-ae87-6e5974b72a44" \
    "API_GATEWAY_TENANT_ID=abbdca26-d233-4a1e-9d8c-c4eebbc16e50"
```

Rollback command (if auth breaks staging):
```bash
az containerapp update --name ca-api-gateway-staging --resource-group rg-aap-staging \
  --set-env-vars "API_GATEWAY_AUTH_MODE=disabled"
```

### Task 3: Wire auth env vars into Terraform `agent-apps` module

Ensure the auth configuration is managed by Terraform, not just set ad-hoc:

In `terraform/modules/agent-apps/variables.tf`, add:
```hcl
variable "api_gateway_client_id" {
  description = "Entra app registration client ID for API gateway Entra auth"
  type        = string
  default     = ""
}
variable "api_gateway_tenant_id" {
  description = "Entra tenant ID for API gateway Entra auth"
  type        = string
  default     = ""
}
variable "api_gateway_auth_mode" {
  description = "Auth mode for API gateway: 'entra' or 'disabled'"
  type        = string
  default     = "entra"
}
```

In `terraform/modules/agent-apps/main.tf`, add these env vars to the `ca-api-gateway-*` container definition:
```hcl
env {
  name  = "API_GATEWAY_AUTH_MODE"
  value = var.api_gateway_auth_mode
}
env {
  name  = "API_GATEWAY_CLIENT_ID"
  value = var.api_gateway_client_id
}
env {
  name  = "API_GATEWAY_TENANT_ID"
  value = var.api_gateway_tenant_id
}
```

In `terraform/envs/prod/terraform.tfvars`, add:
```hcl
api_gateway_client_id  = "505df1d3-3bd3-4151-ae87-6e5974b72a44"
api_gateway_tenant_id  = "abbdca26-d233-4a1e-9d8c-c4eebbc16e50"
api_gateway_auth_mode  = "entra"
```

### Task 4: Lock CORS to explicit prod origin

Verify the CORS env var is correctly applied in prod:

```bash
# Check current CORS setting
az containerapp show --name ca-api-gateway-prod --resource-group rg-aap-prod \
  --query "properties.template.containers[0].env[?name=='CORS_ALLOWED_ORIGINS'].value" -o tsv
```

If it shows `*`, update it:
```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars "CORS_ALLOWED_ORIGINS=https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
```

Verify in `terraform/envs/prod/terraform.tfvars` that `cors_allowed_origins` is set to the explicit prod origin (not `*`). The Terraform variable was added in Phase 7 (Plan 07-04). If missing:

```hcl
# terraform/envs/prod/terraform.tfvars
cors_allowed_origins = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
```

### Task 5: Configure MSAL in the web UI to request the correct scope

In `services/web-ui/`, locate the MSAL configuration. Search for the scopes configuration:

```bash
grep -r "scopes" services/web-ui/src/ --include="*.ts" -l
grep -r "msal" services/web-ui/src/ --include="*.ts" -l
```

Update the MSAL scopes to include the API gateway scope:

In the MSAL auth config file (likely `services/web-ui/src/lib/auth.ts` or similar):

```typescript
export const loginRequest: PopupRequest = {
  scopes: [
    "User.Read",
    `api://505df1d3-3bd3-4151-ae87-6e5974b72a44/incidents.write`
  ]
}
```

The scope format must match exactly what the `EntraTokenValidator` in `auth.py` validates: `api://{client_id}/incidents.write`.

### Task 6: Verify `buildUpstreamHeaders()` forwards the token correctly

In `services/web-ui/lib/api-gateway.ts`, verify the function forwards the `Authorization` header:

```typescript
// Expected pattern in buildUpstreamHeaders():
function buildUpstreamHeaders(request: NextRequest): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  const authHeader = request.headers.get("Authorization")
  if (authHeader) {
    headers["Authorization"] = authHeader
  }
  return headers
}
```

If the function correctly forwards the header (research confirms it does), no code change is needed. Add a comment to document the expected token format for future maintainers.

### Task 7: Add `/api/health` to the unauthenticated allowlist in `auth.py`

Review `services/api-gateway/auth.py` to confirm that the health endpoint is excluded from auth validation. The `EntraTokenValidator` should bypass auth for:
- `GET /health`
- `GET /api/health`
- `GET /api/v1/health`

If not already excluded, add them to the unauthenticated paths list. This ensures Container Apps health probes continue to work after enabling auth.

### Task 8: Staging end-to-end auth validation

Before touching prod, validate the full auth chain in staging:

```bash
# 1. Get a token using MSAL device code flow (or use a test client credentials token)
# 2. Call the staging API gateway with the token
TOKEN="<acquired-token>"
curl -H "Authorization: Bearer $TOKEN" \
  "https://ca-api-gateway-staging.<domain>/api/v1/incidents" \
  -w "\nHTTP Status: %{http_code}\n"

# Expected: 200 or 404 (endpoint exists but no incidents)
# NOT expected: 401 or 403

# 3. Call without token — should be rejected
curl "https://ca-api-gateway-staging.<domain>/api/v1/incidents" \
  -w "\nHTTP Status: %{http_code}\n"
# Expected: 401 Unauthorized

# 4. Call health endpoint — should still work without auth
curl "https://ca-api-gateway-staging.<domain>/health" \
  -w "\nHTTP Status: %{http_code}\n"
# Expected: 200 OK
```

Only proceed to Task 9 once staging auth validation passes.

### Task 9: Apply auth change to prod

After staging validation passes:

```bash
# Apply Terraform changes (covers agent-apps module env vars)
cd terraform/envs/prod
terraform plan -out=plan-19-2.tfplan
terraform apply plan-19-2.tfplan

# Verify prod API gateway health (health endpoint must return 200 without auth)
curl https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/health

# Verify prod API gateway rejects unauthenticated requests
curl https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/incidents \
  -w "\nHTTP Status: %{http_code}\n"
# Expected: 401
```

### Task 10: Set E2E GitHub Actions secrets for authenticated CI runs

In the GitHub repository settings, add the following secrets to the `staging` environment:

| Secret Name | Value | Source |
|---|---|---|
| `E2E_CLIENT_ID` | Client ID of the E2E service principal | Azure Portal > App registrations |
| `E2E_CLIENT_SECRET` | Client secret of the E2E service principal | Azure Portal > App registrations > Certificates & secrets |
| `E2E_API_AUDIENCE` | `api://505df1d3-3bd3-4151-ae87-6e5974b72a44` | Derived from API gateway client ID |

Create the E2E service principal if it doesn't exist:
```bash
# Create service principal for E2E tests
az ad sp create-for-rbac \
  --name "sp-aap-e2e-tests" \
  --role "Reader" \
  --scopes "/subscriptions/4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c/resourceGroups/rg-aap-staging"

# Grant the SP delegated access to the API gateway scope
# (done via Azure Portal: Enterprise Apps > API permissions)
```

Document the service principal creation in `docs/ops/e2e-service-principal.md`.

---

## Success Criteria

1. `az containerapp show --name ca-api-gateway-prod ... --query "properties.template.containers[0].env[?name=='API_GATEWAY_AUTH_MODE'].value"` returns `entra`
2. `curl https://ca-api-gateway-prod.<domain>/api/v1/incidents` (no auth header) returns `HTTP 401 Unauthorized`
3. `curl -H "Authorization: Bearer <valid-token>" https://ca-api-gateway-prod.<domain>/api/v1/incidents` returns `HTTP 200` or `HTTP 404` (not 401/403)
4. `curl https://ca-api-gateway-prod.<domain>/health` returns `HTTP 200` (health endpoint does not require auth)
5. `CORS_ALLOWED_ORIGINS` on `ca-api-gateway-prod` is set to the explicit prod web UI origin (not `*`)
6. Web UI in prod successfully loads and can call API gateway routes with MSAL-acquired tokens (manual verification: open web UI, confirm no 401 errors in browser console)
7. GitHub Actions `staging` environment has `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, and `E2E_API_AUDIENCE` secrets set

---

## Files Touched

### Modified
- `terraform/modules/agent-apps/variables.tf` — add `api_gateway_client_id`, `api_gateway_tenant_id`, `api_gateway_auth_mode` variables
- `terraform/modules/agent-apps/main.tf` — add auth env vars to api-gateway container definition
- `terraform/envs/prod/terraform.tfvars` — add auth and CORS values
- `services/web-ui/src/lib/auth.ts` (or equivalent MSAL config file) — add `api://{client_id}/incidents.write` scope to login request
- `services/api-gateway/auth.py` — verify/add health endpoint to unauthenticated paths allowlist

### Created
- `docs/ops/e2e-service-principal.md` — documents E2E service principal setup
