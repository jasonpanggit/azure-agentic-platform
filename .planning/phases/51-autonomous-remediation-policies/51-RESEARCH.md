# Phase 51: Autonomous Remediation Policies — Research

**Researched:** 2026-04-14
**Phase:** 51 — Autonomous Remediation Policies
**Complexity:** L
**Requirement traceability:** V2-002 (Auto-remediation mode)

---

## 1. What This Phase Does

Adds rule-based auto-approval policies to the platform so that known-safe, low-blast-radius remediations execute without human approval. Operators define policies via CRUD API and manage them from a new Settings tab. The platform evaluates policies inline during the `execute_remediation()` path and auto-approves when all safety guards pass.

**Key outcome:** An operator defines a policy for `restart_container_app` on `tier: dev` resources. When the next matching incident triggers that action, the platform auto-executes it without paging anyone. The Cosmos audit trail records `auto_approved_by_policy: <policy_id>`.

---

## 2. Existing Code Analysis

### 2.1 Remediation Executor (`remediation_executor.py`)

**Current flow in `execute_remediation()`:**
1. Safety switch check (`REMEDIATION_EXECUTION_ENABLED`)
2. Extract fields from `approval_record` (incident_id, thread_id, proposed_action, resource_id)
3. Validate `proposed_action` is in `SAFE_ARM_ACTIONS`
4. Pre-flight check via `_run_preflight()` — blast-radius + new-incident scan
5. Write WAL record (pending)
6. Execute ARM action via `_execute_arm_action()`
7. Update WAL status
8. Fire-and-forget OneLake audit log
9. Schedule delayed verification

**Integration point:** Policy evaluation MUST insert between step 3 (action validation) and step 4 (pre-flight). If a matching policy passes all guards, the function should be callable directly (bypassing the HITL approval gate in `approvals.py`).

**Critical observation:** Today `execute_remediation()` receives a pre-approved `approval_record` dict. For auto-policy execution, we need a new entry point that:
- Receives the raw remediation proposal (action_class + resource_id + resource tags)
- Evaluates policies
- If match: synthesizes an `approval_record` with `approved_by = "policy:<policy_id>"` and calls `execute_remediation()`
- If no match: falls through to normal HITL path

**`SAFE_ARM_ACTIONS` dict (line 31):**
```python
SAFE_ARM_ACTIONS = {
    "restart_vm":    {"arm_op": "restart",           "rollback_op": None},
    "deallocate_vm": {"arm_op": "deallocate",         "rollback_op": "start"},
    "start_vm":      {"arm_op": "start",              "rollback_op": "deallocate"},
    "resize_vm":     {"arm_op": "resize",             "rollback_op": "resize_to_original"},
}
```
Need to add `restart_container_app` here. This requires `azure-mgmt-appcontainers` SDK. The `_execute_arm_action()` function is currently hardcoded to `ComputeManagementClient` — it needs a branch for Container Apps operations.

**`_run_preflight()` (line 101):**
- Blast-radius check: currently hardcoded `> 50` threshold
- Policy evaluation should override this with `policy.max_blast_radius` (more restrictive, per CONTEXT decisions)
- The function signature returns `(passed, blast_radius_size, reason)` — no changes needed to interface

**`_classify_verification()` and DEGRADED rollback (lines 269-596):**
- DEGRADED verification triggers auto-rollback regardless of policy — this is already implemented and non-negotiable
- No changes needed to verification/rollback logic

### 2.2 Approvals (`approvals.py`)

**HITL flow:**
- `create_approval()` creates a pending record in Cosmos
- `process_approval_decision()` enforces ETag concurrency, expiry, prod scope confirmation
- `_resume_foundry_thread()` resumes the agent thread after approval

**Integration point:** When a policy auto-approves, we skip `create_approval()` entirely. The remediation is executed directly, and the audit record in Cosmos `remediation_audit` container records `approved_by = "policy:<policy_id>"`.

### 2.3 Remediation Logger (`remediation_logger.py`)

**`build_remediation_event()`** builds the REMEDI-007 schema from an approval record. For auto-policy executions, we need to pass `approvedBy = "policy:<policy_id>"` through this same schema. The function already extracts `approvedBy` from `approval_record.get("decided_by", "")` — we just need to set `decided_by` to `"policy:<policy_id>"` in the synthesized approval record.

