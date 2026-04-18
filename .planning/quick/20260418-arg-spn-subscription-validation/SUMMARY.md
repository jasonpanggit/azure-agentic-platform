---
status: complete
---
# Summary

Fixed ARG credential usage across all API gateway endpoints and the nav subscription dropdown.

## Changes made

### `services/web-ui/app/api/subscriptions/route.ts`
Replaced ARM `DefaultAzureCredential` + pagination loop with a proxy to `GET /api/v1/subscriptions/managed` on the API gateway. The nav dropdown now shows exactly the onboarded subscriptions (from Cosmos) instead of all ARM-visible subscriptions.

### `services/api-gateway/dependencies.py`
- Added `get_credential_for_subscriptions` async dependency
- Accepts `?subscriptions=` query param, resolves SPN for the first subscription ID via `credential_store`
- Falls back to `DefaultAzureCredential` (pod MI) if `credential_store` absent, lookup fails, or no subscriptions param
- Added `Query` to FastAPI imports

### ARG endpoint files — switched to scoped credential

**Multi-subscription endpoints (switched to `get_credential_for_subscriptions`):**
- `vm_inventory.py` — `GET /api/v1/vms`
- `resources_inventory.py` — `GET /api/v1/resources/inventory`
- `topology_tree.py` — `GET /api/v1/topology/tree`
- `patch_endpoints.py` — `GET /api/v1/patch/assessment`, `GET /api/v1/patch/installations`
- `tagging_endpoints.py` — all 3 endpoints (subscription_id query param)
- `capacity_endpoints.py` — all 4 endpoints (subscription_id query param)
- `finops_endpoints.py` — all 5 endpoints (subscription_id query param)
- `compliance_endpoints.py` — `GET /api/v1/compliance/posture`, `GET /api/v1/compliance/export`
- `nsg_audit_endpoints.py` — scan POST
- `policy_compliance_endpoints.py` — scan POST
- `defender_endpoints.py` — scan POST
- `alert_rule_audit_endpoints.py` — scan POST
- `change_intelligence_endpoints.py` — scan POST
- `storage_security_endpoints.py` — scan POST
- `identity_risk_endpoints.py` — scan POST
- `cve_endpoints.py` — both GET endpoints
- `vnet_peering_endpoints.py` — both GET endpoints

**Already correct (no change needed):**
- `subscription_endpoints.py` — `get_subscription_stats` already uses `get_scoped_credential` ✓
- `cert_expiry_endpoints.py` — scan POST uses `get_managed_subscription_ids`, read endpoints use Cosmos only ✓
- `lock_audit_endpoints.py` — scan POST uses env var subscription list, no ARG in GET endpoints ✓

### Test fixes
- `tests/test_alert_coverage.py` — updated `_make_alert_client` to override `get_credential_for_subscriptions`
- `tests/test_cve_service.py` — updated `test_cves_endpoint_returns_list` to override `get_credential_for_subscriptions`

## Test result
2306 passed, 10 skipped — no regressions.

## Branch
`quick/arg-spn-subscription-validation`
