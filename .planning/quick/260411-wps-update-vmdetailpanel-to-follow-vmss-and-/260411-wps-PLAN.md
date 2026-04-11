# Plan: Update VMDetailPanel to tab-based UI (VMSS/AKS parity)

**Task ID:** 260411-wps  
**Mode:** quick  
**Created:** 2026-04-11

---

## Investigation Summary

### VMSS tabs (5 tabs)
`overview` | `instances` | `metrics` | `scaling` | `chat`

### AKS tabs (5 tabs)
`overview` | `nodepools` | `workloads` | `metrics` | `chat`

### Both panels share the same design system
- Custom `<button>` tab bar (no shadcn Tabs) with `borderBottom: 2px solid var(--accent-blue)` active indicator
- `PANEL_MIN_WIDTH=380`, `PANEL_MAX_WIDTH=1200`, `PANEL_DEFAULT_WIDTH` 520/560 px
- Drag-resize handle on the left edge, width persisted to `localStorage`
- Chat tab: auto-fires opening message on first visit, polls `/api/proxy/chat/result`
- Metrics tab: lazy-fetched on tab activation, time-range selector

### Current VMDetailPanel structure (no tabs)
A single scrollable `<div>` with sections stacked vertically:
1. VM info header (name, health icon, OS/size/location 2×2 grid)
2. Diagnostic Evidence (incident-scoped; only if `incidentId` prop)
3. Metrics (sparklines, time-range pill buttons, metric selector dropdown, AMA diag widget)
4. Active Incidents list
5. AI Investigation (collapsed button → inline chat toggle)

### Available VM proxy endpoints
- `GET  /api/proxy/vms/[vmId]`               → VMDetail (health, OS, incidents, tags)
- `GET  /api/proxy/vms/[vmId]/metrics`        → MetricSeries[]
- `GET  /api/proxy/vms/[vmId]/diagnostic-settings` → AMA/DCR status
- `POST /api/proxy/vms/[vmId]/chat`           → start AI chat run
- `GET  /api/proxy/chat/result`               → poll run result
- `GET  /api/proxy/incidents/[id]/evidence`   → Evidence (metric anomalies, recent changes, log errors)

### Decided VM tab structure (5 tabs)
| Tab | Content |
|-----|---------|
| **Overview** | Summary stat cards (power state, health, AMA status, active alerts) + VM metadata grid (RG, location, size, OS) + Active Incidents list + diagnostic settings status widget |
| **Metrics** | Existing sparkline charts with time-range pill buttons + metric selector dropdown; lazy-fetched on tab activation |
| **Evidence** | Diagnostic Evidence section (currently only shown when `incidentId` is set); shows metric anomalies, recent changes, log errors; shows "No incident selected" empty state when opened without an incidentId |
| **Patches** | _Note: no live patch data per-VM at this API layer today_ → placeholder card pointing operator to the Patch Management tab, with a CTA to open AI Chat to query patches for this VM |
| **AI Chat** | Full-height chat matching VMSS/AKS pattern: auto-fires `"Summarize this VM's health and suggest investigation steps."` on first open, persistent thread, user/assistant bubbles, `Thinking…` dots |

> **Why these tabs?**
> - **Overview** — keeps the "at a glance" info operators first look at
> - **Metrics** — VM metrics are first-class, not buried; matches VMSS/AKS
> - **Evidence** — the incident diagnostic data is high-value but noisy; giving it its own tab declutters Overview
> - **Patches** — VM patch state is an important operational concern surfaced by Phase 32; even as a placeholder it signals the intent and provides the AI Chat CTA to query the patch agent
> - **AI Chat** — consistent last-tab position with VMSS/AKS; promoted from a collapsible toggle to a full tab

---

## Tasks

- [ ] **Task 1 — Restructure VMDetailPanel into tab-based layout**

  Rewrite `services/web-ui/components/VMDetailPanel.tsx` to match the VMSS/AKS pattern:

  1. Add `type DetailTab = 'overview' | 'metrics' | 'evidence' | 'patches' | 'chat'`
  2. Move the custom tab bar (button-per-tab, `borderBottom` active indicator) into the header area — same markup pattern as `VMSSDetailPanel`
  3. Add `activeTab` state, default `'overview'`; reset to `'overview'` on `resourceId` change
  4. **Overview tab** — stat card grid (2×2: Power State, Health, AMA Status, Active Alerts) + metadata `<dl>` (RG / Location / Size / OS / Subscription) + Active Incidents list; re-use the existing `PowerBadge`, `HealthIcon`/`HealthColor` helpers
  5. **Metrics tab** — move existing sparkline section verbatim (time-range pills, metric selector dropdown, Sparkline SVG, AMA diag widget); lazy-fetch metrics on tab activation using the `activeTab === 'metrics'` pattern from VMSS
  6. **Evidence tab** — move the existing diagnostic evidence section; show a gentle empty state ("Open a specific alert to view diagnostic evidence") when `incidentId` is null; polling logic stays the same
  7. **Patches tab** — informational card: "Patch data is available in the Patch Management tab. Use AI Chat to query patch status for this VM." with a short `onClick={() => setActiveTab('chat')}` CTA button
  8. **AI Chat tab** — full-height flex column matching VMSS/AKS exactly: message bubbles, bouncing-dot loader, input+Send; auto-fires opening message `"Summarize this VM's health and suggest investigation steps."` on first tab visit (guard with `chatAutoFired` ref); reuse all existing `sendChatMessage` + `startChatPolling` logic; keep `approval_id` card rendering
  9. Remove `chatOpen` / `openChat()` toggle — chat is now always in its tab
  10. Move `PANEL_MIN_WIDTH`, `PANEL_MAX_WIDTH`, `PANEL_DEFAULT_WIDTH` to module-level constants (was inline inside component)
  11. No API or backend changes required

  **Acceptance criteria:**
  - `tsc --noEmit` exits 0
  - `npm run build` exits 0
  - All 5 tabs render without error when opened from AlertFeed (with incidentId) and from VMTab row click (without incidentId)
  - Chat auto-fires summary on first visit to AI Chat tab
  - Metrics lazy-fetch when Metrics tab is activated
  - Evidence tab shows empty state when `incidentId` is null
  - Panel width persists across opens (localStorage key `vmDetailPanelWidth` unchanged)
  - `incidentId` prop is still accepted (used by Evidence tab + chat context injection)

---

## Files Changed

- `services/web-ui/components/VMDetailPanel.tsx` — full rewrite to tab pattern

---

## Notes

- The `incidentId` prop must remain because chat still injects it as context (`incident_id` in the POST body) and Evidence polls `/api/proxy/incidents/[id]/evidence`
- The `VMDetailPanelProps` interface stays the same — no callers need to change
- Keep all existing helper components (`HealthIcon`, `HealthColor`, `PowerBadge`, `SeverityBadge`, `Sparkline`, `METRIC_CATALOG`, `DEFAULT_METRICS`) in the same file
- Drag-resize should use the same `onDragHandleMouseDown` pattern as current (window-level listeners); no change needed there
