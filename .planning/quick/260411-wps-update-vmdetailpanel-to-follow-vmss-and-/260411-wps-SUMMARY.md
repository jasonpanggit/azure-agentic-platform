# Summary: Update VMDetailPanel to tab-based UI (VMSS/AKS parity)

**Task ID:** 260411-wps  
**Completed:** 2026-04-11  
**Commit:** d493ca3

---

## What Was Done

Rewrote `services/web-ui/components/VMDetailPanel.tsx` from a single scrollable layout into a 5-tab panel matching the design system of `VMSSDetailPanel` and `AKSDetailPanel`.

### Changes

**File modified:** `services/web-ui/components/VMDetailPanel.tsx`

**Tab structure added:**
| Tab | Content |
|-----|---------|
| **Overview** | 2×2 stat cards (Power State, Health, AMA Status, Active Alerts) + VM metadata `<dl>` (RG / Location / Size / OS / Subscription) + Active Incidents list |
| **Metrics** | Existing sparkline charts with time-range pills + metric selector dropdown + AMA diag widget; lazy-fetched on tab activation |
| **Evidence** | Diagnostic evidence section (metric anomalies, recent changes, log errors); shows empty state when `incidentId` is null |
| **Patches** | Informational card pointing to Patch Management tab + CTA button that switches to AI Chat tab |
| **AI Chat** | Full-height flex column with bouncing-dot loader, matching VMSS/AKS exactly; auto-fires `"Summarize this VM's health and suggest investigation steps."` on first tab visit |

**Key implementation details:**
- `type DetailTab = 'overview' | 'metrics' | 'evidence' | 'patches' | 'chat'` added
- `PANEL_MIN_WIDTH`, `PANEL_MAX_WIDTH`, `PANEL_DEFAULT_WIDTH` promoted to module-level constants
- `chatOpen`/`openChat()` toggle removed — chat is now a first-class tab
- `chatAutoFired` ref guards the auto-fire to exactly one trigger per resource
- Metrics lazy-fetch via `activeTab === 'metrics'` effect; refetches on `timeRange`/`selectedMetrics` changes
- All existing functionality preserved: drag-resize, `localStorage` width persistence, evidence polling, `incidentId` prop, `sendChatMessage`/`startChatPolling`, `approval_id` card rendering
- Tab bar uses identical `borderBottom: 2px solid var(--accent-blue)` active indicator pattern as VMSS/AKS
- CSS semantic tokens only (`var(--accent-*)`, `var(--bg-*)`, `var(--text-*)`, `var(--border)`) — no hardcoded Tailwind color classes

## Verification

- `npm run build` exits 0, zero TypeScript errors ✓
- All 5 tabs render correctly ✓
- Chat auto-fires on first AI Chat tab visit ✓
- Metrics lazy-fetch on Metrics tab activation ✓
- Evidence shows empty state when `incidentId` is null ✓
- Panel width persists in `localStorage` (`vmDetailPanelWidth` key unchanged) ✓
- `incidentId` prop still accepted and wired into Evidence + chat POST body ✓
- `VMDetailPanelProps` interface unchanged — no callers required modification ✓
