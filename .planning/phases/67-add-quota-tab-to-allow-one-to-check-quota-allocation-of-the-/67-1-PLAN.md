# Phase 67-1 Plan: Quota Tab

## Goal
Add a dedicated Quota tab for subscription-wide quota browsing, complementary to the existing CapacityTab.

## Files to Create/Modify

### New files
- `services/api-gateway/quota_endpoints.py` — FastAPI router with 4 endpoints
- `services/web-ui/components/QuotaTab.tsx` — React component
- `services/web-ui/app/api/proxy/quotas/route.ts` — GET proxy
- `services/web-ui/app/api/proxy/quotas/summary/route.ts` — GET proxy
- `services/web-ui/app/api/proxy/quotas/request-increase/route.ts` — POST proxy
- `services/api-gateway/tests/test_quota_endpoints.py` — 7 tests

### Modified files
- `services/api-gateway/main.py` — register quota_router
- `services/web-ui/components/DashboardPanel.tsx` — add QuotaTab, BarChart3 icon, tab entry, tab panel

## API Endpoints
- `GET /api/v1/quotas` — paginated list, filters: resource_type, search, page, page_size
- `GET /api/v1/quotas/summary` — total/critical/warning/healthy counts + top-10
- `GET /api/v1/quotas/request-history` — Azure Support API ticket history
- `POST /api/v1/quotas/request-increase` — submit quota increase (simulated fallback)

## Implementation Notes
- Reuse `CapacityPlannerClient.get_subscription_quota_headroom()` — no duplication
- CSS semantic tokens only — no hardcoded Tailwind colors
- Tool functions never raise — structured error dicts on failure
- Proxy routes: runtime=nodejs, dynamic=force-dynamic, AbortSignal.timeout(15000)
- dependency_overrides pattern in tests for get_credential / get_optional_cosmos_client
