# Quick Plan: Replace Deprecated Diagnostic Settings with AMA + DCR

**ID:** 260405-hnb
**Created:** 2026-04-05
**Status:** PLANNED

## Context

The current `GET/POST /api/v1/vms/{id}/diagnostic-settings` uses the ARM `microsoft.insights/diagnosticSettings` API which was deprecated on 2026-03-31. The replacement approach uses:
- **AMA (Azure Monitor Agent)** — VM extension replacing WAD/LAD
- **Data Collection Rules (DCR)** — defines what to collect and where to send
- **DCR Associations** — links a DCR to a VM resource

## Files to Change

| File | Change |
|------|--------|
| `services/api-gateway/vm_detail.py` | Replace `_check_diag_settings` and `_enable_diag_settings` helpers + update route handlers |
| `services/web-ui/components/VMDetailPanel.tsx` | Update `fetchDiagSettings` response handling + diagnostic banner UI states |
| `services/api-gateway/tests/test_vm_detail.py` | Add tests for new AMA/DCR helpers and route handlers |

**No changes needed:** `services/web-ui/app/api/proxy/vms/[vmId]/diagnostic-settings/route.ts` (proxy is a passthrough).

## Tasks

### Task 1: Backend — Replace deprecated helpers in `vm_detail.py`

Replace the deprecated `_check_diag_settings` / `_enable_diag_settings` functions and update the diagnostic settings route handlers.

**Remove:**
- `_DIAG_SETTING_NAME`, `_DIAG_API` constants
- `_check_diag_settings()` — queries `microsoft.insights/diagnosticSettings/{name}`
- `_enable_diag_settings()` — creates/updates diagnostic setting via PUT

**Add:**
- `_check_ama_installed(credential, resource_id)` — GET `{vm}/extensions/AzureMonitorWindowsAgent` or `AzureMonitorLinuxAgent` (api-version=2023-03-01). Return bool. Try Windows first, then Linux. 404 = not installed.
- `_list_dcr_associations(credential, resource_id)` — GET `{vm}/providers/Microsoft.Insights/dataCollectionRuleAssociations?api-version=2022-06-01`. Return bool (any association exists).
- `_ensure_platform_dcr(credential, workspace_resource_id)` — Extract sub/rg from `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID`. PUT `...Microsoft.Insights/dataCollectionRules/aap-dcr?api-version=2022-06-01` with body containing:
  - Windows perf counters (CPU, Memory, Disk, Network)
  - Linux perf counters (same categories)
  - Syslog (LOG_WARNING+) and Windows Event Log (System, Application)
  - Destination: LA workspace
  - Returns DCR resource ID
- `_create_dcr_association(credential, resource_id, dcr_resource_id)` — PUT `{vm}/providers/Microsoft.Insights/dataCollectionRuleAssociations/aap-dcr-assoc?api-version=2022-06-01`
- `_install_ama_extension(credential, resource_id, os_type)` — PUT `{vm}/extensions/{AzureMonitorWindowsAgent|AzureMonitorLinuxAgent}?api-version=2023-03-01`. Set `publisher=Microsoft.Azure.Monitor`, `type=AzureMonitorWindowsAgent|AzureMonitorLinuxAgent`, `typeHandlerVersion=1.*`, `autoUpgradeMinorVersion=true`.

**Update GET handler** (`get_diagnostic_settings`):
- Call `_check_ama_installed` + `_list_dcr_associations` in parallel (run_in_executor)
- Return `{"ama_installed": bool, "dcr_associated": bool, "configured": ama_installed and dcr_associated}`
- Arc VMs (detect by `microsoft.hybridcompute` in resource_id): return `{"ama_installed": false, "dcr_associated": false, "configured": false}` without API calls

**Update POST handler** (`enable_diagnostic_settings`):
- Guard: require `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` (existing check)
- Guard: Arc VM detection — return 400 "AMA install for Arc VMs is not yet supported"
- Need `os_type` to select correct extension name — extract from resource_id path or pass as query param. Simplest: accept optional `?os_type=Windows|Linux` query param, default to "Linux".
- Steps: `_ensure_platform_dcr` -> `_create_dcr_association` -> `_install_ama_extension`
- Return `{"status": "enabled", "ama_installed": true, "dcr_associated": true, "configured": true}`
- Wrap in try/except, return 502 on failure

