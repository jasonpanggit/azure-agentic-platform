---
plan_id: "43-1"
phase: 43
wave: 1
status: completed
completed_at: "2026-04-13"
pr: 75
---

# Summary 43-1: Centralized Logging

## What Was Built

Closed the centralized logging gap across VMSS, AKS, and Arc VMs. Operators can now trigger diagnostic settings from the detail panels, and Arc VMs no longer return HTTP 400.

### Files Created
- `docs/ops/enable-logging-rbac.md` — RBAC setup commands for Monitoring Contributor + VM Contributor
- `services/web-ui/app/api/proxy/vmss/[vmssId]/diagnostic-settings/route.ts` — VMSS diagnostic-settings proxy
- `services/web-ui/app/api/proxy/aks/[aksId]/diagnostic-settings/route.ts` — AKS diagnostic-settings proxy

### Files Modified
- `services/api-gateway/vm_detail.py` — Arc VM HTTP 400 fix: routes to HybridCompute DCR extension path (CENTRAL-005); `os_type` default aligned to `linux` on both GET and POST (CENTRAL-006)
- `services/web-ui/components/VMSSDetailPanel.tsx` — Enable Logging button in Overview tab
- `services/web-ui/components/AKSDetailPanel.tsx` — Enable Logging button in Overview tab
- `terraform/modules/agent-apps/variables.tf` — Added `log_analytics_workspace_resource_id` variable
- `terraform/modules/agent-apps/main.tf` — Inject `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` env var into api-gateway Container App
- `terraform/envs/prod/main.tf` — Pass LAW ARM resource ID value
- `services/api-gateway/tests/test_vm_detail.py` — Updated `test_enable_diag_settings_arc_vm_rejected` → `test_enable_diag_settings_arc_vm_accepted`
- `services/api-gateway/tests/test_aks_la_metrics.py` — Fixed ContainerServiceClient mock to resolve correctly on both Python 3.9 (no package) and Python 3.12 CI (package installed)

## Outcome

- Arc VM `POST /diagnostic-settings` now succeeds (routes to DCR extension path, not ARM path)
- VMSS and AKS detail panels show Enable Logging button in Overview tab
- `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` is available in the api-gateway Container App at runtime
- 878 tests passing
- CI Python 3.12 test isolation fixed: `_mock_containerservice` now always resolves from `sys.modules` so per-test attribute patches land on the correct object

## Key Decisions

- **Arc VM DCR path:** Azure ARM diagnostic-settings API returns 400 for Arc (HybridCompute) resources; the correct path is the DCR extension endpoint under `Microsoft.HybridCompute/machines/{name}/providers/Microsoft.Insights/diagnosticSettings`
- **sys.modules shim approach retained:** The `_mock_containerservice` shim is kept for local (no real package) compatibility; the fix makes it point to the real `sys.modules` entry so CI patches take effect on the installed package
