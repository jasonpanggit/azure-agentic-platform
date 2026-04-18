# ARG SPN & Subscription Validation Plan

**Date:** 2026-04-18  
**Type:** Quick fix / audit  
**Branch:** quick/arg-spn-subscription-validation

---

## Summary of Findings

### Subscription Dropdown (NavSubscriptionPill)

`NavSubscriptionPill` → `SubscriptionSelector` → `GET /api/subscriptions` (Next.js route).

**Issue:** `/api/subscriptions/route.ts` calls the ARM subscriptions API using `DefaultAzureCredential` (the web-ui container's managed identity). It lists **all Azure subscriptions the MI has Reader on** — NOT the onboarded/managed subscriptions stored in Cosmos DB.

After onboarding, the SPN subscription is stored in Cosmos `subscriptions` container (via `subscription_credential_endpoints.py`). But the nav dropdown ignores Cosmos entirely and uses ARM discovery. If the web-ui MI doesn't have Reader on the onboarded subscription, it won't appear in the dropdown.

**Fix:** Change `/api/subscriptions/route.ts` to proxy to the API gateway's `GET /api/v1/subscriptions/managed` endpoint (which reads from Cosmos) instead of calling ARM directly. This ensures the dropdown shows exactly the onboarded subscriptions.

---

### ARG Calls — SPN vs DefaultAzureCredential

**How credential resolution works:**

- `get_credential` (in `dependencies.py`) → returns `DefaultAzureCredential` from `app.state.credential` (the pod's managed identity). **Does NOT use SPN.**
- `get_scoped_credential` → calls `credential_store.get(subscription_id)` → resolves SPN from Key Vault, falls back to MI.

**What ARG endpoints use:**

All ARG-using endpoints (the ones that query Azure Resource Graph) use `Depends(get_credential)` — the MI credential. Only one endpoint (`/api/v1/subscriptions/{subscription_id}/stats`) uses `get_scoped_credential`.

**The problem:** The following ARG-using endpoints call `get_credential` instead of `get_scoped_credential`, meaning they use the pod MI instead of the subscription's SPN:

| File | Endpoint | Issue |
|------|----------|-------|
| `vm_inventory.py` | `GET /api/v1/vms` | Uses `get_credential` |
| `resources_inventory.py` | `GET /api/v1/resources/inventory` | Uses `get_credential` |
| `topology_tree.py` | `GET /api/v1/topology` | Uses `get_credential` |
| `patch_endpoints.py` | `GET /api/v1/patch/*` | Uses `get_credential` |
| `compliance_endpoints.py` | `GET /api/v1/compliance/*` | Uses `get_credential` |
| `finops_endpoints.py` | `GET /api/v1/finops/*` | Uses `get_credential` |
| `nsg_audit_endpoints.py` | `GET /api/v1/nsg-audit/*` | Uses `get_credential` |
| `tagging_endpoints.py` | `GET /api/v1/tagging/*` | Uses `get_credential` |
| `capacity_endpoints.py` | `GET /api/v1/capacity/*` | Uses `get_credential` |
| `cert_expiry_endpoints.py` | `GET /api/v1/certs/*` | Uses `get_credential` |
| `lock_audit_endpoints.py` | `GET /api/v1/locks/*` | Uses `get_credential` |
| `policy_compliance_endpoints.py` | `GET /api/v1/policy-compliance/*` | Uses `get_credential` |
| `defender_endpoints.py` | `GET /api/v1/defender/*` | Uses `get_credential` |
| `alert_rule_audit_endpoints.py` | (ARG) | Uses `get_credential` |
| `vnet_peering_endpoints.py` | (ARG) | Uses `get_credential` |
| `change_intelligence_endpoints.py` | (ARG) | Uses `get_credential` |
| `storage_security_endpoints.py` | (ARG) | Uses `get_credential` |
| `identity_risk_endpoints.py` | (ARG) | Uses `get_credential` |
| `cve_endpoints.py` | (ARG) | Uses `get_credential` |
| `subscription_endpoints.py` | `GET /api/v1/subscriptions/managed` | Uses `get_credential` for `_fetch_resource_counts` (ARG sub-call) |
| `main.py` (various) | Several ARG endpoints | Uses `get_credential` |

**Root cause:** `get_scoped_credential` requires a `subscription_id` path parameter. The multi-subscription endpoints (that accept a `?subscriptions=id1,id2` query param) can't use it directly. Single-subscription endpoints that have `/{subscription_id}/` in their path _can_ switch.

**Pragmatic fix strategy:**

1. **Single-subscription endpoints with `/{subscription_id}/` in path** → switch to `get_scoped_credential`. These can trivially be fixed.
2. **Multi-subscription / no-subscription-path endpoints** → Need a helper that resolves a credential per subscription and uses it per ARG call, OR resolve a single credential from the first/only subscription ID. For the common single-tenant case, adding a `get_credential_for_subscriptions` helper that reads from `credential_store` using the first subscription ID is a practical fix.

---

## Files to Change

### 1. `services/web-ui/app/api/subscriptions/route.ts`
**Change:** Replace the ARM `DefaultAzureCredential` + ARM list call with a proxy to `GET /api/v1/subscriptions/managed` on the API gateway. Return `{ id, name }` shaped from the managed subscription list.

**Why:** The nav dropdown must show onboarded subscriptions (the ones with SPN credentials stored), not all ARM-visible subscriptions.

---

### 2. `services/api-gateway/dependencies.py`
**Change:** Add a new `get_credential_for_subscriptions` dependency that accepts the `subscriptions` query param (comma-separated) and returns the credential for the first subscription ID via `credential_store`. Falls back to `DefaultAzureCredential` if no subscriptions param or store lookup fails.

```python
async def get_credential_for_subscriptions(
    subscriptions: Optional[str] = Query(default=None),
    request: Request = ...,
) -> object:
    if subscriptions:
        first_sub = subscriptions.split(",")[0].strip()
        if first_sub:
            return await request.app.state.credential_store.get(first_sub)
    return request.app.state.credential
```

---

### 3. ARG endpoint files — switch to scoped credential

**Endpoints with `/{subscription_id}/` path param** — switch `get_credential` → `get_scoped_credential`:
- `vm_inventory.py` (single-sub path variants)
- `patch_endpoints.py` (single-sub path variants)
- `cert_expiry_endpoints.py`
- `lock_audit_endpoints.py`
- `subscription_endpoints.py` — `_fetch_resource_counts` call in `get_subscription_stats`

**Endpoints with `?subscriptions=` query param** — switch to new `get_credential_for_subscriptions`:
- `resources_inventory.py` → `GET /api/v1/resources/inventory`
- `topology_tree.py` → `GET /api/v1/topology`
- `nsg_audit_endpoints.py`
- `tagging_endpoints.py`
- `capacity_endpoints.py`
- `finops_endpoints.py`
- `policy_compliance_endpoints.py`
- `defender_endpoints.py`
- `compliance_endpoints.py`
- `alert_rule_audit_endpoints.py`
- `vnet_peering_endpoints.py`
- `change_intelligence_endpoints.py`
- `storage_security_endpoints.py`
- `identity_risk_endpoints.py`
- `cve_endpoints.py`
- `main.py` (any standalone ARG endpoints)

---

## Implementation Steps

- [ ] 1. Fix `services/web-ui/app/api/subscriptions/route.ts` — proxy to managed subscriptions API
- [ ] 2. Add `get_credential_for_subscriptions` to `services/api-gateway/dependencies.py`
- [ ] 3. Update `vm_inventory.py` — scoped credential for single-sub ARG queries
- [ ] 4. Update `resources_inventory.py` + `topology_tree.py` — credential_for_subscriptions
- [ ] 5. Update `patch_endpoints.py` — scoped credential where subscription_id in path
- [ ] 6. Update remaining ARG endpoints (see list above) — credential_for_subscriptions
- [ ] 7. Update `subscription_endpoints.py` `get_subscription_stats` — already has scoped credential but `_fetch_resource_counts` receives it from the wrong dependency; confirm wiring is correct
- [ ] 8. Run existing tests — `pytest services/api-gateway/tests/` to verify no regressions

---

## Out of Scope

- `tool_executor.py` uses an internal `_get_credential()` that calls `DefaultAzureCredential()` directly. This is used by agent tool calls (not UI tabs), so it's a separate concern. Flag for a follow-up phase.
- Multi-subscription fan-out: for tabs that fan across multiple subscriptions, proper fix is to call ARG once per subscription with the right credential. Deferred — the `get_credential_for_subscriptions` approach (use first sub's credential) is the right pragmatic fix for now given all onboarded subscriptions are in the same Entra tenant.

---

## Risk

- **Low** — changes are in the credential-resolution layer only. Business logic unchanged.
- If `credential_store.get()` falls back to MI (KV 404), behavior is unchanged from today.
- No schema changes, no Cosmos changes, no Terraform changes.