**Acceptance criteria:**
- [x] Old deprecated API calls completely removed
- [x] GET returns `ama_installed`, `dcr_associated`, `configured` shape
- [x] POST creates DCR + association + installs AMA
- [x] Arc VMs handled gracefully (no install attempt)
- [x] All ARM calls use `_arm_token` (existing helper)
- [x] Follows existing tool function pattern: `start_time`, `duration_ms`, structured logging

### Task 2: Frontend — Update VMDetailPanel diagnostic banner

Update `fetchDiagSettings()` and the banner UI in `VMDetailPanel.tsx`.

**State changes:**
- Replace `diagConfigured: boolean | null` with:
  - `diagAmaInstalled: boolean | null`
  - `diagDcrAssociated: boolean | null`
  - `diagConfigured: boolean | null` (keep — derived from ama + dcr)

**Update `fetchDiagSettings()`:**
- Parse new response shape: `data.ama_installed`, `data.dcr_associated`, `data.configured`
- Set all three state values

**Update banner UI (below metrics section):**
- If `diagConfigured === true`: green checkmark "Azure Monitor Agent active with data collection rule"
- If `diagAmaInstalled === true && diagDcrAssociated === false`: orange "AMA installed, no data collection rule configured" + Enable button
- If `diagConfigured === false && diagAmaInstalled === false`: blue info "Enable monitoring — installs Azure Monitor Agent + creates data collection rule" + Enable button
- During enable: show spinner (existing `diagEnabling` state)
- On error: show error message (existing `diagError` state)

**Update `enableDiagSettings()`:**
- Add `os_type` query param to POST URL: infer from `vm?.os_type` (already available in VM detail state)
- On success, set all three diag states to true

**Acceptance criteria:**
- [x] Three-state banner (configured / partial / not configured)
- [x] Uses semantic CSS tokens (var(--accent-*)) — no hardcoded Tailwind colors
- [x] `os_type` sent in POST for correct AMA extension selection

### Task 3: Tests — Add unit tests for new AMA/DCR helpers

Add tests to `services/api-gateway/tests/test_vm_detail.py`.

**Tests to add:**
1. `test_check_ama_installed_windows` — mock ARM GET returning 200 for Windows agent
2. `test_check_ama_installed_linux` — mock ARM GET returning 404 for Windows, 200 for Linux
3. `test_check_ama_not_installed` — mock ARM GET returning 404 for both
4. `test_list_dcr_associations_found` — mock ARM GET returning association list
5. `test_list_dcr_associations_empty` — mock ARM GET returning empty list
6. `test_ensure_platform_dcr` — mock ARM PUT returning 200 with DCR body
7. `test_create_dcr_association` — mock ARM PUT returning 200
8. `test_install_ama_extension` — mock ARM PUT returning 200/201
9. `test_get_diagnostic_settings_endpoint_ama_active` — TestClient GET returning configured=true
10. `test_get_diagnostic_settings_endpoint_not_configured` — TestClient GET returning configured=false
11. `test_get_diagnostic_settings_arc_vm_returns_false` — Arc resource ID returns all false without API calls
12. `test_enable_diagnostic_settings_endpoint` — TestClient POST succeeding
13. `test_enable_diagnostic_settings_arc_vm_rejected` — TestClient POST returning 400 for Arc VM

**Acceptance criteria:**
- [x] All new helpers have at least one happy-path + one error-path test
- [x] Route endpoint tests use TestClient (matches existing pattern)
- [x] All tests pass: `pytest services/api-gateway/tests/test_vm_detail.py -v`

## Verification

- [ ] `pytest services/api-gateway/tests/test_vm_detail.py -v` — all pass
- [ ] `cd services/web-ui && npx tsc --noEmit` — zero errors
- [ ] No deprecated `microsoft.insights/diagnosticSettings` references remain in `vm_detail.py`
