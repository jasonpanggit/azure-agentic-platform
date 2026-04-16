---
slug: nav-sla-fix
date: 2026-04-16
status: planned
---

# Fix nav overflow and SLA 404

## Problems
1. Nav tab bar clips items — buttons lack `flex-shrink-0`/`whitespace-nowrap`; 15+ tabs compress before scroll activates
2. SLA tab shows "upstream 404" — `sla_definitions` table missing from `_run_startup_migrations()` in main.py; prod image is pre-phase-55 (no sla router registered → real 404)

## Changes

### 1. DashboardPanel.tsx — nav redesign for many tabs
- Add `whitespace-nowrap` and `shrink-0` to each tab button so they never compress
- Keep `overflow-x-auto` on container but add `scrollbar-none` + subtle fade-out gradient on right edge as scroll affordance
- Group tabs into logical clusters with thin dividers: Core | Resources | Monitoring | Governance | Config

### 2. main.py — add sla_definitions to startup migrations
- Add `CREATE TABLE IF NOT EXISTS sla_definitions (...)` block to `_run_startup_migrations()`
- Update the logger.info message to include sla_definitions

## Files
- `services/web-ui/components/DashboardPanel.tsx`
- `services/api-gateway/main.py`
