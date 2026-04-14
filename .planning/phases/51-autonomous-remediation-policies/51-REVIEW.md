---
status: issues_found
phase: 51
files_reviewed: 19
findings:
  critical: 0
  warning: 3
  info: 6
  total: 9
---

# Phase 51 — Autonomous Remediation Policies: Code Review

> Reviewed: 2026-04-14  
> Diff base: `3b78eb07c21884bd568f33b194d263cafb0a91e2^`  
> Depth: standard

---

## Summary

Phase 51 adds a policy-engine-driven auto-approval path that short-circuits the human-in-the-loop (HITL) gate when a configurable set of guards all pass. It consists of four sub-phases:

| Sub-phase | Deliverable |
|---|---|
| 51-1 | `RemediationPolicy` PostgreSQL table + full CRUD in `admin_endpoints.py` |
| 51-2 | `policy_engine.py` — guard evaluation at `create_approval` intercept point |
| 51-3 | `suggestion_engine.py` — learning sweep that proposes policies from HITL patterns |
| 51-4 | `SettingsTab.tsx` + proxy routes — admin UI for policies and suggestions |

The implementation is large (~1,300 net lines of Python, ~900 net lines of TypeScript) and aligns well with the CLAUDE.md conventions, platform architecture, and stated design intent. No blocking defects were found, but several issues warrant attention before the phase is merged.

---

## Findings by Severity

### HIGH — Must Fix

---

#### H-1 · `create_approval` auto-approval path leaks `approval_id` containing `policy_id` into the HITL record store

**File:** `services/api-gateway/approvals.py` lines 121–133

```python
result = await execute_remediation(
    approval_id=f"auto-policy-{policy_id}",   # ← policy UUID leaks into id
    ...
)
return {
    "approval_id": f"auto-policy-{policy_id}",
    ...
}
```

The auto-approval path bypasses the `create_item` call on the `approvals` container, so no Cosmos document is created for the auto-approved action. However, the `execute_remediation` code writes the WAL record using `approval_id=f"auto-policy-{policy_id}"` — a non-UUID, predictable string.

**Risk:** If this value is ever surfaced to the compliance export endpoint (`/api/v1/audit/remediation-export`) or queried cross-partition by `approval_id`, the query will succeed only if the string happens to be the partition key or is found through a cross-partition scan. More importantly, the WAL record's `approval_id` field differs in format from all HITL-created records (`appr_<uuid>` vs `auto-policy-<uuid>`), which can break downstream audit tooling.

**Recommendation:** Generate a proper UUID for auto-approved executions (`f"auto-{uuid.uuid4()}"`) and write a minimal approval-like document to the `approvals` container with `status="auto_approved"` so the audit trail is consistent.

---

#### H-2 · Daily-cap Cosmos query in `policy_engine.py` is sync inside an `asyncio` hot path

**File:** `services/api-gateway/policy_engine.py` lines 214–227

```python
query_result = list(container.query_items(   # ← sync blocking call
    query=...,
    ...
))
```

`evaluate_auto_approval` is `async` and is invoked directly from `create_approval`, which is called from the sync `create_approval_endpoint` (FastAPI). The Cosmos Python SDK's `query_items` is synchronous and will **block the event loop** for the duration of the round-trip.

The blast-radius check just above it calls `topology_client.get_blast_radius(...)` directly (also sync, line 184). Both are called without `run_in_executor`.

**Risk:** Under load, this will degrade gateway latency for all concurrent requests sharing the same event loop.

**Recommendation:** Wrap both calls in `await asyncio.get_running_loop().run_in_executor(None, ...)` or convert to the async Cosmos SDK (`aio` package). The suggestion engine already uses this pattern correctly (`run_in_executor` in `run_suggestion_sweep`).

---

#### H-3 · `_suggestion_exists` enables partition-key cross-query bug

**File:** `services/api-gateway/suggestion_engine.py` lines 169–191

```python
items = list(container.query_items(
    query=query,
    parameters=parameters,
    enable_cross_partition_query=False,  # action_class is the partition key
))
```

The comment says `action_class` is the partition key and cross-partition is disabled, which implies the SDK should use a direct single-partition read. However, the Cosmos Python SDK requires `partition_key=<value>` to be explicitly passed for single-partition queries; passing `enable_cross_partition_query=False` without a `partition_key` argument causes the SDK to raise `BadRequestException: Cross partition query is required but disabled` when the query touches multiple partitions — or silently returns empty if interpreted as a single-partition scoped to an undefined key.

This means `_suggestion_exists` may always return `False` even when a suggestion exists (deduplication broken), or may throw intermittently.

**Recommendation:** Pass `partition_key=action_class` explicitly:
```python
container.query_items(query=query, parameters=parameters, partition_key=action_class)
```