### 2.4 Models (`models.py`)

**Existing relevant models:**
- `RemediationAuditRecord` — WAL/audit record; already has `executed_by` field. Need `auto_approved_by_policy` field.
- `RemediationResult` — returned by `execute_remediation()`; no changes needed.
- `ApprovalRecord` — full approval record from Cosmos; used by HITL path.

**New models needed:**
- `AutoRemediationPolicy` — main policy model
- `AutoRemediationPolicyCreate` — request body for POST
- `AutoRemediationPolicyUpdate` — request body for PUT
- `PolicyExecution` — execution history per policy
- `PolicySuggestion` — learning suggestion model

### 2.5 Main (`main.py`)

**Router mounting pattern:** Routers are included via `app.include_router(router)`. There are no existing routers under `/api/v1/admin/` prefix except the inline business-tiers endpoints.

**Startup migrations:** The `_run_startup_migrations()` function runs DDL directly via `asyncpg.connect()`. The `remediation_policies` table should be created here (idempotent `CREATE TABLE IF NOT EXISTS`), following the same pattern as `runbooks`, `eol_cache`, `incident_memory`, and `slo_definitions`.

**Lifespan background tasks:** WAL stale monitor, topology sync, forecast sweep, pattern analysis — all use `asyncio.create_task()`. The learning suggestion engine can run as a similar periodic background task.

### 2.6 Migrations (`migrations/003_create_sops_table.py`)

**Pattern:**
- `UP_SQL` string with `CREATE TABLE IF NOT EXISTS`
- `DOWN_SQL` with `DROP TABLE IF EXISTS`
- `async def up(conn)` and `async def down(conn)`
- `if __name__ == "__main__"` block for standalone execution
- Next migration file: `005_create_remediation_policies_table.py` (per CONTEXT; no 004 exists)

### 2.7 PostgreSQL DSN Resolution

All PostgreSQL access uses `resolve_postgres_dsn()` from `runbook_rag.py`, which resolves from `PGVECTOR_CONNECTION_STRING`, `POSTGRES_DSN`, or individual `POSTGRES_*` env vars. The new `admin_endpoints.py` should reuse this same function.

### 2.8 DashboardPanel (`DashboardPanel.tsx`)

**Tab bar pattern:**
- `TabId` union type with all tab names
- `TABS` array with `{ id, label, Icon }` objects
- Tab panels rendered with `hidden={activeTab !== 'tabId'}` pattern
- Each tab panel wrapped in consistent styling

**Adding Settings tab:**
- Add `'settings'` to `TabId` union
- Add `{ id: 'settings', label: 'Settings', Icon: Settings }` to `TABS` array (import `Settings` from `lucide-react`)
- Add `<SettingsTab />` component in a new tab panel

**Missing shadcn/ui components:** The CONTEXT mentions `Sheet` and `Switch` — neither exists in `components/ui/`. These need to be scaffolded via `npx shadcn@latest add sheet switch` before use.

### 2.9 Proxy Routes

**Pattern from `app/api/proxy/runbooks/route.ts`:**
- Import `getApiGatewayUrl()` and `buildUpstreamHeaders()` from `@/lib/api-gateway`
- `AbortSignal.timeout(15000)` for 15s timeout
- Export `runtime = 'nodejs'` and `dynamic = 'force-dynamic'`
- Logger child with route context

Need new proxy route at `app/api/proxy/admin/remediation-policies/route.ts`.

### 2.10 Test Patterns

**From `test_remediation_executor.py`:**
- Class-based test organization (`class TestWriteWal:`)
- Async test methods
- `MagicMock()` for Cosmos clients
- `patch()` for module-level dependencies
- Direct import from `services.api_gateway.*`

**From `test_execute_endpoint.py`:**
- Helper functions like `_make_approval()` for test fixtures
- Tests against FastAPI endpoint via `TestClient` or direct function calls
- Cosmos mock pattern: `MagicMock()` with chained `.get_database_client().get_container_client()`

---

## 3. Data Architecture

### 3.1 PostgreSQL `remediation_policies` Table

