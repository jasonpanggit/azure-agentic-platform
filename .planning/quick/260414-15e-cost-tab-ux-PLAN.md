# Quick Plan: Cost Tab UX Overhaul — Card Layout

**ID:** 260414-15e
**File:** `services/web-ui/components/CostTab.tsx`
**Branch:** `fix/cost-tab-card-layout`

## Problem

The Cost tab renders Azure Advisor service-level recommendations in an 8-column table designed for VM-level SKU changes. For service-level recommendations (e.g. "Consider Microsoft Fabric reservations"):

| Column | Problem |
|--------|---------|
| Resource | Shows `/subscriptions/xxx/...` raw path |
| Resource Type | Shows `Subscriptions/subscriptions` — meaningless |
| Resource Group | Shows full subscription ID (identical for all rows) |
| Current SKU | Always `—` |
| Recommended SKU | Always `—` |
| Description | Truncated at 250px, no way to read full text |

3 of 8 columns are always empty/useless; 2 more show raw IDs; the most useful column is truncated.

## Solution

Replace the dense table with a **card-based layout** optimized for service-level recommendations. Single file change — the component is self-contained.

## Implementation Steps

### Step 1: Add helper functions (top of file)
- [ ] `extractTitle(description: string): string` — extracts the first sentence or first ~80 chars as a recommendation title (split on `.` or truncate at word boundary)
- [ ] `cleanServiceType(resourceType: string): string` — strips `Microsoft.` prefix AND handles the `Subscriptions/subscriptions` case by returning `"Subscription-level"`. Also maps common types to friendly names (e.g. `Compute/virtualMachines` -> `Virtual Machines`)
- [ ] `formatSavings(amount: number, currency: string): string` — existing `formatCurrency` with added `$0` handling

### Step 2: Replace Table with Card grid
- [ ] Remove `Table`, `TableBody`, `TableCell`, `TableHead`, `TableHeader`, `TableRow` imports
- [ ] Add `Card`, `CardContent` imports from `@/components/ui/card`
- [ ] Remove columns: Current SKU, Recommended SKU, Resource Group
- [ ] Replace `<Table>` section with a responsive card grid: `grid grid-cols-1 md:grid-cols-2 gap-3 p-4`

### Step 3: Design each recommendation card
Each card layout (using existing shadcn Card + semantic tokens):

```
+----------------------------------------------------------+
| [Impact Badge: High]              [$X,XXX.XX/mo savings] |
|                                                          |
| Recommendation Title (extracted from description)        |
| text-[14px] font-medium, var(--text-primary)             |
|                                                          |
| Service Type badge: e.g. "Subscription-level"            |
| text-[11px], var(--accent-blue) color-mix badge          |
|                                                          |
| Full description text (no truncation)                    |
| text-[12px], var(--text-secondary), leading-relaxed      |
|                                                          |
| Annual savings: $XX,XXX.XX/yr  |  Last updated: date    |
+----------------------------------------------------------+
```

- [ ] Card border uses `var(--border)` (already default from shadcn Card)
- [ ] Impact badge: reuse existing `impactBadgeStyle()` helper (already uses `color-mix` + semantic tokens)
- [ ] Monthly savings: prominent, `text-[16px] font-semibold`, `var(--accent-green)`
- [ ] Title: first sentence from `description`, `text-[14px] font-medium`
- [ ] Service type: small pill badge with `color-mix(in srgb, var(--accent-blue) 15%, transparent)`
- [ ] Description: full text, `text-[12px]`, `var(--text-secondary)`, `leading-relaxed` — **no truncation** (these are typically 1-3 sentences, not paragraphs)
- [ ] Annual savings as secondary info at card bottom, `text-[11px]`
- [ ] `last_updated` formatted with `toLocaleDateString()` at card bottom

### Step 4: Keep existing header intact
- [ ] Retain the header bar with total savings badge, refresh button, recommendation count
- [ ] Retain the data lag note section
- [ ] Update badge text from "X resources" to "X recommendations" (more accurate for service-level recs)

### Step 5: Sort cards by savings (highest first)
- [ ] Sort `recommendations` by `estimated_monthly_savings` descending before rendering
- [ ] Immutable sort: `[...recommendations].sort((a, b) => b.estimated_monthly_savings - a.estimated_monthly_savings)`

## Kept As-Is
- `CostRecommendation` interface — no changes (backend contract)
- `CostSummaryResponse` interface — no changes
- `CostTabProps` interface — no changes
- `fetchCostData` logic — no changes
- Loading/error/empty states — no changes (already good)
- `impactBadgeStyle()` helper — reused directly

## Removed
- Table component imports (Table, TableBody, TableCell, TableHead, TableHeader, TableRow)
- All 8-column table markup
- `max-w-[250px] truncate` on description

## Added
- Card component imports
- `extractTitle()` helper
- `cleanServiceType()` helper  
- Card grid layout
- Sort by savings

## Verification
- [ ] `npm run build` in `services/web-ui/` — no type errors
- [ ] Visual check: cards render with semantic tokens (no hardcoded colors)
- [ ] Dark mode: verify `color-mix` badges still readable
- [ ] Responsive: single column on mobile, 2 columns on md+
- [ ] Empty/loading/error states unchanged
