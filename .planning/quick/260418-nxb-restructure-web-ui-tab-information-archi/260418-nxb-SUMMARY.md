# Summary: Restructure Web UI Tab Information Architecture

**Date:** 2026-04-18  
**Commit:** b390e0d

## What Was Done

Split `CostHubTab` into two distinct top-level navigation tabs to reduce cognitive overload and group related concerns:

| Tab | Sub-tabs |
|-----|----------|
| **Cost** | Cost & Advisor, Budgets |
| **Capacity & Quota** _(new)_ | Quota Usage, Capacity, Quota Limits |

## Files Changed

| File | Action |
|------|--------|
| `services/web-ui/components/CapacityQuotaHubTab.tsx` | Created — new hub shell with 3 sub-tabs |
| `services/web-ui/components/CostHubTab.tsx` | Trimmed — removed 3 quota/capacity sub-tabs |
| `services/web-ui/components/DashboardPanel.tsx` | Updated — added `capacity` TabId, `Layers` icon, tab entry in Group 2, render block |

## No Proxy/API Changes

Sub-tab components (`QuotaUsageTab`, `CapacityTab`, `QuotaTab`) own their own data fetching and proxy routes — this was a pure UI composition change.