```sql
CREATE TABLE IF NOT EXISTS remediation_policies (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL UNIQUE,
    description             TEXT,
    action_class            TEXT NOT NULL,
    resource_tag_filter     JSONB DEFAULT '{}',
    max_blast_radius        INT DEFAULT 10,
    max_daily_executions    INT DEFAULT 20,
    require_slo_healthy     BOOLEAN DEFAULT true,
    maintenance_window_exempt BOOLEAN DEFAULT false,
    enabled                 BOOLEAN DEFAULT true,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_remediation_policies_action_class
    ON remediation_policies (action_class, enabled);
```

**Why PostgreSQL (not Cosmos):** Policies are structured admin config with low contention. PostgreSQL is the correct store per established patterns (runbooks, SOPs, SLO definitions all in PostgreSQL). ETag-based optimistic concurrency is not needed.

### 3.2 Cosmos DB `remediation_audit` Container (Existing)

The existing `remediation_audit` container needs a new field:
- `auto_approved_by_policy: Optional[str]` — set to `policy_id` when auto-approved, null when HITL-approved

No new Cosmos container needed. Daily execution cap queries this container:
```sql
SELECT COUNT(1) FROM c
WHERE c.auto_approved_by_policy = @policy_id
AND c.executed_at >= @today_start
AND c.action_type = 'execute'
```

### 3.3 Cosmos DB `policy_suggestions` Container (New)

For the learning suggestion engine:
- Partition key: `/action_class`
- TTL: 30 days (suggestions expire if not acted on)
- Fields: `id`, `action_class`, `resource_pattern`, `approval_count`, `rollback_count`, `suggested_at`, `dismissed`, `converted_to_policy_id`

**Decision:** Use a new Cosmos container (not PostgreSQL) because suggestions are event-driven, hot-path writes from the approval flow, and have TTL lifecycle — matching Cosmos usage patterns.

---

## 4. Policy Evaluation Engine — Design

### 4.1 Evaluation Flow

```
Incident detected
    -> Agent proposes remediation (action_class + resource_id)
    -> Policy evaluation:
        1. Query PostgreSQL for enabled policies matching action_class
        2. For each matching policy:
            a. Check resource_tag_filter: resource tags must satisfy filter
            b. Check aap-protected tag: ALWAYS blocks if present (non-negotiable)
            c. Check max_blast_radius: run topology blast-radius check
            d. Check max_daily_executions: count today's auto-executions for this policy
            e. Check require_slo_healthy: query Azure Resource Health
        3. If ALL guards pass for any policy:
            -> Auto-approve with approved_by="policy:<policy_id>"
            -> Execute immediately via execute_remediation()
            -> Log to remediation_audit with auto_approved_by_policy field
        4. If NO policy matches or any guard fails:
            -> Fall through to normal HITL approval path
```

### 4.2 Guard Details

| Guard | Check | Failure Behavior |
|---|---|---|
| `aap-protected: true` tag | Query ARM tags on resource | Block auto-approval always; fall to HITL |
| `max_blast_radius` | `topology_client.get_blast_radius()` | Block if blast_radius > policy.max_blast_radius |
| `max_daily_executions` | Count today's `auto_approved_by_policy=<id>` records in Cosmos | Block if count >= cap |
| `require_slo_healthy` | Azure Resource Health API | Block if resource health != "Available" |
| `resource_tag_filter` | JSONB match (all keys/values must be present on resource) | Block if tags don't match |

### 4.3 Where to Hook In

The integration point is in the approval flow, NOT in `execute_remediation()` directly. The policy evaluation should happen when:
1. An agent proposes a remediation action (via `create_approval()`)
2. Before the HITL gate, check if any policy matches
3. If match: skip creating the approval record, call `execute_remediation()` directly with a synthesized approval record
4. If no match: create the approval record as normal, proceed with HITL

This keeps `execute_remediation()` clean — it doesn't need to know about policies.

---

## 5. `restart_container_app` Action Class

### 5.1 SDK Requirement

```
azure-mgmt-appcontainers>=4.0.0
```

### 5.2 Implementation

```python
# In SAFE_ARM_ACTIONS:
"restart_container_app": {"arm_op": "restart_container_app", "rollback_op": None}
```

Restart is idempotent; no rollback needed (same as `restart_vm`).

### 5.3 ARM Operation

