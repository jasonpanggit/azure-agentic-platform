---
phase: 18
name: observability
status: active
plans:
  - id: 18-01
    name: Recharts Charts in ObservabilityTab
    wave: 1
    status: pending
waves:
  1:
    - 18-01
---

# Phase 18: Observability — Real Charts

## Goal

Replace the text-only MetricCard components in ObservabilityTab with recharts-backed charts.
Add incident throughput data. The tab already fetches real Application Insights data — this
phase replaces the plain number/text display with visualizations that show trends over time.

## Roadmap Reference

Corresponds to Phase 4 (Observability) in `docs/roadmap/PLATFORM-ROADMAP.md`.

## What This Phase Delivers

1. **recharts installed** — Added to `services/web-ui/package.json`
2. **Incident throughput API** — Add `incident_throughput` field to observability endpoint
3. **Agent latency chart** — Line chart (P50/P95 per agent) replacing AgentLatencyCard table
4. **Pipeline lag chart** — Single metric with sparkline history replacing PipelineLagCard
5. **Incident throughput chart** — Bar chart (hourly) replacing placeholder
6. **Active errors** — Kept as table (errors are best read linearly, not charted)
7. **Approval queue** — Kept as prominent number (no history needed)

## Wave Execution

- **Wave 1**: Single plan — all observability chart work

## Success Criteria

- [ ] `npm run build` passes with zero TypeScript errors
- [ ] ObservabilityTab renders recharts charts when data is available
- [ ] Graceful empty state when no Application Insights data
- [ ] No regressions in existing tests
