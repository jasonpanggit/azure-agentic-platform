---
plan_id: "43-1"
phase: 43
wave: 1
title: "Centralized Logging — VMSS/AKS enable-logging buttons, Arc VM DCR fix, Terraform LAW ARM ID injection"
goal: "Enable operators to activate diagnostic settings for VMSS and AKS clusters from the detail panels, fix Arc VM diagnostic-settings routing to use the HybridCompute DCR extension path, and inject the Log Analytics Workspace ARM resource ID into the api-gateway Container App via Terraform."
---

# Plan 43-1: Centralized Logging

## Context

Phase 43 closes the gap where VMSS and AKS resources had no way to enable centralized logging from the UI. Arc VMs were also rejecting diagnostic-settings POSTs with HTTP 400. The Log Analytics Workspace resource ID was not wired into the api-gateway environment.

**Key files to read before tasks:**
- `services/api-gateway/vm_detail.py` — Arc VM routing pattern, DCR extension path
- `services/web-ui/components/VMDetailPanel.tsx` — Enable Logging button pattern
- `terraform/modules/agent-apps/main.tf` — env var injection pattern

---

## Tasks

### Task 1 — Terraform: inject LAW ARM resource ID
- Add `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` variable to `terraform/modules/agent-apps/variables.tf`
- Wire it as an env var on the api-gateway Container App in `terraform/modules/agent-apps/main.tf`
- Pass the value from `terraform/envs/prod/main.tf`

### Task 2 — API Gateway: fix Arc VM diagnostic-settings routing (CENTRAL-005)
- `vm_detail.py`: Arc VMs (`Microsoft.HybridCompute/machines`) must use the DCR extension path, not the ARM diagnostic-settings path (which returns 400)
- Route Arc VM `POST /diagnostic-settings` to HybridCompute DCR extension endpoint

### Task 3 — API Gateway: align os_type default (CENTRAL-006)
- `vm_detail.py`: Ensure `os_type` defaults to `linux` on both GET and POST paths for consistency

### Task 4 — VMSS detail panel: Enable Logging button
- `VMSSDetailPanel.tsx`: Add Enable Logging button in Overview tab
- Proxy route: `services/web-ui/app/api/proxy/vmss/[vmssId]/diagnostic-settings/route.ts`
- Button calls `POST /api/proxy/vmss/{id}/diagnostic-settings`

### Task 5 — AKS detail panel: Enable Logging button
- `AKSDetailPanel.tsx`: Add Enable Logging button in Overview tab
- Proxy route: `services/web-ui/app/api/proxy/aks/[aksId]/diagnostic-settings/route.ts`
- Button calls `POST /api/proxy/aks/{id}/diagnostic-settings`

### Task 6 — RBAC docs
- `docs/ops/enable-logging-rbac.md`: `az role assignment create` commands for Monitoring Contributor + VM Contributor

### Task 7 — Tests
- Update `test_vm_detail.py`: `test_enable_diag_settings_arc_vm_rejected` → `test_enable_diag_settings_arc_vm_accepted`
- Fix `test_aks_la_metrics.py`: ContainerServiceClient mock bypass on Python 3.12 CI
