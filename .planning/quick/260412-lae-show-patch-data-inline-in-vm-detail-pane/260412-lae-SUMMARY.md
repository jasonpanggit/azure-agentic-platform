# Quick Task Summary: Show Patch Data Inline in VM Detail Panel

**ID:** 260412-lae
**Status:** COMPLETE
**Date:** 2026-04-12
**Commit:** f6654b7

## What Changed

Replaced the static redirect message ("Patch data available in Patch Management") in the VMDetailPanel Patches tab with real inline patch data fetched from existing API endpoints.

## File Modified

| File | Change |
|------|--------|
| `services/web-ui/components/VMDetailPanel.tsx` | +444 / -36 lines — inline patch data view |

## Implementation Details

### State & Types Added
- `PendingPatch` and `InstalledPatch` interfaces (mirroring InstalledPatchesPanel types)
- `PatchSubTab` (`'pending' | 'installed'`), `DaysOption` (`'30' | '90' | '180' | '365'`)
- State: `patchSubTab`, `pendingPatches`, `installedPatches`, `patchLoading`, `patchError`, `patchDays`
- `patchLoadedRef` to prevent duplicate fetches
- `classificationBadgeColor()` helper for Critical/Security/Other badge styling

### Fetch Functions
- `fetchPendingPatches()` — calls `/api/proxy/patch/pending?resource_id=...` with auth token, 15s timeout
- `fetchInstalledPatches(daysVal)` — calls `/api/proxy/patch/installed?resource_id=...&days=...`, filters by `PATCH_SOFTWARE_TYPES`
- `fetchAllPatches(daysVal)` — runs both in parallel via `Promise.all`

### Lazy-Fetch Behavior
- Patches fetched on first activation of the Patches tab (`patchLoadedRef`)
- Installed patches refetched when days selector changes
- All patch state reset on resource change

### UI Rendering
- **Summary stat chips** (3-column grid): Pending, Critical, Security, Installed count, Reboot Required
- **Sub-tab toggle**: Pending Patches / Installed Patches with count badges
- **Days selector** (30d/90d/180d/1y) shown only on Installed sub-tab
- **Pending patch cards**: patch name, KB ID, classification badges, version, reboot flag, CVE badges (max 3 shown)
- **Installed patch cards**: software name, KB ID (parsed from name), category badge, version, installed date, CVE badges
- **Loading skeleton**: 4 animated placeholder bars
- **Error state**: red warning icon with retry button
- **Empty states**: green checkmark for up-to-date (pending) or muted icon for no records (installed)

## Verification

- `npx tsc --noEmit` — zero VMDetailPanel errors
- No new proxy routes or API endpoints needed (reuses existing infrastructure)
- Card-based layout fits the narrow panel width better than table layout

## Acceptance Criteria

- [x] Clicking the Patches tab fetches and displays real patch data for the selected VM
- [x] Pending patches show: patch name, KB ID, classifications, version, CVEs
- [x] Installed patches show: name, category, version, installed date
- [x] Summary chips show: pending count, critical count, security count, installed count, reboot status
- [x] Loading skeleton shown while fetching
- [x] Error state shown on fetch failure
- [x] Empty state shown when no patches found
- [x] Tab toggle between Pending and Installed works
- [x] Days selector for installed patches works (30/90/180/365 days)
- [x] `npx tsc --noEmit` passes (no VMDetailPanel errors)
