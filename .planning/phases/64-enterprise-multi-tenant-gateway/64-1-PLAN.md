# Phase 64-1: Enterprise Multi-Tenant Gateway — Plan

## Goal
Make AAP a multi-tenant AIOps platform: operators from different business units have isolated data planes, scoped agent permissions, and their own SLA/compliance reporting.

## Deliverables

| # | File | Description |
|---|------|-------------|
| 1 | `services/api-gateway/tenant_manager.py` | `Tenant` Pydantic model + `TenantManager` (PostgreSQL + 5-min cache) |
| 2 | `services/api-gateway/tenant_middleware.py` | `TenantScopeMiddleware` — injects tenant context, 403 for unknown operators |
| 3 | `services/api-gateway/tenant_endpoints.py` | Admin CRUD router: list/create/get/update-subscriptions |
| 4 | `migrations/008_tenants.sql` | `tenants` table DDL + index on `operator_group_id` |
| 5 | `services/web-ui/components/TenantAdminTab.tsx` | Admin UI: tenant table, create modal, inline subscription editor |
| 6 | `services/web-ui/app/api/proxy/admin/tenants/route.ts` | GET/POST proxy to API gateway |
| 7 | `services/web-ui/app/api/proxy/admin/tenants/[id]/subscriptions/route.ts` | PUT proxy for subscription updates |
| 8 | `services/api-gateway/tests/test_tenant_manager.py` | 10 tests covering manager, middleware, and endpoints |
| 9 | `services/api-gateway/main.py` | Register `tenant_router`; init `TenantManager` in lifespan |
| 10 | `services/web-ui/components/DashboardPanel.tsx` | Add `admin` TabId, `Building2` icon, `TenantAdminTab` panel |

## Architecture Decisions

- **Isolation boundary:** tenant is resolved from `operator_group_id` (Entra group OID), not a bearer token claim directly — keeps auth/authz separation clean
- **Cache strategy:** 5-minute in-memory `dict[operator_id → _CacheEntry]` — sufficient for 99% of requests; TTL avoids stale data after membership changes
- **Skip list pattern:** middleware skips `/health` and `/api/v1/admin/*` so admin routes are never blocked by their own guard
- **TENANT_SCOPE_ENABLED env flag:** allows instant rollback without a redeploy
- **Non-raising:** all TenantManager methods catch exceptions and return `None`/`[]` — middleware degrades gracefully when DB is down

## Test Plan
- 10 pytest tests covering: DB insert, cache hit, tenant isolation, 403 enforcement, skip-list pass-through, list/create endpoints, subscription update
- TypeScript `tsc --noEmit` passes with zero new errors
