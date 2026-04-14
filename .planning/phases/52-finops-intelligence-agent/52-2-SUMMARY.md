---
phase: 52-finops-intelligence-agent
plan: 2
subsystem: api-gateway + orchestrator + detection-plane
tags: [finops, api-gateway, orchestrator-routing, domain-classification, tests, python]

# Dependency graph
requires:
  - plan: 52-1-PLAN.md
    provides: agents/finops/ Python package with 6 @ai_function tools

provides:
  - services/api-gateway/finops_endpoints.py — 6 direct Cost Management REST endpoints
  - Orchestrator DOMAIN_AGENT_MAP + system prompt + _A2A_DOMAINS finops entries
  - agents/shared/routing.py QUERY_DOMAIN_KEYWORDS finops entry
  - services/api-gateway/models.py IncidentPayload domain regex updated
  - services/detection-plane/classify_domain.py DOMAIN_MAPPINGS + VALID_DOMAINS updated
  - fabric/kql/functions/classify_domain.kql finops case added
  - services/api-gateway/tests/test_finops_endpoints.py — 23 tests all passing

key-files:
  created:
    - services/api-gateway/finops_endpoints.py
    - services/api-gateway/tests/test_finops_endpoints.py
  modified:
    - services/api-gateway/main.py
    - agents/orchestrator/agent.py
    - agents/shared/routing.py
    - services/api-gateway/models.py
    - services/detection-plane/classify_domain.py
    - fabric/kql/functions/classify_domain.kql

key-decisions:
  - "finops_endpoints.py uses lazy SDK imports at module level (same pattern as vm_cost.py) — SDKs unavailable locally but tested via mocks"
  - "All 6 endpoints return data_lag_note in successful responses per threat model requirement"
  - "get_idle_resources UI endpoint does NOT create approval records — that is the FinOps agent's responsibility"
  - "RI utilization uses amortized-delta method (AmortizedCost − ActualCost) at subscription scope — avoids Billing Reader role"
  - "group_by validation returns 422 via JSONResponse (not HTTPException) to match the vm_cost.py error pattern"
  - "Test file placed in services/api-gateway/tests/ (not tests/api-gateway/) to match project convention"
  - "Standalone FastAPI test app (not the full main app) avoids lifespan startup overhead in tests"

requirements-completed: [FINOPS-001, FINOPS-002, FINOPS-003]

# Metrics
duration: ~30min
completed: 2026-04-14
---

# Phase 52-2: API Gateway Integration + Orchestrator Routing Summary

**6 FinOps REST endpoints, full orchestrator routing, domain classifier updates, and 23 passing tests**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-04-14
- **Completed:** 2026-04-14
- **Tasks:** 8 (Tasks 1–8; all completed)
- **Files created:** 2
- **Files modified:** 6

## Accomplishments

### Task 1: `services/api-gateway/finops_endpoints.py`
Created with 6 GET endpoints under `/api/v1/finops/` prefix, all calling Azure SDK directly (not delegating to the agent) for fast UI polling:
- `GET /api/v1/finops/cost-breakdown` — ActualCost grouped by ResourceGroup/ResourceType/ServiceName
- `GET /api/v1/finops/resource-cost` — AmortizedCost per resource ID
- `GET /api/v1/finops/idle-resources` — ARG VM list + Monitor metrics, both conditions (CPU + network)
- `GET /api/v1/finops/ri-utilization` — amortized-delta method (no Billing Reader required)
- `GET /api/v1/finops/cost-forecast` — MTD burn rate + optional budget comparison
- `GET /api/v1/finops/top-cost-drivers` — ServiceName grouping, ranked top-N

All 6 endpoints include `data_lag_note` in successful responses. Lazy SDK imports at module level with graceful `None` guards.

### Task 2: `services/api-gateway/main.py`
Added `finops_router` import and `app.include_router(finops_router)` registration adjacent to `vm_cost_router`.

### Task 3: `agents/orchestrator/agent.py`
- `DOMAIN_AGENT_MAP`: added `"finops": "finops_agent"` and `"cost": "finops_agent"` alias
- System prompt routing: added finops keywords bullet (burn rate, idle resources, reserved instance, etc.) before the compute bullet
- Tool allowlist: added `finops_agent` before `classify_incident_domain`
- `_A2A_DOMAINS`: appended `"finops"` with Phase 52 comment

