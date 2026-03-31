# Phase 13 Research: Patch Management Tab

**Date:** 2026-03-31
**Phase:** 13 — Add a new Patch Management tab and show all the patch related information
**Depends on:** Phase 12 (EOL Domain Agent), Phase 11 (Patch Domain Agent), Phase 9 (Web UI Revamp)

---

## 1. What This Phase Builds

A read-only **Patch Management tab** in the existing `DashboardPanel` that shows patch compliance and installation history data for Azure VMs and Arc-enabled servers. The implementation spans three layers:

| Layer | What's New |
|-------|-----------|
| **API Gateway** (Python/FastAPI) | 2 new GET endpoints: `/api/v1/patch/assessment` and `/api/v1/patch/installations` — both query Azure Resource Graph using the exact KQL from `agents/patch/tools.py` |
| **Next.js Proxy** | 1-2 new proxy route files under `app/api/proxy/patch/` — follows the `incidents/route.ts` pattern |
| **Web UI** (React/Tailwind) | 1 new `PatchTab.tsx` component + 4 touch-points in `DashboardPanel.tsx` (TabId type, TABS array, import, tabpanel div) |

**Out of scope:** Patch agent changes, remediation from UI, chat-initiated patch workflows, KB-to-CVE drill-down, export/download, historical trend charts.

---

## 2. Existing Patterns to Follow (Verified by Reading Source)

### 2.1 DashboardPanel Tab Registration

**File:** `services/web-ui/components/DashboardPanel.tsx` (133 lines)

Current state:
- `TabId` union: `'alerts' | 'audit' | 'topology' | 'resources' | 'observability'`
- `TABS` array: 5 entries with `{ id, label, Icon }` objects using lucide-react icons
- Tab rendering: `button` elements with `role="tab"`, `aria-selected`, keyboard nav via `handleTabKeyDown`
- Panel rendering: `div` elements with `role="tabpanel"`, `aria-labelledby`, `hidden` prop — each wrapping its component in `rounded-lg overflow-hidden` with `var(--bg-surface)` background and `1px solid var(--border)` border

**Changes needed (4 locations):**
1. Add `'patch'` to `TabId` union
2. Add `{ id: 'patch', label: 'Patch', Icon: ShieldCheck }` to `TABS` array (position 6)
3. Import `PatchTab` and `ShieldCheck`
4. Add `tabpanel-patch` div matching the existing pattern

### 2.2 Data-Fetching Pattern (ResourcesTab)

**File:** `services/web-ui/components/ResourcesTab.tsx` (209 lines)

Established pattern for a data-heavy tab:
- **Props:** `subscriptions: string[]` (single prop)
- **State:** `allResources`, `loading`, `error`, `search`, `typeFilter` — all `useState`
- **Fetching:** `useCallback(loadResources, [subscriptions])` + `useEffect(() => { loadResources() }, [loadResources])`
- **Client-side filtering:** Separate from fetch — filter on loaded data using `Array.filter()`
- **Loading state:** 6 `Skeleton` rows (h-10 w-full)
- **Error state:** `<p className="text-sm text-destructive">{error}</p>`
- **Empty state:** Centered column with lucide icon (h-8 w-8), semibold heading, muted description, `py-16`
- **Table:** `rounded-md border overflow-hidden` wrapper, `Table className="w-full text-sm"`, `TableRow className="border-b hover:bg-muted/30 transition-colors"`
- **Filters:** `Search` icon positioned absolutely in `Input`, `Select` with `w-[160px]`, result count as `text-sm text-muted-foreground`

### 2.3 MetricCard Component

**File:** `services/web-ui/components/MetricCard.tsx` (63 lines)

- **Props:** `title: string`, `health: HealthStatus`, `children: ReactNode`
- **HealthStatus:** `'healthy' | 'warning' | 'critical'`
- **Visual:** `Card` with `border-left: 3px solid {color}`, `Badge` with variant mapping (destructive/outline/default), `font-mono text-2xl font-semibold` value area
- **Color map:** `{ healthy: 'var(--accent-green)', warning: 'var(--accent-yellow)', critical: 'var(--accent-red)' }`
- Reuse for all 5 summary cards with computed health values

### 2.4 ObservabilityTab Patterns

**File:** `services/web-ui/components/ObservabilityTab.tsx` (122 lines)

