---
phase: "108-2"
title: "Frontend — Issues Drawer Redesign"
depends_on: ["108-1"]
estimated_effort: "M"
wave: 2
files_to_modify:
  - services/web-ui/components/NetworkTopologyTab.tsx
files_to_create: []
---

# Plan 108-2: Frontend — Issues Drawer Redesign

## Goal

Replace the flat red-card issues drawer with a severity-tiered, explanation-rich issues panel supporting all 17 issue types. Update the summary pill, `focusIssue()`, and issue cards to use the unified `NetworkIssue` schema from Plan 108-1. No backend changes — frontend only.

---

## Task 2.1 — Define `NetworkIssue` TypeScript Interface

<read_first>
- `services/web-ui/components/NetworkTopologyTab.tsx` lines 1-80 (existing types, TopologyData interface)
- `.planning/phases/108-network-topology-full-issue-detection/108-RESEARCH.md` § 4.1 (unified schema)
</read_first>

<action>
1. Define the `NetworkIssue` interface near the top of `NetworkTopologyTab.tsx` (or in a shared types file if one exists):
   ```typescript
   interface RemediationStep {
     step: number
     action: string
     cli?: string
   }

   interface NetworkIssue {
     id: string
     type: string
     severity: "critical" | "high" | "medium" | "low"
     title: string
     explanation: string
     impact: string
     affected_resource_id: string
     affected_resource_name: string
     related_resource_ids: string[]
     remediation_steps: RemediationStep[]
     portal_link: string
     auto_fix_available: boolean
     auto_fix_label: string | null
     // Legacy backward compat
     source_nsg_id?: string
     dest_nsg_id?: string
     port?: number
     description?: string
   }
   ```
2. Update `TopologyData.issues` from `Array<Record<string, unknown>>` to `NetworkIssue[]`.
3. Remove all `as any` / type casts on issue field access throughout the file.
</action>

<acceptance_criteria>
- `NetworkIssue` interface defined with all fields matching backend schema
- `TopologyData.issues` typed as `NetworkIssue[]`
- No `Record<string, unknown>` or `any` casts remaining for issue access
- TypeScript compilation passes with `--strict`
</acceptance_criteria>

---

## Task 2.2 — Severity Badge Component + Color Map

<read_first>
- `services/web-ui/components/NetworkTopologyTab.tsx` lines 1958-2025 (existing issues drawer)
- `services/web-ui/app/globals.css` (CSS custom properties / semantic tokens)
</read_first>

<action>
1. Define a `SEVERITY_CONFIG` constant:
   ```typescript
   const SEVERITY_CONFIG = {
     critical: { color: "var(--accent-red)", label: "Critical", icon: "🔴" },
     high:     { color: "var(--accent-orange)", label: "High", icon: "🟠" },
     medium:   { color: "var(--accent-yellow)", label: "Medium", icon: "🟡" },
     low:      { color: "var(--accent-blue)", label: "Low", icon: "🔵" },
   } as const
   ```
2. Create a `SeverityBadge` inline component that renders:
   - Background: `color-mix(in srgb, {color} 15%, transparent)` (matches existing dark-mode-safe badge pattern)
   - Text color: the accent color
   - Text: icon + label (e.g. "🔴 Critical")
3. Use CSS semantic tokens exclusively — no hardcoded Tailwind color classes.
</action>

<acceptance_criteria>
- `SeverityBadge` renders for all 4 severity levels
- Uses `color-mix(in srgb, var(--accent-*) 15%, transparent)` for background (dark-mode safe)
- No hardcoded Tailwind color classes (e.g. no `bg-red-100`, `text-red-700`)
</acceptance_criteria>

---

## Task 2.3 — Redesign Issue Cards in Drawer

<read_first>
- `services/web-ui/components/NetworkTopologyTab.tsx` lines 1958-2025 (existing issues drawer cards)
- `.planning/phases/108-network-topology-full-issue-detection/108-RESEARCH.md` § 4.2 (issue card sections)
</read_first>

<action>
Replace the existing flat red issue cards with structured cards containing these sections:

