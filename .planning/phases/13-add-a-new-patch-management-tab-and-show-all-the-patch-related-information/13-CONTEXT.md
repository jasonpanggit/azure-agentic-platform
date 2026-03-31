# Phase 13: add a new patch management tab and show all the patch related information - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a **Patch Management tab** to the existing `DashboardPanel` in the web UI (`services/web-ui`). The tab shows patch compliance and status data for Azure VMs and Arc-enabled servers across selected subscriptions.

This phase covers:
- Two new API gateway endpoints that expose ARG patch data
- A new `PatchTab` React component with summary cards and two data tables
- Wiring the tab into `DashboardPanel.tsx`
- A Next.js proxy route for the API gateway patch endpoints
- Unit tests for new gateway endpoints

This phase does **not** cover:
- Changes to the patch agent itself (`agents/patch/`)
- New remediation flows from the UI
- Chat-initiated patch workflows

</domain>

<decisions>
## Implementation Decisions

### Data Source & Fetching

- **D-01:** Data is fetched via **two new API gateway endpoints** (not direct ARG calls from Next.js):
  - `GET /api/v1/patch/assessment` — returns per-machine compliance data (wraps `query_patch_assessment` KQL from `agents/patch/tools.py`)
  - `GET /api/v1/patch/installations` — returns installation run history (wraps `query_patch_installations` KQL from `agents/patch/tools.py`)
- **D-02:** Both endpoints accept a `subscriptions` query param (comma-separated subscription IDs). They call ARG using the API gateway's managed identity (`DefaultAzureCredential`), reusing the **exact same KQL** from `agents/patch/tools.py`.
- **D-03:** The web UI calls these endpoints via a **new Next.js proxy route** at `app/api/proxy/patch/route.ts` (or split into `assessment/route.ts` and `installations/route.ts`), following the same pattern as `app/api/proxy/incidents/route.ts` — passes through the browser's Authorization header.

### Information Layout & Sections

- **D-04:** The Patch tab has **three sections** stacked vertically:
  1. **Summary cards row** (5 cards across the top)
  2. **Assessment table** (per-machine compliance data)
  3. **Installation history table** (per-machine last-7-days runs)
- **D-05:** **5 summary cards** — all color-coded with health indicators (green/yellow/red):
  1. **Total Machines** — count of machines in assessment results
  2. **Compliant %** — percentage of machines in Compliant state
  3. **Critical + Security Patches** — total missing Critical + Security patches across all machines
  4. **Reboot Pending** — count of machines with `rebootPending: true`
  5. **Failed Installs** — count of failed installation runs in the last 7 days (from installations data)
- **D-06:** **Assessment table** — full columns (not condensed):
  - Machine name, OS type, Compliance state (badge: Compliant/NonCompliant/Unknown), Critical, Security, UpdateRollup, FeaturePack, ServicePack, Definition, Tools, Updates counts, Reboot Pending (badge), Last Assessment time
- **D-07:** **Installation history table** — columns:
  - Machine name (from resource ID), Start time (relative), Status (badge: Succeeded/Failed/etc.), Installed count, Failed count, Pending count, Reboot status, Started by
- **D-08:** Reuse the existing `MetricCard` component (already used in `ObservabilityTab`) for the 5 summary cards. Reuse shadcn `Table`, `Badge`, `Skeleton`, `Input`, `Select` following patterns from `ResourcesTab` and `AuditLogViewer`.

### Filtering & Scope

- **D-09:** The Patch tab **respects `selectedSubscriptions`** from `useAppState()` (same pattern as `AlertFeed`, `ResourcesTab`, `ObservabilityTab`). When the user changes the subscription selector in the top nav, the patch data re-fetches.
- **D-10:** The **assessment table** has two local filters:
  - Compliance state `Select` (All / Compliant / NonCompliant / Unknown)
  - Machine name `Input` search (client-side filter on the loaded data)
