# Summary: Remove VM Filter from Cost Tab — Show All Advisor Cost Recommendations

**ID:** 260413-v9x
**Status:** COMPLETE
**Date:** 2026-04-13
**Commit:** 8c2fccf

## Changes Made

### Task 1: Generalized `vm_cost.py` backend endpoint
- **Removed** the `impacted_field` VM filter (`"virtualmachines" not in rec.impacted_field.lower()`) — all Cost category recommendations now returned
- **Renamed** response fields: `vm_name` -> `resource_name`, added `resource_type` field (from `rec.impacted_field`)
- **Added** `"recommendations"` as the primary response array key; `"vms"` retained as deprecated alias for backward compat
- **Updated** docstrings and module docstring to reflect all resource types
- Endpoint path stays `/api/v1/vms/cost-summary` (no breaking URL change)

### Task 2: Updated `CostTab.tsx` frontend component
- **Renamed** `CostVM` interface to `CostRecommendation` with `resource_name` and `resource_type` fields
- **Updated** response parsing: reads `data.recommendations ?? data.vms ?? []` for backward compat during rollout
- **Added** "Resource Type" column (formatted with `Microsoft.` prefix stripped)
- **Updated** header badge: `{count} VMs` -> `{count} resources`
- **Updated** header title: "Top Rightsizing Opportunities" -> "Top Cost Optimization Opportunities"
- **Updated** empty state: "No rightsizing recommendations" -> "No cost recommendations found"
- **Renamed** state variables: `vms`/`setVMs` -> `recommendations`/`setRecommendations`

### Task 3: Updated tests
- **Renamed** `test_cost_summary_filters_vm_recommendations` -> `test_cost_summary_returns_all_cost_recommendations`
- **Updated** to expect BOTH VM and storage Cost recs (2 results, not 1); Performance rec still excluded
- **Added** full `cost_storage_rec` mock with resource metadata, impacted_field, savings fields
- **Updated** all field assertions: `data["recommendations"]` primary, `data["vms"]` deprecated alias verified
- **Added** `resource_type`, `resource_name`, `resource_group` assertions on both recs
- Route collision regression test and SDK-missing/subscription-required tests updated for new field names

## Verification

- [x] `pytest services/api-gateway/tests/test_vm_cost.py` — 5/5 tests pass
- [x] `npx tsc --noEmit` in web-ui — zero TypeScript errors
- [x] Response includes non-VM resources (storage mock in test)
- [x] Empty state still works when no Cost recommendations exist (test verified)
- [x] Backward compat: `"vms"` key still present in all responses

## Files Changed

| File | Change |
|------|--------|
| `services/api-gateway/vm_cost.py` | Remove VM filter, rename fields, add `recommendations` key |
| `services/web-ui/components/CostTab.tsx` | New interface, Resource Type column, generic labels |
| `services/api-gateway/tests/test_vm_cost.py` | Test all cost recs returned, updated assertions |