---

### MEDIUM — Should Fix

---

#### M-1 · Per-request PostgreSQL connections create N connections per list-policies call

**File:** `services/api-gateway/admin_endpoints.py` — all route handlers

Every endpoint in `admin_endpoints.py` calls `_get_pg_connection()` which opens a new `asyncpg.connect()` per request and closes it in `finally`. The `list_policies` handler also calls `_count_executions_today` in a loop over all policies — one Cosmos query per policy with no batching.

**Impact:** For N policies, list-policies performs 1 PG query + N Cosmos queries sequentially, all under a single HTTP request. With 20 policies this is measurably slow. Additionally, frequent PG connection churn under load can hit connection limits on the Flexible Server.

**Recommendation:**
1. Use an `asyncpg.Pool` initialized at startup (store on `app.state`) rather than per-request connections.
2. Consider a single batch Cosmos query to count executions for all policy IDs at once:
   ```sql
   SELECT c.auto_approved_by_policy, COUNT(1) AS cnt FROM c WHERE ...
   GROUP BY c.auto_approved_by_policy
   ```

---

#### M-2 · `handleToggleEnabled` in `SettingsTab.tsx` sends full policy object instead of PATCH

**File:** `services/web-ui/components/SettingsTab.tsx` lines 438–443

```typescript
body: JSON.stringify({ ...policy, enabled: !policy.enabled }),
```

The toggle sends the full policy payload via `PUT`. This is correct per the existing `AutoRemediationPolicyUpdate` model (all fields optional), but it sends `execution_count_today`, `created_at`, `updated_at`, `success_rate` — fields unknown to the update schema. FastAPI will silently ignore extra fields by default, but this is fragile: if the backend ever adds strict validation, this will break.

**Recommendation:** Send only the delta:
```typescript
body: JSON.stringify({ enabled: !policy.enabled }),
```

---

#### M-3 · `RemediationPolicy` TypeScript type has `executions_today` but API returns `execution_count_today`

**File:** `services/web-ui/components/SettingsTab.tsx` line 52 vs API model `models.py` line 586

The TS interface declares:
```typescript
executions_today: number
```

The Python model and DB column is:
```python
execution_count_today: int  # in AutoRemediationPolicy
```

The table cell references `policy.executions_today` (line 575), which will always be `undefined`, rendering `0` via `?? 0`. The "Today" column is non-functional.

**Recommendation:** Align the TypeScript field name: rename to `execution_count_today` in the interface and table cell.

---

#### M-4 · `dismiss_suggestion` route requires `action_class` as a query param but the UI doesn't send it

**File:** `services/api-gateway/admin_endpoints.py` line 445–446

```python
async def dismiss_policy_suggestion(
    suggestion_id: str,
    action_class: str,         # ← required query param
```

**File:** `services/web-ui/components/SettingsTab.tsx` line 681

```typescript
const res = await fetch(`/api/proxy/admin/policy-suggestions/${id}/dismiss`, { method: 'POST' })
```

The UI does not pass `action_class` in the query string. The proxy route in `[id]/[action]/route.ts` does forward `req.nextUrl.searchParams` (line 21), but the `suggestion` object has `action_class` and it is never appended to the URL.

**Impact:** Every dismiss call will return `422 Unprocessable Entity` from FastAPI because `action_class` is a required query parameter.

**Recommendation:** The UI must append `action_class` as a query param:
```typescript
const res = await fetch(
  `/api/proxy/admin/policy-suggestions/${id}/dismiss?action_class=${encodeURIComponent(suggestion.action_class)}`,
  { method: 'POST' }
)
```

---

#### M-5 · `convert_policy_suggestion` endpoint accepts `action_class` as query param but also as body — ambiguous contract

**File:** `services/api-gateway/admin_endpoints.py` lines 463–470

```python
async def convert_policy_suggestion(
    suggestion_id: str,
    action_class: str,            # ← query param
    body: AutoRemediationPolicyCreate,  # ← request body (also has action_class)
```

Both `action_class` (query param) and `body.action_class` (request body) exist independently. The `action_class` query param is used for the Cosmos partition-key lookup (to find the suggestion), while `body.action_class` governs the created policy. These can diverge silently, creating a policy linked to a suggestion for a different action class.

**Recommendation:** Remove the separate `action_class` query param and derive it from `body.action_class`, or add an assertion that they match.

---

#### M-6 · `_verify_remediation` passes hardcoded `"Unknown"` as `pre_execution_status`

**File:** `services/api-gateway/remediation_executor.py` line 547

```python
classification = _classify_verification(current_health, "Unknown")
```

