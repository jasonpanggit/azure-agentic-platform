---
plan: 07-01
title: "Observability — OTel Auto-Instrumentation + Observability Tab"
phase: 7
status: complete
completed: 2026-03-27
---

# Plan 07-01 Summary

## Goal

Add OpenTelemetry auto-instrumentation to all services (Python FastAPI + TypeScript Express) exporting traces to Application Insights, and build the Observability tab in the Web UI showing agent latency, pipeline lag, approval queue depth, and active errors.

---

## Tasks Completed

### Task 7-01-01: Python OTel — api-gateway auto-instrumentation ✅
- Added `azure-monitor-opentelemetry>=1.0.0` to `services/api-gateway/requirements.txt`
- Added `import os` to `main.py`
- Added conditional OTel init block BEFORE `app = FastAPI(...)`:
  - Reads `APPLICATIONINSIGHTS_CONNECTION_STRING` from env
  - Calls `configure_azure_monitor(connection_string=...)` when set
  - Logs warning when not set (no crash)

### Task 7-01-02: TypeScript OTel — teams-bot auto-instrumentation ✅
- Added `"@azure/monitor-opentelemetry": "^1.0.0"` and `"@opentelemetry/auto-instrumentations-node": "^0.50.0"` to `services/teams-bot/package.json`
- Created `services/teams-bot/src/instrumentation.ts` with `useAzureMonitor(...)` conditional on env var
- Added `import "./instrumentation"` as first line of `services/teams-bot/src/index.ts`

### Task 7-01-03: Observability API route — Next.js server-side data fetcher ✅
- Added `"@azure/monitor-query": "^1.3.0"`, `"@azure/identity": "^4.0.0"`, `"@azure/cosmos": "^4.0.0"` to `services/web-ui/package.json`
- Created `services/web-ui/app/api/observability/route.ts` with:
  - `GET` handler with `timeRange` query param
  - Parallel execution of 4 queries via `Promise.all`
  - KQL query against `AppDependencies` for agent latency (P50/P95)
  - KQL query for pipeline lag
  - KQL query against `AppExceptions` for active errors
  - Cosmos DB query for approval queue pending count + oldest pending age
  - Returns `{ agentLatency, pipelineLag, approvalQueue, activeErrors, lastUpdated }`
  - Returns 503 when `LOG_ANALYTICS_WORKSPACE_ID` not configured

### Task 7-01-04: TimeRangeSelector component ✅
- Created `services/web-ui/components/TimeRangeSelector.tsx`
- Fluent UI `Dropdown` with 4 options: `1h`, `6h`, `24h`, `7d`
- Props: `value: string`, `onChange: (value: string) => void`
- `aria-label="Time range"`, width 160px

### Task 7-01-05: MetricCard component ✅
- Created `services/web-ui/components/MetricCard.tsx`
- Exports `MetricCard` (title, health, children) and `HealthStatus` type
- Border-left 3px solid using semantic health color tokens:
  - `colorPaletteGreenForeground1` — healthy
  - `colorPaletteYellowForeground1` — warning
  - `colorPaletteRedForeground1` — critical
- `role="region"` and `aria-label={title}` on Card
- `Badge` with `aria-label="Health status: {label}"`

### Task 7-01-06: Four metric card components ✅
- **AgentLatencyCard**: DataGrid with Agent/P50/P95 columns; P95 color-coded by threshold (>3000ms=warning, >5000ms=critical); worst-case card health
- **PipelineLagCard**: 3 rows (Alert to Incident, Incident to Triage, Total End-to-End); `formatDuration` shows ms/<1000 or seconds; health based on totalE2EMs (>60s=warning, >120s=critical)
- **ApprovalQueueCard**: 2 rows (Pending, Oldest pending); health based on pending count (>10=warning, >25=critical)
- **ActiveErrorsCard**: Fluent `Accordion` with expandable error items; monospace detail on expand; health=critical if errors.length > 0

### Task 7-01-07: ObservabilityTab container component ✅
- Created `services/web-ui/components/ObservabilityTab.tsx`
- Polls `/api/observability?timeRange={value}` every 30 seconds via `setInterval`
- Loading state: 4 `Skeleton` cards (3 `SkeletonItem` each)
- Error state: `MessageBar` with `intent="error"`
- Empty state: "No observability data" with descriptive body text
- Data state: 2×2 CSS grid with AgentLatency, PipelineLag, ActiveErrors, ApprovalQueue
- `aria-live="polite"` on last-updated timestamp
- `@container (max-width: 600px)` collapses to single column

### Task 7-01-08: Wire ObservabilityTab into DashboardPanel ✅
- Added `import { ObservabilityTab } from './ObservabilityTab'`
- Extended `DashboardTab` type to include `'observability'`
- Added `<Tab value="observability">Observability</Tab>` as 5th tab
- Added `{activeTab === 'observability' && <ObservabilityTab subscriptions={subscriptions} />}`

