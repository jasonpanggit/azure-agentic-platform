# Debug: Patch Tab VM Count, Machine Name, and OS Version

## Issue Summary

Three problems in the Patch Management tab:

1. **Only 1 machine shown** instead of 8 (6 Azure VMs + 2 Arc-enabled servers)
2. **Machine column shows UUID** ("b7c7af89-...") instead of human-readable name
3. **OS column shows "Windows"** without version info (should be "Windows Server 2022")

## Root Cause Analysis

### Issue 1: Only 1 machine showing

**Root cause:** NOT a query/pagination issue. The ARG KQL query correctly includes both
`microsoft.compute/virtualmachines/patchassessmentresults` and
`microsoft.hybridcompute/machines/patchassessmentresults`, and the `_run_arg_query` helper
handles pagination via skip_token.

The real cause is the **frontend deduplication logic** on line 242 of `PatchTab.tsx`:

```ts
machineName: m.name !== 'latest' ? m.name : extractMachineName(m.id),
```

The ARG query returns `patchAssessmentResults` resources, and for every machine the `name`
field is always `"latest"` (it's the latest assessment result, not the machine name).
The `extractMachineName(m.id)` correctly parses the machine name from the resource ID path.

**The actual 1-machine issue is likely:** All 8 ARG rows return `name: "latest"`, the
`extractMachineName` works, BUT since `id` is the unique key and contains the full ARM
resource path, de-duplication isn't the problem. The most likely cause is the backend is
returning all 8 rows correctly, but ARG queries for `patchassessmentresources` naturally
return one result per machine (the latest assessment). This means the 1-machine issue is
actually an **environment/data issue** OR the subscriptions being passed don't cover all
8 machines.

Wait - re-reading more carefully: the `name` field from ARG for patchAssessmentResults is
always "latest" because the resource path is `.../patchAssessmentResults/latest`. So that's
expected. The `id` contains the full ARM resource ID, which includes the machine name.

**Revised root cause for Issue 1:** If only 1 machine is showing, it's either:
- a) Only 1 subscription is being passed (or the subscription doesn't have all machines)
- b) The data in Azure only has 1 machine with assessment results
- c) A frontend filtering issue

Since the user sees exactly 1 machine and the bug report says there should be 8, and the
backend query/pagination looks correct, this is likely a **data completeness issue** in the
Azure environment. However, we should ensure the query is optimal.

### Issue 2: UUID instead of machine name

**Root cause:** The `name` field from the ARG `patchassessmentresources` table is `"latest"`
(the assessment result name, not the machine name). The frontend's `extractMachineName(m.id)`
helper on line 81-94 correctly parses machine names from the ARM resource ID path.

BUT: The user is seeing a UUID `"b7c7af89-61c6-4fb4-a37b-88672a2085c0"`. This means the
`id` field being returned is NOT the full ARM resource path, but just a GUID. This happens
when ARG returns results with a shortened/hashed `id` for some resource types, OR when the
backend response transforms the data.

Looking at the KQL: `| project id, name, ...` - this projects the raw `id` from ARG. For
`patchassessmentresources`, the `id` IS the full ARM resource path. But the `name` is always
`"latest"`.

**The fix:** The KQL should explicitly extract the machine name from the resource ID.
We should add a `machineName` field in the KQL using `extract()` or by splitting the parent
resource ID. We should also include `properties.osType` with version info.

### Issue 3: OS without version

**Root cause:** The KQL query only extracts `osType = tostring(properties.osType)` which
returns just "Windows" or "Linux". The `patchassessmentresources` table does NOT contain
the full OS version string - that information lives on the parent VM/Arc resource.

To get the OS version, we need to either:
1. Join with the `resources` table to get `properties.storageProfile.imageReference` (for VMs)
   or `properties.osProfile` (for Arc machines)
2. Extract it from `properties.osVersion` if available in patchassessmentresources

Actually, looking at the Azure docs, `patchassessmentresources` has:
- `properties.osType` - "Windows" or "Linux"

The parent VM resource has:
- `properties.storageProfile.imageReference.offer` - e.g. "WindowsServer"
- `properties.storageProfile.imageReference.sku` - e.g. "2022-Datacenter"
- `properties.extended.instanceView.osName` - e.g. "Windows Server 2022 Datacenter"
- `properties.extended.instanceView.osVersion` - e.g. "10.0.20348.2340"

For Arc machines: `properties.osName` and `properties.osVersion`