`_classify_verification` uses `pre_execution_status` to distinguish `RESOLVED` (was unhealthy, now Available) from `IMPROVED` (was already available). Passing `"Unknown"` always means a healthy post-execution result maps to `IMPROVED` rather than `RESOLVED`, even when the resource was clearly unhealthy before.

**Impact:** Incidents that were genuinely RESOLVED will be classified as IMPROVED, causing unnecessary re-diagnosis loops.

**Recommendation:** Capture the pre-execution resource health status before executing the ARM action and pass it to `_verify_remediation` / `_classify_verification`. This was likely a deferred improvement but has behavioral impact.

---

### LOW — Consider Fixing

---

#### L-1 · `suggestion_engine.py` `_run_sweep_sync` computes `resource_pattern: {}` always

**File:** `services/api-gateway/suggestion_engine.py` line 136

```python
"resource_pattern": {},   # always empty
```

The `PolicySuggestion` model has `resource_pattern: dict` described as "Common resource tag pattern observed". The sweep has enough data to infer a common tag pattern (the `resource_id` list is available), but it is not computed. This is a known limitation but the UI and API surface it as if it were populated.

**Recommendation:** Either compute the common tag pattern (e.g., extract shared tags from resource IDs via ARM API) or document in the Cosmos document that `resource_pattern` is intentionally empty in v1.

---

#### L-2 · `_count_executions_today` in `admin_endpoints.py` does not filter by `action_type = 'execute'`

**File:** `services/api-gateway/admin_endpoints.py` lines 106–109

```python
query = (
    "SELECT VALUE COUNT(1) FROM c "
    "WHERE c.auto_approved_by_policy = @policy_id "
    "AND c.executed_at >= @today_start"
)
```

The policy engine's own cap check (in `policy_engine.py` line 222) correctly filters `AND c.action_type = 'execute'`, but the admin endpoint's counter omits this filter. Rollback records (`action_type = 'rollback'`) could inflate the displayed count.

**Recommendation:** Add `AND c.action_type = 'execute'` for consistency.

---

#### L-3 · `handleConvert` in `SettingsTab.tsx` does not pass `action_class` query param to the convert proxy

Same root cause as M-4. The convert endpoint also requires `action_class` as a query param alongside the POST body:

```typescript
const res = await fetch(
  `/api/proxy/admin/policy-suggestions/${convertingSuggestionId}/convert`,
  { method: 'POST', ... }
)
```

No `action_class` query param is appended. This will also return 422 from FastAPI.

**Recommendation:** Append `?action_class=${encodeURIComponent(convertFormData.action_class)}` to the convert URL.

---

#### L-4 · `incidents` container partition key mismatch in `approvals.py`

**File:** `services/api-gateway/approvals.py` lines 785–795 (noise reducer) and `cosmos.tf` line 60