---

## Files Modified

| File | Change |
|------|--------|
| `services/api-gateway/requirements.txt` | Added `azure-monitor-opentelemetry>=1.0.0` |
| `services/api-gateway/main.py` | Added `import os` + conditional OTel init before `app = FastAPI(...)` |
| `services/teams-bot/package.json` | Added `@azure/monitor-opentelemetry` + `@opentelemetry/auto-instrumentations-node` |
| `services/teams-bot/src/index.ts` | Added `import "./instrumentation"` as first line |
| `services/web-ui/package.json` | Added `@azure/monitor-query`, `@azure/identity`, `@azure/cosmos` |
| `services/web-ui/components/DashboardPanel.tsx` | Added ObservabilityTab import, type, tab, content |

## Files Created

| File | Purpose |
|------|---------|
| `services/teams-bot/src/instrumentation.ts` | OTel auto-instrumentation for teams-bot |
| `services/web-ui/app/api/observability/route.ts` | Next.js API route — KQL + Cosmos queries |
| `services/web-ui/components/TimeRangeSelector.tsx` | Fluent Dropdown for time range |
| `services/web-ui/components/MetricCard.tsx` | Reusable health-aware card wrapper |
| `services/web-ui/components/AgentLatencyCard.tsx` | Agent P50/P95 DataGrid card |
| `services/web-ui/components/PipelineLagCard.tsx` | Pipeline stage lag card |
| `services/web-ui/components/ApprovalQueueCard.tsx` | Approval queue depth card |
| `services/web-ui/components/ActiveErrorsCard.tsx` | Active errors accordion card |
| `services/web-ui/components/ObservabilityTab.tsx` | Container with polling + all 4 cards |

---

## Acceptance Criteria Results

### D-05: OTel Auto-Instrumentation

| Criterion | Result |
|-----------|--------|
| `requirements.txt` contains `azure-monitor-opentelemetry>=1.0.0` | ✅ |
| `main.py` contains `from azure.monitor.opentelemetry import configure_azure_monitor` | ✅ |
| `main.py` contains `configure_azure_monitor(connection_string=` before `app = FastAPI(` | ✅ |
| OTel init is conditional on env var (no crash when absent) | ✅ |
| `teams-bot/package.json` contains `"@azure/monitor-opentelemetry"` | ✅ |
| `teams-bot/package.json` contains `"@opentelemetry/auto-instrumentations-node"` | ✅ |
| `instrumentation.ts` exists with `useAzureMonitor(` | ✅ |
| `index.ts` first import is `import "./instrumentation"` | ✅ |

### D-06: Observability Tab

| Criterion | Result |
|-----------|--------|
| `web-ui/package.json` contains `"@azure/monitor-query"` | ✅ |
| `web-ui/package.json` contains `"@azure/identity"` | ✅ |
| `web-ui/package.json` contains `"@azure/cosmos"` | ✅ |
| `route.ts` exports `async function GET(` | ✅ |
| Route queries `AppDependencies` KQL table | ✅ |
| Route queries Cosmos DB `approvals` container | ✅ |
| Route returns `agentLatency`, `pipelineLag`, `approvalQueue`, `activeErrors`, `lastUpdated` | ✅ |
| `TimeRangeSelector.tsx` with 4 options + `aria-label="Time range"` | ✅ |
| `MetricCard.tsx` with `role="region"`, health badge, border colors | ✅ |
| `AgentLatencyCard.tsx` with DataGrid Agent/P50/P95 | ✅ |
| `PipelineLagCard.tsx` with 3 rows | ✅ |
| `ApprovalQueueCard.tsx` with Pending + Oldest | ✅ |
| `ActiveErrorsCard.tsx` with Accordion | ✅ |
| `ObservabilityTab.tsx` polls every 30s, skeleton/error/empty/data states | ✅ |
| `DashboardPanel.tsx` has 5th tab `observability` | ✅ |
| All health thresholds correct (P95: 3000/5000ms; lag: 60/120s; queue: 10/25; errors >0) | ✅ |
| All Fluent v9 components — no third-party chart library | ✅ |

---

## must_haves Checklist

- [x] OTel auto-instrumentation configured for api-gateway (Python) and teams-bot (TypeScript)
- [x] Observability tab renders in DashboardPanel as 5th tab
- [x] API route queries Application Insights for agent latency and errors
- [x] API route queries Cosmos DB for approval queue depth
- [x] Health thresholds: P95 latency 3000/5000ms, pipeline lag 60/120s, queue depth 10/25, errors >0
- [x] All Fluent v9 components — no third-party chart library

---

## Commit Hash

See git log for commit hash after this plan was committed.