**Fix:** Join with `resources` table to get the detailed OS information, or accept that
patchassessmentresources only provides osType and enrich on the backend.

## Fix Plan

### Backend (patch_endpoints.py)

1. **Flip the KQL query direction**: Start from `resources` table (source of truth for VM list)
2. **Left-join `patchassessmentresources`** onto the VM list using resource ID as join key
3. Add `hasAssessmentData: bool` field to distinguish assessed vs unassessed machines
4. Machine name, OS type, OS version always come from `resources` (authoritative)
5. Patch counts default to 0 and rebootPending to false for unassessed machines

### Frontend (PatchTab.tsx)

1. **Add `hasAssessmentData`** to `AssessmentMachine` interface
2. **Update `deriveCompliance`** to return "Unknown" for unassessed machines
3. **Remove `name` field** from interface (no longer needed — `machineName` comes from resources table directly)
4. Simplify `assessmentWithCompliance` mapping (no more `extractMachineName` fallback)

### Tests (test_patch_endpoints.py)

1. Update sample data to use resource-based IDs (not assessment result IDs)
2. Add unassessed machine to sample data
3. Add dedicated test for unassessed machines
4. Add test verifying KQL starts from resources table

## Changes Made

### Iteration 1 (Previous) — Join added to patchassessmentresources-first query

The initial fix added a leftouter join from `patchassessmentresources` → `resources` to get
machine names and OS versions. This fixed Issues 2 & 3 (UUID names, missing OS versions) but
did NOT fix Issue 1 (only showing machines with assessment data).

### Iteration 2 (Current) — Flipped to resources-first query

**Root cause of Issue 1 correctly identified:** The KQL started from `patchassessmentresources`,
which is a derived table that only contains machines Azure Update Manager has assessed. Machines
that are offline, newly provisioned, or never had AUM configured are invisible.

**Fix:** Flipped the query direction:

### Backend — `services/api-gateway/patch_endpoints.py`

**KQL query rewritten** to:
1. Start from `resources` table, filtering for `microsoft.compute/virtualmachines` and `microsoft.hybridcompute/machines`
2. Extract machine name, OS type, and OS version directly from the resources table (authoritative)
3. Left-join `patchassessmentresources` using derived join key:
   - `resources.id` (lowered) matches `tolower(split(patchassessmentresources.id, '/patchAssessmentResults/')[0])`
4. Add `hasAssessmentData = isnotnull(patchMachineId)` to distinguish assessed vs unassessed
5. Default all patch counts to 0 and rebootPending to false for unassessed machines via `iff()`
6. OS version uses `coalesce()` across multiple Azure property paths:
   - `properties.extended.instanceView.osName` (Azure VMs with instance view)
   - `storageProfile.imageReference.offer + sku` (Azure VMs from image)
   - `properties.osName` (Arc-enabled servers)
   - `properties.osSku` (fallback)
   - `properties.osType` (final fallback)

### Frontend — `services/web-ui/components/PatchTab.tsx`

1. Removed `name` field from `AssessmentMachine` interface (no longer in response)
2. Added `hasAssessmentData: boolean` field
3. Changed `lastAssessment` type to `string | null` (null for unassessed machines)
4. `deriveCompliance()` now returns "Unknown" for machines where `hasAssessmentData === false`
5. Simplified `assessmentWithCompliance` mapping — no more `extractMachineName` fallback needed

### Tests — `services/api-gateway/tests/test_patch_endpoints.py`

1. Sample data updated: IDs are now resource IDs (not assessment result IDs), `name` field removed, `hasAssessmentData` added
2. Added third sample machine (vm-dev-01) with `hasAssessmentData: false` to test unassessed case
3. Added `test_unassessed_machines_have_zeroed_patch_counts` — verifies all counts = 0, rebootPending = false, lastAssessment = null
4. Added `test_kql_starts_from_resources_table` — validates KQL starts with `resources\n`, contains `join kind=leftouter`, and includes `hasAssessmentData`
5. Updated `test_returns_assessment_data` to verify 3 machines (2 assessed + 1 unassessed) and `hasAssessmentData` flags

## Status: FIXED

## Verification

- [x] Backend tests pass (17 tests, 0 failures)
- [x] TypeScript type check passes (`npx tsc --noEmit` — no errors)
- [x] KQL starts from `resources` table (source of truth for all VMs/Arc servers)
- [x] KQL left-joins `patchassessmentresources` (unassessed machines get zeros)
- [x] `hasAssessmentData` field distinguishes assessed vs unassessed
- [x] Frontend `deriveCompliance` returns "Unknown" for unassessed machines
- [x] Response shape preserved (machines array + summary counts)

