# Multi-Subscription SPN Onboarding Design

**Date:** 2026-04-17  
**Status:** Reviewed — v2  
**Scope:** Full — credential routing, onboarding UI, setup script, subscription column across all tabs

---

## 1. Problem Statement

The platform currently monitors a single Azure subscription using a global `DefaultAzureCredential` (the platform's managed identity). Every service file hardcodes this credential pattern:

```python
credential = app.state.credential  # always the MI
client = ResourceGraphClient(credential)
```

This prevents multi-subscription monitoring because:
1. The MI has no access to subscriptions in other tenants
2. There is no way for a user to self-service onboard a new subscription
3. If multiple subscriptions are loaded, there is no credential routing — all calls use the same MI regardless of which subscription is being queried

The goal is to allow any Azure subscription (same or cross-tenant) to be onboarded to the platform by providing Service Principal credentials, with all sensitive data stored in Key Vault, and with per-subscription credential routing throughout the entire API layer.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Admin UI — Monitored Subscriptions tab                  │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Info banner: step-by-step SPN setup guide        │   │
│  │ + download setup_spn.sh                          │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ Subscription list — status, health, secret expiry│   │
│  │ Add / Update Credentials / Re-validate / Remove  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────┘
                          │ REST API
┌─────────────────────────▼───────────────────────────────┐
│  subscription_credential_endpoints.py                    │
│  POST   /api/v1/subscriptions/onboard/preview-validate  │
│  POST   /api/v1/subscriptions/onboard                   │
│  GET    /api/v1/subscriptions/managed                   │
│  GET    /api/v1/subscriptions/onboard/{id}/validate     │
│  PUT    /api/v1/subscriptions/onboard/{id}/credentials  │
│  DELETE /api/v1/subscriptions/onboard/{id}              │
└──────────┬──────────────────────────┬───────────────────┘
           │ store/retrieve secrets    │ persist metadata
┌──────────▼──────────┐   ┌───────────▼──────────────────┐
│  Key Vault          │   │  Cosmos DB                    │
│  kv-aap-prod        │   │  container: subscriptions     │
│                     │   │  (pre-existing, schema updated)│
│  sub-{id}-secret    │   │  subscription_id              │
│  (JSON blob)        │   │  tenant_id, client_id         │
│                     │   │  kv_secret_name               │
│                     │   │  secret_expires_at            │
│                     │   │  permission_status {}         │
│                     │   │  last_validated_at            │
│                     │   │  monitoring_enabled           │
│                     │   │  environment                  │
│                     │   │  credential_type (spn|mi)     │
│                     │   │  deleted_at (soft-delete)     │
└──────────┬──────────┘   └───────────────────────────────┘
           │ async fetch on miss
┌──────────▼───────────────────────────────────────────────┐
│  CredentialStore (app.state.credential_store)            │
│                                                          │
│  async get(subscription_id) → TokenCredential           │
│    → cache hit + not expired: return cached (TTL 6h)     │
│    → cache miss or expired: fetch secret from KV, cache  │
│    → no KV secret: fall back to DefaultAzureCredential   │
│    → KV unavailable at startup: MI fallback, log warning │
│                                                          │
│  async invalidate(subscription_id) → None               │
│  background TTL eviction via asyncio periodic task      │
└──────────┬───────────────────────────────────────────────┘
           │ injected via Depends(get_scoped_credential)
┌──────────▼───────────────────────────────────────────────┐
│  All 41 subscription-scoped endpoint files               │
│  topology, ARG, VM, network, patch, security, cost, etc. │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Key Vault Secret Design

**Naming convention:** `sub-{subscription_id_no_dashes}-secret`

The subscription ID `4c727b88-12f4-4c91-9c2b-372aab3bbae9` becomes:
`sub-4c727b8812f44c919c2b372aab3bbae9-secret`

> ⚠️ Dashes are stripped left-to-right from the canonical UUID format. Always derive the KV name programmatically via `sub_id.replace("-", "")` — never manually.

**Secret value:** JSON blob to keep all credential fields together as an atomic unit:

```json
{
  "client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "client_secret": "the-actual-secret",
  "tenant_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "subscription_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

**Why JSON:** Avoids needing 3 separate KV secrets per subscription; atomic read/write; rotation replaces the entire blob.

**API Gateway KV access:** The platform's managed identity (`ca-api-gateway-prod`) requires `Key Vault Secrets Officer` role on `kv-aap-prod`. This must be verified/granted during Phase 1 deployment.

**Secret never returned to UI:** No endpoint ever includes `client_secret` in any response body, log entry, or error message.

---

## 4. CredentialStore

**File:** `services/api-gateway/credential_store.py` (new)

### 4.1 Class interface

```python
class CredentialStore:
    """Resolves the correct Azure credential for a given subscription ID.

    Resolution order:
    1. In-memory cache (lazy TTL expiry check on hit)
    2. Key Vault secret fetch → build ClientSecretCredential → cache
    3. DefaultAzureCredential fallback (for MI-accessible subscriptions)

    All methods are async. Thread-safe via asyncio.Lock.
    """

    async def get(self, subscription_id: str) -> TokenCredential:
        """Return the credential for the given subscription.

        Never raises — returns DefaultAzureCredential as last resort.
        """
        ...

    async def invalidate(self, subscription_id: str) -> None:
        """Remove a subscription's credential from the cache.

        Call this after credential rotation or subscription removal.
        Do NOT call before writing the new secret to KV — always write
        KV first, then invalidate, to avoid a race where concurrent
        requests re-cache the old secret.

        If subscription_id is not in cache (e.g. after a restart), this is a no-op.
        """
        ...

    async def _evict_expired(self) -> None:
        """Internal: remove all cache entries whose TTL has elapsed.

        Called by the background eviction task every 30 minutes.
        Handles the case where a secret was rotated directly in KV
        (outside the platform) — the stale cache entry expires and the
        next request fetches the new secret from KV.
        """
        ...
```

### 4.2 Cache structure

```python
_cache: dict[str, tuple[TokenCredential, datetime]]
# key: subscription_id
# value: (credential, expires_at)  expires_at = now + 6h at cache time
```

On `get()`:
1. Check cache — if entry exists and `expires_at > now`, return it
2. Else fetch KV secret `sub-{id}-secret` via `SecretClient.get_secret()`
3. Parse JSON blob, build `ClientSecretCredential(tenant_id, client_id, client_secret)`
4. Store in cache with `expires_at = now + 6h`
5. If KV secret not found (404) or KV unavailable → return `DefaultAzureCredential`

### 4.3 KV unavailability at startup

The CredentialStore is **lazily initialized** — no KV calls at construction time. The `get()` method fetches from KV on first cache miss. If KV is temporarily unavailable:
- The `get()` call catches the `ServiceRequestError` / `HttpResponseError`
- Logs a warning: `credential_store: KV unavailable for sub={id}, falling back to MI`
- Returns `DefaultAzureCredential` for that request
- Does NOT cache the fallback — next request will retry KV

This means the platform starts and serves requests using the MI fallback. Subscriptions that require SPN credentials will surface 424 errors until KV is reachable, but the platform does not hard-fail at startup.

### 4.4 Background eviction task

A background `asyncio` task runs every 30 minutes and calls `_evict_expired()` to remove cache entries whose 6h TTL has elapsed. This handles external KV rotations. Registered in `main.py` lifespan alongside the subscription refresh loop.

### 4.5 FastAPI dependency — canonical pattern

The **only** correct pattern for injecting a scoped credential is:

```python
# dependencies.py
async def get_scoped_credential(
    subscription_id: str,       # extracted from path param by FastAPI
    request: Request,
) -> TokenCredential:
    """Return the credential for the subscription_id path parameter."""
    store: CredentialStore = request.app.state.credential_store
    return await store.get(subscription_id)
```

Usage in endpoint files:

```python
# Any endpoint with subscription_id in path — CORRECT pattern
@router.get("/{subscription_id}/scan")
async def scan(
    subscription_id: str,
    credential: TokenCredential = Depends(get_scoped_credential),
):
    client = ResourceGraphClient(credential)
```

> ⚠️ Do NOT use `Depends(get_scoped_credential(subscription_id))` — this is syntactically invalid in FastAPI because `subscription_id` is a path parameter not in scope at function definition time. The `get_scoped_credential` function receives `subscription_id` automatically from FastAPI's dependency resolver because the endpoint declares it as a path param.

**Endpoints without `subscription_id` in their path** (platform-level, tenant-level) continue using `Depends(get_credential)` unchanged.

### 4.6 Credential failure at runtime

When a `ClientSecretCredential` token fetch fails (expired/revoked secret):
- Azure SDK raises `ClientAuthenticationError`
- Each service's try/except catches this and returns:
  ```json
  HTTP 424 Failed Dependency
  {"error": "subscription_credentials_invalid", "subscription_id": "..."}
  ```
- The UI surfaces a "Credentials invalid — re-validate" badge on the subscription

---

## 5. Onboarding Endpoints

**File:** `services/api-gateway/subscription_credential_endpoints.py` (new)  
**Router prefix:** `/api/v1/subscriptions`  
**Auth:** All endpoints require `verify_token` (Entra ID Bearer token)

### 5.1 POST /onboard/preview-validate — Validate credentials without saving

Accepts the same body as onboard but performs auth + permission checks only. Nothing is written to KV or Cosmos. Returns the full permission result. Used by the UI's "Validate" button before the user clicks Save.

**Request body:** Same as §5.2  
**Response:** `{"auth_ok": true, "permission_status": {...}}`  
**Error:** HTTP 422 if auth fails, HTTP 400 if UUID invalid

### 5.2 POST /onboard — Add subscription

**Request body:**
```json
{
  "subscription_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "display_name": "Production - APAC",
  "tenant_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "client_secret": "...",
  "secret_expires_at": "2026-10-01T00:00:00Z",
  "environment": "prod"
}
```

`secret_expires_at` is optional but strongly recommended. The UI shows a warning if absent. If provided, it must be a future datetime — the API validates this and returns HTTP 422 if it is in the past.

**Steps:**
1. Validate subscription ID is a valid UUID
2. Validate `secret_expires_at` is in the future (if provided)
3. Build `ClientSecretCredential` and call `SubscriptionClient.subscriptions.get(sub_id)` — fail fast (HTTP 422 `credential_auth_failed`) if auth fails
4. Run permission validation in parallel (see §5.7)
5. **Write JSON blob to Key Vault** (`sub-{id}-secret`) — fail HTTP 503 if KV unavailable
6. **Upsert Cosmos `subscriptions` record** (no secret fields) — if this fails, attempt to delete the KV secret as a compensating action, then return HTTP 503. If the compensating KV delete also fails, log the orphaned secret name (`sub-{id}-secret`) at ERROR level so it can be cleaned up manually.
7. Invalidate CredentialStore cache entry (after both KV write and Cosmos upsert succeed)
8. Write audit log: `subscription_onboarded`
9. Return onboard result with `permission_status`

**RBAC propagation:** All soft roles (`Monitoring Reader`, `Security Reader`, `Cost Management Reader`, `Virtual Machine Contributor`, `Azure Kubernetes Service Contributor`, `Container Apps Contributor`) may show `"missing"` immediately after assignment due to Azure's 2–5 minute propagation delay. The subscription is saved regardless. The UI informs the user: "Some permissions may be propagating — re-validate in 5 minutes."

### 5.3 GET /managed — List all monitored subscriptions

Returns all non-deleted Cosmos `subscriptions` records with metadata. Does **not** include secrets. This endpoint replaces the existing `GET /api/v1/subscriptions/managed` endpoint.

**Auth:** Requires `verify_token` (changed from public — see §14).

**Response:**
```json
{
  "subscriptions": [
    {
      "subscription_id": "...",
      "display_name": "...",
      "credential_type": "spn",
      "client_id": "...",
      "permission_status": {"reader": "granted", ...},
      "secret_expires_at": "2026-10-01T00:00:00Z",
      "days_until_expiry": 167,
      "last_validated_at": "...",
      "monitoring_enabled": true,
      "environment": "prod",
      "last_synced": "..."
    }
  ],
  "total": 3
}
```

`client_id` is included (not a secret). `client_secret` is never included.

### 5.4 POST /onboard/{subscription_id}/validate — Re-validate stored credentials

Re-runs permission checks using the credential fetched from KV. Does not require re-entering the secret. Uses POST (not GET) because it writes `permission_status` and `last_validated_at` to Cosmos and appends an audit log entry — these side effects make GET semantically incorrect.

Updates `permission_status` and `last_validated_at` in Cosmos. Writes audit log: `subscription_validated` with `changed_from` showing previous permission_status.

### 5.5 PUT /onboard/{subscription_id}/credentials — Rotate credentials

Accepts `client_id`, `client_secret`, `tenant_id`, `secret_expires_at`. All four fields are **optional** — only fields provided are updated. A user rotating only the secret can send just `{"client_secret": "new-secret"}` keeping the existing `client_id` and `tenant_id` unchanged. The API merges the provided fields with the existing KV blob before writing.

Steps:
1. Validate new credential via auth check
2. **Write new JSON blob to KV first** (overwrites existing)
3. **Then** invalidate CredentialStore cache (after KV write, to avoid race — see §4.2)
4. Re-validate permissions
5. Update Cosmos metadata
6. Write audit log: `subscription_credentials_rotated`

Never returns secret in response.

### 5.6 DELETE /onboard/{subscription_id} — Remove subscription

1. Delete KV secret
2. **Soft-delete** Cosmos record: set `deleted_at = now()`, `monitoring_enabled = false` (record preserved for audit trail)
3. Invalidate CredentialStore cache
4. Write audit log: `subscription_removed`

Soft-delete is chosen over hard-delete to preserve the audit trail. Deleted subscriptions do not appear in `GET /managed`.

### 5.7 Permission Validation Logic

Seven roles checked via live SDK calls using the provided SPN credential. All checks run concurrently via `asyncio.gather`. Each is independently try/except.

| Role | Check method | Required? | Missing means |
|------|-------------|----------|--------------|
| `Reader` | `SubscriptionClient.subscriptions.get(sub_id)` | ✅ Hard required | Blocks onboard (HTTP 422) |
| `Monitoring Reader` | `MonitorManagementClient.metric_definitions.list(...)` | ⚠️ Soft | Metrics/alerts/logs tabs degraded |
| `Security Reader` | `SecurityCenter.secure_scores.list(...)` | ⚠️ Soft | Security tab degraded |
| `Cost Management Reader` | `CostManagementClient.query.usage(...)` | ⚠️ Soft | Cost tab degraded |
| `Virtual Machine Contributor` | `ComputeManagementClient.virtual_machines.get(...)` then check action via ARM permissions | ⚠️ Soft | VM restart/deallocate/start remediations disabled |
| `Azure Kubernetes Service Contributor` | `ContainerServiceClient.managed_clusters.get(...)` then check action | ⚠️ Soft | AKS upgrade remediations disabled |
| `Container Apps Contributor` | `ContainerAppsAPIClient.container_apps.get(...)` then check action | ⚠️ Soft | Container App restart remediations disabled |

> **Note on action-permission checks:** Azure RBAC action permissions (write/action vs read) cannot be tested directly without attempting the operation. The validation checks use `AuthorizationManagementClient.permissions.list_for_resource_group()` to enumerate what actions the SPN has, then asserts the required action strings are present (e.g. `Microsoft.Compute/virtualMachines/restart/action`). This avoids performing destructive test operations.

**Result shape:**
```json
{
  "reader": "granted",
  "monitoring_reader": "granted",
  "security_reader": "missing",
  "cost_management_reader": "missing",
  "vm_contributor": "granted",
  "aks_contributor": "missing",
  "container_apps_contributor": "missing"
}
```

Values: `"granted"` | `"missing"` | `"auth_failed"` | `"check_failed"` (unexpected error)

---

## 6. Secret Expiry Tracking

- `secret_expires_at` stored in Cosmos at onboard time (user-supplied, advisory)
- Must be a future date — validated at onboard and rotation time
- If not provided, UI shows a persistent "⚠️ No expiry date set — add one to enable expiry alerts" notice
- `days_until_expiry` computed server-side in `GET /managed` response
- UI expiry badge tiers:
  - No date: ⚠️ grey — "No expiry tracked"
  - > 30 days: 🟢 green — "Exp: Nd"
  - ≤ 30 days: 🟡 yellow — "Secret expires in Nd"
  - Expired: 🔴 red — "Secret expired — update credentials"
- API gateway logs warning on startup for any subscription with `days_until_expiry < 7`
- No automated rotation — user must rotate manually via "Update Credentials"

---

## 7. Existing Subscription Migration

The current subscription (`4c727b88-12f4-4c91-9c2b-372aab3bbae9`) will be re-onboarded via SPN — the operator will create an App Registration, run `setup_spn.sh`, and onboard it through the UI like any other subscription. The `DefaultAzureCredential` MI fallback in `CredentialStore` is retained as a safety net during the transition window (between Phase 1 deploy and the re-onboard completing) but is not the intended long-term credential for any subscription.

**Cosmos record:** The existing subscription already has a record in the `subscriptions` container. Phase 1 schema migration adds the new fields (`credential_type`, `client_id`, `tenant_id`, `kv_secret_name`, `permission_status`, `last_validated_at`, `secret_expires_at`, `deleted_at`) with safe defaults (null for all / `"mi"` for `credential_type` as temporary placeholder until re-onboarded).

**Re-onboard sequence:**
1. Deploy Phases 1–3
2. Operator creates App Registration for the existing subscription, grants roles via `setup_spn.sh`
3. Operator onboards via the new UI — KV secret is written, `credential_type` updates to `"spn"`
4. CredentialStore now uses the SPN for this subscription; MI fallback is no longer exercised

**UI treatment before re-onboard:** The existing subscription appears with a `"🔵 Platform MI — re-onboard required"` warning badge prompting the operator to complete the SPN migration.

---

## 8. Tenant Data Migration

The `TenantAdminTab` and `tenants` PostgreSQL table currently store:
- Subscription lists → already superseded by Cosmos `subscriptions` container
- Compliance frameworks → move to Settings tab (new `platform_settings` table)
- Operator group ID → move to Settings tab

**Migration steps (Phase 5):**
1. Run migration script: read `tenants` PostgreSQL table → write `compliance_frameworks` and `operator_group_id` to new `platform_settings` table
2. Verify no application code references the `tenants` table (grep codebase for `tenants` table queries)
3. Run `DROP TABLE tenants` — the data has been migrated and the table is no longer needed
4. `TenantAdminTab` is hidden (not rendered) starting Phase 3, before removal in Phase 5

**No data loss risk:** All data is copied to `platform_settings` before the table is dropped. The migration script is idempotent — safe to re-run if interrupted.

---

## 9. Service File Credential Routing (41 files)

### 9.1 The canonical dependency pattern

All 41 endpoint files must be updated to use `get_scoped_credential` (defined in §4.5) in place of `get_credential` for any endpoint that accepts `subscription_id` as a path parameter.

**Before:**
```python
from services.api_gateway.dependencies import get_credential

@router.get("/{subscription_id}/scan")
async def scan(
    subscription_id: str,
    credential = Depends(get_credential),
):
    ...
```

**After:**
```python
from services.api_gateway.dependencies import get_scoped_credential

@router.get("/{subscription_id}/scan")
async def scan(
    subscription_id: str,
    credential: TokenCredential = Depends(get_scoped_credential),
):
    ...
```

FastAPI resolves `subscription_id` from the path and passes it to `get_scoped_credential` automatically — no factory function or wrapper is needed.

### 9.2 Endpoints not requiring credential routing

Endpoints that do not accept a `subscription_id` path parameter (platform-level endpoints, audit, settings, SLA admin, etc.) continue using `Depends(get_credential)` unchanged.

---

## 10. UI — Redesigned Admin Tab

### 10.1 Tab structure change

`AdminHubTab` sub-tabs change from:
```
Subscriptions | Settings | Tenant & Admin
```
To:
```
Monitored Subscriptions | Settings
```

"Tenant & Admin" is hidden from Phase 3 onward and removed in Phase 5. The `TenantAdminTab` component continues to exist in the codebase during Phases 3–4 (not rendered) to avoid breaking imports. Removed in Phase 5 after migration is confirmed.

### 10.2 Monitored Subscriptions tab layout

```
┌─────────────────────────────────────────────────────────────┐
│ ℹ️  How to onboard a subscription          [▼ Expand guide] │
└─────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┬──────────┐
│ Monitored Subscriptions                   (3)    │ + Add    │
└──────────────────────────────────────────────────┴──────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ Name       │ Subscription ID  │ Credential │ Permissions │ Expiry   │
├────────────┼──────────────────┼────────────┼─────────────┼──────────┤
│ Production │ 4c727b88-...     │ 🔵 MI      │ ✅ ✅ ⚠️ ⚠️  │ —        │
│            │                  │            │             │ [···]    │
├────────────┼──────────────────┼────────────┼─────────────┼──────────┤
│ APAC Prod  │ b1234abc-...     │ 🔑 SPN     │ ✅ ✅ ✅ ✅  │ 🟢 90d   │
│            │                  │            │             │ [···]    │
├────────────┼──────────────────┼────────────┼─────────────┼──────────┤
│ Dev/Test   │ c5678def-...     │ 🔑 SPN     │ ✅ ✅ ⚠️ ⚠️  │ 🔴 Exp'd │
│            │                  │            │             │ [···]    │
└─────────────────────────────────────────────────────────────────────┘
```

Permissions column shows four icons (Reader / Monitoring / Security / Cost) as ✅/⚠️/❌ with tooltip on hover. Clicking a row expands inline details.

### 10.3 Info banner — collapsible SPN setup guide

Collapsed by default (user preference persisted to localStorage). When expanded:

```
How to onboard a subscription
──────────────────────────────────────────────────────────────

Step 1: Create an App Registration (you need Entra ID access)
  • Azure Portal → Entra ID → App Registrations → New Registration
  • Name: e.g. "aap-monitor-<subscription-name>"
  • Note: Application (client) ID, Directory (tenant) ID
  • Go to Certificates & Secrets → New client secret
  • ⚠️  Copy the secret value immediately — it is shown once only
  • Note the expiry date

Step 2: Grant required roles on the target subscription
  Prerequisite: You need Owner or User Access Administrator
  on the target subscription.

  [⬇ Download setup_spn.sh]

  Option A — Script (recommended):
    ./setup_spn.sh \
      --subscription-id <id> \
      --client-id <client-id> \
      --tenant-id <tenant-id> \
      --onboard \
      --api-url https://ca-api-gateway-prod...
    # Script prompts for client secret securely (no shell history exposure)

  Option B — Azure Portal:
    Subscriptions → <your subscription> → Access control (IAM) → Add role:
      - Reader                        (required)
      - Monitoring Reader             (required — logs, metrics, alerts)
      - Security Reader               (required — Defender, compliance)
      - Cost Management Reader        (required — cost, Advisor)
      - Virtual Machine Contributor   (required — VM restart/deallocate remediations)
      - Azure Kubernetes Service Contributor  (required — AKS upgrade remediations)
      - Container Apps Contributor    (required — Container App restart remediations)

Step 3: Click "+ Add" above and enter your credentials
```

### 10.4 Add Subscription drawer (slide-in panel)

**Fields:**
- Subscription ID (UUID format validated client-side)
- Display Name
- Tenant ID
- Client ID
- Client Secret (masked input — password field — value cleared if user navigates away without saving)
- Secret Expiry Date (date picker — future dates only; shows "⚠️ No expiry set" if left blank)
- Environment (prod / staging / dev) — used for visual grouping only

**Flow:**
1. User fills form
2. Clicks **Validate** — calls `POST /onboard/preview-validate`, shows live permission results inline. Reader missing = Save button disabled + red error. Soft roles missing = yellow warnings but Save enabled
3. Clicks **Save** (enabled only after Reader confirmed) — calls `POST /onboard`
4. Success: drawer closes, subscription appears in list
5. Error: inline error message, drawer stays open

**Client Secret handling:** The secret field is type=password. It is sent to the API over HTTPS only. It is never stored in React state beyond the form lifetime. It is never logged by the frontend.

### 10.5 Update Credentials drawer

Same as Add but:
- Subscription ID is read-only
- Client Secret field shows placeholder: "••••••••• — last updated N days ago"
- User enters new credentials; Validate runs the same pre-save check
- Save calls `PUT /onboard/{id}/credentials`

### 10.6 Per-subscription action menu (···)

- Re-validate permissions → `GET /onboard/{id}/validate`
- Update credentials → opens Update Credentials drawer
- Edit display name / environment → inline edit (PATCH to existing metadata endpoint)
- Remove subscription → confirmation dialog: "This will remove monitoring for {name}. This action cannot be undone." → `DELETE /onboard/{id}`

---

## 11. Subscription Column Across All Tabs

All resource tables that can show data from multiple subscriptions gain a **Subscription** column showing the display name (not the full GUID). Tooltip on hover shows the full subscription ID.

**Tabs affected:**
- Resources → All Resources, VMs, Scale Sets, Kubernetes, Disks, AZ Coverage
- Network → Topology, VNet Peerings, Load Balancers, Private Endpoints
- Security → all sub-tabs
- Cost → all sub-tabs
- Change → Patch Management, IaC Drift
- Alerts → alert list
- Operations → Runbooks, SLA

**Global subscription selector:** A multi-select pill strip in the top navigation bar. Defaults to "All subscriptions". Selection stored in React context (`SubscriptionContext`). All tabs consume the context. When selection changes, tabs either filter client-side (if data already loaded) or re-fetch with `?subscription_id=<id>` query param.

**`environment` field** is used for visual grouping only: the subscription selector shows subscriptions grouped by environment (prod / staging / dev). No routing or access control differences between environments.

---

## 12. setup_spn.sh Script

**Location:** `scripts/setup_spn.sh`

**Prerequisites:**
- `az` CLI installed and logged in (`az login`)
- User has Owner or User Access Administrator on the target subscription
- App Registration already created manually (Step 1 of the guide)

**Inputs:**
```
--subscription-id   Required. Azure subscription GUID
--client-id         Required. App Registration client ID
--tenant-id         Required. Entra tenant ID
--sp-name           Optional. Display label (default: aap-monitor-<sub-id-short>)
--onboard           Flag. If set, calls platform API after role assignments
--api-url           Required if --onboard. Platform API gateway base URL
--skip-reader       Flag. Skip Reader role assignment (already granted)
--dry-run           Flag. Print commands without executing
```

**Client secret handling:** The script **never** accepts `--client-secret` as a command-line argument to avoid shell history exposure. Instead:
- If `--onboard` is set, the script prompts interactively: `Enter client secret (input hidden):`
- Uses `read -rs CLIENT_SECRET` (silent, no echo)
- Passes the secret via `--data @-` with a heredoc to `curl` (never in the process argument list)

**Script flow:**
```bash
1. Validate required inputs; print --help if missing
2. az account show --subscription $SUBSCRIPTION_ID  (verify accessible)
3. For each required role (Reader, Monitoring Reader, Security Reader, Cost Management Reader,
   Virtual Machine Contributor, Azure Kubernetes Service Contributor, Container Apps Contributor):
   az role assignment create \
     --assignee $CLIENT_ID \
     --role "$ROLE" \
     --scope /subscriptions/$SUBSCRIPTION_ID
4. If --onboard:
   a. Prompt: read -rs CLIENT_SECRET
   b. curl -s -X POST $API_URL/api/v1/subscriptions/onboard \
        -H "Content-Type: application/json" \
        --data @- <<EOF
      {"subscription_id":"$SUB_ID","client_id":"$CLIENT_ID","tenant_id":"$TENANT_ID","client_secret":"$CLIENT_SECRET",...}
      EOF
   c. Print permission validation result from response
5. Print summary table
```

**Output example:**
```
Role assignments:
✅ Reader                                  assigned
✅ Monitoring Reader                       assigned
✅ Security Reader                         assigned
✅ Cost Management Reader                  assigned
✅ Virtual Machine Contributor             assigned
✅ Azure Kubernetes Service Contributor    assigned
✅ Container Apps Contributor              assigned

Onboarding to platform...
✅ Reader                          granted
✅ Monitoring Reader               granted
✅ Security Reader                 granted
✅ Cost Management Reader          granted
⚠️  Virtual Machine Contributor    missing  (RBAC propagation may take 2-5 min — re-validate in the UI)
⚠️  AKS Contributor                missing  (RBAC propagation may take 2-5 min — re-validate in the UI)
⚠️  Container Apps Contributor     missing  (RBAC propagation may take 2-5 min — re-validate in the UI)

Subscription 'APAC Production' added to platform. Re-validate in 5 minutes if permissions show missing.
```

---

## 13. Audit Log Integration

All onboarding actions write to the existing audit log. `client_secret` is **never** logged.

| Action | `audit_event_type` | Fields logged |
|--------|-------------------|---------------|
| Preview validate | `subscription_preview_validated` | subscription_id, auth_ok, permission_status |
| Onboard | `subscription_onboarded` | subscription_id, display_name, credential_type, permission_status |
| Re-validate | `subscription_validated` | subscription_id, permission_status, changed_from |
| Rotate credentials | `subscription_credentials_rotated` | subscription_id, rotated_by, new_expires_at |
| Remove | `subscription_removed` | subscription_id, display_name |

---

## 14. Access Control

All onboarding endpoints (`/onboard/*`, `/managed`) require `verify_token` (Entra ID Bearer token).

> **Change from previous design:** `GET /subscriptions/managed` is now auth-gated. The previous design left it public, but it returns subscription IDs, client IDs, and permission status which constitute sensitive reconnaissance data. Moving it behind `verify_token` is the correct posture.

The existing public `GET /subscriptions/managed` endpoint used by the current SubscriptionManagementTab will be updated to the new auth-gated version in Phase 3 (when the new UI ships).

---

## 15. Implementation Phases

### Phase 1 — CredentialStore + KV integration + onboard endpoints
1. Add `azure-keyvault-secrets>=4.8.0` to `requirements.txt`
2. `credential_store.py` — async CredentialStore with KV fetch, TTL cache, background eviction task, MI fallback
3. `subscription_credential_endpoints.py` — all 6 endpoints (preview-validate, onboard, managed, validate, update-credentials, delete)
4. Cosmos `subscriptions` schema migration — add new fields with safe defaults
5. Wire CredentialStore into `main.py` lifespan; register background eviction task
6. Add `KEY_VAULT_URL` env var to `ca-api-gateway-prod` Container App
7. Grant `ca-api-gateway-prod` MI `Key Vault Secrets Officer` on `kv-aap-prod` (if not already)

### Phase 2 — Dependency injection + service file credential routing
1. Add `get_scoped_credential` to `dependencies.py`
2. Update all 41 endpoint files — replace `Depends(get_credential)` with `Depends(get_scoped_credential)` for subscription-scoped endpoints
3. Endpoints without `subscription_id` path param remain unchanged

### Phase 3 — Onboarding UI + setup script
1. `scripts/setup_spn.sh` — full script with secure secret prompting
2. New `MonitoredSubscriptionsTab.tsx` — replaces both SubscriptionManagementTab and TenantAdminTab
3. Update `AdminHubTab.tsx` — hide "Tenant & Admin" sub-tab (not rendered, not removed yet); rename "Subscriptions" to "Monitored Subscriptions"
4. Update `SettingsTab.tsx` — add compliance frameworks and operator group fields
5. Add proxy routes for new endpoints
6. Subscription selector context provider in nav bar

### Phase 4 — Subscription column + global selector across all tabs
1. `SubscriptionContext.tsx` — React context + provider for global subscription selection
2. Update all affected resource tables — add Subscription column (display name + tooltip with full GUID)
3. Update fetch hooks — pass selected subscription IDs from context as repeated query params
4. Update API endpoints that aggregate across subscriptions — add `subscription_id` as a repeated query param (e.g. `?subscription_id=uuid1&subscription_id=uuid2`). FastAPI receives this as `List[str]`. Affected endpoints: resources inventory, VM inventory, alerts list, patch list, topology tree, cost endpoints, security posture, AZ coverage, disk audit, cert expiry, identity risks. Endpoints that already take a single `subscription_id` path param are unchanged.

### Phase 5 — Data migration + cleanup
1. PostgreSQL migration: `tenants` → `platform_settings` (compliance_frameworks, operator_group_id)
2. Remove `TenantAdminTab.tsx`
3. Remove `tenant_endpoints.py` registration from `main.py`
4. Grep codebase to confirm no code references the `tenants` table, then run `DROP TABLE tenants`

---

## 16. Dependencies

New Python packages:
- `azure-keyvault-secrets>=4.8.0` — KV secret read/write

Already added:
- `azure-mgmt-subscription>=3.0.0` — subscription discovery

New environment variable:
- `KEY_VAULT_URL=https://kv-aap-prod.vault.azure.net/` — add to `ca-api-gateway-prod`

New IAM assignment (if not already in place):
- `ca-api-gateway-prod` managed identity → `Key Vault Secrets Officer` on `kv-aap-prod`

---

## 17. Out of Scope

- Automated secret rotation (future — use KV rotation policies + webhook)
- Multi-tenant RBAC within the platform (different users see different subscriptions)
- Azure Lighthouse / cross-tenant MI delegation
- Certificate-based SPN authentication (client secret only)
- Subscription-level user access control (all authenticated users see all subscriptions)