The `_execute_arm_action()` function needs a new branch:
```python
elif arm_op == "restart_container_app":
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    ca_client = ContainerAppsAPIClient(credential, subscription_id)
    # Container Apps don't have a restart API — the pattern is:
    # 1. Create a new revision (or restart active revision)
    # ca_client.container_apps.begin_update(...)
    # OR: stop + start
    poller = ca_client.container_apps.begin_stop(resource_group, app_name)
    poller.result(timeout=120)
    poller = ca_client.container_apps.begin_start(resource_group, app_name)
    poller.result(timeout=120)
```

**Research note:** Azure Container Apps does not have a direct "restart" API. The restart is achieved via `stop` + `start` or by creating a new revision. The stop/start approach is simpler and matches the `restart_vm` pattern.

---

## 6. Learning Suggestion Engine

### 6.1 Trigger

After each successful HITL-approved remediation (no rollback within 24 hours):
1. Query `remediation_audit` for completed executions of the same `action_class + resource_tag_pattern`
2. If count >= 5 with 0 rollbacks:
3. Create/update a `policy_suggestion` record in Cosmos

### 6.2 Implementation Approach

- **Background sweep:** Every 6 hours, scan recent HITL-approved remediations
- **Pattern grouping:** Group by `(action_class, resource_tag_hash)` where `resource_tag_hash` is a deterministic hash of the resource's `tier` and similar operational tags
- **Threshold:** 5 HITL approvals with 0 rollbacks
- **Output:** `PolicySuggestion` record in Cosmos with human-readable message

### 6.3 API

- `GET /api/v1/admin/policy-suggestions` — returns pending suggestions
- `POST /api/v1/admin/policy-suggestions/{id}/dismiss` — dismiss a suggestion
- `POST /api/v1/admin/policy-suggestions/{id}/convert` — converts suggestion to a real policy (creates it in PostgreSQL)

---

## 7. Frontend — Settings Tab

### 7.1 Component Hierarchy

```
DashboardPanel
  -> SettingsTab
       -> PolicyListPanel (default view)
            -> PolicyTable (shadcn Table)
            -> PolicyCreateSheet (shadcn Sheet slide-over)
            -> PolicyEditSheet (shadcn Sheet slide-over)
       -> PolicyExecutionsPanel (on click "Last 10")
            -> ExecutionHistoryTable
       -> PolicySuggestionsPanel (sub-tab)
            -> SuggestionCard[] (dismissible cards)
```

### 7.2 Required shadcn/ui Components (Not Yet Scaffolded)

- `Sheet` — slide-over panel for create/edit
- `Switch` — toggle for enabled/disabled

These need to be scaffolded: `npx shadcn@latest add sheet switch`

### 7.3 Proxy Route

New file: `services/web-ui/app/api/proxy/admin/remediation-policies/route.ts`

Follows the existing pattern from `runbooks/route.ts`:
- GET: proxy to `GET /api/v1/admin/remediation-policies`
- POST: proxy to `POST /api/v1/admin/remediation-policies`

Additional routes for individual policy CRUD may need dynamic route segments.

### 7.4 CSS Token Usage

Per project conventions:
- `var(--accent-blue)` for primary actions
- `var(--accent-green)` for success/enabled states
- `var(--accent-red)` for destructive/disabled states
- Badge backgrounds: `color-mix(in srgb, var(--accent-*) 15%, transparent)`
- Never hardcoded Tailwind color classes

---

## 8. API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/admin/remediation-policies` | List all policies (with execution counts) |
| `POST` | `/api/v1/admin/remediation-policies` | Create policy |
| `GET` | `/api/v1/admin/remediation-policies/{id}` | Get single policy |
| `PUT` | `/api/v1/admin/remediation-policies/{id}` | Update policy |
| `DELETE` | `/api/v1/admin/remediation-policies/{id}` | Delete policy |
| `GET` | `/api/v1/admin/remediation-policies/{id}/executions` | Last 10 auto-executions |
| `GET` | `/api/v1/admin/policy-suggestions` | List pending suggestions |
| `POST` | `/api/v1/admin/policy-suggestions/{id}/dismiss` | Dismiss suggestion |
| `POST` | `/api/v1/admin/policy-suggestions/{id}/convert` | Convert to real policy |

All endpoints require Entra ID Bearer token (`Depends(verify_token)`).

**Router:** New file `admin_endpoints.py` with `APIRouter(prefix="/api/v1/admin", tags=["admin"])`. Mounted in `main.py` via `app.include_router(admin_router)`.