- **Layout:** `flex flex-col gap-6 h-full` (gap-6 for section spacing)
- **Refresh pattern:** Manual refresh via button (not in this tab, but the pattern is: Button variant="outline" size="sm" + RefreshCw icon)
- **Error state:** `Alert variant="destructive"` with `AlertDescription`
- **Grid for cards:** `grid grid-cols-2 gap-4` (Phase 13 will use `grid-cols-5 gap-4` with responsive fallback)
- **Polling:** POLL_INTERVAL_MS = 30000 (NOT used in Patch tab per D-11 — patch data changes on minute/hour timescales)

### 2.5 Next.js Proxy Route Pattern

**File:** `services/web-ui/app/api/proxy/incidents/route.ts` (47 lines)

Established pattern:
```typescript
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest): Promise<NextResponse> {
  const apiGatewayUrl = getApiGatewayUrl()
  const { searchParams } = new URL(request.url)
  const query = searchParams.toString()
  const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false)
  const res = await fetch(`${apiGatewayUrl}/api/v1/...${query ? `?${query}` : ''}`, {
    headers: upstreamHeaders,
    signal: AbortSignal.timeout(15000),
  })
  // ... error handling, JSON passthrough
}
```

**Helpers:** `getApiGatewayUrl()` (env-based, dev fallback to localhost:8000) and `buildUpstreamHeaders(auth, includeContentType)` from `@/lib/api-gateway`.

### 2.6 API Gateway Module Pattern

**File:** `services/api-gateway/incidents_list.py` (89 lines) — extracted query module

Pattern for a new module:
- Module-level docstring
- `from __future__ import annotations`
- Logger: `logger = logging.getLogger(__name__)`
- Helper function for container/client access
- Async query function with typed parameters
- Return raw `list[dict]` (route handler in `main.py` converts to Pydantic models)

**Registration in main.py:** Routes are defined directly in `main.py` using `@app.get(...)` decorators, with business logic imported from modules. Some routes use `Depends(verify_token)` for auth and `Depends(get_credential)` for Azure credentials.

### 2.7 API Gateway Test Pattern

**File:** `services/api-gateway/tests/conftest.py` (197 lines)

- `os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")` before import
- `client` fixture with `TestClient(app)` and mocked `app.state`
- Individual test files mock specific dependencies with `@patch` / `MagicMock`

---

## 3. Source KQL Queries (From Patch Agent)

### 3.1 Patch Assessment Query

**Source:** `agents/patch/tools.py` lines 141-166

```kql
patchassessmentresources
| where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"
    or type =~ "microsoft.hybridcompute/machines/patchassessmentresults"
| extend rebootPending = tobool(properties.rebootPending),
         osType = tostring(properties.osType),
         lastAssessment = todatetime(properties.lastModifiedDateTime),
         criticalCount = toint(properties.availablePatchCountByClassification.Critical),
         securityCount = toint(properties.availablePatchCountByClassification.Security),
         updateRollupCount = toint(properties.availablePatchCountByClassification.UpdateRollup),
         featurePackCount = toint(properties.availablePatchCountByClassification.FeaturePack),
         servicePackCount = toint(properties.availablePatchCountByClassification.ServicePack),
         definitionCount = toint(properties.availablePatchCountByClassification.Definition),
         toolsCount = toint(properties.availablePatchCountByClassification.Tools),
         updatesCount = toint(properties.availablePatchCountByClassification.Updates)
| project id, name, resourceGroup, subscriptionId, osType, rebootPending,
          lastAssessment, criticalCount, securityCount, updateRollupCount,
          featurePackCount, servicePackCount, definitionCount, toolsCount, updatesCount
```

**Return shape:** `{ machines: [...], total_count: int, query_status: str }`

### 3.2 Patch Installations Query

**Source:** `agents/patch/tools.py` lines 246-267

```kql
patchinstallationresources
| where type =~ "microsoft.compute/virtualmachines/patchinstallationresults"
    or type =~ "microsoft.hybridcompute/machines/patchinstallationresults"
| extend startTime = todatetime(properties.startDateTime),
         status = tostring(properties.status),
         rebootStatus = tostring(properties.rebootStatus),
         installedCount = toint(properties.installedPatchCount),
         failedCount = toint(properties.failedPatchCount),
         pendingCount = toint(properties.pendingPatchCount),
         startedBy = tostring(properties.startedBy)
| where startTime > ago(7d)
| project id, resourceGroup, subscriptionId, startTime, status,
          rebootStatus, installedCount, failedCount, pendingCount, startedBy
```

