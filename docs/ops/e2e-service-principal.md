# E2E Service Principal Setup

> **Created:** 2026-04-02 — Plan 19-2: Authentication Enablement (Task 10)
>
> This document describes the `sp-aap-e2e-tests` service principal used by
> GitHub Actions E2E tests to authenticate against the staging API gateway.

## Overview

The E2E test suite (`e2e/`) uses client credentials flow (MSAL CCAF) to acquire
a Bearer token for the `api://505df1d3-3bd3-4151-ae87-6e5974b72a44/incidents.write`
scope. This allows automated tests to call authenticated API endpoints in staging.

---

## Service Principal

| Field | Value |
|---|---|
| **Display Name** | `sp-aap-e2e-tests` |
| **Type** | App Registration (Service Principal) |
| **Tenant** | `abbdca26-d233-4a1e-9d8c-c4eebbc16e50` |
| **Scope** | `api://505df1d3-3bd3-4151-ae87-6e5974b72a44/incidents.write` |

---

## Creation Steps

Run these commands once. The outputs are stored as GitHub Actions secrets.

### 1. Create the service principal

```bash
# Create a service principal for E2E tests with Reader access to staging RG
az ad sp create-for-rbac \
  --name "sp-aap-e2e-tests" \
  --role "Reader" \
  --scopes "/subscriptions/4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c/resourceGroups/rg-aap-staging"
```

This outputs:
```json
{
  "appId": "<E2E_CLIENT_ID>",
  "displayName": "sp-aap-e2e-tests",
  "password": "<E2E_CLIENT_SECRET>",
  "tenant": "abbdca26-d233-4a1e-9d8c-c4eebbc16e50"
}
```

Save `appId` and `password` — you will not be able to retrieve `password` again.

### 2. Grant the E2E SP access to the API scope

The SP needs delegated or application access to the `incidents.write` scope.

**Option A: Azure Portal (recommended)**
1. Azure Portal → **Azure Active Directory** → **App registrations**
2. Find `aap-web-ui-prod` (client ID `505df1d3-...`)
3. **Expose an API** → Confirm or set App ID URI to `api://505df1d3-3bd3-4151-ae87-6e5974b72a44`
4. Add scope `incidents.write` if not present (Type: Admins and users)
5. **Enterprise Applications** → Find `sp-aap-e2e-tests`
6. **API permissions** → Add permission → **My APIs** → `aap-web-ui-prod` → select `incidents.write`
7. **Grant admin consent**

**Option B: CLI**
```bash
# Get the service principal object ID of sp-aap-e2e-tests
SP_OBJECT_ID=$(az ad sp show --id <E2E_CLIENT_ID> --query id -o tsv)

# Grant API permission (requires Global Administrator or Privileged Role Administrator)
# This grants the incidents.write scope as a delegated permission
az ad app permission add \
  --id <E2E_CLIENT_ID> \
  --api 505df1d3-3bd3-4151-ae87-6e5974b72a44 \
  --api-permissions <scope-object-id>=Scope

# Grant admin consent
az ad app permission grant \
  --id <E2E_CLIENT_ID> \
  --api 505df1d3-3bd3-4151-ae87-6e5974b72a44
```

### 3. Set GitHub Actions secrets

Go to: **GitHub** → **Settings** → **Environments** → `staging` → **Add secret**

| Secret Name | Value | Description |
|---|---|---|
| `E2E_CLIENT_ID` | `<appId from step 1>` | Service principal client ID |
| `E2E_CLIENT_SECRET` | `<password from step 1>` | Service principal client secret |
| `E2E_API_AUDIENCE` | `api://505df1d3-3bd3-4151-ae87-6e5974b72a44` | Token audience for API gateway |

---

## E2E Auth Flow

The `e2e/global-setup.ts` acquires a token using client credentials:

```typescript
const credential = new ClientSecretCredential(
  process.env.AZURE_TENANT_ID,
  process.env.E2E_CLIENT_ID,
  process.env.E2E_CLIENT_SECRET
);
const token = await credential.getToken(process.env.E2E_API_AUDIENCE + '/.default');
```

The Bearer token is then passed in `Authorization: Bearer <token>` headers for all
test requests via the `bearerToken` fixture in `e2e/fixtures/auth.ts`.

---

## Secret Rotation

Client secrets expire. The default lifetime is 2 years but should be rotated annually.

To rotate:
1. Azure Portal → **App registrations** → `sp-aap-e2e-tests` → **Certificates & secrets**
2. Add new client secret → copy value immediately
3. Update `E2E_CLIENT_SECRET` in GitHub Actions `staging` environment
4. Delete old secret

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `AADSTS70011: The provided value for the input parameter 'scope' is not valid` | Scope not exposed on the app registration | Follow Step 2 to expose `incidents.write` scope |
| `AADSTS65001: The user or administrator has not consented` | Admin consent not granted | Grant admin consent in Azure Portal |
| `401 Unauthorized` from API gateway | Token audience mismatch | Verify `E2E_API_AUDIENCE=api://505df1d3-...` matches `API_GATEWAY_CLIENT_ID` |
| `E2E_CLIENT_SECRET` expired | Secret rotation needed | Rotate client secret (see above) |
