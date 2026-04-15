---
wave: 4
status: complete
---

## Summary

Created 3 Next.js proxy routes and `SLATab.tsx`. Updated `DashboardPanel.tsx`.

### Proxy routes
- `app/api/proxy/sla/compliance/route.ts` — GET proxy → `/api/v1/sla/compliance`, 15s timeout, empty-array fallback
- `app/api/proxy/sla/definitions/route.ts` — GET proxy → `/api/v1/admin/sla-definitions`, passthrough `include_inactive` param
- `app/api/proxy/sla/report/[slaId]/route.ts` — POST proxy → `/api/v1/sla/report/{slaId}`, **60s timeout** (PDF generation)

### SLATab.tsx
- `'use client'` directive
- **SVG radial gauge** — `stroke-dasharray` / `stroke-dashoffset` trick; color changes green/red/muted based on attainment vs target
- **ComplianceBadge** — `color-mix(in srgb, var(--accent-*) 15%, transparent)` for Compliant/Breach/No data
- **Resource breakdown table** — shadcn Table, truncates resource IDs to last path segment
- **12-month stub sparkline** — recharts `BarChart` with synthetic data; note "Historical data available after 12 months"
- **Report trigger button** — per-SLA card; shows "Generating…" while in-flight; displays recipient count on success
- **EmptyState** — `BarChart2` icon + message when no SLA definitions configured
- **Zero hardcoded Tailwind color classes** — all via `var(--accent-*)` CSS tokens

### DashboardPanel.tsx
5 targeted edits: `BarChart2` lucide import, `import { SLATab }`, `'sla'` in TabId union, SLA entry in TABS array, `tabpanel-sla` div between runbooks and settings.

### TypeScript
`npx tsc --noEmit` — no new errors introduced (pre-existing OpsTab.test.tsx error unrelated to Phase 55).
