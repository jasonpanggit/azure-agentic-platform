---
plan_id: "39-1"
phase: 39
title: "VM Cost Intelligence & Rightsizing Tools"
status: complete
completed_at: "2026-04-11"
branch: gsd/phase-39-vm-cost-intelligence-rightsizing
---

# Summary — Plan 39-1: VM Cost Intelligence & Rightsizing Tools

## What Was Built

Phase 39 adds full VM cost intelligence and rightsizing capability to the Azure Agentic Platform:
- 3 new `@ai_function` tools in the compute agent
- `GET /api/v1/vms/cost-summary` API gateway endpoint
- `CostTab.tsx` web UI component with proxy route
- SOP for low-CPU rightsizing workflow
- 15 unit tests (all passing)
- Cost Management Reader RBAC in Terraform

## Commits (16 tasks)

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 1ad7b60 | Lazy imports for AdvisorManagementClient and CostManagementClient |
| 2 | 62695a0 | `query_advisor_rightsizing_recommendations` tool |
| 3 | 93254f6 | `query_vm_cost_7day` tool |
| 4 | 9555293 | `propose_vm_sku_downsize` HITL tool |
| 5 | b5f0ae3 | compute requirements.txt — 2 new packages |
| 6 | cd412c1 | agent.py registration — 4 locations |
| 7 | 7de05ef | `vm_cost.py` gateway module |
| 8+16 | 1aa31f2 | vm_cost router in main.py + gateway requirements |
| 9 | 0f84fac | `CostTab.tsx` component |
| 10 | b4f9a74 | Proxy route `GET /api/proxy/vms/cost-summary` |
| 11 | 2531926 | DashboardPanel — 'cost' tab wired |
| 12 | d7fb9a6 | SOP: `vm-low-cpu-rightsizing.md` |
| 13 | b519dc9 | 15 unit tests in `test_compute_cost.py` |
| 14 | d2c27eb | Registration test updated 27→30 tools |
| 15 | f83cdd8 | Terraform Cost Management Reader RBAC |

## Files Changed

### New Files
- `agents/compute/tools.py` — 3 new tools appended in Phase 39 section
- `agents/tests/compute/test_compute_cost.py` — 15 unit tests
- `services/api-gateway/vm_cost.py` — `GET /api/v1/vms/cost-summary`
- `services/web-ui/components/CostTab.tsx` — rightsizing table UI
- `services/web-ui/app/api/proxy/vms/cost-summary/route.ts` — proxy route
- `sops/compute/vm-low-cpu-rightsizing.md` — SOP

### Modified Files
- `agents/compute/tools.py` — lazy imports + 3 tools
- `agents/compute/agent.py` — 4 registration locations + VM Cost Intelligence section in prompt
- `agents/compute/requirements.txt` — 2 new packages
- `agents/tests/compute/test_compute_agent_registration.py` — count 27→30
- `services/api-gateway/main.py` — vm_cost router import + include_router
- `services/api-gateway/requirements.txt` — azure-mgmt-advisor added
- `services/web-ui/components/DashboardPanel.tsx` — TrendingDown import, CostTab import, TabId union, TABS array, tabpanel-cost div
- `terraform/modules/rbac/main.tf` — 2 new Cost Management Reader assignments

## Test Results

```
agents/tests/compute/test_compute_cost.py         15/15 passed
agents/tests/compute/test_compute_agent_registration.py  5/5 passed
agents/tests/compute/ (full suite)               98/98 passed
tsc --noEmit                                      0 errors
terraform fmt -check                              PASS
```

## Key Decisions

- **`propose_vm_sku_downsize` risk_level="medium"**: Downsize is reversible and less disruptive than resize/redeploy. Consistent with HITL pattern for `propose_vm_restart`.
- **`incident_id=""`**: Cost proposals have no incident context; empty string is correct per existing pattern.
- **`new_callable=MagicMock` on `create_approval_record` patches**: `asyncio mode=auto` in pytest creates AsyncMocks by default; explicit `new_callable=MagicMock` prevents coroutine leakage.
- **Model classes patched separately in `query_vm_cost_7day` tests**: `TimeframeType`, `GranularityType`, etc. are `None` when `azure-mgmt-costmanagement` is not installed; tests must patch all of them to avoid `NoneType.CUSTOM` errors.
- **CostTab fetches first subscription only**: Multi-subscription cost aggregation deferred to future iteration; documented in component comment.
