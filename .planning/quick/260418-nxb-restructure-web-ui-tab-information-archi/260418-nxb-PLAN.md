# Plan: Restructure Web UI Tab Information Architecture

**Mode:** quick  
**Date:** 2026-04-18  
**Branch:** (current working branch)

## Objective

Split `CostHubTab` into two separate top-level tabs:
- **Cost** — Cost & Advisor, Budgets sub-tabs
- **Capacity & Quota** — Quota Usage, Quota Limits, Capacity sub-tabs

---

## Tasks

### Task 1 — Create `CapacityQuotaHubTab.tsx`

Create `services/web-ui/components/CapacityQuotaHubTab.tsx` as a new hub tab component.

- Copy the hub tab shell pattern from `CostHubTab.tsx`
- Sub-tabs: `quota-usage` (Quota Usage / BarChart3), `capacity` (Capacity / Gauge), `quotas` (Quota Limits / BarChart2)
- Import `QuotaUsageTab`, `CapacityTab`, `QuotaTab`
- Props: `{ subscriptions: string[]; initialSubTab?: string }`
- Export: `CapacityQuotaHubTab`

### Task 2 — Trim `CostHubTab.tsx`

Remove the Quota/Capacity sub-tabs from `CostHubTab.tsx`:

- Remove `quota-usage`, `capacity`, `quotas` entries from `subTabs`
- Remove imports: `QuotaUsageTab`, `CapacityTab`, `QuotaTab`
- Remove icons: `BarChart3`, `Gauge`, `BarChart2`
- Remove render blocks for those three sub-tabs

### Task 3 — Update `DashboardPanel.tsx`

Wire the new tab into the navigation:

1. Add `'capacity'` to the `TabId` union type
2. Import `CapacityQuotaHubTab`
3. Add icon import: `Layers` from `lucide-react` (represents resource layers/quota)
4. Add tab to `TAB_GROUPS` Group 2, after `cost`:
   ```ts
   { id: 'capacity', label: 'Capacity & Quota', Icon: Layers },
   ```
5. Add render block in the tab panel section:
   ```tsx
   {activeTab === 'capacity' && (
     <CapacityQuotaHubTab subscriptions={selectedSubscriptions} />
   )}
   ```

---

## Files Changed

| File | Action |
|------|--------|
| `services/web-ui/components/CapacityQuotaHubTab.tsx` | CREATE |
| `services/web-ui/components/CostHubTab.tsx` | MODIFY (remove 3 sub-tabs) |
| `services/web-ui/components/DashboardPanel.tsx` | MODIFY (add tab + import) |

## No proxy route changes needed
The sub-tab components (`QuotaUsageTab`, `CapacityTab`, `QuotaTab`) already own their own proxy routes. Splitting the hub tab is purely a UI composition change.