**Return shape:** `{ installations: [...], total_count: int, days: int, query_status: str }`

### 3.3 ARG Pagination Pattern

Both queries use a `skip_token` pagination loop:
```python
while True:
    options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
    request = QueryRequest(subscriptions=subscription_ids, query=kql, options=options)
    response = client.resources(request)
    all_results.extend(response.data)
    skip_token = response.skip_token
    if not skip_token:
        break
```

This must be ported to the API gateway endpoints.

---

## 4. Technical Considerations

### 4.1 Dependency: `azure-mgmt-resourcegraph`

- **Currently in:** `agents/patch/requirements.txt` (already used by the patch agent)
- **Must be added to:** `services/api-gateway/requirements.txt` (confirmed missing — currently has azure-identity, azure-cosmos, azure-ai-agents, mcp, asyncpg, etc., but NOT azure-mgmt-resourcegraph)
- **SDK pattern:** `ResourceGraphClient(credential)` + `QueryRequest` + `QueryRequestOptions` — see [Python SDK quickstart](https://learn.microsoft.com/en-us/azure/governance/resource-graph/first-query-python)

### 4.2 Authentication for ARG Queries

The API gateway already uses `DefaultAzureCredential` (stored in `app.state.credential`). ARG queries require the managed identity to have **Reader** role on the target subscriptions. The patch agent already has this RBAC (Phase 11: "Reader + Monitoring Reader on all subscriptions"). The API gateway's managed identity (`69e05934-...`) needs the same Reader role if it doesn't already have it.

**Key risk:** The gateway MI may not have cross-subscription Reader access. This is an RBAC deployment concern, not a code concern. The implementation should handle ARG permission errors gracefully (return 403-style error message, not 500).

### 4.3 ARG Query Response Format

ARG's Python SDK returns `response.data` as a list of dicts where keys match the KQL `project` column names. The field names in the KQL are already camelCase (matching the TypeScript interfaces in the UI-SPEC), so no transformation needed at the gateway level.

However, the `id` field is a full ARM resource ID (e.g., `/subscriptions/.../providers/Microsoft.Compute/virtualMachines/my-vm/patchAssessmentResults/latest`). The UI extracts the machine name from this ID (last segment before `/patchAssessmentResults`). This extraction should happen client-side per the UI-SPEC.

### 4.4 Endpoint Design

**Decision D-01 from CONTEXT:** Two new GET endpoints:
- `GET /api/v1/patch/assessment?subscriptions=sub1,sub2`
- `GET /api/v1/patch/installations?subscriptions=sub1,sub2`

Both accept `subscriptions` as a required comma-separated query parameter.

**Implementation options (Claude's discretion per CONTEXT):**
1. **New `patch_endpoints.py` module** (recommended) — follows `incidents_list.py` pattern, keeps `main.py` lean
2. **Inline in `main.py`** — viable but `main.py` is already 633 lines

**Route registration:** Add 2 `@app.get(...)` decorators in `main.py` importing from the new module.

### 4.5 Proxy Route Structure

**Decision D-03 from CONTEXT:** Two options:
1. Single route at `app/api/proxy/patch/route.ts` that dispatches to both assessment and installations based on a path segment or query param
2. Split into `app/api/proxy/patch/assessment/route.ts` and `app/api/proxy/patch/installations/route.ts`

**Recommendation:** Split into two route files (option 2). This matches Next.js App Router conventions (one route handler per path) and keeps each file simple. The PatchTab component fetches both in parallel via `Promise.all()`.

### 4.6 Error Handling

The CONTEXT specifies partial-data support (D-12 in UI-SPEC):
- If assessment fails but installations succeed: show Alert for assessment error, show installations table
- If installations fail but assessment succeed: show assessment table + summary cards, show Alert for installations error
- Summary cards derive from whichever data is available

This means the PatchTab must use **separate error states** for assessment and installations, not a single error state. The `Promise.all()` approach should use `Promise.allSettled()` or individual try/catch blocks.

### 4.7 Component Size Estimate

The PatchTab component has:
- 5 summary cards with computed health values
- 2 data tables (13 columns + 8 columns)
- Compliance state derivation logic
- Filter state (compliance + machine search)
- Two data-fetch calls with parallel loading
- Loading/error/empty state handling

**Estimate:** 350-450 lines. The CONTEXT suggests optionally extracting a `PatchSummaryCards.tsx` sub-component if it exceeds ~300 lines. Given the complexity, this extraction is likely needed to stay under the 400-line guideline.

### 4.8 Relative Time Formatting

The UI-SPEC specifies relative time display (e.g., "2h ago"). This utility doesn't exist in the codebase yet. Need to create a `formatRelativeTime(isoString: string): string` helper in `lib/` or inline in PatchTab. Keep it simple — no external dependency needed for basic relative time formatting.

---

## 5. Available shadcn/ui Components (All Pre-installed)

All required components were scaffolded in Phase 9 and are confirmed present:

| Component | File | Status |
|-----------|------|--------|
| Table, TableBody, TableCell, TableHead, TableHeader, TableRow | `components/ui/table.tsx` | Installed |
| Badge | `components/ui/badge.tsx` | Installed |
| Button | `components/ui/button.tsx` | Installed |
| Input | `components/ui/input.tsx` | Installed |
| Select, SelectContent, SelectItem, SelectTrigger, SelectValue | `components/ui/select.tsx` | Installed |
| Skeleton | `components/ui/skeleton.tsx` | Installed |
| Alert, AlertDescription | `components/ui/alert.tsx` | Installed |
| Card, CardContent | `components/ui/card.tsx` | Installed (used by MetricCard) |

**No new shadcn components need to be installed.**

---

## 6. Files to Create

| File | Purpose | Est. Lines |
|------|---------|-----------|
| `services/api-gateway/patch_endpoints.py` | ARG query logic for both endpoints | ~150 |
| `services/web-ui/components/PatchTab.tsx` | Main tab component | ~350-450 |
| `services/web-ui/components/PatchSummaryCards.tsx` | (Optional) Summary card row sub-component | ~80 |
| `services/web-ui/app/api/proxy/patch/assessment/route.ts` | Proxy route for assessment endpoint | ~45 |
| `services/web-ui/app/api/proxy/patch/installations/route.ts` | Proxy route for installations endpoint | ~45 |
| `services/api-gateway/tests/test_patch_endpoints.py` | Unit tests for gateway endpoints | ~200 |

## 7. Files to Modify

| File | Changes | Risk |
|------|---------|------|
| `services/api-gateway/main.py` | Import `patch_endpoints`, add 2 `@app.get(...)` routes | Low — additive only |
| `services/api-gateway/requirements.txt` | Add `azure-mgmt-resourcegraph>=8.0.0` | Low — no conflict |
| `services/web-ui/components/DashboardPanel.tsx` | Add to TabId, TABS, import PatchTab, add tabpanel div | Low — 4 surgical additions |
| `services/api-gateway/models.py` | (Optional) Add Pydantic response models for patch endpoints | Low |

---

## 8. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Gateway MI lacks Reader RBAC on subscriptions for ARG queries | HIGH | Verify RBAC before deployment; implementation returns clear 403 error message |
| `azure-mgmt-resourcegraph` version conflict with existing deps | LOW | Pin to `>=8.0.0`; no known conflicts with existing gateway deps |
| PatchTab component exceeds 400 lines | MEDIUM | Extract PatchSummaryCards sub-component; follow ObservabilityTab's card extraction pattern |
| ARG returns 0 results for subscriptions without Azure Update Manager | LOW | Handle gracefully with empty state per UI-SPEC |
| ARG pagination for large estates (>1000 machines) could be slow | MEDIUM | Gateway should cap at reasonable limit (e.g., 500) or implement server-side pagination in future phase |
| Partial data failure (one endpoint succeeds, one fails) | LOW | Use separate error states per UI-SPEC D-12; `Promise.allSettled` pattern |

---

## 9. Implementation Order (Suggested Plan Breakdown)

### Plan 13-01: API Gateway Patch Endpoints
1. Add `azure-mgmt-resourcegraph` to `requirements.txt`
2. Create `patch_endpoints.py` with `query_patch_assessment()` and `query_patch_installations()` functions
3. Add (optional) Pydantic response models to `models.py`
4. Register routes in `main.py`
5. Write unit tests in `test_patch_endpoints.py` (mock ARG client)
6. Verify with `pytest`

### Plan 13-02: Next.js Proxy Routes
1. Create `app/api/proxy/patch/assessment/route.ts`
2. Create `app/api/proxy/patch/installations/route.ts`
3. Both follow the `incidents/route.ts` pattern exactly

### Plan 13-03: PatchTab Component + DashboardPanel Integration
1. Create `PatchTab.tsx` (and optionally `PatchSummaryCards.tsx`)
2. Wire into `DashboardPanel.tsx` (TabId, TABS, import, tabpanel)
3. Implement all sections per UI-SPEC: summary cards, assessment table, installations table
4. Implement filters (compliance Select, machine search Input)
5. Implement loading/error/empty states
6. Verify `npx tsc --noEmit` passes
7. Verify `npm run build` passes

---

## 10. Azure Resource Graph Reference

### Key Resources
- [How to query AUM data using ARG](https://techcommunity.microsoft.com/blog/azuregovernanceandmanagementblog/how-to-query-azure-update-manager-aum-data-using-azure-resource-graph-arg-explor/4498030) — Detailed walkthrough of ARG table structure for Azure Update Manager
- [patchassessmentresources table reference](https://learn.microsoft.com/en-us/azure/governance/resource-graph/reference/supported-tables-resources/patchassessmentresources) — Official table schema
- [List Azure Update Manager data using ARG](https://learn.microsoft.com/en-us/azure/update-manager/query-logs) — Sample KQL queries for assessment and installation data
- [Python SDK quickstart](https://learn.microsoft.com/en-us/azure/governance/resource-graph/first-query-python) — `azure-mgmt-resourcegraph` usage pattern
- [azure.mgmt.resourcegraph package](https://learn.microsoft.com/en-us/python/api/azure-mgmt-resourcegraph/?view=azure-python) — Python SDK API reference
- [Sample ARG queries for AUM](https://learn.microsoft.com/en-us/azure/update-manager/sample-query-logs?tabs=azure-cli) — Pre-built query templates

### ARG Table Structure

The two ARG tables used are:

| Table | Resource Types | Content |
|-------|---------------|---------|
| `patchassessmentresources` | `microsoft.compute/virtualmachines/patchassessmentresults`, `microsoft.hybridcompute/machines/patchassessmentresults` | Compliance state, missing patch counts by classification, reboot-pending, OS type, last assessment time |
| `patchinstallationresources` | `microsoft.compute/virtualmachines/patchinstallationresults`, `microsoft.hybridcompute/machines/patchinstallationresults` | Installation run history: status, installed/failed/pending counts, reboot status, started-by |

Both tables cover Azure VMs AND Arc-enabled servers (via `microsoft.hybridcompute`).

---

## 11. Acceptance Criteria (Derived from CONTEXT + UI-SPEC)

1. `GET /api/v1/patch/assessment?subscriptions=...` returns machine-level compliance data from ARG
2. `GET /api/v1/patch/installations?subscriptions=...` returns 7-day installation history from ARG
3. Both endpoints handle ARG pagination (skip_token loop)
4. Both endpoints handle permission errors gracefully (not 500)
5. Proxy routes at `/api/proxy/patch/assessment` and `/api/proxy/patch/installations` forward to gateway
6. PatchTab appears as 6th tab in DashboardPanel with ShieldCheck icon
7. 5 MetricCards show: Total Machines, Compliant %, Critical+Security, Reboot Pending, Failed Installs
8. Assessment table shows all 13 columns with client-side compliance + machine search filters
9. Installation history table shows all 8 columns
10. Loading state shows Skeleton placeholders
11. Error state shows destructive Alert
12. Empty state shows ShieldCheck icon + guidance text
13. Partial data failure handled (one endpoint can fail independently)
14. Tab respects `selectedSubscriptions` from `useAppState()`
15. Manual Refresh button re-fetches both endpoints
16. `npx tsc --noEmit` exits 0
17. `npm run build` exits 0
18. Gateway unit tests pass with mocked ARG client

---

*Phase: 13-add-a-new-patch-management-tab-and-show-all-the-patch-related-information*
*Research completed: 2026-03-31*