### Task 4: `agents/shared/routing.py`
Added `finops` tuple to `QUERY_DOMAIN_KEYWORDS` after `security` with 15 specific keywords (finops, cost breakdown, cloud cost, spending, monthly bill, burn rate, budget, reserved instance, ri utilization, savings plan, idle resources, rightsizing, cost optimization, overspend, cost management).

### Task 5: `services/api-gateway/models.py`
Updated `IncidentPayload.domain` regex from `...messaging` to `...messaging|finops` — allows detection-plane budget alerts to route correctly.

### Task 6: `services/detection-plane/classify_domain.py`
- `DOMAIN_MAPPINGS`: added 4 Cost Management entries (`microsoft.costmanagement`, `microsoft.costmanagement/budgets`, `microsoft.costmanagement/alerts`, `microsoft.billing`)
- `VALID_DOMAINS`: added `"finops"` and `"patch"`, `"eol"` (were missing from the frozenset but present in the regex)
- Updated comment to reflect current regex

### Task 7: `fabric/kql/functions/classify_domain.kql`
Added `finops` case block for `Microsoft.CostManagement/budgets`, `Microsoft.CostManagement/alerts`, `Microsoft.Billing/billingAccounts` immediately before the `"sre"` fallback.

### Task 8: `services/api-gateway/tests/test_finops_endpoints.py`
Created 23 tests across 6 test classes. All 23 pass:
- `TestCostBreakdown` (5 tests) — valid params, invalid group_by 422, days out-of-range 422, days below min 422, SDK exception 500
- `TestResourceCost` (3 tests) — valid params, missing resource_id 422, SDK exception 500
- `TestIdleResources` (4 tests) — 2 idle VMs, 0 idle VMs (high CPU), custom threshold, SDK exception 500
- `TestRiUtilization` (3 tests) — ri_benefit_estimated_usd, data_lag_note, SDK exception 500
- `TestCostForecast` (4 tests) — no budget, budget_name, over_budget flag, SDK exception 500
- `TestTopCostDrivers` (4 tests) — drivers list with rank, n>25 422, n=0 422, SDK exception 500

## Task Commits

1. **Task 1: finops_endpoints.py** — `c588b5a`
2. **Task 2: main.py registration** — `bfda2ff`
3. **Task 3: orchestrator routing** — `7024186`
4. **Task 4: shared routing keywords** — `d6e2f3c`
5. **Task 5: models.py domain regex** — `23e5314`
6. **Task 6: classify_domain.py** — `900721d`
7. **Task 7: classify_domain.kql** — `b0ee253`
8. **Task 8: tests** — `6eabe73`

## Verification Results

```
✅ services/api-gateway/finops_endpoints.py — 6 GET routes registered
✅ app.include_router(finops_router) in main.py
✅ DOMAIN_AGENT_MAP contains "finops" and "cost" alias
✅ _A2A_DOMAINS contains "finops"
✅ IncidentPayload accepts domain="finops"
✅ VALID_DOMAINS frozenset contains "finops"
✅ KQL classify_domain.kql has finops case before sre fallback
✅ 23/23 tests pass
```

## Deviations from Plan

### Auto-fixed Issues

**1. VALID_DOMAINS was missing patch, eol domains**
- **Found during:** Task 6 inspection — frozenset only had 7 domains but models.py regex already had 9
- **Fix:** Added `"patch"` and `"eol"` to `VALID_DOMAINS` alongside `"finops"` to bring frozenset in sync with the IncidentPayload regex
- **Impact:** Correctness improvement; no scope creep

**2. Test file location**
- **Plan said:** `tests/api-gateway/test_finops_endpoints.py`
- **Actual:** `services/api-gateway/tests/test_finops_endpoints.py`
- **Reason:** Existing test files are in `services/api-gateway/tests/` — confirmed from `test_vm_cost.py` location
- **Impact:** None — tests collected and pass correctly

**Total deviations:** 2 auto-fixed (both correctness improvements)

## Issues Encountered

None — all tasks executed cleanly on first attempt.

## Next Phase Readiness

- API gateway is fully wired for FinOps UI polling
- Orchestrator routes `domain: "finops"` incidents to `finops_agent`
- Detection plane classifies `microsoft.costmanagement` resources as `finops`
- Ready for Plan 52-3: Frontend FinOps Tab (extend CostTab.tsx + 6 proxy routes)
- Ready for Plan 52-4: Infrastructure (ca-finops-prod Container App + RBAC + CI/CD)

---
*Phase: 52-finops-intelligence-agent*
*Completed: 2026-04-14*
