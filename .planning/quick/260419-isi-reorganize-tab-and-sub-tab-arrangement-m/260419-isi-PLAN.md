# Plan: Reorganize Tab and Sub-Tab Arrangement

**Mode:** quick  
**Date:** 2026-04-19  
**Branch:** current working branch

## Objective

5 targeted changes to tab/sub-tab layout across 4 files. No logic changes — purely organizational.

---

## Tasks

### Task 1 — ResourcesHubTab.tsx: Remove Firewall, reorder sub-tabs

**File:** `services/web-ui/components/ResourcesHubTab.tsx`

Changes:
1. Remove `Flame` from lucide-react import
2. Remove `FirewallTab` import
3. Reorder `subTabs` array to: All Resources, VMs, Scale Sets, Kubernetes, App Services, Disks, AZ Coverage, Messaging, Resource Hierarchy
4. Remove `firewall` render block (`{activeSubTab === 'firewall' && ...}`)

Target order:
```
all-resources → vms → vmss → aks → app-services → disks → az-coverage → messaging → resource-hierarchy
```

---

### Task 2 — NetworkHubTab.tsx: Add Firewall sub-tab after Private Endpoints

**File:** `services/web-ui/components/NetworkHubTab.tsx`

Changes:
1. Add `import FirewallTab from './FirewallTab'`
2. Add `Flame` to lucide-react imports
3. Add `{ id: 'firewall', label: 'Firewall', icon: Flame }` to `subTabs` after `private-endpoints` (before `nsg-audit`)
4. Add render block: `{activeSubTab === 'firewall' && <FirewallTab subscriptions={subscriptions} />}`

Final sub-tab order: Topology Map, VNet Peerings, Load Balancers, Private Endpoints, Firewall, NSG Audit

---

### Task 3 — ChangeHubTab.tsx: Add ChangeIntelligenceTab sub-tab

**File:** `services/web-ui/components/ChangeHubTab.tsx`

Changes:
1. Add `import { ChangeIntelligenceTab } from './ChangeIntelligenceTab'`
2. Add appropriate icon import (e.g. `Brain` or `Sparkles` from lucide-react — check what's available; use `Zap` as fallback)
3. Append `{ id: 'change-intelligence', label: 'Change Intelligence', icon: <icon> }` to `subTabs`
4. Add render block: `{activeSubTab === 'change-intelligence' && <ChangeIntelligenceTab subscriptions={subscriptions} />}`

---

### Task 4 — DashboardPanel.tsx: Rename label + regroup rows

**File:** `services/web-ui/components/DashboardPanel.tsx`

Changes:
1. Rename `'Capacity & Quota'` → `'Capacity'` (line 71, label field only — `id: 'capacity'` stays unchanged)
2. Move `security` entry from Row 2 into Row 1 (after `network`):
   - Row 1: Dashboard, Alerts, Resources, Network, **Security**
   - Row 2: Cost, Capacity, Change, Databases, Operations
   - Row 3: Audit, Admin (unchanged)

Current Row 1 ends at Network; current Row 2 starts with Security. Move Security to end of Row 1.

---

## Verification

- [ ] `subTabs` in ResourcesHubTab has 9 entries (no Firewall, Hierarchy last)
- [ ] `subTabs` in NetworkHubTab has 6 entries (Firewall after Private Endpoints)
- [ ] `subTabs` in ChangeHubTab has 5 entries (Change Intelligence appended)
- [ ] DashboardPanel Row 1 has 5 tabs ending with Security
- [ ] DashboardPanel capacity label reads `'Capacity'` not `'Capacity & Quota'`
- [ ] No TypeScript errors from unused imports (Flame removed from Resources, no dangling refs)
