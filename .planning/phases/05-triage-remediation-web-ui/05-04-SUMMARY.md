# Plan 05-04 Summary — HITL Approval Gate

**Completed:** 2026-03-27
**Branch:** phase-5-wave-0-test-infrastructure
**Commits:** 8

---

## What Was Built

### Task 5-04-01: Pydantic Models
- Added `ApprovalAction`, `ApprovalResponse`, `ApprovalRecord`, `IncidentSummary` to `services/api-gateway/models.py`
- `ApprovalRecord` covers the full approval lifecycle: pending → approved/rejected/expired/executed/aborted

### Task 5-04-02: Approval Endpoints
- Created `services/api-gateway/approvals.py` — core approval engine:
  - `process_approval_decision()` with ETag optimistic concurrency (`match_condition="IfMatch"`)
  - 30-minute expiry enforced via `_is_expired()` → `raise ValueError("expired")`
  - Prod subscription scope confirmation guard (REMEDI-006)
  - `_resume_foundry_thread()` — injects approval_response message + creates new run
- Updated `services/api-gateway/main.py` with three new routes:
  - `POST /api/v1/approvals/{approval_id}/approve` — 403 for missing prod scope, 410 for expired
  - `POST /api/v1/approvals/{approval_id}/reject` — 410 for expired
  - `GET /api/v1/approvals/{approval_id}` — read approval record

### Task 5-04-03: Resource Identity Certainty
- Updated `agents/shared/triage.py`: added `ResourceSnapshot` class with SHA-256 hash over `resource_id|provisioning_state|tags|resource_health`
- Created `agents/shared/resource_identity.py`:
  - `StaleApprovalError` — raised when resource diverges
  - `capture_resource_snapshot()` — called at proposal time
  - `verify_resource_identity()` — checks 2 independent signals before execution

### Task 5-04-04: Rate Limiter
- Created `services/api-gateway/rate_limiter.py`:
  - `RateLimiter` — sliding 60-second window, per (agent_name, subscription_id) key
  - `check_protected_tag()` — blocks remediation on resources with `protected:true` tag
  - Singleton `rate_limiter` instance for process-wide enforcement

### Task 5-04-05: Teams Adaptive Card Posting
- Created `services/api-gateway/teams_notifier.py`:
  - `post_approval_card()` — async, non-blocking, gracefully no-ops if webhook not configured
  - `_build_adaptive_card()` — Adaptive Card v1.5 with FactSet details and Action.Http approve/reject buttons
  - Degrades gracefully: missing `TEAMS_WEBHOOK_URL` logs warning, returns `None`

### Task 5-04-06: Message Envelope + Approval Manager
- Updated `agents/shared/envelope.py`:
  - Added `"approval_request"` and `"approval_response"` to `Literal[...]` and `VALID_MESSAGE_TYPES`
- Created `agents/shared/approval_manager.py`:
  - `create_approval_record()` — writes pending record to Cosmos DB with 30-min expiry
  - Implements write-then-return pattern: agent parks, webhook callback resumes

### Task 5-04-07: GitOps PR Path
- Created `services/api-gateway/migrations/003_create_gitops_config_table.sql` — `gitops_cluster_config` table mapping clusters to GitOps repos
- Created `agents/shared/gitops.py`:
  - `is_gitops_managed()` — returns True if Flux configs detected
  - `create_gitops_pr()` — creates branch `aiops/fix-{incident_id}-remediation`, commits manifest, opens PR via GitHub API

### Task 5-04-08: ProposalCard UI Component
- Replaced stub `services/web-ui/components/ProposalCard.tsx` with full implementation:
  - 5-state display: pending / approved / rejected / expired / aborted
  - Countdown timer (updates every second) showing time remaining
  - Fluent UI v9 Dialog confirmation for both approve and reject
  - Monospace resource ID display
  - Aborted state surfaces `stale_approval` reason to operator
  - `stale_approval` displayed in aborted state badge label

---

## Requirements Satisfied

| Req | Description | Implemented In |
|-----|-------------|----------------|
| REMEDI-001 | All proposals require explicit approval | `ApprovalRecord.status = "pending"` mandatory |
| REMEDI-002 | Teams card for high-risk proposals | `teams_notifier.py` + `approval_manager.py` |
| REMEDI-003 | ETag optimistic concurrency | `approvals.py` `match_condition="IfMatch"` |
| REMEDI-004 | Resource Identity Certainty | `triage.ResourceSnapshot` + `resource_identity.py` |
| REMEDI-005 | Approve/reject API endpoints | `main.py` POST routes |
| REMEDI-006 | Rate limiting + protected tag guard | `rate_limiter.py` |
| REMEDI-008 | GitOps PR path for Arc K8s | `gitops.py` + migration 003 |
| D-09 | `ApprovalAction` payload with `decided_by` | `models.py` |
| D-10 | Thread resume after approval | `_resume_foundry_thread()` in `approvals.py` |
| D-12 | `ApprovalRecord` full schema | `models.py` |
| D-13 | 410 Gone for expired approvals | `approvals.py` + endpoint handlers |

---

## Architecture Decisions

- **Write-then-return pattern**: Agents write to Cosmos DB and return. No thread blocking. Webhook callback resumes via new Foundry run. This avoids Foundry run timeout on long-running human approvals.
- **ETag concurrency**: Prevents double-approve race condition. Both reads and writes use the same `_etag` — `replace_item` with `match_condition="IfMatch"` will 409 on concurrent decisions.
- **SHA-256 resource snapshot**: Captures `resource_id|provisioning_state|tags|resource_health` at proposal time. Any change to any signal aborts execution with `StaleApprovalError`.
- **Teams outbound only (Phase 5)**: `Action.Http` buttons in the Adaptive Card call back to the API gateway. Full bidirectional Teams bot conversation is Phase 6.
