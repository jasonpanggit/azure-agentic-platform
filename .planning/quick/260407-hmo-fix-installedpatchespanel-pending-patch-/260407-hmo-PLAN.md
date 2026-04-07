# Quick Fix: InstalledPatchesPanel Pending Patch Count

**Created:** 2026-04-07
**Type:** Bug fix
**File:** `services/web-ui/components/InstalledPatchesPanel.tsx`

## Problem

The "Pending Patches" tab badge shows only Critical + Security patch counts instead of the total count of all pending patches. For example, a machine with 5 pending patches (2 Security + 2 Definition + 1 Updates) shows "2" in the badge.

**Root cause** (line 561):
```typescript
const totalPending = displayCritical + displaySecurity;
```

This sums only Critical and Security classifications, ignoring Definition, Updates, and other patch types.

## Fix

- [ ] **Task 1:** Change `totalPending` to use `pendingPatches.length` (total count of all fetched pending patches) instead of `displayCritical + displaySecurity`. When loading, fall back to `machine.criticalCount + machine.securityCount` as a best-effort estimate.
- [ ] **Task 2:** Verify `npm run build` passes with zero TypeScript errors.

## Change Detail

**Line 561** — replace:
```typescript
const totalPending = displayCritical + displaySecurity;
```

With:
```typescript
const totalPending = pendingLoading
  ? (machine.criticalCount ?? 0) + (machine.securityCount ?? 0)
  : pendingPatches.length;
```

This ensures the badge reflects all pending patches regardless of classification, while still showing a reasonable estimate during loading.
