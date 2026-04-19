---
plan: "108-2"
title: "Frontend — Issues Drawer Redesign"
status: "complete"
commit: "ce371106b860b77078d9dfa6ce0e07f111baed40"
---

# Summary: Plan 108-2 — Frontend Issues Drawer Redesign

## What Was Done

All tasks completed and delivered in commit `ce37110` alongside the backend work.

### Task 2.1 — `NetworkIssue` TypeScript Interface ✅
- Full `NetworkIssue` interface defined in `NetworkTopologyTab.tsx` with all fields:
  `id`, `type`, `severity`, `title`, `explanation`, `impact`, `affected_resource_id`,
  `related_resource_ids`, `remediation_steps`, `portal_link`, `auto_fix_available`,
  plus backward-compat fields (`source_nsg_id`, `dest_nsg_id`, `port`, `description`)

### Task 2.2 — `SeverityBadge` Component ✅
- `SeverityBadge` renders color-coded severity chips using dark-mode-safe `color-mix(in srgb, ...)` CSS tokens
- Colors: critical=red, high=orange, medium=yellow, low=blue
- Used inline in issue card headers and drawer section headers

### Task 2.3 — Structured `IssueCard` Component ✅
- Header row: `SeverityBadge` + title + affected resource chip
- Collapsible explanation section (single-line truncated → expanded on click)
- Impact box: grey background, "Impact:" label + impact text
- Numbered remediation steps with CLI copy buttons (clipboard API)
- Azure Portal deep-link button (opens in new tab)
- "Fix Now" CTA for auto-fixable issues; "Request Approval" for HITL issues

### Task 2.4 — Severity-Grouped Issues Drawer ✅
- Issues grouped by severity: Critical → High → Medium → Low
- Each group has a collapsible section header with badge + count
- Total count and per-severity counts shown in drawer header
- Empty state: "No issues detected" message when no issues

### Task 2.5 — Summary Pill Redesign ✅
- Old: single red circle with total count
- New: severity breakdown pill — 🔴{critical} 🟠{high} 🟡{medium} 🔵{low}
- Clicking any part opens the issues drawer

### Task 2.6 — Filter Bar ✅
- 4 severity toggle buttons (active = solid, inactive = outline)
- Debounced text search (300ms) matching title, type, affected resource
- "Showing X of Y issues" count below filter bar
- Filter state preserved across drawer open/close

### Task 2.7 — `focusIssue()` Updated ✅
- Updated to use `affected_resource_id` as primary highlight target
- `related_resource_ids` used for secondary highlights (lighter highlight)
- Backward-compat: falls back to `source_nsg_id`/`dest_nsg_id` if unified fields absent

## Files Modified

- `services/web-ui/components/NetworkTopologyTab.tsx` — all frontend changes (+689 lines net)
