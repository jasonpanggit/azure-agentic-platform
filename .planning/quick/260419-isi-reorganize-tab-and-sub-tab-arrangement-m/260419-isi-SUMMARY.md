# Summary: Reorganize Tab and Sub-Tab Arrangement

**Date:** 2026-04-19  
**Commit:** 7629a18

## Changes Made

### Task 1 — ResourcesHubTab.tsx ✅
- Removed `Flame` icon and `FirewallTab` import
- Reordered sub-tabs: All Resources → VMs → Scale Sets → Kubernetes → App Services → Disks → AZ Coverage → Messaging → Resource Hierarchy
- Removed `firewall` render block

### Task 2 — NetworkHubTab.tsx ✅
- Added `Flame` to lucide-react imports
- Added `FirewallTab` import
- Added `firewall` sub-tab after `private-endpoints` (before `nsg-audit`)
- Added `{activeSubTab === 'firewall' && <FirewallTab subscriptions={subscriptions} />}` render block

### Task 3 — ChangeHubTab.tsx ✅
- Added `Zap` to lucide-react imports
- Added `ChangeIntelligenceTab` import
- Added `change-intelligence` sub-tab (5th entry)
- Added render block for `change-intelligence`

### Task 4 — DashboardPanel.tsx ✅
- Renamed `'Capacity & Quota'` → `'Capacity'`
- Moved `security` from Row 2 to end of Row 1
- Row 1: Dashboard, Alerts, Resources, Network, Security
- Row 2: Cost, Capacity, Change, Databases, Operations

## Verification

- [x] ResourcesHubTab has 9 sub-tabs (no Firewall, Hierarchy last)
- [x] NetworkHubTab has 6 sub-tabs (Firewall after Private Endpoints)
- [x] ChangeHubTab has 5 sub-tabs (Change Intelligence appended)
- [x] DashboardPanel Row 1 has 5 tabs ending with Security
- [x] DashboardPanel capacity label reads `'Capacity'`
- [x] No unused imports (Flame removed from Resources, added to Network)
