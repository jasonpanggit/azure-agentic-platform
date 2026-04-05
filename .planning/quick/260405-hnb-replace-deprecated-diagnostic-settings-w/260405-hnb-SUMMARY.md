# Summary: Replace Deprecated Diagnostic Settings with AMA + DCR

**ID:** 260405-hnb
**Status:** COMPLETE
**Date:** 2026-04-05

## What Changed

Replaced the deprecated `microsoft.insights/diagnosticSettings` API (sunset 2026-03-31) with Azure Monitor Agent (AMA) + Data Collection Rules (DCR) approach across backend, frontend, and tests.

## Commits

| # | Commit | Description |
|---|--------|-------------|
| 1 | `1d8efcd` | refactor: replace deprecated diagnostic settings with AMA + DCR helpers |
| 2 | `87c67f7` | feat: update frontend diagnostic banner for AMA + DCR three-state UI |
| 3 | `3eca489` | test: add 19 tests for AMA/DCR helpers and diagnostic settings endpoints |

## Files Changed

| File | Change |
|------|--------|
| `services/api-gateway/vm_detail.py` | Removed `_check_diag_settings`, `_enable_diag_settings`, `_DIAG_SETTING_NAME`, `_DIAG_API`. Added 6 new helpers: `_is_arc_vm`, `_check_ama_installed`, `_list_dcr_associations`, `_ensure_platform_dcr`, `_create_dcr_association`, `_install_ama_extension`. Updated GET/POST route handlers with new response shape and `os_type` query param. |
| `services/web-ui/components/VMDetailPanel.tsx` | Added `diagAmaInstalled` and `diagDcrAssociated` state. Three-state diagnostic banner (green/amber/blue). `os_type` query param passed in GET and POST. |
| `services/web-ui/app/api/proxy/vms/[vmId]/diagnostic-settings/route.ts` | Forward query params to upstream API gateway (both GET and POST). |
| `services/api-gateway/tests/test_vm_detail.py` | Added 19 new tests covering all new helpers + endpoint behaviors. |

## API Changes

**GET `/api/v1/vms/{id}/diagnostic-settings`**
- New query param: `os_type` (optional, defaults to "windows")
- New response shape: `{ ama_installed: bool, dcr_associated: bool, configured: bool }`
- Arc VMs: returns `{ ama_installed: false, dcr_associated: false, configured: false }` without API calls

**POST `/api/v1/vms/{id}/diagnostic-settings`**
- New query param: `os_type` (optional, defaults to "linux")
- Operations: ensure platform DCR + create DCR association + install AMA extension (parallel where possible)
- Arc VMs: returns 400 with message

## Verification

- [x] `pytest services/api-gateway/tests/test_vm_detail.py -v` -- 28/28 pass
- [x] `cd services/web-ui && npx tsc --noEmit` -- zero errors
- [x] No deprecated `microsoft.insights/diagnosticSettings` references remain in vm_detail.py (only in comment documenting the replacement)
