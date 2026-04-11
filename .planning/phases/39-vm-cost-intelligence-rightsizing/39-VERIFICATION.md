---
phase: 39
status: passed
verified: 2026-04-11
must_haves_total: 15
must_haves_verified: 15
---

# Phase 39 Verification

## Must-Haves

| # | Check | Status | Evidence |
|---|-------|--------|----------|
| 1 | 3 `@ai_function` tools exist in `agents/compute/tools.py` (`query_advisor_rightsizing_recommendations`, `query_vm_cost_7day`, `propose_vm_sku_downsize`) | ✅ PASS | Grep confirmed all 3 at lines ~2728, ~2822, ~2938; each decorated with `@ai_function` |
| 2 | Tools registered in `agent.py` at 4 locations (import block, system prompt tools list, `ChatAgent tools=`, `PromptAgentDefinition tools=`) | ✅ PASS | All 4 locations confirmed — alphabetical import block (lines 41–55), `ALLOWED_MCP_TOOLS` format list (lines 167–169), `ChatAgent(tools=[…])` (lines 220–222), `PromptAgentDefinition(tools=[…])` (lines 280–282) |
| 3 | `azure-mgmt-advisor>=9.0.0` and `azure-mgmt-costmanagement>=4.0.0` in `agents/compute/requirements.txt` | ✅ PASS | Both packages present at lines 8–9 |
| 4 | `GET /api/v1/vms/cost-summary` endpoint exists in `services/api-gateway/vm_cost.py` | ✅ PASS | `@router.get("/cost-summary")` confirmed; router prefix `/api/v1/vms` gives full path `/api/v1/vms/cost-summary` |
| 5 | `vm_cost` router imported and included in `services/api-gateway/main.py` | ✅ PASS | Import at line 120; `app.include_router(vm_cost_router)` at line 489 |
| 6 | `CostTab.tsx` exists in `services/web-ui/components/` | ✅ PASS | File found via glob |
| 7 | Proxy route exists at `services/web-ui/app/api/proxy/vms/cost-summary/route.ts` | ✅ PASS | File found via glob |
| 8 | `CostTab` wired into `DashboardPanel.tsx` (`TabId` union, `TABS` array, panel div) | ✅ PASS | `TabId` includes `'cost'`; `TABS` has `{ id: 'cost', label: 'Cost', Icon: TrendingDown }`; `tabpanel-cost` div renders `<CostTab subscriptions={selectedSubscriptions} />`; `CostTab` imported at line 14 |
| 9 | SOP exists at `sops/compute/vm-low-cpu-rightsizing.md` | ✅ PASS | File found via glob |
| 10 | 15 unit tests in `agents/tests/compute/test_compute_cost.py` — all pass | ✅ PASS | `pytest agents/tests/compute/test_compute_cost.py` → **15 passed** (0 failures, 0 errors) |
| 11 | Agent registration test updated (tool count 27→30) and passes | ✅ PASS | `test_exactly_30_tools_registered` asserts `len(registered) == 30`; new tool names in `_TOOL_NAMES`; **5/5 registration tests pass** |
| 12 | Cost Management Reader RBAC in `terraform/modules/rbac/main.tf` | ✅ PASS | Two blocks present: `compute-costmgmtreader-compute` and `compute-costmgmtreader-platform`, both with `role_definition_name = "Cost Management Reader"` |
| 13 | `propose_vm_sku_downsize` follows HITL pattern (`container=None`, `risk_level="medium"`, `incident_id=""`, `resource_id` in snapshot) | ✅ PASS | `container=None` (line 2991); `incident_id=""` (line 2994); `risk_level="medium"` (line 2998); `resource_snapshot={"vm_name": vm_name, "resource_id": resource_id, "target_sku": target_sku}` (line 2997) |
| 14 | No redundant stdlib imports inside function bodies | ✅ PASS | `datetime`, `timedelta`, `timezone` imported at module top-level (line 20); `query_vm_cost_7day` uses them directly without any inner `from datetime import …`; no other stdlib re-imports found inside tool function bodies |
| 15 | `total_recommendations` reflects pre-slice count in `vm_cost.py` | ✅ PASS | `total_recommendations = len(vms)` captured at line 111 **before** `vms = vms[:top]` slice at line 112; returned as `"total_recommendations": total_recommendations` |

## Summary

**Phase 39 PASSED — 15/15 must-haves verified.**

All 3 `@ai_function` tools are implemented, correctly decorated, and registered in all 4 required agent.py locations. Both new Azure SDK packages are present in compute requirements. The API gateway module exposes the `/api/v1/vms/cost-summary` endpoint and is registered in `main.py`. The `CostTab.tsx` component and its proxy route exist and are wired into `DashboardPanel.tsx` with correct TypeScript types. The SOP is present with the correct YAML front-matter and triage structure. All 15 unit tests pass (including HITL contract tests for `risk_level`, `incident_id`, and no-ARM-call assertions), and the agent registration test correctly asserts 30 tools. Terraform RBAC has two Cost Management Reader assignments scoped to compute and platform subscriptions. No stdlib imports inside function bodies. The `total_recommendations` count is captured before the `[:top]` slice.
