---
phase: 57-capacity-planning-engine
plan: 2
subsystem: api
tags: [fastapi, pydantic, aks, capacity-planning, azure-mgmt-containerservice, resourcegraph]

requires:
  - phase: 57-1-backend-foundation
    provides: CapacityPlannerClient, get_subscription_quota_headroom, get_ip_address_space_headroom, linear regression engine

provides:
  - get_aks_node_quota_headroom() method + standalone function on CapacityPlannerClient
  - _VM_SKU_TO_QUOTA_FAMILY lookup table (22 SKUs)
  - ARG_AKS_QUERY constant for AKS node pool headroom via ResourceGraph
  - CapacityQuotaItem, CapacityHeadroomResponse, SubnetHeadroomItem, IPSpaceHeadroomResponse, AKSNodePoolHeadroomItem, AKSHeadroomResponse Pydantic models
  - capacity_endpoints.py FastAPI router with 4 endpoints (headroom, quotas, ip-space, aks)
  - capacity_router registered in main.py
  - 21 passing unit tests in tests/test_capacity_endpoints.py

affects: [57-3, sre-agent, aks-agent, network-agent, capacity-ui]

tech-stack:
  added: [azure-mgmt-containerservice (guarded import)]
  patterns: [_VM_SKU_TO_QUOTA_FAMILY constant dict, ARG bulk query for AKS, start_time/duration_ms timing on every endpoint, try/except → JSONResponse(500) never-raise pattern]

key-files:
  created:
    - services/api-gateway/capacity_endpoints.py
    - tests/test_capacity_endpoints.py
  modified:
    - services/api-gateway/capacity_planner.py
    - services/api-gateway/models.py
    - services/api-gateway/main.py

key-decisions:
  - "Unknown VM SKUs return quota_family='unknown' — safe fallback, no crash"
  - "max_nodes=0 or null falls back to 1000 (hard AKS autoscale limit) — prevents division by zero"
  - "Headroom filter: usage_pct>=90 OR days_to_exhaustion<=threshold — matches plan spec exactly"
  - "Sort: days_to_exhaustion ASC nulls-last, then usage_pct DESC — most urgent first"
  - "ContainerServiceClient imported with guard (same pattern as compute/network/storage)"

patterns-established:
  - "Endpoint pattern: start_time=time.monotonic(), try/except → JSONResponse({'error':str(exc)}, 500)"
  - "AKS headroom via ARG mv-expand on agentPoolProfiles — avoids N+1 API calls"
  - "VM SKU to quota family mapping as module-level constant dict"

requirements-completed: []

duration: 18min
completed: 2026-04-16
---

# Phase 57-2: AKS + API Endpoints Summary

**AKS node pool headroom via ARG + VM SKU→quota-family table, 4 FastAPI capacity endpoints, 6 Pydantic models, and 21 passing tests**

## Performance

- **Duration:** 18 min
- **Started:** 2026-04-16T00:00:00Z
- **Completed:** 2026-04-16T00:18:00Z
- **Tasks:** 5
- **Files modified:** 5 (3 modified, 2 created)

## Accomplishments
- `get_aks_node_quota_headroom()` added to `CapacityPlannerClient` using ARG bulk query (no N+1), with 22-SKU VM→quota-family lookup table and `"unknown"` fallback for unmapped SKUs
- 6 Pydantic models (`CapacityQuotaItem`, `CapacityHeadroomResponse`, `SubnetHeadroomItem`, `IPSpaceHeadroomResponse`, `AKSNodePoolHeadroomItem`, `AKSHeadroomResponse`) added to `models.py`
- `capacity_endpoints.py` router with 4 endpoints: `/headroom` (top-10 filtered+sorted), `/quotas` (all, usage_pct DESC), `/ip-space`, `/aks`
- Router registered in `main.py`; 21 unit tests all passing

## Task Commits

1. **Task 1: AKS headroom in capacity_planner** - `0184b0c` (feat)
2. **Task 2: Pydantic models in models.py** - `2e3b5f2` (feat)
3. **Task 3: capacity_endpoints.py FastAPI router** - `a47b529` (feat)
4. **Task 4: Register capacity_router in main.py** - `d0426df` (feat)
5. **Task 5: 21 unit tests** - `517b1b9` (test)

## Files Created/Modified
- `services/api-gateway/capacity_planner.py` - Added `_VM_SKU_TO_QUOTA_FAMILY`, `ARG_AKS_QUERY`, `get_aks_node_quota_headroom()` method + standalone, `ContainerServiceClient` guard
- `services/api-gateway/models.py` - Added 6 capacity Pydantic models; added `List` to typing import
- `services/api-gateway/capacity_endpoints.py` - New: 4 FastAPI endpoints with timing, filtering, sorting, never-raise pattern
- `services/api-gateway/main.py` - Import + `app.include_router(capacity_router)`
- `tests/test_capacity_endpoints.py` - New: 21 unit tests covering all 4 endpoints + SKU table

## Decisions Made
- `max_nodes=0/null` fallback to 1000 prevents division by zero (hard AKS autoscale limit)
- `/headroom` filter: `usage_pct >= 90 OR days_to_exhaustion <= threshold` — most actionable items
- None-DTE items sort after numeric DTE (float("inf") sentinel)
- `ContainerServiceClient` imported with same guard pattern as other SDKs in capacity_planner

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None — all 21 tests passed on first run.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 4 capacity API endpoints live and tested; ready for Phase 57-3 (UI integration or sweep wiring)
- `get_aks_node_quota_headroom()` standalone function available for SRE/AKS agent tool wiring

---
*Phase: 57-capacity-planning-engine*
*Completed: 2026-04-16*