---

## Iteration 3 — LAW Enrichment + MSRC CVE Mapper + Installed Patches Endpoint

### Objective

Enrich the patch assessment tab with installed patch counts from Log Analytics
(ConfigurationData), add a per-VM installed patch detail endpoint, and build
a MSRC KB→CVE mapper for security enrichment.

### Changes Made

#### New File: `services/api-gateway/msrc_client.py`
- MSRC Security Update Guide API client (no auth required)
- `get_cves_for_kb(kb_id)` — maps a single KB article ID to CVE identifiers
- `get_cves_for_kbs(kb_ids)` — batch parallel lookup via `asyncio.gather`
- In-process cache with 24h TTL to avoid redundant API calls
- Uses `urllib.request` (stdlib) — no new dependencies added
- Graceful degradation: returns `[]` on HTTP error, timeout, or parse failure

#### Updated: `services/api-gateway/patch_endpoints.py`
1. **LAW helpers added:**
   - `_query_law_installed_summary()` — queries ConfigurationData for installed
     software count and last install date per VM (90d window)
   - `_query_law_installed_detail()` — queries ConfigurationData for per-VM
     installed patch detail with software name, type, version, publisher
   - Both use `LogsQueryClient` from `azure.monitor.query`, wrapped in
     `run_in_executor()` for async compatibility
   - Both gracefully degrade to empty results on any failure

2. **Assessment endpoint enriched:**
   - After ARG query, calls `_query_law_installed_summary()` with resource IDs
   - Merges `installedCount` and `lastInstalled` onto each machine record
   - Defaults: `installedCount=0`, `lastInstalled=null` when LAW unavailable

3. **New endpoint: `GET /api/v1/patch/installed`**
   - Query params: `resource_id` (required), `days` (1-365, default 90)
   - Queries LAW ConfigurationData for per-VM installed patch detail
   - Extracts KB IDs from Windows hotfixes and security patches
   - Enriches with CVE identifiers via MSRC client (gracefully degraded)
   - Response: `{ patches: [...], total_count, resource_id, days }`

#### Updated: `services/api-gateway/requirements.txt`
- Added `azure-monitor-query>=1.4.0` for `LogsQueryClient`

#### New File: `services/web-ui/app/api/proxy/patch/installed/route.ts`
- Next.js proxy route for `/api/proxy/patch/installed`
- Follows same pattern as existing `assessment/route.ts`
- Forwards `resource_id` and `days` query params + auth header

#### Updated: `services/web-ui/components/PatchTab.tsx`
1. `AssessmentMachine` interface — added `installedCount: number` and
   `lastInstalled: string | null`
2. Assessment table — added 2 new columns after "Last Assessed":
   - **Installed** — count from LAW (shows "—" when 0)
   - **Last Installed** — relative time or "Never"
3. Table min-width increased from 1000px to 1200px for new columns

#### New File: `services/api-gateway/tests/test_msrc_client.py`
- 14 tests covering normalisation, async lookup, caching, error handling,
  deduplication, batch lookup, and empty inputs

#### Updated: `services/api-gateway/tests/test_patch_endpoints.py`
- Assessment tests now mock `_query_law_installed_summary` (AsyncMock)
- Added `test_assessment_includes_law_enrichment` — verifies LAW data merged
- Added `test_assessment_graceful_degradation_when_law_fails` — verifies
  assessment still works when LAW returns empty
- Added 6 tests for `GET /api/v1/patch/installed`:
  - 503 when workspace not configured
  - 422 when resource_id missing
  - Successful response with CVE enrichment
  - Empty result
  - CVE enrichment graceful degradation
  - Days parameter validation (0 and 400 rejected)
- Total: 39 tests in patch endpoints + MSRC client files

### Verification

- [x] 39 new/updated tests pass (test_patch_endpoints.py + test_msrc_client.py)
- [x] Full API gateway test suite: 192 passed, 1 pre-existing failure (runbook_rag), 2 skipped
- [x] TypeScript type check passes (`npx tsc --noEmit` — no errors)
- [x] LAW enrichment gracefully degrades when LOG_ANALYTICS_WORKSPACE_ID not set
- [x] MSRC CVE mapper gracefully degrades on API failure
- [x] No new pip dependencies beyond `azure-monitor-query` (MSRC uses stdlib `urllib.request`)
- [x] Immutable patterns used (new dicts created, not mutating originals in tests)
