# Phase 51: Autonomous Remediation Policies - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous)

<domain>
## Phase Boundary

Deliver a complete auto-approval policy engine: operators define rule-based policies that let the platform execute known-safe, low-blast-radius remediations without human approval. Includes:
- PostgreSQL `remediation_policies` table and migration
- `AutoRemediationPolicy` Pydantic model with all guards
- `POST/GET/PUT/DELETE /api/v1/admin/remediation-policies` CRUD API
- Policy evaluation engine integrated into `remediation_executor.py` execute_remediation() path
- All safety guards (blast-radius cap, daily execution cap, SLO health gate, `aap-protected: true` tag exclusion)
- Audit trail: `auto_approved_by_policy` field in Cosmos DB remediation_audit records
- UI: Remediation Policies panel in a new Settings tab in DashboardPanel
- Automatic learning suggestion: after 5 HITL-approved identical actions with 0 rollbacks → platform emits `policy_suggestion` event
- Extend SAFE_ARM_ACTIONS to include `restart_container_app` action class

</domain>

<decisions>
## Implementation Decisions

### Policy Model & Storage
- Store policies in PostgreSQL `remediation_policies` table (same pattern as `runbooks`, `sops`)
- Migration: `005_create_remediation_policies_table.py` (Python migration following existing pattern)
- Schema: `id UUID PK`, `name TEXT`, `description TEXT`, `action_class TEXT`, `resource_tag_filter JSONB`, `max_blast_radius INT DEFAULT 10`, `max_daily_executions INT DEFAULT 20`, `require_slo_healthy BOOLEAN DEFAULT true`, `maintenance_window_exempt BOOLEAN DEFAULT false`, `enabled BOOLEAN DEFAULT true`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`
- No Cosmos DB for policies — PostgreSQL is the right store (structured config, not hot-path events)
- ETag-based concurrency not needed here (low-contention admin config)

### Policy Evaluation Engine
- Integrate policy check into `execute_remediation()` in `remediation_executor.py` BEFORE the HITL gate
- Check order: (1) policy lookup by action_class, (2) tag filter match, (3) blast-radius guard, (4) daily cap check, (5) SLO health gate, (6) `aap-protected` tag exclusion
- If all guards pass → set `approved_by = "policy:<policy_id>"`, skip HITL, execute immediately
- Log `auto_approved_by_policy: <policy_id>` in Cosmos DB remediation_audit record
- Policy evaluation is synchronous (no async needed — simple DB query + guard checks)
- Daily cap tracked via count query on remediation_audit container filtered by policy_id + today

### Safety Guards — Non-negotiable
- `aap-protected: true` resource tag ALWAYS blocks auto-approval regardless of policy
- DEGRADED verification ALWAYS triggers rollback regardless of policy (existing REMEDI-012 logic unchanged)
- Blast-radius check reuses `_run_preflight()` existing logic, policy `max_blast_radius` overrides the hardcoded 50 limit (policy-specific cap, more restrictive)
- SLO health gate: check Azure Resource Health — skip auto-approval if resource health ≠ Available
- Daily execution cap: count today's auto-approved executions for this policy_id from Cosmos DB audit

### New Action Class
- Add `restart_container_app` to `SAFE_ARM_ACTIONS` in `remediation_executor.py`
- Uses Azure Container Apps management SDK (`azure-mgmt-appcontainers`)
- rollback_op: None (restart is idempotent, no rollback needed)

### API Endpoints
- `GET /api/v1/admin/remediation-policies` — list all policies (with execution counts from audit)
- `POST /api/v1/admin/remediation-policies` — create policy
- `GET /api/v1/admin/remediation-policies/{id}` — get single policy
- `PUT /api/v1/admin/remediation-policies/{id}` — update policy  
- `DELETE /api/v1/admin/remediation-policies/{id}` — delete policy
- `GET /api/v1/admin/remediation-policies/{id}/executions` — last 10 auto-executions for this policy
- Router: `admin_router` in `admin_endpoints.py` (new file, mounted at `/api/v1/admin`)

### Learning Suggestion Engine
- After each HITL approval completes successfully (no rollback within 24h), check if identical action_class + resource pattern has occurred ≥5 times with 0 rollbacks
- If threshold met → emit `policy_suggestion` record to new Cosmos DB `policy_suggestions` container
- `GET /api/v1/admin/policy-suggestions` endpoint returns pending suggestions
- UI shows dismissible suggestion cards in the Policies panel
- Keep it simple: "Consider creating a policy for `restart_container_app` on `tier: dev` resources — approved 5 times, 0 rollbacks"

### Frontend — Settings Tab
- Add `settings` TabId to DashboardPanel (`DashboardPanel.tsx`)
- New `SettingsTab.tsx` component with sub-tabs: "Remediation Policies" | "Policy Suggestions"
- Policy list table: Name, Action Class, Tag Filter, Max Blast Radius, Daily Cap, Enabled toggle, Last 10 executions button
- Create/edit policy via inline form or slide-over `Sheet` component (using existing shadcn/ui Sheet)
- Execution history in expandable `Table` showing timestamp, resource, outcome, duration
- Use `var(--accent-blue)` / `var(--accent-green)` semantic tokens (never hardcoded Tailwind colors)
- Dark-mode-safe badges for policy status (enabled/disabled)

### Testing
- Unit tests for policy evaluation engine (match, no-match, each guard failure path)
- Unit tests for CRUD API endpoints
- Unit tests for learning suggestion logic
- Target: 20+ tests covering all guard paths and happy path

### Claude's Discretion
- Exact column layout for the Settings UI
- Whether to use a modal dialog or Sheet for policy create/edit (Sheet preferred — consistent with existing panels)
- Pagination strategy for policy list (policies likely < 50, no pagination needed)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `remediation_executor.py` — existing `execute_remediation()` function is the integration point; `_run_preflight()` has blast-radius logic to reuse
- `approvals.py` — HITL approval flow; policy evaluation inserts before this path
- `remediation_logger.py` — `build_remediation_event()` / `log_remediation_event()` for audit writes
- `migrations/003_create_sops_table.py` — template for new PostgreSQL migration (async `up(conn)` pattern)
- `DashboardPanel.tsx` — tab bar pattern; add `settings` tab following same `TABS` array structure
- shadcn/ui `Sheet`, `Table`, `Badge`, `Switch` components already in `components/ui/`

### Established Patterns
- PostgreSQL migrations: Python file with `UP_SQL` string + async `up(conn)` function
- API endpoints: FastAPI router files (`approvals.py`, `audit.py` pattern) — each domain has its own router
- Cosmos DB audit writes: `log_remediation_event()` from `remediation_logger.py`
- Frontend tabs: `DashboardPanel.tsx` TABS array + lazy-loaded tab content components
- Pydantic models: `models.py` — all request/response models centralized
- CSS tokens: `var(--accent-*)`, `var(--bg-canvas)`, `var(--text-primary)` — never hardcoded Tailwind

### Integration Points
- `main.py` — mount new `admin_router` for `/api/v1/admin` routes
- `remediation_executor.py` `execute_remediation()` — add policy evaluation before HITL gate
- `DashboardPanel.tsx` — add `settings` tab + `SettingsTab` import
- `services/web-ui/app/api/proxy/` — add proxy routes for `/api/v1/admin/remediation-policies`

</code_context>

<specifics>
## Specific Ideas

- Success metric from ROADMAP: Policy defined for `restart_container_app` on resources tagged `tier: dev`; next matching incident auto-executes without HITL; audit record shows `auto_approved_by_policy: <policy_id>`
- DEGRADED verification triggers auto-rollback regardless of policy — this is non-negotiable per ROADMAP
- The `aap-protected: true` resource tag is the emergency brake — always blocks auto-approval
- Learning suggestion threshold: 5 HITL approvals of identical pattern with 0 rollbacks

</specifics>

<deferred>
## Deferred Ideas

- Multi-policy conflict resolution (e.g., two policies match same action) — defer to Phase 65 or standalone
- Time-window-based policies (e.g., "only auto-approve during business hours") — deferred
- Policy import/export (JSON bulk upload) — deferred
- Cross-subscription policy templates — deferred to Phase 64 (Enterprise Multi-Tenant Gateway)

</deferred>
