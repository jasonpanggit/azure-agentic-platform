# Plan 15-05 Summary: Frontend Evidence Integration

## Status: COMPLETE

## Tasks Completed

- [x] **Task 1**: Created `services/web-ui/app/api/proxy/incidents/[incidentId]/evidence/route.ts`
  - Uses correct project pattern: `getApiGatewayUrl()` + `buildUpstreamHeaders()` (not `getProxyHeaders` as plan draft showed)
  - Handles 202 (pipeline pending) with `Retry-After` header forwarding
  - Handles 200 (evidence ready) with full data passthrough
  - Fixed Next.js 15 async params: `{ params: Promise<{ incidentId: string }> }`
- [x] **Task 2**: Created `services/web-ui/app/api/proxy/vms/route.ts`
  - Forwards `subscriptions`, `status`, `search` query params
  - Returns `{ vms: [], total: 0, has_more: false }` gracefully on non-OK response or network error
  - Correct pattern: `buildUpstreamHeaders()` + `AbortSignal.timeout(15000)`
- [x] **Task 3**: AlertFeed `resource_name` + `resource_group` columns — already present from plan 15-03
- [x] **Task 4**: AlertFeed "Evidence Ready" badge — already present from plan 15-03
- [x] **Task 5**: AlertFeed "Investigate" button + "Actions" column header added
  - Added `Actions` column to both loading skeleton header and live table header
  - Added skeleton cell for Actions column in loading state
  - Added `Investigate` button to data rows (only when `resource_name` is set)
  - `onClick` calls `e.stopPropagation()` to prevent row click conflict
- [x] **Task 6**: Created `services/web-ui/components/VMTab.tsx`
  - `PowerStateBadge` and `HealthBadge` sub-components
  - Fetches from `/api/proxy/vms` endpoint
  - Loading skeleton (5-row pulse animation)
  - Empty state with Server icon + "VM inventory endpoint available in Phase 2" note
  - Error state
  - Full VM table (Name, Resource Group, Size, OS, Power State, Health, Alerts)
  - Search input + Refresh button in header
- [x] **Task 7**: Updated `services/web-ui/components/DashboardPanel.tsx`
  - Imported `Monitor` from lucide-react and `VMTab` from `./VMTab`
  - Added `'vms'` to `TabId` union type
  - Added `{ id: 'vms', label: 'VMs', Icon: Monitor }` to TABS array (between Resources and Observability)
  - Added `tabpanel-vms` panel div with `<VMTab subscriptions={selectedSubscriptions} />`
- [x] **Task 8**: Committed with plan-specified commit message

## Files Modified

| File | Type | Change |
|------|------|--------|
| `services/web-ui/app/api/proxy/incidents/[incidentId]/evidence/route.ts` | New | Evidence proxy route |
| `services/web-ui/app/api/proxy/vms/route.ts` | New | VM inventory proxy route |
| `services/web-ui/components/VMTab.tsx` | New | VM fleet table component |
| `services/web-ui/components/AlertFeed.tsx` | Modified | Added Actions column + Investigate button |
| `services/web-ui/components/DashboardPanel.tsx` | Modified | Added VMs tab |

## Test Results

### Build
```
✓ Compiled successfully
✓ Types checked — no errors
5 new/modified files in route manifest
```

New routes in build output:
- `ƒ /api/proxy/incidents/[incidentId]/evidence`
- `ƒ /api/proxy/vms`

### Jest
- **Pre-existing failures**: 3 tests failing before and after these changes (stream-poll-url, stream heartbeat, jest-globals-setup empty suite) — unrelated to this plan
- **No regressions**: Test count identical to baseline (3 failed, 3 skipped, 25 passed)

## Issues Encountered

1. **Next.js 15 async params**: The plan's `route.ts` template used `{ params: { incidentId: string } }` but Next.js 15 requires `{ params: Promise<{ incidentId: string }> }` with `await params`. Build caught this immediately — fixed before commit.

2. **`getProxyHeaders` doesn't exist**: The plan referenced `getProxyHeaders` but the actual codebase uses `buildUpstreamHeaders(authHeader, includeContentType)`. Detected by reading the existing route before writing — used correct function.

3. **AlertFeed already partially updated**: Tasks 3 and 4 (resource columns + Evidence Ready badge) were already implemented by plan 15-03. Only Task 5 (Investigate button + Actions column) needed to be added. Verified current state before editing to avoid duplication.
