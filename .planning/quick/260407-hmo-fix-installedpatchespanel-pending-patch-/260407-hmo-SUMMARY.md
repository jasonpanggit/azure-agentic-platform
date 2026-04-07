# Quick Fix Summary: InstalledPatchesPanel Pending Patch Count

**Task ID:** 260407-hmo
**Status:** COMPLETE
**Date:** 2026-04-07

## Problem

The "Pending Patches" tab badge in `InstalledPatchesPanel.tsx` showed only the count of Critical + Security patches instead of the total count of all pending patches. A machine with 5 pending patches (2 Security + 2 Definition + 1 Updates) would display "2" in the badge.

**Root cause (line 561):**
```typescript
const totalPending = displayCritical + displaySecurity;
```

This summed only Critical and Security classifications, ignoring Definition, Updates, and other patch types.

## Fix Applied

**File:** `services/web-ui/components/InstalledPatchesPanel.tsx` (line 561)

Replaced:
```typescript
const totalPending = displayCritical + displaySecurity;
```

With:
```typescript
const totalPending = pendingLoading
  ? (machine.criticalCount ?? 0) + (machine.securityCount ?? 0)
  : pendingPatches.length;
```

- **After loading:** Uses `pendingPatches.length` for the accurate total count of all pending patches regardless of classification.
- **During loading:** Falls back to the assessment summary fields (`criticalCount + securityCount`) as a best-effort estimate until the full list arrives.

## Verification

- `npx tsc --noEmit` exits 0 (zero TypeScript errors)
- Single atomic commit: `048053d`

## Commits

| Hash | Description |
|------|-------------|
| `048053d` | fix(patch): use total pending patches count for tab badge |
