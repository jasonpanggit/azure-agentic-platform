# Plan 18-01 Summary: Recharts Charts in ObservabilityTab

**Date:** 2026-04-02
**Branch:** gsd/phase-18-observability
**Status:** COMPLETE

## What Was Built

Replaced the text-only `MetricCard` displays in `ObservabilityTab` with recharts-backed charts:

1. **recharts installed** — `^3.8.1` added to `services/web-ui/package.json`
2. **API: incident_throughput** — New `queryIncidentThroughput()` KQL function added to `/api/observability`; queries `AppRequests` for `POST /api/v1/incidents` by hour; wired into the parallel `Promise.all`; `IncidentThroughputPoint[]` returned in response
3. **AgentLatencyCard** — Replaced text table with `BarChart` (P50 blue, P95 yellow); empty-state guard added; `Tooltip.formatter` uses `unknown` cast pattern for recharts type compatibility
4. **PipelineLagCard** — Replaced three-row text layout with prominent `text-3xl` total + single breakdown row; cleaner visual hierarchy
5. **IncidentThroughputCard** — New component; shows total count prominently + hourly `BarChart` (80px height); empty-state shows "No incidents in period"
6. **ObservabilityTab** — Added `incidentThroughput` field to `ObservabilityData` interface; imported `IncidentThroughputCard`; updated grid to 2×2 (`AgentLatency | PipelineLag` / `IncidentThroughput | ApprovalQueue`) + full-width `ActiveErrorsCard` below

## Files Changed

| File | Change |
|------|--------|
| `services/web-ui/package.json` | Added `recharts: ^3.8.1` |
| `services/web-ui/package-lock.json` | Updated lockfile |
| `services/web-ui/app/api/observability/route.ts` | Added `IncidentThroughputPoint` interface, updated `ObservabilityResponse`, added `queryIncidentThroughput()`, wired into `Promise.all` |
| `services/web-ui/components/AgentLatencyCard.tsx` | Replaced text table with recharts `BarChart` |
| `services/web-ui/components/PipelineLagCard.tsx` | Improved to prominent metric display |
| `services/web-ui/components/IncidentThroughputCard.tsx` | **NEW** — hourly incident bar chart |
| `services/web-ui/components/ObservabilityTab.tsx` | Added `incidentThroughput` field, imported + rendered `IncidentThroughputCard`, updated grid layout |

## Build Result

```
✓ Compiled successfully in 2.6s
✓ Generating static pages (7/7)
```

Zero TypeScript errors. Zero regressions.

## TypeScript Constraint Resolved

recharts' `Tooltip.formatter` callback uses `ValueType | undefined` not `number`. Fixed by using `unknown` parameters with explicit `Number()` / `String()` casts — consistent with the existing `(row: unknown[])` pattern in the KQL row mappers.

## Commits

1. `23e678e` — `feat(frontend): replace ObservabilityTab MetricCard text with recharts charts`
2. `0f67b01` — `chore(deps): add recharts to web-ui package.json`

## Success Criteria

- [x] `recharts` appears in `package.json`
- [x] `GET /api/observability` returns `incidentThroughput` array
- [x] AgentLatencyCard renders BarChart (not text table)
- [x] IncidentThroughputCard exists and renders BarChart
- [x] ObservabilityTab renders 5 cards (AgentLatency, PipelineLag, Throughput, ApprovalQueue, ActiveErrors)
- [x] `npm run build` passes with zero TypeScript errors
- [x] No regressions (existing card health logic preserved)
