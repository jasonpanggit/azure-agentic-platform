# Phase 13: add a new patch management tab and show all the patch related information - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-31
**Phase:** 13-add-a-new-patch-management-tab-and-show-all-the-patch-related-information
**Areas discussed:** Data source & fetching, Information layout & sections, Filtering & scope, Tab identity & integration

---

## Data Source & Fetching

| Option | Description | Selected |
|--------|-------------|----------|
| New API gateway endpoints | Add GET /api/v1/patch/assessment and GET /api/v1/patch/installations to the API gateway. Reuses the exact KQL from patch agent tools.py. Web UI proxies through gateway. | ✓ |
| Direct ARG from Next.js | Next.js route handler queries ARG REST API directly with managed identity — same pattern as ResourcesTab querying ARM. Duplicates KQL logic. | |
| Both datasets (assessment + installations) | Both assessment and installation data exposed — no data truncation. | (implicit, folded into chosen approach) |

**User's choice:** New API gateway endpoints
**Notes:** User explicitly said "check patch agent and see if we can leverage on it" — confirmed by reading agents/patch/tools.py that the exact KQL and return shapes are already written; the gateway endpoints will port this KQL directly.

---

## Information Layout & Sections

| Option | Description | Selected |
|--------|-------------|----------|
| Summary cards + two tables | Top: 3-4 summary cards. Below: Assessment table + Installation history table. | ✓ |
| Single detailed table per machine | Unified table with all columns per machine. | |
| Summary cards only | Lightweight overview without per-machine data. | |

**User's choice:** Summary cards + two tables

### Summary Cards Follow-up

| Option | Description | Selected |
|--------|-------------|----------|
| 4 cards: Total, Compliance %, Critical+Security, Reboot Pending | Standard set. | |
| 5 cards: add Failed Installs | Adds Failed Installs (last 7 days) from installation history data. | ✓ |
| 3 cards: Compliance, Critical, Reboot Pending | Minimal set. | |

**User's choice:** 5 cards (Total Machines, Compliant %, Critical+Security Patches, Reboot Pending, Failed Installs)

### Assessment Table Depth Follow-up

| Option | Description | Selected |
|--------|-------------|----------|
| Full columns on assessment table | All columns: name, OS, compliance state, Critical, Security, UpdateRollup, FeaturePack, ServicePack, Definition, Tools, Updates, reboot-pending, last assessment. | ✓ |
| Condensed assessment table | Fewer columns: name, compliance state, critical+security combined, reboot-pending, last assessment. | |

**User's choice:** Full columns on assessment table

---

## Filtering & Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Respect selectedSubscriptions from app state | Follows selectedSubscriptions from useAppState() — re-fetches when subscription selector changes. | ✓ |
| Always query all subscriptions | Ignores subscription selector. | |

**User's choice:** Respect selectedSubscriptions from app state

### Local Filters Follow-up

| Option | Description | Selected |
|--------|-------------|----------|
| Compliance state filter + machine name search | Select (All/Compliant/NonCompliant/Unknown) + Input search. | ✓ |
| Compliance + machine + classification filters | Three filters. | |
| No filters, pagination only | No client-side filtering. | |

**User's choice:** Compliance state filter + machine name search

### Refresh Pattern Follow-up

| Option | Description | Selected |
|--------|-------------|----------|
| Load on tab activation + manual refresh button | Data loads when tab activates; Refresh button for explicit re-fetch. | ✓ |
| Auto-poll every 60 seconds | Automatic polling. | |
| Load on activation only (no refresh) | No refresh capability. | |

**User's choice:** Load on tab activation + manual refresh button

---

## Tab Identity & Integration

| Option | Description | Selected |
|--------|-------------|----------|
| "Patch" label, ShieldCheck icon, 6th tab | Label: "Patch", Icon: ShieldCheck (lucide), Position: after Observability. | ✓ |
| "Patching" label, Shield icon, 6th tab | Alternative label/icon. | |
| "Updates" label, RefreshCw icon, 6th tab | Alternative label/icon. | |

**User's choice:** "Patch" label, ShieldCheck icon, 6th tab (after Observability)

---

## Claude's Discretion

- Exact Python file organization for new API gateway endpoints (new module vs. inline in main.py)
- Whether to use FastAPI APIRouter for patch routes
- Empty state design (no machines found)
- Pagination strategy for large datasets
- Test approach for new gateway endpoints

## Deferred Ideas

- KB-to-CVE drill-down (clicking a machine to see individual CVEs) — future phase
- Triggering patch assessment runs or installations from the UI — chat workflow handles this
- Export/download patch report — future phase
- Historical compliance trend chart — future phase