- **D-11:** **Refresh pattern** — data loads when the tab becomes active (not before). A manual **Refresh** button in the tab header triggers a re-fetch. No auto-polling (patch data changes on minute/hour timescales, not seconds).
- **D-12:** Loading state uses shadcn `Skeleton` rows (same as `ResourcesTab`). Error state uses shadcn `Alert` (same as `ObservabilityTab`).

### Tab Identity & Integration

- **D-13:** Tab label: **"Patch"**, icon: **`ShieldCheck`** (lucide-react), tab ID: `'patch'`, position: **6th tab** (appended after `'observability'` in the `TABS` array in `DashboardPanel.tsx`).
- **D-14:** `TabId` union in `DashboardPanel.tsx` is extended: `type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'observability' | 'patch'`.
- **D-15:** The new component lives at `services/web-ui/components/PatchTab.tsx`. It accepts `subscriptions: string[]` as its sole prop (matching the pattern of `ResourcesTab`, `TopologyTab`, `ObservabilityTab`).
- **D-16:** The `tabpanel-patch` div is added to `DashboardPanel.tsx` alongside the existing 5 tabpanels, wrapped in the standard `rounded-lg overflow-hidden` container with `bg-surface` + `border` inline styles.

### Claude's Discretion

- Exact Python implementation of the two new API gateway endpoints (file organization: new `patch.py` module vs. inline in `main.py`)
- Whether to add a `patch_router` using FastAPI `APIRouter` or inline routes
- Exact heading/section labels within the PatchTab component
- Empty state design when no machines are found (e.g., "No patch data found for selected subscriptions" with a ShieldCheck icon)
- Pagination strategy for large machine counts (client-side page size or server-side limit)
- Test approach for gateway endpoints (unit tests with mocked ARG client, following `services/api-gateway/tests/` pattern)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Tab Pattern to Follow
- `services/web-ui/components/DashboardPanel.tsx` — Tab array, TabId type, tabpanel rendering pattern, CSS custom properties used
- `services/web-ui/components/ResourcesTab.tsx` — Data-fetching pattern: useEffect on subscription change, Skeleton loading, Alert error state, Table + Badge + Select + Input pattern
- `services/web-ui/components/ObservabilityTab.tsx` — MetricCard usage, refresh button pattern, error/loading state
- `services/web-ui/components/MetricCard.tsx` — Reusable summary card with health-colored left border

### Existing API Proxy Route Pattern
- `services/web-ui/app/api/proxy/incidents/route.ts` — Proxy pattern: getApiGatewayUrl(), buildUpstreamHeaders(), AbortSignal.timeout
- `services/web-ui/lib/api-gateway.ts` — getApiGatewayUrl() and buildUpstreamHeaders() helpers

### Existing API Gateway Patterns
- `services/api-gateway/main.py` — Route registration pattern, FastAPI app structure, existing endpoints
- `services/api-gateway/incidents_list.py` — Example of a query module extracted from main.py
- `services/api-gateway/auth.py` — Auth dependency injection pattern

### Patch Agent KQL Source (port these queries to gateway)
- `agents/patch/tools.py` — `query_patch_assessment()` KQL (lines ~145–175) and `query_patch_installations()` KQL (lines ~260–290) — these are the exact ARG queries to reuse in the gateway endpoints
- `agents/patch/tools.py` — Return shapes: assessment returns `{machines: [...], total_count, query_status}`, installations returns `{installations: [...], total_count, days, query_status}`

### shadcn/ui Components Available
- `services/web-ui/components/ui/` — table, badge, button, input, select, skeleton, alert, card — all already scaffolded (Phase 9)

### Azure ARG SDK
- `agents/patch/requirements.txt` — `azure-mgmt-resourcegraph` dependency (already in patch agent; must also be added to API gateway `requirements.txt`)

