# Plan 13-01 Summary: Patch Management Tab — Full Stack Implementation

**Phase:** 13-add-a-new-patch-management-tab-and-show-all-the-patch-related-information
**Plan:** 13-01
**Status:** Complete
**Completed:** 2026-03-31

## What Was Built

A full-stack Patch Management tab added to the AAP web UI dashboard, showing patch compliance and installation history data from Azure Update Manager via Azure Resource Graph.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 13-01-01 | API Gateway: `patch_endpoints.py` with GET /api/v1/patch/assessment and /installations, `azure-mgmt-resourcegraph` dependency, router registration | 17d5cd3 |
| 13-01-02 | Unit tests: 15 tests covering both endpoints (200, 400, 422, 502, 503, pagination) | ee64f76 |
| 13-01-03 | Next.js proxy routes: `/api/proxy/patch/assessment` and `/api/proxy/patch/installations` | 2ffaeb8 |
| 13-01-04 | PatchTab component: 5 summary cards, 13-column assessment table, 8-column installation table, filters, all states | a44ad4a |
| 13-01-05 | DashboardPanel integration: TabId extended, TABS array updated, tabpanel-patch added | 9fc2e79 |

## Architecture

```
Browser
  |
  |-- GET /api/proxy/patch/assessment?subscriptions=...
  |-- GET /api/proxy/patch/installations?subscriptions=...
  |
  v
Next.js Route Handlers (proxy)
  |
  |-- GET /api/v1/patch/assessment?subscriptions=...
  |-- GET /api/v1/patch/installations?subscriptions=...
  |
  v
API Gateway (FastAPI)
  |-- patch_endpoints.py (APIRouter)
  |-- _run_arg_query() with pagination
  |
  v
Azure Resource Graph (ARG)
  |-- patchassessmentresources (KQL)
  |-- patchinstallationresources (KQL)
```

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Port KQL from `agents/patch/tools.py` into gateway | Gateway is the data layer for UI; agent tools are for LLM function calling |
| FastAPI APIRouter for patch routes | Keeps routes organized; follows pattern of health_router |
| `_run_arg_query` with lazy import | Allows gateway to start without azure-mgmt-resourcegraph installed (graceful 503) |
| Client-side filtering for compliance/machine search | Assessment data is small enough; avoids re-fetching on filter change |
| No auto-polling (manual Refresh only) | Patch data changes on minute/hour timescales, not seconds (D-11) |
| Parallel fetch for assessment + installations | Promise.all() for concurrent fetch; partial data support on single endpoint failure |

## Files Changed

### New Files (5)
- `services/api-gateway/patch_endpoints.py` — FastAPI router with 2 GET endpoints
- `services/api-gateway/tests/test_patch_endpoints.py` — 15 unit tests
- `services/web-ui/app/api/proxy/patch/assessment/route.ts` — Next.js proxy
- `services/web-ui/app/api/proxy/patch/installations/route.ts` — Next.js proxy
- `services/web-ui/components/PatchTab.tsx` — React component (582 lines)

### Modified Files (3)
- `services/api-gateway/requirements.txt` — Added `azure-mgmt-resourcegraph>=8.0.0`
- `services/api-gateway/main.py` — Registered patch_router
- `services/web-ui/components/DashboardPanel.tsx` — Extended TabId, TABS, added tabpanel

## Verification

- [x] 15/15 unit tests pass (`python3 -m pytest services/api-gateway/tests/test_patch_endpoints.py`)
- [x] `npx tsc --noEmit` passes with zero errors on web-ui
- [x] All 5 tasks committed atomically
- [x] KQL queries match `agents/patch/tools.py` source exactly
- [x] UI-SPEC compliance: 5 summary cards, 13-column assessment table, 8-column installation table, ShieldCheck icon, 6th tab position