1. **Header row:** `SeverityBadge` + issue `title` + `affected_resource_name` (truncated to 40 chars)
2. **Explanation section:** `explanation` text, collapsible (default collapsed for medium/low, expanded for critical/high)
3. **Impact section:** `impact` text in a subtle warning-toned box
4. **Remediation steps:** Numbered list from `remediation_steps[]`. If a step has `cli`, render it in a `<code>` block with a copy button.
5. **Portal link:** "Open in Azure Portal" button — `<a href={portal_link} target="_blank" rel="noopener noreferrer">` styled as a secondary button with an external-link icon from lucide-react.
6. **Action row:**
   - If `auto_fix_available`: render a primary "Fix Now" button with `auto_fix_label` text (wired in Plan 108-3; for now just `disabled` with tooltip "Coming in Phase 108-3")
   - Else: render a secondary "Request Approval" button (also disabled for now)
7. **Focus button:** "Focus in Graph" button (existing behavior, updated in Task 2.4)

Group issues by severity in the drawer: Critical section → High section → Medium section → Low section, each with a header.
</action>

<acceptance_criteria>
- Issue cards show all 7 sections (header, explanation, impact, steps, portal link, action row, focus)
- Explanation collapsible — expanded by default for critical/high, collapsed for medium/low
- CLI commands in remediation steps rendered in `<code>` with copy-to-clipboard
- Portal link opens in new tab
- Fix Now / Request Approval buttons present but disabled (placeholder for 108-3)
- Issues grouped by severity with section headers
</acceptance_criteria>

---

## Task 2.4 — Update `focusIssue()` for Unified Schema

<read_first>
- `services/web-ui/components/NetworkTopologyTab.tsx` lines 1041-1080 (`focusIssue` function)
</read_first>

<action>
1. Update `focusIssue()` to accept a `NetworkIssue` parameter.
2. Primary highlight: find node matching `issue.affected_resource_id` (match against node `data.id` or node `id`).
3. Secondary highlights: find nodes matching each ID in `issue.related_resource_ids`.
4. Fallback for backward compat: if `issue.source_nsg_id` and `issue.dest_nsg_id` exist, use them (existing NSG asymmetry behavior).
5. Fit the graph viewport to show all highlighted nodes with padding.
6. Clear previous highlights before applying new ones.
7. Update the focused-issue banner (lines ~1909-1956) to show `issue.title` instead of hardcoded `Port X/TCP blocked`.
</action>

<acceptance_criteria>
- `focusIssue()` highlights `affected_resource_id` node as primary (red border)
- `related_resource_ids` nodes highlighted as secondary (orange border)
- NSG asymmetry issues still work via backward-compat fields
- Focused-issue banner shows dynamic `issue.title`
- Previous highlights cleared when new issue focused
</acceptance_criteria>

---

## Task 2.5 — Upgrade Issues Summary Pill

<read_first>
- `services/web-ui/components/NetworkTopologyTab.tsx` lines 1564-1583 (issues pill in summary bar)
</read_first>

<action>
1. Replace the flat `🚫 Issues: N — click to view` pill with a severity breakdown:
   ```
   🔴 3  🟠 4  🟡 2  🔵 1
   ```
2. Each count is a clickable span that opens the issues drawer AND scrolls to that severity section.
3. If a severity has 0 issues, omit it from the pill.
4. If total issues is 0, show `✅ No issues detected` in green.
5. Use CSS semantic tokens for colors (same `SEVERITY_CONFIG` from Task 2.2).
</action>

<acceptance_criteria>
- Pill shows severity breakdown with colored icons
- Clicking a severity count opens drawer and scrolls to that section
- Zero-count severities omitted
- Zero total issues shows green "No issues detected"
</acceptance_criteria>

---

## Task 2.6 — Filter and Search in Issues Drawer

<read_first>
- `services/web-ui/components/NetworkTopologyTab.tsx` lines 1958-2025 (issues drawer)
</read_first>

<action>
1. Add a filter bar at the top of the issues drawer with:
   - **Severity filter:** 4 toggle buttons (Critical, High, Medium, Low) — all enabled by default. Click to toggle.
   - **Search input:** Free-text search across `title`, `affected_resource_name`, `explanation`. Debounce 300ms.
2. Filter state stored in component state (not URL).
3. Show count of visible issues vs total: "Showing 5 of 12 issues".
4. When the pill severity count is clicked (from Task 2.5), pre-set the severity filter to only that severity.
</action>

<acceptance_criteria>
- Severity toggle buttons filter issues in real time
- Search filters across title, resource name, and explanation
- "Showing X of Y" count updates correctly
- Pill click pre-filters to clicked severity
- Debounce on search input (300ms)
</acceptance_criteria>