The `incidents` container Terraform uses `partition_key_paths = ["/resource_id"]`, but `_run_preflight` (in `remediation_executor.py`) queries incidents cross-partition by `resource_id` field — which IS the partition key. This is fine. However, several `approvals.py` callers query the Cosmos `incidents` container using `partition_key=incident_id` (the doc's `id`, not the partition key `/resource_id`). This will cause cross-partition fallback or errors at runtime when `incident_id != resource_id`.

This issue pre-dates Phase 51 but the new auto-approval path adds another call site in `approvals.py` line 802 that writes an incident with `id=incident_id` and no `resource_id` field set — meaning the partition key would be `None` / missing.

**Recommendation:** Ensure the auto-approval suppressed-incident write includes `resource_id`, and audit incident container access patterns for PK alignment.

---

#### L-5 · `SheetContent` in `sheet.tsx` has hardcoded `sm:max-w-sm` conflicting with SettingsTab override

**File:** `services/web-ui/components/ui/sheet.tsx` line 46

The shadcn/ui Sheet for right-side sets `sm:max-w-sm` (384px) as the default. `SettingsTab.tsx` overrides with `sm:max-w-lg` (line 630), which works but conflicts with the base component's built-in `sm:max-w-sm`. Tailwind specificity means the last-declared class wins in a static bundle, which is non-deterministic.

**Recommendation:** Remove the hardcoded `sm:max-w-sm` from `sheet.tsx` and require callers to pass width via `className`, or use a `size` prop pattern consistent with shadcn/ui conventions.

---

#### L-6 · Missing `@pytest.mark.asyncio` decorator on all async test functions

**Files:** `tests/test_policy_engine.py`, `tests/test_suggestion_engine.py`

All test functions are defined as `async def` but lack `@pytest.mark.asyncio`. Unless `asyncio_mode = "auto"` is set in `pyproject.toml`, pytest-asyncio will not run them and they will appear as "collected but not run" or silently pass as no-ops.

**Recommendation:** Either add `@pytest.mark.asyncio` to each async test, or confirm `asyncio_mode = "auto"` is set in the project's `pyproject.toml`.

---

## Architecture & Design Observations

### Positives

1. **Guard ordering is correct.** The `aap-protected` tag check runs first as a non-negotiable brake before any DB queries, then policies are queried, then each policy's guards run in sequence. This is defensive-by-default.

2. **Conservative failure mode.** Every guard exception returns `False` (blocks auto-approval). This is the right default for a safety-critical path.

3. **WAL-before-ARM pattern preserved.** The auto-approval path calls `execute_remediation` which writes the WAL record before the ARM call, maintaining the REMEDI-011 invariant.

4. **Suggestion engine is well-scoped.** Sweeping only `action_type='execute' AND status='complete' AND auto_approved_by_policy IS NULL` correctly excludes auto-approved records from inflating the threshold counter.

5. **Proxy routes follow established patterns.** All four Next.js proxy routes correctly use `getApiGatewayUrl()`, `buildUpstreamHeaders()`, `AbortSignal.timeout(15000)`, and handle 204 separately on DELETE — consistent with the project's proxy route convention.

6. **Terraform container provisioned.** The `policy_suggestions` container is correctly defined in Terraform with `action_class` as partition key (matching suggestion engine's read/write), 30-day TTL, and a corresponding output. The `remediation_audit` composite indexes cover the new daily-cap query pattern.

### Concerns

1. **No rate-limiting on the new admin endpoints.** The `admin_endpoints` router is mounted with `verify_token` per endpoint, but there is no rate limiting applied to the policy CRUD or suggestion actions. The existing `apply_http_rate_limit` middleware only covers `/api/v1/chat` and `/api/v1/incidents`. Admin endpoints that trigger DB writes should have per-IP or per-user rate limits.

2. **`maintenance_window_exempt` field is persisted and surfaced in the UI but never evaluated.** There is no maintenance window check in `_evaluate_policy_guards`. The field is wired through the full stack (DB, model, UI) but the guard is a no-op. This is acceptable as a deferred feature but should be documented as not yet enforced, or the UI toggle should be disabled with a tooltip.

3. **`success_rate` field on `AutoRemediationPolicy` is always `None`.** Defined in the model (line 587) and surfaced in the response type, but never computed in `_row_to_policy` or anywhere else. The UI doesn't display it, so this is harmless but adds noise to the API schema.

4. **`approvals.py` create_approval `topology_client` and `credential` parameters come from `None` defaults.** When `create_approval_endpoint` in `main.py` calls `create_approval`, it does not pass `topology_client` or `credential` (lines 1655–1664). These will be `None` in the policy engine, meaning blast-radius is treated as 0 (always passes) and the SLO health gate is skipped (credential is None, guard is bypassed). This effectively makes the blast-radius and SLO guards non-functional for the synthetic approval path.

---

## Test Coverage Assessment

| Module | Tests Present | Coverage Estimate | Notes |
|---|---|---|---|
| `policy_engine.py` | Yes — 14 test cases | ~90% | All guard paths covered; DB query path not directly tested |
| `suggestion_engine.py` | Yes — 7 test cases | ~80% | Loop and CRUD paths covered; `_suggestion_exists` bug not caught (H-3) |
| `admin_endpoints.py` | No tests in reviewed files | ~0% | CRUD endpoints completely untested |
| `approvals.py` (Phase 51 path) | No tests in reviewed files | ~0% | Auto-approval intercept path untested |

`test_policy_engine.py` tests are well-structured: each test is focused, the helpers `_make_policy`, `_make_cosmos_client`, and `_make_topology_client` are clean. However, the missing `@pytest.mark.asyncio` (L-6) means these tests may not actually execute.

The admin endpoint tests are absent entirely. At minimum, the `create_policy` and `update_policy` action-class validation should be tested.

---

## Required Actions Before Merge

| Priority | ID | File | Action |
|---|---|---|---|
| HIGH | H-1 | `approvals.py` | Use UUID for auto-approval_id; write Cosmos approval doc for audit completeness |
| HIGH | H-2 | `policy_engine.py` | Wrap sync Cosmos/topology calls in `run_in_executor` |
| HIGH | H-3 | `suggestion_engine.py` | Fix `_suggestion_exists` to pass `partition_key=action_class` |
| MEDIUM | M-4 | `SettingsTab.tsx` | Add `action_class` query param to dismiss fetch call |
| MEDIUM | M-3 | `SettingsTab.tsx` | Fix `executions_today` → `execution_count_today` field name |
| MEDIUM | M-4 / L-3 | `SettingsTab.tsx` | Add `action_class` query param to convert fetch call |
| LOW | L-6 | test files | Add `@pytest.mark.asyncio` or confirm `asyncio_mode = "auto"` |
