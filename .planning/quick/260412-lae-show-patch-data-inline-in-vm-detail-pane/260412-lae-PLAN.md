# Quick Task: Show Patch Data Inline in VM Detail Panel

**ID:** 260412-lae
**Created:** 2026-04-12
**Type:** UI Enhancement

## Problem

The VM detail panel's **Patches** tab (lines 1048-1093 of `VMDetailPanel.tsx`) currently shows a static redirect message: "Patch data available in Patch Management" with a link to the AI Chat tab. It should show the actual patch data inline — pending patches and installed patches — scoped to the selected VM.

## Analysis

The infrastructure to show per-VM patch data already exists:

1. **API endpoints exist:** The API gateway has `GET /api/v1/patch/pending?resource_id=...` and `GET /api/v1/patch/installed?resource_id=...&days=...` — both accept a full ARM resource ID and return per-VM patch data.

2. **Proxy routes exist:** The web UI has `/api/proxy/patch/pending` and `/api/proxy/patch/installed` proxy routes that forward to the API gateway.

3. **Full patch detail panel exists:** `InstalledPatchesPanel.tsx` already implements the exact UI needed — pending patches table, installed patches table, stat chips, days selector, CVE badges, and all sub-components. It fetches from the same proxy routes.

4. **VM detail panel has the resource ID:** `VMDetailPanel` receives `resourceId` (full ARM resource ID) as a prop, which is exactly what the patch endpoints need.

**Key insight:** Rather than duplicating the table components or building new ones, we can reuse the existing fetch logic pattern from `InstalledPatchesPanel.tsx` and render a simplified inline version of the patch data within the VMDetailPanel's Patches tab.

## Approach

Embed a lightweight inline patch view in the VMDetailPanel Patches tab that:
- Fetches pending and installed patches for the current VM using the existing proxy routes
- Shows summary stat chips (pending count, critical, security, installed, reboot status)
- Shows a tabbed view with Pending Patches and Installed Patches tables
- Reuses the existing type definitions and badge components from `InstalledPatchesPanel.tsx`

## Tasks

### Task 1: Add inline patch data fetching and rendering to VMDetailPanel Patches tab

**File:** `services/web-ui/components/VMDetailPanel.tsx`

**Changes:**
1. Add state variables for patch data (pending patches, installed patches, loading, error, days selector)
2. Add fetch functions for `/api/proxy/patch/pending?resource_id=...` and `/api/proxy/patch/installed?resource_id=...&days=...` (following the same pattern as `fetchMetrics`/`fetchVM`)
3. Add a lazy-fetch effect that triggers when the Patches tab is activated (same pattern as the metrics tab lazy-fetch on line 508-517)
4. Replace the static redirect message (lines 1048-1093) with:
   - Summary stat chips row (Pending, Critical, Security, Installed, Reboot)
   - Tab toggle (Pending / Installed) with a days selector for installed tab
   - Pending patches table (patch name, KB ID, classifications badge, version, CVEs)
   - Installed patches table (name, KB ID, category badge, version, installed date, CVEs)
   - Loading skeleton, empty state, and error state
5. Reset patch state in the `useEffect` that resets on resource change (line 461-479)

**Reuse from InstalledPatchesPanel.tsx:**
- Type definitions: `PendingPatch`, `InstalledPatch` (import or inline — since InstalledPatchesPanel exports `PanelMachine` but not the patch types, we'll define them inline or extract to a shared types file)
- Badge styling pattern: `classificationBadgeStyle()` helper
- CVE badge rendering pattern (simplified — just show count/list, without the full CveDetailDialog)
- `PATCH_SOFTWARE_TYPES` filter for installed patches

**Key design decisions:**
- Compact table rows (smaller than PatchTab's 16-column table) to fit the narrow panel width
- No drag-to-reposition or resize — data is inline within the existing panel
- Days selector defaults to 90 days, matching InstalledPatchesPanel
- Auth token forwarded via existing `getAccessToken()` helper

### Task 2: Verify build and test

- Run `npx tsc --noEmit` to verify TypeScript compiles
- Run `npm run build` to verify Next.js build succeeds
- Manually verify the Patches tab renders with loading states

## Acceptance Criteria

- [ ] Clicking the Patches tab in VMDetailPanel fetches and displays real patch data for the selected VM
- [ ] Pending patches show: patch name, KB ID, classifications, version, CVEs
- [ ] Installed patches show: name, category, version, installed date
- [ ] Summary chips show: pending count, critical count, security count, installed count, reboot status
- [ ] Loading skeleton shown while fetching
- [ ] Error state shown on fetch failure
- [ ] Empty state shown when no patches found
- [ ] Tab toggle between Pending and Installed works
- [ ] Days selector for installed patches works (30/90/180/365 days)
- [ ] `npx tsc --noEmit` passes
- [ ] `npm run build` succeeds

## Files Modified

| File | Change |
|------|--------|
| `services/web-ui/components/VMDetailPanel.tsx` | Replace static redirect with inline patch data view |

## Dependencies

- Existing proxy routes: `/api/proxy/patch/pending`, `/api/proxy/patch/installed` (no changes needed)
- Existing API gateway endpoints: `GET /api/v1/patch/pending`, `GET /api/v1/patch/installed` (no changes needed)