### Phase Context
- `.planning/phases/11-patch-domain-agent/11-CONTEXT.md` — Patch agent decisions: KQL strategy, return shapes, ARG table schemas
- `CLAUDE.md` §"Frontend (Next.js + Fluent UI 2)" — SSE approach, App Router, Node.js runtime (not Edge)
- `CLAUDE.md` §"What NOT to Use" — No @fluentui/react, no Vercel AI SDK for dashboard routes

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `MetricCard` (components/MetricCard.tsx) — already used in ObservabilityTab; accepts `title`, `value`, `health` prop (green/yellow/red border). Reuse for all 5 summary cards.
- `shadcn Table` — used in ResourcesTab, AlertFeed, AuditLogViewer. Same import pattern applies.
- `shadcn Badge` — used in ResourcesTab for resource type labels. Use for compliance state (Compliant=green, NonCompliant=red, Unknown=gray) and reboot-pending indicator.
- `shadcn Skeleton` — used in ResourcesTab for loading state rows.
- `shadcn Alert` — used in ObservabilityTab for error state.
- `shadcn Select` — used in ResourcesTab for type filter. Use for compliance state filter.
- `shadcn Input` — used in ResourcesTab for name search. Use for machine name search.
- `useAppState()` from `@/lib/app-state-context` — provides `selectedSubscriptions`

### Established Patterns
- **Data fetching:** `useEffect` triggered by subscriptions change + manual `fetchData()` callback. `useState` for `data`, `loading`, `error`. Pattern exact match to `ResourcesTab`.
- **CSS custom properties:** `var(--bg-surface)`, `var(--bg-canvas)`, `var(--border)`, `var(--text-primary)`, `var(--text-secondary)`, `var(--accent-red)`, `var(--accent-green)`, `var(--accent-yellow)`.
- **API gateway proxy:** `getApiGatewayUrl()` + `buildUpstreamHeaders(authHeader, false)` + `AbortSignal.timeout(15000)`.
- **Tailwind only** — no inline `style={{}}` beyond the CSS custom property vars (which can't be expressed in Tailwind utility classes).

### Integration Points
- `DashboardPanel.tsx` — 4 locations to modify: `TabId` type, `TABS` array, import of `PatchTab`, new `tabpanel-patch` div
- `services/api-gateway/main.py` — add 2 new GET route registrations
- `services/api-gateway/requirements.txt` — add `azure-mgmt-resourcegraph` dependency
- `services/web-ui/app/api/proxy/` — add new `patch/` subdirectory with route handler(s)

### New Components to Create
- `services/web-ui/components/PatchTab.tsx` — main tab component
- (Optional) `services/web-ui/components/PatchSummaryCards.tsx` — summary card row sub-component if PatchTab.tsx exceeds ~300 lines
- `services/api-gateway/patch_endpoints.py` (or inline in main.py) — two new FastAPI route handlers

</code_context>

<specifics>
## Specific Ideas

- **User explicitly requested:** Check the patch agent and leverage it — confirmed approach: **port the exact KQL from `agents/patch/tools.py`** into new API gateway endpoints. The gateway becomes the data layer for the UI, not the agent's Python tools (which are designed for LLM function calling, not direct HTTP calls).
- **MetricCard health coloring for Compliant %:**
  - ≥ 90% → green (`health="healthy"`)
  - 70–89% → yellow (`health="warning"`)
  - < 70% → red (`health="critical"`)
- **Compliance state badge colors:**
  - Compliant → `bg-green-100 text-green-700` (or shadcn success variant)
  - NonCompliant → `bg-red-100 text-red-700` (destructive variant)
  - Unknown → default/outline badge
- **Reboot Pending badge:** destructive/orange when `rebootPending: true`, absent/hidden when false
- **Failed Installs card:** pulls from installations data — count where `status !== "Succeeded"` in last 7 days

</specifics>

<deferred>
## Deferred Ideas

- KB-to-CVE drill-down from the assessment table (clicking a machine to see individual CVEs) — belongs in a future phase
- Triggering a patch assessment run or installation from the UI — out of scope (chat workflow handles this)
- Export/download patch report — future phase
- Historical compliance trend chart — future phase

</deferred>

---

*Phase: 13-add-a-new-patch-management-tab-and-show-all-the-patch-related-information*
*Context gathered: 2026-03-31*