---

## 9. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Auto-remediation causes cascading failures | Critical | `aap-protected` tag always blocks; DEGRADED verification always triggers rollback; daily execution cap; SLO health gate |
| Policy evaluation adds latency to approval path | Medium | PostgreSQL query is fast (<10ms); guard checks are parallelizable; evaluation is synchronous |
| Container Apps restart stops/starts the wrong app | High | Resource identity verification already required (REMEDI-004); `_parse_arm_resource_id()` extracts app name from resource ID |
| Daily cap count is eventually consistent | Low | Cosmos cross-partition query may lag by seconds; acceptable for a daily cap (not a hard safety boundary) |
| Learning suggestions create noise | Low | Threshold of 5 with 0 rollbacks is conservative; suggestions are dismissible; no auto-creation of policies |
| Sheet/Switch components missing from shadcn/ui | Low | Scaffold via `npx shadcn@latest add sheet switch` before development |
| Migration 004 doesn't exist (gap from 003 to 005) | Low | CONTEXT specifies 005; acceptable — migration numbering gaps are common |
| `azure-mgmt-appcontainers` not in requirements | Medium | Add to `requirements.txt` before implementation |

---

## 10. Dependencies and Prerequisites

### 10.1 New Python Packages
- `azure-mgmt-appcontainers>=4.0.0` — for `restart_container_app` action

### 10.2 New shadcn/ui Components
- `Sheet` — slide-over for policy create/edit
- `Switch` — enabled/disabled toggle

### 10.3 Prerequisite Phases
- Phase 27 (Closed-Loop Remediation) — COMPLETE. Provides `remediation_executor.py`, WAL, verification, rollback.
- Phase 22 (Resource Topology Graph) — COMPLETE. Provides `topology_client.get_blast_radius()`.
- Phase 50 (Cross-Subscription Federated View) — COMPLETE. Provides `SubscriptionRegistry`.

### 10.4 No Blockers
All prerequisites are met. No open PRs or outstanding blockers affect this phase.

---

## 11. Estimated Plan Structure

Based on complexity L and the deliverables, recommend **4 plans**:

| Plan | Scope | Estimated Tests |
|---|---|---|
| 51-1 | PostgreSQL migration + Pydantic models + policy CRUD endpoints + `admin_endpoints.py` router | ~10 tests |
| 51-2 | Policy evaluation engine in `remediation_executor.py` + safety guards + `restart_container_app` action + Cosmos audit field | ~12 tests |
| 51-3 | Learning suggestion engine (Cosmos container + background sweep + API endpoints) | ~6 tests |
| 51-4 | Settings tab UI (SettingsTab + PolicyListPanel + create/edit Sheet + execution history + suggestion cards + proxy routes) | ~4 tests (TypeScript) |

**Total estimated:** ~32 tests (exceeds the 20+ target from CONTEXT)

---

## 12. Success Criteria Verification Plan

Per ROADMAP success metric:
1. Define policy for `restart_container_app` on resources tagged `tier: dev`
2. Inject incident that triggers `restart_container_app` on a `tier: dev` resource
3. Verify: no HITL approval prompt appears
4. Verify: `remediation_audit` record shows `auto_approved_by_policy: <policy_id>`
5. Verify: if verification returns DEGRADED, rollback still triggers regardless of policy
6. Verify: resource tagged `aap-protected: true` always falls through to HITL

---

## 13. Key Design Decisions Summary

| Decision | Rationale |
|---|---|
| Policies in PostgreSQL, not Cosmos | Structured config, low-contention admin operations; follows runbooks/SOPs/SLOs pattern |
| Policy suggestions in Cosmos | Event-driven writes, TTL lifecycle; follows incidents/approvals pattern |
| Policy evaluation before HITL gate | Cleanest integration — `execute_remediation()` stays unchanged |
| `restart_container_app` via stop+start | Container Apps has no restart API; stop+start is idempotent and mirrors restart_vm |
| No multi-policy conflict resolution | Deferred — policies likely < 50; first match wins for now |
| Background sweep for learning suggestions | Keeps the HITL approval path fast; 6-hour interval is sufficient for suggestions |
| Settings tab (not separate admin page) | Follows DashboardPanel tab pattern; keeps admin within existing UI paradigm |
