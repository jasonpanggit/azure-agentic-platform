# Summary: Cost Tab UX Overhaul — Card Layout

**ID:** 260414-15e
**Status:** Done
**Branch:** `fix/cost-tab-card-layout`

## Changes

Single file: `services/web-ui/components/CostTab.tsx`

### Removed
- Table component imports (Table, TableBody, TableCell, TableHead, TableHeader, TableRow)
- 8-column table markup with dead columns (Current SKU, Recommended SKU, Resource Group)
- `max-w-[250px] truncate` on description — descriptions are now shown in full

### Added
- **Card + CardContent** imports from `@/components/ui/card`
- **`extractTitle(description)`** — extracts first sentence (up to 80 chars) as card title
- **`cleanServiceType(resourceType)`** — maps `Subscriptions/subscriptions` to `"Subscription-level"`, strips `Microsoft.` prefix, maps common types to friendly names
- **Responsive card grid:** `grid grid-cols-1 md:grid-cols-2 gap-3 p-4`
- **Sort by savings descending** — immutable `[...recommendations].sort()` before render
- Badge text updated from "X resources" to "X recommendations"

### Card layout per recommendation
- Top row: impact badge (left) + monthly savings in green (right)
- Title: first sentence from description, `text-[14px] font-medium`
- Service type: blue `color-mix` pill badge
- Full description: `text-[12px]`, `leading-relaxed`, no truncation
- Bottom row (separator): annual savings (left) + last updated date (right)

### Unchanged
- All interfaces (`CostRecommendation`, `CostSummaryResponse`, `CostTabProps`)
- `fetchCostData` logic, loading/error/empty states
- `impactBadgeStyle()` and `formatCurrency()` helpers
- Header bar with total savings + refresh button + data lag note

## Verification
- `tsc --noEmit` — zero errors
- `npm run build` — clean build, no warnings
- Semantic CSS tokens only (no hardcoded Tailwind colors)
- Dark-mode safe via `color-mix` badges
- Responsive: 1 column mobile, 2 columns md+
