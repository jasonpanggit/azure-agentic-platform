# Plan 05-05 Summary — Alert Feed, Audit Log, DashboardPanel Real Components

**Completed:** 2026-03-27
**Branch:** phase-5-wave-0-test-infrastructure
**Commits:** 6 (120e470, 38b5d4b, ab27368, 22ce144, c0a343c, 19694dc)

---

## What Was Built

### Backend (API Gateway)

**`services/api-gateway/models.py`**
- Added `IncidentSummary` model (UI-006): `incident_id`, `severity`, `domain`, `status`, `created_at`, `title`, `resource_id`, `subscription_id`
- Added `AuditEntry` model (AUDIT-004): `timestamp`, `agent`, `tool`, `outcome`, `duration_ms`, `properties`

**`services/api-gateway/incidents_list.py`** (new)
- Queries Cosmos DB `incidents` container with `ORDER BY c.created_at DESC`
- Query parameters: `since`, `severity`, `domain`, `status`, `limit`
- Client-side subscription filter (cross-partition can't filter on non-PK subscription_id)
- `COSMOS_ENDPOINT` env var gated; raises `ValueError` if absent

**`services/api-gateway/audit_trail.py`** (new, AUDIT-002)
- Dual write: Cosmos DB (blocking, caller's responsibility) + OneLake (non-blocking fire-and-forget)
- OneLake path: `approvals/YYYY/MM/DD/<id>.json` via `DataLakeServiceClient`
- `overwrite=True` prevents duplicate failures on retry
- `ONELAKE_ENDPOINT` absent → silent skip with debug log

**`services/api-gateway/audit.py`** (new, AUDIT-004)
- `LogsQueryClient` queries `AppDependencies` table in Log Analytics
- KQL filters: incident_id (Properties has), agent (AppRoleName), action (Name), resource (Properties has), from_time, to_time
- `LOG_ANALYTICS_WORKSPACE_ID` absent → returns empty list with warning
- Query failures are caught and return empty list (never raise to caller)

**`services/api-gateway/main.py`** (modified)
- Added `GET /api/v1/incidents` with `list[IncidentSummary]` response
  - Accepts: `since`, `subscription` (comma-sep), `severity`, `domain`, `status`, `limit`
  - Strips Cosmos `_rid`/`_etag` internal fields before model construction
- Added `GET /api/v1/audit` with `list[AuditEntry]` response
  - Accepts: `incident_id`, `agent`, `action`, `resource`, `from_time`, `to_time`, `limit`

### Frontend (Web UI)

**`services/web-ui/components/AlertFeed.tsx`** (new, UI-006)
- Fluent UI `DataGrid` with sortable columns: Severity, Domain, Resource, Status, Time
- Polls `/api/proxy/incidents` every `POLL_INTERVAL_MS = 5000` ms via `setInterval`
- Severity badge colors: Sev0/Sev1 → `danger`, Sev2/Sev3 → `warning`
- Skeleton loading state (5 rows) and empty state with descriptive message
- `useCallback` + `useEffect` for stable poll interval with filter/subscription deps

**`services/web-ui/components/AlertFilters.tsx`** (new, UI-007)
- Fluent UI `Toolbar` with three `Dropdown` controls: Severity, Domain, Status
- Severity options: All, Sev0, Sev1, Sev2, Sev3
- Domain options: All, Compute, Network, Storage, Security, Arc, SRE
- Status options: All, New, Acknowledged, Closed
- Controlled component: receives `filters` state + `onChange` callback

**`services/web-ui/components/AuditLogViewer.tsx`** (new, AUDIT-004)
- Fetches `/api/proxy/audit` with `incidentId`, `agentFilter`, `actionFilter`
- `DataGrid` columns: Timestamp, Agent, Tool, Outcome, Duration
- Outcome badge: `success`/`200` → green, otherwise danger
- Agent `Dropdown` + free-text action `Input` in `Toolbar`
- Empty state: "No actions recorded" message
- Re-fetches when any filter changes via `useCallback` dep array

**`services/web-ui/components/DashboardPanel.tsx`** (replaced)
- Owns tab state internally: `alerts | audit | topology | resources`
- `alerts` tab: `AlertFilters` + `AlertFeed` with `FilterState` managed here
- `audit` tab: `AuditLogViewer` scoped to `selectedIncidentId` prop
- `topology` / `resources`: Phase 6 placeholder empty states
- Props: `subscriptions: string[]`, `selectedIncidentId?: string`

**`services/web-ui/components/AppLayout.tsx`** (modified)
- Removed: `activeTab` state, `DashboardTab` type, `TabList`, `Tab`, icon imports (`AlertRegular`, `OrganizationRegular`, `ServerRegular`, `ClipboardTaskRegular`)
- Removed: outer wrapper `<div>` around TabList+DashboardPanel in right Panel
- Added: `selectedIncidentId` state (`useState<string | undefined>()`)
- Right Panel now renders `<DashboardPanel subscriptions=... selectedIncidentId=... />` directly

---

## Architecture Decisions

| Decision | Rationale |
|---|---|
| Client-side subscription filter in `list_incidents` | Cosmos cross-partition queries can't efficiently filter on `subscription_id` when it's not the partition key; client filter is correct for O(n) result sets |
| `ONELAKE_ENDPOINT` absent → silent skip | OneLake is non-critical path; dev environments don't need it configured |
| `LOG_ANALYTICS_WORKSPACE_ID` absent → empty list | Graceful degradation for dev; audit tab shows empty state instead of error |
| Tab state moved into `DashboardPanel` | `AppLayout` was acting as a state broker for DashboardPanel internals; encapsulation is cleaner — AppLayout only needs `selectedIncidentId` |
| `POLL_INTERVAL_MS = 5000` constant | Named constant prevents magic number; easy to tune per environment |

---

## Requirements Satisfied

| Req ID | Description | Status |
|---|---|---|
| UI-006 | Alert feed with severity/domain/status filters | ✅ `AlertFeed` + `AlertFilters` |
| UI-007 | Alert feed polling | ✅ 5-second `setInterval` |
| AUDIT-002 | Approval audit dual-write to Cosmos + OneLake | ✅ `audit_trail.py` |
| AUDIT-004 | Agent action history query via App Insights KQL | ✅ `audit.py` + `AuditLogViewer` |
